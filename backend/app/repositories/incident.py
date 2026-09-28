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


class IncidentRepository(BaseRepository[EmergencySession]):
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
        if session is None or session.status in ("expired", "aborted"):
            return session
        if session.expires_at and datetime.now(UTC) > _as_utc(session.expires_at):
            session.status = "expired"
            self.db.flush()
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
        session.identified_user_id = identified_user_id
        session.confidence_category = confidence_category
        session.outcome = outcome
        session.status = "completed"
        session.completed_at = datetime.now(UTC)
        self.db.flush()

    def abort(self, session: EmergencySession) -> None:
        session.status = "aborted"
        session.outcome = "aborted"
        session.completed_at = datetime.now(UTC)
        self.db.flush()

    def count_expired(self) -> int:
        return (
            self.db.query(EmergencySession)
            .filter(EmergencySession.status == "expired")
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
