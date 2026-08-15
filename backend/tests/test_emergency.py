"""Emergency session lifecycle, validation and location/timeline tests."""
from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta

from app.database.session import SessionLocal
from app.models import EmergencySession

from .conftest import start_session


def test_start_session(client):
    session = start_session(client)
    assert session["session_id"]
    assert session["session_code"].startswith("ER-")
    assert session["status"] == "active"
    assert session["expires_at"]


def test_session_status(client):
    session = start_session(client)
    r = client.get(f"/api/emergency/{session['session_id']}")
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] == session["session_id"]
    assert body["status"] == "active"


def test_session_not_found(client):
    assert client.get("/api/emergency/nonexistent").status_code == 404


def test_expired_session_returns_410(client):
    db = SessionLocal()
    past = EmergencySession(
        session_code="ER-TEST-EXPIRED",
        access_type="public",
        status="active",
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
    r = client.post(f"/api/emergency/{session['session_id']}/capture", json={"image": "!!!!not-base64!!!!"})
    assert r.status_code == 422


def test_capture_rejects_oversized(client):
    session = start_session(client)
    big = base64.b64encode(b"\xff\xd8" + b"\x00" * (7 * 1024 * 1024)).decode()
    r = client.post(f"/api/emergency/{session['session_id']}/capture", json={"image": big})
    assert r.status_code == 413


def test_capture_rejects_wrong_format(client):
    session = start_session(client)
    png_junk = base64.b64encode(b"GIF89a" + b"\x00" * 64).decode()
    r = client.post(f"/api/emergency/{session['session_id']}/capture", json={"image": png_junk})
    assert r.status_code == 422


def test_location_capture_and_timeline(client):
    session = start_session(client)
    sid = session["session_id"]

    r = client.post(f"/api/emergency/{sid}/location", json={"latitude": 28.6139, "longitude": 77.209, "source": "gps"})
    assert r.status_code == 200
    loc = r.json()
    assert loc["latitude"] == 28.6139
    assert loc["source"] == "gps"

    timeline = client.get(f"/api/emergency/{sid}/timeline").json()
    actions = [ev["action"] for ev in timeline]
    assert "location.shared" in actions or any("location" in a for a in actions)


def test_location_validation(client):
    session = start_session(client)
    r = client.post(f"/api/emergency/{session['session_id']}/location", json={"latitude": 999, "longitude": 0})
    assert r.status_code == 422


def test_timeline_records_session_start(client):
    session = start_session(client)
    timeline = client.get(f"/api/emergency/{session['session_id']}/timeline").json()
    assert any(ev["action"] == "session.started" for ev in timeline)


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
