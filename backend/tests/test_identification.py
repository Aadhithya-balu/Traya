"""End-to-end identification flow tests (capture -> identify -> confirm)."""
from __future__ import annotations

from .conftest import (
    auth_headers,
    degraded_image,
    identify,
    make_user,
    session_headers,
    start_session,
)


def test_high_confidence_flow(client, aarav_image):
    login = client.post(
        "/api/auth/login",
        json={"email": "aarav.kumar@demo.traya", "password": "TrayaDemo#2026"},
    ).json()
    aarav_id = login["user"]["id"]

    session = start_session(client)
    sid = session["session_id"]
    hdr = session_headers(session)

    cap = client.post(f"/api/emergency/{sid}/capture", headers=hdr, json={"image": aarav_image})
    assert cap.status_code == 200
    assert cap.json()["usable_for_matching"] is True

    result = identify(client, session, aarav_image)
    assert result["status"] == "HIGH_CONFIDENCE"
    assert result["confidence"] >= 0.82
    assert result["medical_alerts_available"] is True
    assert result["requires_human_confirmation"] is False
    assert result["candidates"], "expected at least one candidate"
    assert result["candidates"][0]["user_id"] == aarav_id
    assert result["candidates"][0]["status"] == "accepted"
    assert "face" in result["method"]

    status = client.get(f"/api/emergency/{sid}", headers=hdr).json()
    assert status["status"] == "identified"
    assert status["outcome"] == "identified"
    assert status["identified_user_id"] == aarav_id


def test_medical_summary_requires_a_clinical_responder(client, aarav_image):
    """A successful face match must not hand clinical data to a session token.

    This is the Phase 7 security fix. Previously the endpoint ran on
    ``_get_active_session`` alone, so anyone who could start an emergency and
    photograph a matching face could read another person's allergies, blood
    group and medications. A session token proves nothing about the holder.
    """
    session = start_session(client)
    sid = session["session_id"]
    identify(client, session, aarav_image)

    # The session token alone is not enough, even after a high-confidence match.
    anonymous = client.get(
        f"/api/emergency/{sid}/medical-summary", headers=session_headers(session)
    )
    assert anonymous.status_code == 401

    # A bystander is not a clinician.
    registered = client.get(
        f"/api/emergency/{sid}/medical-summary",
        headers=make_user(client)["headers"],
    )
    assert registered.status_code == 403


def test_medical_summary_denied_to_police_responder(client, aarav_image):
    """Identification is necessary but not sufficient.

    Police legitimately stand for identity and contact data. They do not get the
    clinical history, so ``view_medical_alerts`` is what opens the endpoint -
    not the face match.
    """
    session = start_session(client)
    sid = session["session_id"]
    identify(client, session, aarav_image)

    police = auth_headers(client, "suresh.patil@responder.traya")
    r = client.get(f"/api/emergency/{sid}/medical-summary", headers=police)
    assert r.status_code == 403

    # The same responder still gets the profile they are entitled to.
    profile = client.get(f"/api/emergency/{sid}/responder-profile", headers=police)
    assert profile.status_code == 200
    assert profile.json()["full_name"] == "Aarav Kumar"


def test_medical_summary_after_high_confidence(client, aarav_image):
    session = start_session(client)
    sid = session["session_id"]
    identify(client, session, aarav_image)

    headers = auth_headers(client, "neha.rao@responder.traya")
    r = client.get(f"/api/emergency/{sid}/medical-summary", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["full_name"] == "Aarav Kumar"
    assert body["blood_group"] == "O+"
    assert "Penicillin" in body["critical_allergies"]
    assert "Epilepsy" in body["critical_conditions"]
    assert body["emergency_contact"]["name"] == "Sneha Kumar"


def test_medical_access_is_written_to_the_incident_log(client, aarav_image):
    """Reading a clinical summary is an event, not just an audit row.

    The audit trail records that it happened. The incident log records who read
    whose record, so "how was this person identified and who then looked at
    their medical data" is answerable from the incident alone.
    """
    session = start_session(client)
    sid = session["session_id"]
    identify(client, session, aarav_image)
    headers = auth_headers(client, "neha.rao@responder.traya")
    client.get(f"/api/emergency/{sid}/medical-summary", headers=headers)

    events = client.get(
        f"/api/emergency/{sid}/events",
        headers={**session_headers(session), **headers},
    )
    assert events.status_code == 200
    types = [e["event_type"] for e in events.json()["events"]]
    assert "PROFILE_ACCESSED" in types


def test_medical_summary_gated_without_identification(client):
    session = start_session(client)
    r = client.get(
        f"/api/emergency/{session['session_id']}/medical-summary",
        headers=auth_headers(client, "neha.rao@responder.traya"),
    )
    assert r.status_code == 403


def test_no_match_for_unknown_person(client, unknown_image):
    session = start_session(client)
    result = identify(client, session, unknown_image)
    assert result["status"] == "NO_MATCH"
    assert result["candidates"] == []
    assert result["medical_alerts_available"] is False


def test_multiple_faces_rejected(client):
    image = degraded_image("aarav-kumar-demo", faces=2)
    session = start_session(client)
    result = identify(client, session, image)
    assert result["status"] == "MULTIPLE_FACES"
    assert result["face_count"] == 2


def test_poor_quality_rejected(client):
    image = degraded_image("aarav-kumar-demo", dark=True, blur=True, occluded=0.5)
    session = start_session(client)
    result = identify(client, session, image)
    assert result["status"] == "POOR_QUALITY"


def test_review_required_for_degraded_capture(client):
    image = degraded_image("aarav-kumar-demo", noise=0.30, occluded=0.30)
    session = start_session(client)
    result = identify(client, session, image)
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["requires_human_confirmation"] is True
    assert result["candidates"], "expected candidates for review"


def test_confirm_requires_confirm_identity_permission(client):
    """A bystander-style account may not confirm a candidate, even holding a token."""
    image = degraded_image("aarav-kumar-demo", noise=0.30, occluded=0.30)
    session = start_session(client)
    result = identify(client, session, image)
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
    result = identify(client, session, image)
    candidate = result["candidates"][0]

    headers = auth_headers(client, "neha.rao@responder.traya")
    r = client.post(
        f"/api/emergency/{session['session_id']}/confirm",
        headers=headers,
        json={"candidate_user_id": candidate["user_id"], "accept": True},
    )
    assert r.status_code == 200

    status = client.get(f"/api/emergency/{session['session_id']}", headers=headers).json()
    assert status["status"] == "identified"
    assert status["outcome"] == "identified"
    assert status["confidence_category"] == "HUMAN_CONFIRMED"
    assert status["identified_user_id"] == candidate["user_id"]

    summary = client.get(
        f"/api/emergency/{session['session_id']}/medical-summary", headers=headers
    )
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


def test_responder_profile_requires_permission(client, aarav_image):
    session = start_session(client)
    sid = session["session_id"]
    identify(client, session, aarav_image)

    assert client.get(f"/api/emergency/{sid}/responder-profile").status_code == 401
    assert (
        client.get(
            f"/api/emergency/{sid}/responder-profile",
            headers=auth_headers(client, "aarav.kumar@demo.traya"),
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


def test_police_get_responder_profile(client, aarav_image):
    """Police hold responder standing for identity and contact data."""
    session = start_session(client)
    identify(client, session, aarav_image)
    headers = auth_headers(client, "suresh.patil@responder.traya")
    r = client.get(f"/api/emergency/{session['session_id']}/responder-profile", headers=headers)
    assert r.status_code == 200
    assert r.json()["full_name"] == "Aarav Kumar"


def test_contact_action_after_match(client, aarav_image):
    session = start_session(client)
    sid = session["session_id"]
    identify(client, session, aarav_image)

    r = client.post(
        f"/api/emergency/{sid}/contact",
        headers=session_headers(session),
        json={"action": "call"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["action"] == "call"
    assert body["contact_name"] == "Sneha Kumar"


def test_contact_action_gated_without_match(client):
    session = start_session(client)
    r = client.post(
        f"/api/emergency/{session['session_id']}/contact",
        headers=session_headers(session),
        json={"action": "sms"},
    )
    assert r.status_code == 403
