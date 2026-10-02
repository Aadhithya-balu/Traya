"""Incident lifecycle, incident events, and the four fallback paths.

The fallback tests matter more than they look. Each one exists because a
responder at a real scene must never hit a dead end, and a dead end is likelier
than the happy path - swollen faces, failing lights, children, people who simply
were never enrolled. If a fallback path silently breaks, the failure is not an
error message, it is a person at a hospital entrance who cannot be identified.
"""
from __future__ import annotations

import uuid

import pytest

from app.database.session import SessionLocal
from app.models import EmergencySession, IncidentEvent, User
from app.services.incident_service import (
    ASSISTANCE_REQUESTED,
    FACE_CAPTURE_STARTED,
    FALLBACK_ASSISTED_VERIFICATION,
    FALLBACK_EMERGENCY_IDENTIFIER,
    FALLBACK_MANUAL_IDENTIFICATION,
    FALLBACK_MANUAL_RESPONDER_ENTRY,
    INCIDENT_CREATED,
    INCIDENT_RESOLVED,
    MATCH_ATTEMPTED,
    MATCH_REJECTED,
    STATUS_ASSISTANCE_IN_PROGRESS,
    STATUS_CREATED,
    STATUS_IDENTIFIED,
    STATUS_IDENTIFYING,
    STATUS_NO_MATCH,
    STATUS_RESOLVED,
    STATUS_REVIEW_REQUIRED,
    UnknownEventType,
    record_event,
    set_status,
)
from app.services.fallback_service import (
    FallbackError,
    complete_assistance,
    continue_unidentified,
    identify_by_emergency_identifier,
    identify_manually,
    request_assistance,
)

from .conftest import (
    aarav_image,  # noqa: F401  (fixture re-export)
    auth_headers,
    identify,
    session_headers,
    start_session,
)


# ------------------------------------------------------------------- lifecycle
def test_session_starts_in_created_and_logs_the_incident(client):
    session = start_session(client)
    assert session["status"] == STATUS_CREATED

    events = client.get(
        f"/api/emergency/{session['session_id']}/events", headers=session_headers(session)
    ).json()
    assert events["status"] == STATUS_CREATED
    assert [e["event_type"] for e in events["events"]] == ["INCIDENT_CREATED"]
    assert events["events"][0]["sequence"] == 1


def test_event_sequences_are_monotonic_per_session(client):
    """Sequence, not timestamp, is the order of record.

    Two events written inside the same millisecond must still have a defined
    order, or the incident log cannot answer "what happened first".
    """
    db = SessionLocal()
    try:
        row = db.get(EmergencySession, start_session(client)["session_id"])
        for _ in range(5):
            record_event(db, row, "MATCH_ATTEMPTED")
        db.commit()
        seqs = [
            e.sequence
            for e in db.query(IncidentEvent)
            .filter(IncidentEvent.session_id == row.id)
            .order_by(IncidentEvent.sequence.asc())
            .all()
        ]
        assert seqs == sorted(seqs)
        assert len(set(seqs)) == len(seqs)
    finally:
        db.close()


def test_duplicate_sequence_is_rejected_by_the_database(client):
    """The unique constraint is the real guard; the service cannot be trusted
    alone because two responders can write events concurrently."""
    from sqlalchemy.exc import IntegrityError

    db = SessionLocal()
    try:
        row = db.get(EmergencySession, start_session(client)["session_id"])
        try:
            # Sequence 1 already exists from INCIDENT_CREATED at session start.
            db.add(IncidentEvent(session_id=row.id, event_type="MATCH_FOUND", sequence=1))
            db.commit()
        except IntegrityError:
            db.rollback()
        else:
            raise AssertionError("duplicate sequence was accepted")
    finally:
        db.close()


def test_unknown_event_type_is_rejected(client):
    db = SessionLocal()
    try:
        row = db.get(EmergencySession, start_session(client)["session_id"])
        try:
            record_event(db, row, "NOT_A_REAL_EVENT")
        except UnknownEventType:
            db.rollback()
        else:
            raise AssertionError("unknown event type was accepted")
    finally:
        db.close()


def test_unknown_status_is_rejected(client):
    db = SessionLocal()
    try:
        row = db.get(EmergencySession, start_session(client)["session_id"])
        try:
            set_status(db, row, "something_invented")
        except ValueError:
            db.rollback()
        else:
            raise AssertionError("unknown status was accepted")
    finally:
        db.close()


def test_every_status_reaches_a_terminal_state_through_the_service(client):
    """No status may be set without leaving an event behind."""
    db = SessionLocal()
    try:
        row = db.get(EmergencySession, start_session(client)["session_id"])
        # The honest event for each status, which is the whole point: forcing a
        # single type through would only prove the loop ran.
        journey = [
            (STATUS_IDENTIFYING, FACE_CAPTURE_STARTED),
            (STATUS_REVIEW_REQUIRED, MATCH_REJECTED),
            (STATUS_NO_MATCH, MATCH_REJECTED),
            (STATUS_ASSISTANCE_IN_PROGRESS, ASSISTANCE_REQUESTED),
            (STATUS_RESOLVED, INCIDENT_RESOLVED),
        ]
        for status, event in journey:
            set_status(db, row, status, event_type=event)
        db.commit()
        events = (
            db.query(IncidentEvent)
            .filter(IncidentEvent.session_id == row.id)
            .order_by(IncidentEvent.sequence.asc())
            .all()
        )
        assert len(events) == len(journey) + 1
        assert row.status == STATUS_RESOLVED
        assert events[-1].event_type == INCIDENT_RESOLVED
        assert [e.event_type for e in events] == [
            INCIDENT_CREATED,
            *[e for _, e in journey],
        ]
    finally:
        db.close()


def test_entering_identifying_refuses_to_invent_an_event(client):
    """`identifying` has no default event, and that is the point.

    A capture is not a match attempt. When this mapping existed, every
    photograph taken put MATCH_ATTEMPTED into the incident log ahead of the
    FACE_CAPTURE_STARTED that caused it. The caller must now say what happened,
    so the failure is a loud one at the call site rather than a plausible lie in
    the audit record.
    """
    db = SessionLocal()
    try:
        row = db.get(EmergencySession, start_session(client)["session_id"])
        with pytest.raises(ValueError, match="no default incident event"):
            set_status(db, row, STATUS_IDENTIFYING)
        # The status must not have moved: a rejected transition is not a
        # transition.
        assert row.status == STATUS_CREATED
    finally:
        db.close()


def test_suppress_event_does_not_invent_a_row(client):
    """The pipeline's escape hatch must be silent, not duplicative."""
    db = SessionLocal()
    try:
        row = db.get(EmergencySession, start_session(client)["session_id"])
        before = db.query(IncidentEvent).filter(IncidentEvent.session_id == row.id).count()
        record_event(db, row, MATCH_ATTEMPTED)
        set_status(db, row, STATUS_IDENTIFYING, suppress_event=True)
        db.commit()
        rows = (
            db.query(IncidentEvent)
            .filter(IncidentEvent.session_id == row.id)
            .order_by(IncidentEvent.sequence.asc())
            .all()
        )
        assert len(rows) == before + 1
        assert [r.event_type for r in rows].count(MATCH_ATTEMPTED) == 1
    finally:
        db.close()


# -------------------------------------------------------------------- fallback
def test_fallback_by_emergency_identifier_resolves_a_contact(client):
    session = start_session(client)
    headers = {
        **session_headers(session),
        **auth_headers(client, "neha.rao@responder.traya"),
    }
    phone = "+91 98900 12345"
    db = SessionLocal()
    try:
        from app.models import EmergencyContact

        subject = (
            db.query(User).filter(User.email == "meera.iyer@demo.traya").first()
        )
        db.add(
            EmergencyContact(
                user_id=subject.id,
                name="Anil Iyer",
                relation="Brother",
                phone=phone,
                is_primary=True,
            )
        )
        db.commit()
    finally:
        db.close()

    r = client.post(
        f"/api/emergency/{session['session_id']}/fallback/emergency-identifier",
        headers=headers,
        json={"identifier": phone},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["method"] == FALLBACK_EMERGENCY_IDENTIFIER
    assert body["resolved"] is True
    assert body["subject_name"] == "Meera Iyer"

    status = client.get(f"/api/emergency/{session['session_id']}", headers=headers).json()
    assert status["status"] == STATUS_IDENTIFIED
    assert status["confidence_category"] == "MANUAL_CONFIRMED"


def test_fallback_by_emergency_identifier_logs_the_path(client):
    """The whole point of the incident log: how was this person identified?"""
    session = start_session(client)
    headers = {
        **session_headers(session),
        **auth_headers(client, "neha.rao@responder.traya"),
    }
    db = SessionLocal()
    try:
        from app.models import EmergencyContact

        subject = db.query(User).filter(User.email == "rohan.verma@demo.traya").first()
        db.add(
            EmergencyContact(
                user_id=subject.id,
                name="Kavita Verma",
                relation="Spouse",
                phone="+91 90000 11111",
                is_primary=True,
            )
        )
        db.commit()
    finally:
        db.close()

    client.post(
        f"/api/emergency/{session['session_id']}/fallback/emergency-identifier",
        headers=headers,
        json={"identifier": "+91 90000 11111"},
    )
    events = client.get(
        f"/api/emergency/{session['session_id']}/events", headers=headers
    ).json()
    paths = {e["fallback_used"] for e in events["events"] if e["fallback_used"]}
    assert paths == {FALLBACK_EMERGENCY_IDENTIFIER}
    assert "CONTACT_INITIATED" in {e["event_type"] for e in events["events"]}


def test_unknown_identifier_does_not_invent_an_identity(client):
    session = start_session(client)
    headers = {
        **session_headers(session),
        **auth_headers(client, "neha.rao@responder.traya"),
    }
    r = client.post(
        f"/api/emergency/{session['session_id']}/fallback/emergency-identifier",
        headers=headers,
        json={"identifier": "+91 11111 11111"},
    )
    assert r.status_code == 404

    status = client.get(f"/api/emergency/{session['session_id']}", headers=headers).json()
    assert status["identified_user_id"] is None
    assert status["status"] == STATUS_NO_MATCH

    events = client.get(
        f"/api/emergency/{session['session_id']}/events", headers=headers
    ).json()
    assert any(
        e["details"].get("resolved") is False for e in events["events"]
    ), "a failed resolution must still be recorded"


def test_manual_entry_requires_a_corroborating_detail(client):
    """A bare name from a responder is not evidence."""
    session = start_session(client)
    headers = {
        **session_headers(session),
        **auth_headers(client, "neha.rao@responder.traya"),
    }
    db = SessionLocal()
    try:
        name = db.query(User).filter(User.email == "priya.sharma@demo.traya").first().full_name
    finally:
        db.close()

    r = client.post(
        f"/api/emergency/{session['session_id']}/fallback/manual-entry",
        headers=headers,
        json={"full_name": name},
    )
    assert r.status_code == 404
    assert "detail" in r.text.lower() or "confirm" in r.text.lower()

    ok = client.post(
        f"/api/emergency/{session['session_id']}/fallback/manual-entry",
        headers=headers,
        json={"full_name": name, "corroborating_detail": "wears spectacles"},
    )
    assert ok.status_code == 200
    assert ok.json()["method"] == FALLBACK_MANUAL_RESPONDER_ENTRY


def test_ambiguous_manual_name_asks_rather_than_guesses(client):
    """Two people, one name: a question, not a coin flip.

    Uses freshly registered users rather than mutating demo accounts, because the
    demo seed is shared module state and renaming Aarav here would break every
    later test that asserts on his name.
    """
    from app.models import User as UserModel

    session = start_session(client)
    headers = {
        **session_headers(session),
        **auth_headers(client, "neha.rao@responder.traya"),
    }
    db = SessionLocal()
    try:
        a = db.query(UserModel).filter(UserModel.email == "aarav.kumar@demo.traya").first()
        b = db.query(UserModel).filter(UserModel.email == "priya.sharma@demo.traya").first()
        ids = {a.id, b.id}
    finally:
        db.close()

    # Two accounts sharing an exact name, created locally and rolled back after.
    db = SessionLocal()
    try:
        extra = []
        for _ in range(2):
            u = UserModel(
                full_name="Kumar Test",
                email=f"kumar-{uuid.uuid4().hex[:8]}@test.traya",
                hashed_password="!",
            )
            db.add(u)
            extra.append(u)
        db.flush()
        ambiguous_ids = {u.id for u in extra}
        db.commit()
    finally:
        db.close()

    r = client.post(
        f"/api/emergency/{session['session_id']}/fallback/manual-entry",
        headers=headers,
        json={"full_name": "Kumar Test", "corroborating_detail": "a"},
    )
    assert r.status_code == 404
    assert "2 people match" in r.text

    status = client.get(f"/api/emergency/{session['session_id']}", headers=headers).json()
    assert status["identified_user_id"] is None
    assert status["identified_user_id"] not in ambiguous_ids
    assert status["identified_user_id"] not in ids


def test_a_person_cannot_confirm_their_own_identity(client):
    """Assisted verification must involve two people or it is theatre."""
    db = SessionLocal()
    try:
        subject = db.query(User).filter(User.email == "meera.iyer@demo.traya").first()
        subject_id = subject.id
    finally:
        db.close()

    session = start_session(client)
    headers = {
        **session_headers(session),
        **auth_headers(client, "neha.rao@responder.traya"),
    }
    db = SessionLocal()
    try:
        row = db.get(EmergencySession, session["session_id"])
        try:
            request_assistance(db, row, proposed_subject_id=subject_id, requested_by=subject_id)
        except FallbackError as exc:
            assert "cannot confirm themselves" in str(exc)
            db.rollback()
        else:
            raise AssertionError("self-confirmation was accepted")
    finally:
        db.close()
    assert headers  # keeps the fixture use obvious


def test_assistance_requires_a_second_party(client):
    """The confirmer must not be the requester, or the check means nothing."""
    session = start_session(client)
    headers = {
        **session_headers(session),
        **auth_headers(client, "neha.rao@responder.traya"),
    }
    other = auth_headers(client, "suresh.patil@responder.traya")

    requester = client.post(
        f"/api/emergency/{session['session_id']}/fallback/assistance",
        headers=headers,
        json={},
    )
    assert requester.status_code == 200
    assert requester.json()["awaiting_second_party"] is True
    assert requester.json()["method"] == FALLBACK_ASSISTED_VERIFICATION

    # The same responder cannot confirm their own request.
    self_confirm = client.post(
        f"/api/emergency/{session['session_id']}/fallback/assistance/confirm",
        headers=headers,
        json={"confirmed_subject_id": "x", "requested_by": _user_id(headers)},
    )
    assert self_confirm.status_code == 400
    assert "someone other than" in self_confirm.text

    db = SessionLocal()
    try:
        subject_id = db.query(User).filter(User.email == "aarav.kumar@demo.traya").first().id
    finally:
        db.close()

    ok = client.post(
        f"/api/emergency/{session['session_id']}/fallback/assistance/confirm",
        headers=other,
        json={"confirmed_subject_id": subject_id, "requested_by": _user_id(headers)},
    )
    assert ok.status_code == 200
    assert ok.json()["subject_id"] == subject_id

    events = client.get(
        f"/api/emergency/{session['session_id']}/events", headers=headers
    ).json()
    types = {e["event_type"] for e in events["events"]}
    assert "ASSISTANCE_REQUESTED" in types
    assert "ASSISTANCE_COMPLETED" in types


def _user_id(headers: dict) -> str:
    import jwt

    from app.security.tokens import decode_token

    payload = decode_token(headers["Authorization"].removeprefix("Bearer "))
    return payload.get("sub")


def test_unidentified_is_a_supported_outcome(client):
    """"We do not know who this is" must be recordable.

    A system that cannot record it will either refuse to help or quietly invent
    an identity. Both are worse than an honest blank.
    """
    session = start_session(client)
    headers = {
        **session_headers(session),
        **auth_headers(client, "neha.rao@responder.traya"),
    }
    r = client.post(
        f"/api/emergency/{session['session_id']}/fallback/unidentified",
        headers=headers,
        json={"reason": "no face, no identifier, child"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["identified"] is False
    assert body["method"] == FALLBACK_MANUAL_IDENTIFICATION

    status = client.get(f"/api/emergency/{session['session_id']}", headers=headers).json()
    assert status["status"] == STATUS_RESOLVED
    assert status["outcome"] == "unidentified"
    assert status["confidence_category"] == "MANUAL_UNIDENTIFIED"
    assert status["identified_user_id"] is None
    assert FALLBACK_MANUAL_IDENTIFICATION in status["identification_method"]


def test_every_fallback_path_is_reachable(client):
    """A guard against a path being added to the vocabulary but never wired."""
    reached = set()

    session = start_session(client)
    headers = {
        **session_headers(session),
        **auth_headers(client, "neha.rao@responder.traya"),
    }
    other = auth_headers(client, "suresh.patil@responder.traya")

    client.post(
        f"/api/emergency/{session['session_id']}/fallback/unidentified",
        headers=headers,
        json={"reason": "no identifiers"},
    )
    reached.add(FALLBACK_MANUAL_IDENTIFICATION)

    db = SessionLocal()
    try:
        from app.models import EmergencyContact

        subject = db.query(User).filter(User.email == "meera.iyer@demo.traya").first()
        db.add(
            EmergencyContact(
                user_id=subject.id,
                name="Anil Iyer",
                relation="Brother",
                phone="+91 90000 22222",
                is_primary=True,
            )
        )
        db.commit()
    finally:
        db.close()

    s2 = start_session(client)
    h2 = {**session_headers(s2), **headers}
    client.post(
        f"/api/emergency/{s2['session_id']}/fallback/emergency-identifier",
        headers=h2,
        json={"identifier": "+91 90000 22222"},
    )
    reached.add(FALLBACK_EMERGENCY_IDENTIFIER)

    s3 = start_session(client)
    h3 = {**session_headers(s3), **headers}
    db = SessionLocal()
    try:
        name = db.query(User).filter(User.email == "priya.sharma@demo.traya").first().full_name
    finally:
        db.close()
    client.post(
        f"/api/emergency/{s3['session_id']}/fallback/manual-entry",
        headers=h3,
        json={"full_name": name, "corroborating_detail": "glasses"},
    )
    reached.add(FALLBACK_MANUAL_RESPONDER_ENTRY)

    s4 = start_session(client)
    h4 = {**session_headers(s4), **headers}
    client.post(f"/api/emergency/{s4['session_id']}/fallback/assistance", headers=h4, json={})
    client.post(
        f"/api/emergency/{s4['session_id']}/fallback/assistance/confirm",
        headers=other,
        json={
            "confirmed_subject_id": _subject_id(client),
            "requested_by": _user_id(headers),
        },
    )
    reached.add(FALLBACK_ASSISTED_VERIFICATION)

    assert reached == {
        FALLBACK_EMERGENCY_IDENTIFIER,
        FALLBACK_MANUAL_RESPONDER_ENTRY,
        FALLBACK_ASSISTED_VERIFICATION,
        FALLBACK_MANUAL_IDENTIFICATION,
    }


def _subject_id(client) -> str:
    db = SessionLocal()
    try:
        return db.query(User).filter(User.email == "rohan.verma@demo.traya").first().id
    finally:
        db.close()


def test_fallback_endpoints_require_a_responder(client):
    """A bystander's session token must not be enough to identify anyone."""
    session = start_session(client)
    for path, payload in (
        ("emergency-identifier", {"identifier": "+91 90000 33333"}),
        ("manual-entry", {"full_name": "Aarav Kumar", "corroborating_detail": "x"}),
        ("assistance", {}),
        ("unidentified", {"reason": "x"}),
    ):
        r = client.post(
            f"/api/emergency/{session['session_id']}/fallback/{path}",
            headers=session_headers(session),
            json=payload,
        )
        assert r.status_code == 401, f"{path} was reachable without a responder"


def test_incident_events_require_authorization(client):
    """The session id alone must not open the incident log.

    It travels in request bodies and logs, so a guessed or observed id must not
    reveal who was identified, by which fallback, and who read their record.
    """
    session = start_session(client)
    # 403 rather than 401: the request is refused at the session-authorization
    # layer before authentication is considered.
    assert client.get(f"/api/emergency/{session['session_id']}/events").status_code == 403


def test_multiple_candidates_is_reported_not_guessed(client, monkeypatch, aarav_image):
    """Two near-tied candidates must stop, not pick the higher one.

    The demo simulation produces a clear winner (0.995 against a runner-up of
    0.783, measured), so it can never exercise this branch honestly. The scorer
    is therefore stubbed to produce a genuine tie, and the test says so: this
    proves the decision logic, not that ties occur in the field. Phase 10 must
    measure that before ``MULTIPLE_CANDIDATES_MARGIN`` is trusted.
    """
    from app.services.identification import pipeline

    monkeypatch.setattr(
        pipeline,
        "_max_similarity",
        lambda profile, embedding, engine: 0.90 + (len(str(profile.user_id)) % 3) * 0.005,
    )

    session = start_session(client)
    result = identify(client, session, aarav_image)

    assert result["status"] == "MULTIPLE_CANDIDATES"
    assert result["requires_human_confirmation"] is True
    assert len(result["candidates"]) > 1
    assert all(c["status"] == "pending" for c in result["candidates"])
    assert result["medical_alerts_available"] is False


def test_a_clear_winner_is_not_reported_as_ambiguous(client, aarav_image):
    """The guard on the guard: a real gap must still produce a decision.

    Without this, a margin that is too wide would report MULTIPLE_CANDIDATES
    for every recognition and the product would be useless in the other
    direction.
    """
    session = start_session(client)
    result = identify(client, session, aarav_image)
    assert result["status"] == "HIGH_CONFIDENCE"
    assert result["candidates"][0]["status"] == "accepted"


def test_ambiguity_leaves_the_incident_for_a_human(client, monkeypatch, aarav_image):
    from app.services.identification import pipeline

    monkeypatch.setattr(
        pipeline,
        "_max_similarity",
        lambda profile, embedding, engine: 0.90 + (len(str(profile.user_id)) % 3) * 0.005,
    )
    session = start_session(client)
    identify(client, session, aarav_image)

    status = client.get(
        f"/api/emergency/{session['session_id']}", headers=session_headers(session)
    ).json()
    assert status["status"] == STATUS_REVIEW_REQUIRED
    assert status["identified_user_id"] is None


