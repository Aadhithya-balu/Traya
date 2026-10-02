"""Append-only incident event log.

An incident is a sequence of things that happened to one person, in order. The
audit log cannot answer that question: it is keyed by actor, not by incident, so
reconstructing "what happened, in order" from it means filtering by session and
re-sorting by a timestamp that has second granularity. This module writes the
sequence directly, once, at the moment each thing happens.

Three rules this module enforces:

* **Never updated, never deleted.** There is no update path and no delete path,
  and that is deliberate. An event that can be edited is not evidence.
* **One writer assigns the sequence.** ``next_sequence`` reads the current
  maximum inside the caller's transaction, so two events written in the same
  millisecond still order deterministically and the unique constraint on
  ``(session_id, sequence)`` cannot be violated by a retry.
* **Never commits.** The caller owns the transaction, so an event and the domain
  write it describes land together or not at all. An ``INCIDENT_RESOLVED`` that
  committed without its status change would be worse than no event at all.
"""
from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import EmergencySession, IncidentEvent

# The nine types Phase 7 requires, plus the three that make a sequence legible
# without changing its meaning. Names are the API contract: they are stored, and
# the frontend maps them to guidance codes, so they must not be renamed casually.
INCIDENT_CREATED = "INCIDENT_CREATED"
FACE_CAPTURE_STARTED = "FACE_CAPTURE_STARTED"
FACE_DETECTED = "FACE_DETECTED"
MATCH_ATTEMPTED = "MATCH_ATTEMPTED"
MATCH_FOUND = "MATCH_FOUND"
MATCH_REJECTED = "MATCH_REJECTED"
PROFILE_ACCESSED = "PROFILE_ACCESSED"
CONTACT_INITIATED = "CONTACT_INITIATED"
INCIDENT_RESOLVED = "INCIDENT_RESOLVED"

# Additions, not replacements. CAPTURE_REJECTED is what distinguishes "we tried
# and could not use the image" from "we never tried", which is the difference
# between a retake instruction and a fallback. ASSISTANCE_REQUESTED and
# ASSISTANCE_COMPLETED make the assisted-verification fallback observable from
# the incident log alone rather than only from audit rows.
CAPTURE_REJECTED = "CAPTURE_REJECTED"
ASSISTANCE_REQUESTED = "ASSISTANCE_REQUESTED"
ASSISTANCE_COMPLETED = "ASSISTANCE_COMPLETED"

EVENT_TYPES: frozenset[str] = frozenset(
    {
        INCIDENT_CREATED,
        FACE_CAPTURE_STARTED,
        FACE_DETECTED,
        MATCH_ATTEMPTED,
        MATCH_FOUND,
        MATCH_REJECTED,
        PROFILE_ACCESSED,
        CONTACT_INITIATED,
        INCIDENT_RESOLVED,
        CAPTURE_REJECTED,
        ASSISTANCE_REQUESTED,
        ASSISTANCE_COMPLETED,
    }
)

# The four fallback paths Phase 7 requires. Stored on the event so a responder
# reading the incident can tell which signal identified the person, and so a
# later accuracy review can measure the fallbacks separately from face matching.
FALLBACK_EMERGENCY_IDENTIFIER = "emergency_identifier"
FALLBACK_MANUAL_RESPONDER_ENTRY = "manual_responder_entry"
FALLBACK_ASSISTED_VERIFICATION = "assisted_verification"
FALLBACK_MANUAL_IDENTIFICATION = "manual_identification"

FALLBACK_PATHS: frozenset[str] = frozenset(
    {
        FALLBACK_EMERGENCY_IDENTIFIER,
        FALLBACK_MANUAL_RESPONDER_ENTRY,
        FALLBACK_ASSISTED_VERIFICATION,
        FALLBACK_MANUAL_IDENTIFICATION,
    }
)

# Incident statuses. Deliberately separate from both the matching statuses the
# pipeline emits and the UI result states: these describe the incident, not the
# biometric decision.
# ----------------------------------------------------------------- lifecycle
# Lowercase because the persisted vocabulary already was: existing rows carry
# "active" and "completed". Event types are uppercase because they are new and
# nothing reads them as words in a query.
#
# The vocabulary deliberately replaces "active"/"completed" with something that
# says how far the attempt got. An incident that ended with nobody identified is
# `resolved`, not `completed` - "completed" reads as success and an unidentified
# person at a hospital is not a success.
STATUS_CREATED = "created"
STATUS_IDENTIFYING = "identifying"
STATUS_IDENTIFIED = "identified"
STATUS_REVIEW_REQUIRED = "review_required"
STATUS_NO_MATCH = "no_match"
STATUS_ASSISTANCE_IN_PROGRESS = "assistance_in_progress"
STATUS_RESOLVED = "resolved"
STATUS_CANCELLED = "cancelled"
STATUS_EXPIRED = "expired"
STATUS_ABORTED = "aborted"

INCIDENT_STATUSES: frozenset[str] = frozenset(
    {
        STATUS_CREATED,
        STATUS_IDENTIFYING,
        STATUS_IDENTIFIED,
        STATUS_REVIEW_REQUIRED,
        STATUS_NO_MATCH,
        STATUS_ASSISTANCE_IN_PROGRESS,
        STATUS_RESOLVED,
        STATUS_CANCELLED,
        STATUS_EXPIRED,
        STATUS_ABORTED,
    }
)

# Statuses an incident can never leave. `_get_active_session` refuses expired
# and aborted sessions outright, so anything written after one of these is a bug
# rather than a late update.
TERMINAL_STATUSES: frozenset[str] = frozenset(
    {STATUS_RESOLVED, STATUS_CANCELLED, STATUS_EXPIRED, STATUS_ABORTED}
)

# One honest event per status. REVIEW_REQUIRED and NO_MATCH share MATCH_REJECTED
# because a human declined to accept an automatic result and a system found no
# result are the same fact from the incident's point of view: nothing was
# identified automatically, and a person has to decide what happens next.
#
# STATUS_IDENTIFYING is deliberately absent, and that omission is load-bearing.
# Entering `identifying` is not a match attempt - a responder opening the camera
# has attempted nothing - so there is no honest default event for it. Mapping it
# to MATCH_ATTEMPTED put "a match was tried" into the log of every photo ever
# taken, and put it *before* the FACE_CAPTURE_STARTED that actually caused it.
# Callers entering this status must name their own event, and `set_status` raises
# rather than guessing.
STATUS_EVENTS: dict[str, str] = {
    STATUS_CREATED: INCIDENT_CREATED,
    STATUS_IDENTIFIED: MATCH_FOUND,
    STATUS_REVIEW_REQUIRED: MATCH_REJECTED,
    STATUS_NO_MATCH: MATCH_REJECTED,
    STATUS_ASSISTANCE_IN_PROGRESS: ASSISTANCE_REQUESTED,
    STATUS_RESOLVED: INCIDENT_RESOLVED,
    STATUS_CANCELLED: INCIDENT_RESOLVED,
    STATUS_EXPIRED: INCIDENT_RESOLVED,
    STATUS_ABORTED: INCIDENT_RESOLVED,
}


class UnknownEventType(ValueError):
    """Raised for an event type outside :data:`EVENT_TYPES`.

    Exists so a typo in a caller is a startup-shaped failure in a test rather
    than a row that nothing reads.
    """


def next_sequence(db: Session, session_id: str) -> int:
    """The next per-session sequence number. Reads inside the caller's
    transaction; the caller must not have committed since reading."""
    current = (
        db.query(func.max(IncidentEvent.sequence))
        .filter(IncidentEvent.session_id == session_id)
        .scalar()
    )
    return int(current or 0) + 1


def record_event(
    db: Session,
    session: EmergencySession,
    event_type: str,
    *,
    actor_id: str | None = None,
    subject_id: str | None = None,
    fallback_used: str | None = None,
    details: dict | None = None,
) -> IncidentEvent:
    """Append one event. Never commits; never mutates anything else.

    ``subject_id`` defaults to the session's identified user so the common case
    needs no argument, but it is explicit on the events where the subject is the
    point of the record.
    """
    if event_type not in EVENT_TYPES:
        raise UnknownEventType(event_type)
    if fallback_used is not None and fallback_used not in FALLBACK_PATHS:
        raise ValueError(f"unknown fallback path: {fallback_used}")

    event = IncidentEvent(
        session_id=session.id,
        event_type=event_type,
        sequence=next_sequence(db, session.id),
        actor_id=actor_id,
        subject_id=subject_id if subject_id is not None else session.identified_user_id,
        fallback_used=fallback_used,
        details=details or {},
    )
    db.add(event)
    db.flush()
    return event


def set_status(
    db: Session,
    session: EmergencySession,
    status: str,
    *,
    event_type: str | None = None,
    actor_id: str | None = None,
    subject_id: str | None = None,
    fallback_used: str | None = None,
    details: dict | None = None,
    suppress_event: bool = False,
) -> IncidentEvent | None:
    """Move the incident to ``status`` and record why.

    The only sanctioned way to change ``session.status``. Centralised so the
    status field and the event log can never disagree - a status reached without
    an event is exactly the gap that makes an incident unexplainable.

    The event type is derived from the status by default, because most pairs are
    not free-form. A caller may override it
    when the transition is more specific than the status, which is why
    ``NO_MATCH`` reached through a fallback records ``ASSISTANCE_REQUESTED``.

    ``suppress_event`` exists for exactly one situation: the caller has already
    written the event that explains the transition. The identification pipeline
    records ``MATCH_ATTEMPTED`` and then moves to ``identifying``, and inventing
    a second attempt row there would put the same fact in the log twice.
    """
    if status not in INCIDENT_STATUSES:
        raise ValueError(f"unknown incident status: {status}")
    if suppress_event:
        session.status = status
        return None
    # Resolved before the status is touched, so a caller that cannot name an
    # honest event leaves the session exactly as it found it. A half-applied
    # transition is worse than a rejected one.
    resolved = event_type or STATUS_EVENTS.get(status)
    if resolved is None:
        raise ValueError(
            f"status {status!r} has no default incident event; pass event_type= "
            "so the log records what actually happened"
        )
    session.status = status
    return record_event(
        db,
        session,
        resolved,
        actor_id=actor_id,
        subject_id=subject_id,
        fallback_used=fallback_used,
        details={"status": status, **(details or {})},
    )


def timeline(db: Session, session_id: str) -> list[dict]:
    """The incident's events in order. Read-only; used by the incident view."""
    rows = (
        db.query(IncidentEvent)
        .filter(IncidentEvent.session_id == session_id)
        .order_by(IncidentEvent.sequence.asc())
        .all()
    )
    return [
        {
            "sequence": r.sequence,
            "event_type": r.event_type,
            "actor_id": r.actor_id,
            "subject_id": r.subject_id,
            "fallback_used": r.fallback_used,
            "details": r.details,
            "at": r.created_at,
        }
        for r in rows
    ]
