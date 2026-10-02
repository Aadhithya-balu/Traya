"""Emergency session lifecycle, validation, access control and location."""
from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta

from app.database.session import SessionLocal
from app.models import EmergencySession

from .conftest import auth_headers, session_headers, start_session


def test_start_session(client):
    session = start_session(client)
    assert session["session_id"]
    assert session["session_code"].startswith("ER-")
    assert session["status"] == "created"
    assert session["expires_at"]
    assert session["session_token"]


def test_session_token_is_never_stored_in_the_clear(client):
    """Only the hash is persisted, so a database leak is not session access."""
    session = start_session(client)
    db = SessionLocal()
    try:
        row = db.get(EmergencySession, session["session_id"])
        assert row.access_token_hash is not None
        assert row.access_token_hash != session["session_token"]
        assert len(row.access_token_hash) == 64
    finally:
        db.close()


def test_session_status(client):
    session = start_session(client)
    r = client.get(
        f"/api/emergency/{session['session_id']}", headers=session_headers(session)
    )
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] == session["session_id"]
    assert body["status"] == "created"


def test_session_not_found(client):
    assert client.get("/api/emergency/nonexistent").status_code == 404


def test_session_id_alone_does_not_grant_access(client):
    """A leaked session id must not expose the session.

    Session ids travel in request bodies and logs, so possession of one is
    not treated as authorization.
    """
    session = start_session(client)
    sid = session["session_id"]
    assert client.get(f"/api/emergency/{sid}").status_code == 403
    r = client.post(
        f"/api/emergency/{sid}/identify", json={"image": "x" * 64}
    )
    assert r.status_code == 403


def test_wrong_session_token_is_rejected(client):
    session = start_session(client)
    r = client.get(
        f"/api/emergency/{session['session_id']}",
        headers={"X-TRAYA-Session-Token": "not-the-token"},
    )
    assert r.status_code == 403


def test_token_of_another_session_is_rejected(client):
    """Tokens are per-session, not global."""
    first = start_session(client)
    second = start_session(client)
    r = client.get(
        f"/api/emergency/{second['session_id']}",
        headers=session_headers(first),
    )
    assert r.status_code == 403


def test_signed_in_responder_may_join_a_session(client, responder_headers):
    """A responder confirming a candidate is not the bystander who opened it."""
    session = start_session(client)
    r = client.get(f"/api/emergency/{session['session_id']}", headers=responder_headers)
    assert r.status_code == 200


def test_account_without_standing_cannot_join_a_session(client, auditor_headers):
    """A token is required, but possession of one is not a backdoor: an
    account with no identification standing still cannot read the session."""
    session = start_session(client)
    r = client.get(f"/api/emergency/{session['session_id']}", headers=auditor_headers)
    assert r.status_code == 403


def test_denied_access_is_audited(client):
    session = start_session(client)
    sid = session["session_id"]
    client.get(f"/api/emergency/{sid}/timeline")
    db = SessionLocal()
    try:
        from app.models import AuditLog

        denied = (
            db.query(AuditLog)
            .filter(AuditLog.session_id == sid, AuditLog.action == "session.access_denied")
            .count()
        )
        assert denied >= 1
    finally:
        db.close()


def test_expired_session_returns_410(client):
    db = SessionLocal()
    past = EmergencySession(
        session_code="ER-TEST-EXPIRED",
        access_type="public",
        status="created",
        expires_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    db.add(past)
    db.commit()
    sid = past.id
    db.close()

    r = client.get(f"/api/emergency/{sid}")
    assert r.status_code == 410


def test_capture_rejects_invalid_base64(client):
    session = start_session(client)
    r = client.post(
        f"/api/emergency/{session['session_id']}/capture",
        headers=session_headers(session),
        json={"image": "!!!!not-base64!!!!"},
    )
    assert r.status_code == 422


def test_capture_rejects_oversized(client):
    session = start_session(client)
    big = base64.b64encode(b"\xff\xd8" + b"\x00" * (7 * 1024 * 1024)).decode()
    r = client.post(
        f"/api/emergency/{session['session_id']}/capture",
        headers=session_headers(session),
        json={"image": big},
    )
    assert r.status_code == 413


def test_capture_rejects_wrong_format(client):
    session = start_session(client)
    png_junk = base64.b64encode(b"GIF89a" + b"\x00" * 64).decode()
    r = client.post(
        f"/api/emergency/{session['session_id']}/capture",
        headers=session_headers(session),
        json={"image": png_junk},
    )
    assert r.status_code == 422


def test_location_capture_and_timeline(client):
    session = start_session(client)
    sid = session["session_id"]
    hdr = session_headers(session)

    r = client.post(
        f"/api/emergency/{sid}/location",
        headers=hdr,
        json={"latitude": 28.6139, "longitude": 77.209, "source": "gps"},
    )
    assert r.status_code == 200
    loc = r.json()
    assert loc["latitude"] == 28.6139
    assert loc["source"] == "gps"

    timeline = client.get(f"/api/emergency/{sid}/timeline", headers=hdr).json()
    actions = [ev["action"] for ev in timeline]
    assert "location.shared" in actions or any("location" in a for a in actions)


def test_location_validation(client):
    session = start_session(client)
    r = client.post(
        f"/api/emergency/{session['session_id']}/location",
        headers=session_headers(session),
        json={"latitude": 999, "longitude": 0},
    )
    assert r.status_code == 422


def test_timeline_records_session_start(client):
    session = start_session(client)
    timeline = client.get(
        f"/api/emergency/{session['session_id']}", headers=session_headers(session)
    )
    assert timeline.status_code == 200
    events = client.get(
        f"/api/emergency/{session['session_id']}/timeline",
        headers=session_headers(session),
    ).json()
    assert any(ev["action"] == "session.started" for ev in events)


def test_hospitals_nearby_delhi(client):
    r = client.get("/api/hospitals/nearby", params={"lat": 28.6139, "lng": 77.209, "radius_km": 30})
    assert r.status_code == 200
    hospitals = r.json()
    assert len(hospitals) >= 2
    assert all(h["distance_km"] <= 30 for h in hospitals)
    names = [h["name"] for h in hospitals]
    assert any("Delhi" in n or "Safdarjung" in n or "Karol" in n for n in names)


def test_hospitals_nearby_mumbai(client):
    r = client.get("/api/hospitals/nearby", params={"lat": 19.0596, "lng": 72.8295, "radius_km": 30})
    assert r.status_code == 200
    hospitals = r.json()
    assert len(hospitals) >= 4
    assert all(h["distance_km"] <= 30 for h in hospitals)
