"""Emergency session and incident records.

TRAYA models an emergency as a session: one scan-to-response episode with a
life span, its own access token, its own audit trail and at most one
identified victim.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models import (
    AuditLog,
    EmergencySession,
    IdentificationAttempt,
    IdentificationCandidate,
    Location,
)
from app.repositories.base import BaseRepository
from app.services.incident_service import (
    INCIDENT_RESOLVED,
    MATCH_FOUND,
    STATUS_ABORTED,
    STATUS_EXPIRED,
    STATUS_IDENTIFIED,
    STATUS_RESOLVED,
    set_status,
)


class IncidentRepository(BaseRepository[EmergencySession]):
    """Session and incident persistence.

    **Nothing here writes `session.status` directly.** Every status change goes
    through `incident_service.set_status`, even though that means a repository
    calling a service. The alternative was a second, unlogged way to write a
    status, and before Phase 7 that second way existed here: `complete` wrote
    `completed`, a value the incident vocabulary does not contain and the
    frontend union could not represent. A repository method that looks like the
    supported path and quietly produces a status nothing else understands is
    worse than a layering complaint, so the dependency is deliberate.

    No router or service currently uses this class - the emergency API goes
    through `incident_service` and the pipeline. It is kept because the data
    access it wraps is real and referenced from
    [repositories.md](../../../docs/backend/repositories.md).
    """

    model = EmergencySession

    # ------------------------------------------------------------- sessions
    def start(self, *, session_code: str, expires_at: datetime, **fields) -> EmergencySession:
        session = EmergencySession(
            session_code=session_code, expires_at=expires_at, **fields
        )
        self.db.add(session)
        self.db.flush()
        return session

    def get_active(self, session_id: str) -> EmergencySession | None:
        """Return the session unless it has been closed out.

        Expiry is evaluated here and persisted, so an abandoned session stops
        being usable the moment it lapses rather than whenever it is next read.
        """
        session = self.db.get(EmergencySession, session_id)
        if session is None or session.status in (STATUS_EXPIRED, STATUS_ABORTED):
            return session
        if session.expires_at and datetime.now(UTC) > _as_utc(session.expires_at):
            set_status(
                self.db,
                session,
                STATUS_EXPIRED,
                event_type=INCIDENT_RESOLVED,
                details={"reason": "expired_at_passed"},
            )
        return session

    def recent(self, limit: int = 100) -> list[EmergencySession]:
        return (
            self.db.query(EmergencySession)
            .order_by(EmergencySession.created_at.desc())
            .limit(limit)
            .all()
        )

    def complete(
        self,
        session: EmergencySession,
        *,
        identified_user_id: str,
        confidence_category: str,
        outcome: str = "identified",
    ) -> None:
        """Record an identification and close the incident as `identified`.

        The pre-Phase-7 code wrote `completed`, which no reader understood: the
        incident vocabulary has `identified` and `resolved` as separate
        outcomes, because an unidentified person at a hospital entrance is not
        a success. An `outcome` other than `identified` therefore resolves
        rather than identifies, and says so in the log.
        """
        session.identified_user_id = identified_user_id
        session.confidence_category = confidence_category
        session.outcome = outcome
        session.completed_at = datetime.now(UTC)
        if outcome == "identified":
            set_status(
                self.db,
                session,
                STATUS_IDENTIFIED,
                event_type=MATCH_FOUND,
                subject_id=identified_user_id,
                details={"via": "IncidentRepository.complete"},
            )
        else:
            set_status(
                self.db,
                session,
                STATUS_RESOLVED,
                details={"via": "IncidentRepository.complete", "outcome": outcome},
            )
        self.db.flush()

    def abort(self, session: EmergencySession) -> None:
        session.outcome = "aborted"
        session.completed_at = datetime.now(UTC)
        set_status(
            self.db,
            session,
            STATUS_ABORTED,
            event_type=INCIDENT_RESOLVED,
            details={"reason": "aborted"},
        )
        self.db.flush()

    def count_expired(self) -> int:
        return (
            self.db.query(EmergencySession)
            .filter(EmergencySession.status == STATUS_EXPIRED)
            .count()
        )

    # ------------------------------------------------------------ locations
    def add_location(
        self, session_id: str, *, latitude: float, longitude: float, source: str, accuracy: float | None = None
    ) -> Location:
        location = Location(
            session_id=session_id,
            latitude=latitude,
            longitude=longitude,
            accuracy=accuracy,
            source=source,
        )
        self.db.add(location)
        self.db.flush()
        return location

    # ------------------------------------------------------------ attempts
    def record_attempt(self, session: EmergencySession, **fields) -> IdentificationAttempt:
        attempt = IdentificationAttempt(session_id=session.id, **fields)
        self.db.add(attempt)
        self.db.flush()
        return attempt

    def latest_attempt(self, session_id: str) -> IdentificationAttempt | None:
        return (
            self.db.query(IdentificationAttempt)
            .filter(IdentificationAttempt.session_id == session_id)
            .order_by(IdentificationAttempt.created_at.desc())
            .first()
        )

    def add_candidate(
        self, attempt: IdentificationAttempt, *, user_id: str, confidence: float, rank: int, method: list[str]
    ) -> IdentificationCandidate:
        candidate = IdentificationCandidate(
            attempt_id=attempt.id,
            user_id=user_id,
            confidence=confidence,
            rank=rank,
            method=method,
        )
        self.db.add(candidate)
        self.db.flush()
        return candidate

    def candidates(self, attempt_id: str) -> list[IdentificationCandidate]:
        return (
            self.db.query(IdentificationCandidate)
            .filter(IdentificationCandidate.attempt_id == attempt_id)
            .order_by(IdentificationCandidate.rank)
            .all()
        )

    def candidate(self, candidate_id: str) -> IdentificationCandidate | None:
        return self.db.get(IdentificationCandidate, candidate_id)

    # -------------------------------------------------------------- timeline
    def timeline(self, session_id: str) -> list[AuditLog]:
        return (
            self.db.query(AuditLog)
            .filter(AuditLog.session_id == session_id)
            .order_by(AuditLog.created_at)
            .all()
        )


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)
