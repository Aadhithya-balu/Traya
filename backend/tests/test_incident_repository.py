"""`IncidentRepository` writes statuses the rest of the system can read.

This class is not wired into any router, which is precisely why it went
untested and why it was allowed to keep a second, unlogged way to write
`session.status`. Before Phase 7 `complete` wrote `completed` - a value that is
not in `INCIDENT_STATUSES`, not in the frontend `IncidentStatus` union, and not
readable as anything. Nothing failed, because nothing looked.

The assertions here are deliberately blunt: every status this repository writes
must be in the vocabulary, and every one must leave an event behind.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.database.session import SessionLocal
from app.models import EmergencySession, IncidentEvent
from app.repositories.incident import IncidentRepository
from app.services.incident_service import (
    INCIDENT_RESOLVED,
    MATCH_FOUND,
    STATUS_ABORTED,
    STATUS_CREATED,
    STATUS_EXPIRED,
    STATUS_IDENTIFIED,
    STATUS_RESOLVED,
    INCIDENT_STATUSES,
)

from .conftest import start_session


def test_complete_writes_identified_not_completed(client):
    db = SessionLocal()
    try:
        row = db.get(EmergencySession, start_session(client)["session_id"])
        repo = IncidentRepository(db)
        subject = _any_user_id(db)

        repo.complete(
            row, identified_user_id=subject, confidence_category="HUMAN_CONFIRMED"
        )
        db.commit()

        assert row.status == STATUS_IDENTIFIED
        assert row.status in INCIDENT_STATUSES
        assert row.status != "completed"
        events = _events(db, row.id)
        assert [e.event_type for e in events] == ["INCIDENT_CREATED", MATCH_FOUND]
    finally:
        db.close()


def test_complete_with_a_non_identified_outcome_resolves_instead(client):
    """`identified` and `resolved` are separate outcomes on purpose.

    An unidentified person at a hospital entrance is not a success, and a
    repository that reports it as one is the bug this vocabulary exists to
    prevent.
    """
    db = SessionLocal()
    try:
        row = db.get(EmergencySession, start_session(client)["session_id"])
        repo = IncidentRepository(db)

        repo.complete(
            row,
            identified_user_id=_any_user_id(db),
            confidence_category="NO_MATCH",
            outcome="not_identified",
        )
        db.commit()

        assert row.status == STATUS_RESOLVED
        last = _events(db, row.id)[-1]
        assert last.event_type == INCIDENT_RESOLVED
        assert last.details["outcome"] == "not_identified"
    finally:
        db.close()


def test_abort_writes_a_vocabulary_status_and_an_event(client):
    db = SessionLocal()
    try:
        row = db.get(EmergencySession, start_session(client)["session_id"])
        IncidentRepository(db).abort(row)
        db.commit()

        assert row.status == STATUS_ABORTED
        assert row.status in INCIDENT_STATUSES
        assert _events(db, row.id)[-1].event_type == INCIDENT_RESOLVED
    finally:
        db.close()


def test_expiry_persists_through_the_service_not_a_bare_assignment(client):
    db = SessionLocal()
    try:
        repo = IncidentRepository(db)
        before = repo.count_expired()

        row = db.get(EmergencySession, start_session(client)["session_id"])
        row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()

        assert repo.get_active(row.id).status == STATUS_EXPIRED
        db.commit()

        assert row.status in INCIDENT_STATUSES
        last = _events(db, row.id)[-1]
        assert last.event_type == INCIDENT_RESOLVED
        assert last.details["reason"] == "expired_at_passed"
        # Relative, because the seed and other tests may already have expired
        # sessions and this file must not depend on their number.
        assert repo.count_expired() == before + 1
    finally:
        db.close()


def test_an_unexpired_session_is_not_touched(client):
    db = SessionLocal()
    try:
        row = db.get(EmergencySession, start_session(client)["session_id"])
        IncidentRepository(db).get_active(row.id)
        db.commit()
        assert row.status == STATUS_CREATED
    finally:
        db.close()


def test_every_status_this_repository_can_write_is_in_the_vocabulary(client):
    """The general guard, so a future method cannot reintroduce the trap."""
    db = SessionLocal()
    try:
        row = db.get(EmergencySession, start_session(client)["session_id"])
        repo = IncidentRepository(db)
        subject = _any_user_id(db)

        repo.complete(row, identified_user_id=subject, confidence_category="X")
        repo.abort(row)
        db.commit()

        written = {row.status}
        assert written <= INCIDENT_STATUSES
        assert "completed" not in written
    finally:
        db.close()


def _events(db, session_id: str) -> list[IncidentEvent]:
    return (
        db.query(IncidentEvent)
        .filter(IncidentEvent.session_id == session_id)
        .order_by(IncidentEvent.sequence.asc())
        .all()
    )


def _any_user_id(db) -> str:
    from app.models import User

    return db.query(User).first().id
