"""End-to-end identification flow tests (capture -> identify -> confirm)."""
from __future__ import annotations

from .conftest import auth_headers, degraded_image, identify, make_user, start_session


def test_high_confidence_flow(client, aarav_image):
    login = client.post(
        "/api/auth/login",
        json={"email": "aarav.kumar@demo.traya", "password": "TrayaDemo#2026"},
    ).json()
    aarav_id = login["user"]["id"]

    session = start_session(client)
    sid = session["session_id"]

    cap = client.post(f"/api/emergency/{sid}/capture", json={"image": aarav_image})
    assert cap.status_code == 200
    assert cap.json()["usable_for_matching"] is True

    result = identify(client, sid, aarav_image)
    assert result["status"] == "HIGH_CONFIDENCE"
    assert result["confidence"] >= 0.82
    assert result["medical_alerts_available"] is True
    assert result["requires_human_confirmation"] is False
    assert result["candidates"], "expected at least one candidate"
    assert result["candidates"][0]["user_id"] == aarav_id
    assert result["candidates"][0]["status"] == "accepted"
    assert "face" in result["method"]

    status = client.get(f"/api/emergency/{sid}").json()
    assert status["status"] == "completed"
    assert status["outcome"] == "identified"
    assert status["identified_user_id"] == aarav_id


def test_medical_summary_after_high_confidence(client, aarav_image):
    session = start_session(client)
    sid = session["session_id"]
    identify(client, sid, aarav_image)

    r = client.get(f"/api/emergency/{sid}/medical-summary")
    assert r.status_code == 200
    body = r.json()
    assert body["full_name"] == "Aarav Kumar"
    assert body["blood_group"] == "O+"
    assert "Penicillin" in body["critical_allergies"]
    assert "Epilepsy" in body["critical_conditions"]
    assert body["emergency_contact"]["name"] == "Sneha Kumar"


def test_medical_summary_gated_without_identification(client):
    session = start_session(client)
    r = client.get(f"/api/emergency/{session['session_id']}/medical-summary")
    assert r.status_code == 403


def test_no_match_for_unknown_person(client, unknown_image):
    session = start_session(client)
    result = identify(client, session["session_id"], unknown_image)
    assert result["status"] == "NO_MATCH"
    assert result["candidates"] == []
    assert result["medical_alerts_available"] is False


def test_multiple_faces_rejected(client):
    image = degraded_image("aarav-kumar-demo", faces=2)
    session = start_session(client)
    result = identify(client, session["session_id"], image)
    assert result["status"] == "MULTIPLE_FACES"
    assert result["face_count"] == 2


def test_poor_quality_rejected(client):
    image = degraded_image("aarav-kumar-demo", dark=True, blur=True, occluded=0.5)
    session = start_session(client)
    result = identify(client, session["session_id"], image)
    assert result["status"] == "POOR_QUALITY"


def test_review_required_for_degraded_capture(client):
    image = degraded_image("aarav-kumar-demo", noise=0.30, occluded=0.30)
    session = start_session(client)
    result = identify(client, session["session_id"], image)
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["requires_human_confirmation"] is True
    assert result["candidates"], "expected candidates for review"


def test_confirm_requires_responder_role(client):
    image = degraded_image("aarav-kumar-demo", noise=0.30, occluded=0.30)
    session = start_session(client)
    result = identify(client, session["session_id"], image)
    candidate = result["candidates"][0]

    registered = make_user(client)
    r = client.post(
        f"/api/emergency/{session['session_id']}/confirm",
        headers=registered["headers"],
        json={"candidate_user_id": candidate["user_id"], "accept": True},
    )
    assert r.status_code == 403


def test_confirm_by_responder_completes_session(client):
    image = degraded_image("aarav-kumar-demo", noise=0.30, occluded=0.30)
    session = start_session(client)
    result = identify(client, session["session_id"], image)
    candidate = result["candidates"][0]

    headers = auth_headers(client, "neha.rao@responder.traya")
    r = client.post(
        f"/api/emergency/{session['session_id']}/confirm",
        headers=headers,
        json={"candidate_user_id": candidate["user_id"], "accept": True},
    )
    assert r.status_code == 200

    status = client.get(f"/api/emergency/{session['session_id']}").json()
    assert status["status"] == "completed"
    assert status["outcome"] == "identified"
    assert status["confidence_category"] == "HUMAN_CONFIRMED"
    assert status["identified_user_id"] == candidate["user_id"]

    summary = client.get(f"/api/emergency/{session['session_id']}/medical-summary")
    assert summary.status_code == 200


def test_confirm_unknown_candidate_404(client):
    session = start_session(client)
    headers = auth_headers(client, "neha.rao@responder.traya")
    r = client.post(
        f"/api/emergency/{session['session_id']}/confirm",
        headers=headers,
        json={"candidate_user_id": "00000000-0000-0000-0000-000000000000", "accept": True},
    )
    assert r.status_code == 404


def test_responder_profile_requires_role(client, aarav_image):
    session = start_session(client)
    sid = session["session_id"]
    identify(client, sid, aarav_image)

    assert client.get(f"/api/emergency/{sid}/responder-profile").status_code == 401
    assert (
        client.get(
            f"/api/emergency/{sid}/responder-profile", headers=auth_headers(client, "aarav.kumar@demo.traya")
        ).status_code
        == 403
    )
    headers = auth_headers(client, "neha.rao@responder.traya")
    r = client.get(f"/api/emergency/{sid}/responder-profile", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["full_name"] == "Aarav Kumar"
    assert len(body["visible_features"]) >= 1
    assert len(body["all_contacts"]) >= 1


def test_contact_action_after_match(client, aarav_image):
    session = start_session(client)
    sid = session["session_id"]
    identify(client, sid, aarav_image)

    r = client.post(f"/api/emergency/{sid}/contact", json={"action": "call"})
    assert r.status_code == 200
    body = r.json()
    assert body["action"] == "call"
    assert body["contact_name"] == "Sneha Kumar"


def test_contact_action_gated_without_match(client):
    session = start_session(client)
    r = client.post(f"/api/emergency/{session['session_id']}/contact", json={"action": "sms"})
    assert r.status_code == 403
