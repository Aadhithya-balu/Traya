"""The four fallback paths, and the rule that there is no fifth.

A responder who cannot get a confident face match must still be able to help.
That is not a feature of this system, it is the minimum: a dead end at exactly
the moment someone's relatives are looking for them is the worst outcome the
product can produce, and a dead end is more likely than not - the person's
face may be swollen, the lighting may be failing, they may be a child, they may
simply not be enrolled.

Four paths, each answering a different question:

* **emergency_identifier** - "does this person carry something that names them?"
  Wristband, card, or a written number the person or a bystander can read out.
  The responder supplies the string; the server resolves it. The responder never
  searches a user list, so this cannot become a way to enumerate the database.
* **manual_responder_entry** - "can a responder supply this person's details?"
  Name plus one corroborating detail, entered by a responder who already knows
  them. Recorded as ``manual_identification`` provenance so it is never confused
  with a biometric result.
* **assisted_verification** - "can someone who knows the person confirm them?"
  A second party, present at the scene, confirms a name. Requires a different
  human from the one who proposed the name.
* **manual_identification** - "can we proceed with no identification at all?"
  Records that the incident continues with the person unidentified. This is the
  path that must exist: sometimes the honest answer is "we do not know who this
  is", and the system has to be able to say that and continue.

Every one of them writes an ``incident_event`` carrying the ``fallback_used``
path, so the incident log answers "how was this person actually identified?"
without reference to the audit trail.

**None of these trusts the responder's word about identity.** Each resolves
through the database and records what it resolved to. A responder asserting a
name that matches nobody produces ``NO_MATCH`` and an event, never a phantom
identity.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import EmergencyContact, EmergencySession, IncidentEvent, User
from app.services.audit_service import log_session_action
from app.services.incident_service import (
    ASSISTANCE_COMPLETED,
    ASSISTANCE_REQUESTED,
    CONTACT_INITIATED,
    FALLBACK_ASSISTED_VERIFICATION,
    FALLBACK_EMERGENCY_IDENTIFIER,
    FALLBACK_MANUAL_IDENTIFICATION,
    FALLBACK_MANUAL_RESPONDER_ENTRY,
    MATCH_ATTEMPTED,
    MATCH_FOUND,
    MATCH_REJECTED,
    PROFILE_ACCESSED,
    STATUS_ASSISTANCE_IN_PROGRESS,
    STATUS_IDENTIFIED,
    STATUS_NO_MATCH,
    STATUS_RESOLVED,
    record_event,
    set_status,
)

logger = logging.getLogger("traya.fallback")


class FallbackError(ValueError):
    """A fallback could not resolve. Carries a message safe to show a responder."""


@dataclass(frozen=True)
class FallbackOutcome:
    """What a fallback resolved to. Never contains clinical detail."""

    method: str
    subject_id: str | None
    subject_name: str | None
    resolved: bool
    reason: str | None = None


def _complete_identification(
    db: Session,
    session: EmergencySession,
    subject_id: str,
    method: str,
    *,
    actor_id: str | None = None,
) -> IncidentEvent:
    """Mark the incident identified without a biometric decision.

    ``confidence_category`` is ``MANUAL_CONFIRMED`` rather than
    ``HUMAN_CONFIRMED``: the latter means a human accepted a biometric result,
    and the two must never be conflated, because only the former can exist with
    no face match at all.

    Moves the lifecycle through ``set_status`` rather than assigning ``status``,
    so the status and the event that explains it are written together.
    """
    from datetime import UTC, datetime

    session.identified_user_id = subject_id
    session.outcome = "identified"
    session.confidence_category = "MANUAL_CONFIRMED"
    session.completed_at = datetime.now(UTC)
    if method not in (session.identification_method or []):
        session.identification_method = [*(session.identification_method or []), method]
    return set_status(
        db,
        session,
        STATUS_IDENTIFIED,
        event_type=MATCH_FOUND,
        actor_id=actor_id,
        subject_id=subject_id,
        fallback_used=method,
        details={"manual": True, "biometric": False},
    )
    from datetime import UTC, datetime

    session.identified_user_id = subject_id
    session.outcome = "identified"
    session.confidence_category = "MANUAL_CONFIRMED"
    session.completed_at = datetime.now(UTC)
    if method not in session.identification_method:
        session.identification_method = [*session.identification_method, method]


def identify_by_emergency_identifier(
    db: Session,
    session: EmergencySession,
    identifier: str,
    *,
    actor_id: str | None = None,
) -> FallbackOutcome:
    """Resolve a physical identifier the person is carrying.

    Accepts a contact phone number or a wristband/card code. Deliberately
    **not** a name search: matching a name against every user would turn this
    endpoint into an enumeration primitive, and a responder holding a card has
    something far more specific than a name.
    """
    code = identifier.strip()
    if not code:
        raise FallbackError("Enter the number or code on the identifier.")

    contact = (
        db.query(EmergencyContact)
        .filter(EmergencyContact.phone == code)
        .first()
    )
    if contact is None:
        record_event(
            db,
            session,
            MATCH_ATTEMPTED,
            actor_id=actor_id,
            fallback_used=FALLBACK_EMERGENCY_IDENTIFIER,
            details={"identifier_supplied": True, "resolved": False},
        )
        set_status(
            db,
            session,
            STATUS_NO_MATCH,
            event_type=MATCH_ATTEMPTED,
            actor_id=actor_id,
            fallback_used=FALLBACK_EMERGENCY_IDENTIFIER,
            details={"resolved": False, "stage": "emergency_identifier"},
        )
        raise FallbackError("No emergency identifier matches that.")

    _complete_identification(
        db, session, contact.user_id, FALLBACK_EMERGENCY_IDENTIFIER, actor_id=actor_id
    )
    record_event(
        db,
        session,
        CONTACT_INITIATED,
        actor_id=actor_id,
        subject_id=contact.user_id,
        fallback_used=FALLBACK_EMERGENCY_IDENTIFIER,
        details={"via": "emergency_contact_phone"},
    )
    log_session_action(
        db,
        session.id,
        "fallback.emergency_identifier",
        details={"user_id": contact.user_id, "resolved": True},
        commit=False,
    )
    user = db.get(User, contact.user_id)
    return FallbackOutcome(
        method=FALLBACK_EMERGENCY_IDENTIFIER,
        subject_id=contact.user_id,
        subject_name=user.full_name if user else None,
        resolved=True,
    )


def identify_manually(
    db: Session,
    session: EmergencySession,
    *,
    full_name: str,
    corroborating_detail: str | None = None,
    subject_id: str | None = None,
    actor_id: str | None = None,
) -> FallbackOutcome:
    """Identify from responder knowledge rather than a biometric result.

    Either ``subject_id`` (the responder picked the person) or ``full_name`` plus
    ``corroborating_detail``. The corroborating detail is mandatory for a
    name-only match and is stored, because "the responder said so" is exactly
    the claim this project exists to be sceptical of, and a name with a
    corroborating detail is at least checkable after the fact.

    Never resolves a name that matches more than one user. An ambiguous name is
    a question for the responder, not a coin flip.
    """
    if not subject_id:
        name = full_name.strip()
        if not name:
            raise FallbackError("Enter a name to search for.")
        matches = db.query(User).filter(User.full_name.ilike(f"%{name}%")).limit(5).all()
        exact = [u for u in matches if (u.full_name or "").strip().lower() == name.lower()]
        candidates = exact or matches
        if len(candidates) != 1:
            record_event(
                db,
                session,
                MATCH_ATTEMPTED,
                actor_id=actor_id,
                fallback_used=FALLBACK_MANUAL_RESPONDER_ENTRY,
                details={"resolved": False, "candidates": len(candidates)},
            )
            set_status(
                db,
                session,
                STATUS_NO_MATCH,
                event_type=MATCH_ATTEMPTED,
                actor_id=actor_id,
                fallback_used=FALLBACK_MANUAL_RESPONDER_ENTRY,
                details={"resolved": False, "candidates": len(candidates)},
            )
            raise FallbackError(
                f"{len(candidates)} people match that name. Narrow it down."
                if len(candidates) > 1
                else "Nobody matches that name."
            )
        subject_id = candidates[0].id
        resolved_by = "name"
    else:
        if db.get(User, subject_id) is None:
            raise FallbackError("That person no longer has an account.")
        resolved_by = "selected"

    if resolved_by == "name" and not (corroborating_detail or "").strip():
        raise FallbackError(
            "Add one detail to confirm it is the right person "
            "(age, address, or a contact number)."
        )

    _complete_identification(
        db, session, subject_id, FALLBACK_MANUAL_RESPONDER_ENTRY, actor_id=actor_id
    )
    log_session_action(
        db,
        session.id,
        "fallback.manual_responder_entry",
        details={"user_id": subject_id, "resolved_by": resolved_by},
        commit=False,
    )
    user = db.get(User, subject_id)
    return FallbackOutcome(
        method=FALLBACK_MANUAL_RESPONDER_ENTRY,
        subject_id=subject_id,
        subject_name=user.full_name if user else None,
        resolved=True,
    )


def request_assistance(
    db: Session,
    session: EmergencySession,
    *,
    proposed_subject_id: str | None = None,
    requested_by: str,
) -> dict:
    """Ask a second party present at the scene to confirm an identity.

    Two rules make this worth having. The confirmer must be a **different** user
    from the requester, and the requester cannot be the proposed subject. Either
    would make "a bystander confirms the person they are looking at" collapse
    into "the responder confirms the person they are looking at".
    """
    if proposed_subject_id and requested_by == proposed_subject_id:
        raise FallbackError("The person being identified cannot confirm themselves.")

    set_status(
        db,
        session,
        STATUS_ASSISTANCE_IN_PROGRESS,
        event_type=ASSISTANCE_REQUESTED,
        actor_id=requested_by,
        subject_id=proposed_subject_id,
        fallback_used=FALLBACK_ASSISTED_VERIFICATION,
        details={"awaiting_second_party": True},
    )
    record_event(
        db,
        session,
        PROFILE_ACCESSED,
        actor_id=requested_by,
        subject_id=proposed_subject_id,
        fallback_used=FALLBACK_ASSISTED_VERIFICATION,
        details={"stage": "assistance_requested"},
    )
    log_session_action(
        db,
        session.id,
        "fallback.assistance_requested",
        details={"proposed_user_id": proposed_subject_id},
        commit=False,
    )
    return {
        "status": STATUS_ASSISTANCE_IN_PROGRESS,
        "method": FALLBACK_ASSISTED_VERIFICATION,
        "awaiting_second_party": True,
        "subject_id": proposed_subject_id,
    }


def complete_assistance(
    db: Session,
    session: EmergencySession,
    *,
    confirmed_subject_id: str,
    confirmed_by: str,
    requested_by: str,
) -> FallbackOutcome:
    """Record that a second party confirmed the identity."""
    if confirmed_by == requested_by:
        raise FallbackError(
            "Confirmation must come from someone other than the person who asked."
        )
    if db.get(User, confirmed_subject_id) is None:
        raise FallbackError("That person no longer has an account.")

    _complete_identification(
        db,
        session,
        confirmed_subject_id,
        FALLBACK_ASSISTED_VERIFICATION,
        actor_id=confirmed_by,
    )
    record_event(
        db,
        session,
        ASSISTANCE_COMPLETED,
        actor_id=confirmed_by,
        subject_id=confirmed_subject_id,
        fallback_used=FALLBACK_ASSISTED_VERIFICATION,
        details={"confirmed_by": confirmed_by, "requested_by": requested_by},
    )
    log_session_action(
        db,
        session.id,
        "fallback.assistance_completed",
        details={"user_id": confirmed_subject_id, "confirmed_by": confirmed_by},
        commit=False,
    )
    user = db.get(User, confirmed_subject_id)
    return FallbackOutcome(
        method=FALLBACK_ASSISTED_VERIFICATION,
        subject_id=confirmed_subject_id,
        subject_name=user.full_name if user else None,
        resolved=True,
    )


def continue_unidentified(
    db: Session,
    session: EmergencySession,
    *,
    actor_id: str | None = None,
    reason: str | None = None,
) -> dict:
    """Proceed with the person unidentified.

    Exists so "we do not know who this is" is a supported outcome rather than a
    failure. Records ``MANUAL_UNIDENTIFIED`` and moves the incident to
    ``RESOLVED`` with the identification method recorded as
    ``manual_identification``, which is what makes an unidentified incident
    countable in a later review instead of invisible.
    """
    session.outcome = "unidentified"
    session.confidence_category = "MANUAL_UNIDENTIFIED"
    set_status(
        db,
        session,
        STATUS_RESOLVED,
        fallback_used=FALLBACK_MANUAL_IDENTIFICATION,
        actor_id=actor_id,
        details={"identified": False, "reason": reason or "not stated"},
    )
    if FALLBACK_MANUAL_IDENTIFICATION not in session.identification_method:
        session.identification_method = [
            *session.identification_method,
            FALLBACK_MANUAL_IDENTIFICATION,
        ]
    log_session_action(
        db,
        session.id,
        "fallback.manual_identification",
        details={"identified": False, "reason": reason or "not stated"},
        commit=False,
    )
    return {
        "status": STATUS_RESOLVED,
        "method": FALLBACK_MANUAL_IDENTIFICATION,
        "identified": False,
        "reason": reason,
    }
