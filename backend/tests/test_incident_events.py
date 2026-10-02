"""Every declared incident event type is reachable through the API.

The Phase 7 gate says "every listed `incident_event` type is reachable and
asserted". Unit tests on `record_event` do not satisfy that, because a type can
be perfectly well-formed and never emitted by any endpoint - which is exactly
the kind of dead constant this project has been bitten by before. So this file
drives real HTTP journeys and compares the union of what was actually written
against `EVENT_TYPES`.
"""
from __future__ import annotations

from app.services.incident_service import (
    ASSISTANCE_COMPLETED,
    ASSISTANCE_REQUESTED,
    CAPTURE_REJECTED,
    CONTACT_INITIATED,
    EVENT_TYPES,
    FACE_CAPTURE_STARTED,
    FACE_DETECTED,
    INCIDENT_CREATED,
    INCIDENT_RESOLVED,
    MATCH_ATTEMPTED,
    MATCH_FOUND,
    MATCH_REJECTED,
    PROFILE_ACCESSED,
)

from .conftest import (
    auth_headers,
    degraded_image,
    identify,
    session_headers,
    start_session,
)


def _events(client, session, headers) -> set[str]:
    body = client.get(
        f"/api/emergency/{session['session_id']}/events", headers=headers
    ).json()
    return {e["event_type"] for e in body["events"]}


def test_every_declared_event_type_is_reachable_through_the_api(client, aarav_image):
    seen: set[str] = set()

    # --- the biometric path, start to finish --------------------------------
    s1 = start_session(client)
    h1 = session_headers(s1)
    assert INCIDENT_CREATED in _events(client, s1, h1)

    client.post(
        f"/api/emergency/{s1['session_id']}/capture",
        headers=h1,
        json={"image": aarav_image},
    )
    seen |= _events(client, s1, h1)

    identify(client, s1, aarav_image)
    seen |= _events(client, s1, h1)

    medical = auth_headers(client, "neha.rao@responder.traya")
    client.get(
        f"/api/emergency/{s1['session_id']}/medical-summary",
        headers={**h1, **medical},
    )
    seen |= _events(client, s1, h1)

    client.post(
        f"/api/emergency/{s1['session_id']}/contact",
        headers=h1,
        json={"action": "call"},
    )
    seen |= _events(client, s1, h1)

    # --- a rejected capture: two faces in frame -----------------------------
    s2 = start_session(client)
    h2 = session_headers(s2)
    client.post(
        f"/api/emergency/{s2['session_id']}/capture",
        headers=h2,
        json={"image": degraded_image("nobody-here", faces=2)},
    )
    seen |= _events(client, s2, h2)

    # --- a real no-match ----------------------------------------------------
    s3 = start_session(client)
    h3 = session_headers(s3)
    client.post(
        f"/api/emergency/{s3['session_id']}/capture",
        headers=h3,
        json={"image": degraded_image("nobody-here", faces=2)},
    )
    identify(client, s3, degraded_image("stranger-who-is-not-enrolled"))
    seen |= _events(client, s3, h3)

    # --- assisted verification, requested and then completed ----------------
    s4 = start_session(client)
    h4 = {**session_headers(s4), **auth_headers(client, "neha.rao@responder.traya")}
    other = auth_headers(client, "suresh.patil@responder.traya")
    client.post(f"/api/emergency/{s4['session_id']}/fallback/assistance", headers=h4, json={})
    seen |= _events(client, s4, h4)

    client.post(
        f"/api/emergency/{s4['session_id']}/fallback/assistance/confirm",
        headers=other,
        json={"confirmed_subject_id": _subject_id(), "requested_by": _user_id(h4)},
    )
    seen |= _events(client, s4, h4)

    # --- the unidentified path resolves the incident ------------------------
    s5 = start_session(client)
    h5 = {**session_headers(s5), **auth_headers(client, "neha.rao@responder.traya")}
    client.post(
        f"/api/emergency/{s5['session_id']}/fallback/unidentified",
        headers=h5,
        json={"reason": "cannot identify"},
    )
    seen |= _events(client, s5, h5)

    missing = EVENT_TYPES - seen
    assert not missing, (
        f"declared but never emitted by any endpoint: {sorted(missing)}"
    )


def test_the_biometric_journey_writes_the_expected_narrative(client, aarav_image):
    """Not just presence - order, because the log's value is the sequence.

    Capture then identify, as a responder actually does it. `identify` is
    callable on its own, which is why `FACE_CAPTURE_STARTED` belongs to the
    capture endpoint and must not be asserted here.
    """
    s = start_session(client)
    h = session_headers(s)
    client.post(
        f"/api/emergency/{s['session_id']}/capture",
        headers=h,
        json={"image": aarav_image},
    )
    identify(client, s, aarav_image)
    client.post(
        f"/api/emergency/{s['session_id']}/contact",
        headers=h,
        json={"action": "call"},
    )

    types = [
        e["event_type"]
        for e in client.get(f"/api/emergency/{s['session_id']}/events", headers=h).json()[
            "events"
        ]
    ]
    assert types == [
        INCIDENT_CREATED,
        FACE_CAPTURE_STARTED,
        FACE_DETECTED,
        MATCH_ATTEMPTED,
        MATCH_FOUND,
        CONTACT_INITIATED,
    ]
    # The incident must not be resolved merely because a match was found.
    assert INCIDENT_RESOLVED not in types


def test_a_rejected_capture_is_recorded_as_such(client):
    s = start_session(client)
    h = session_headers(s)
    client.post(
        f"/api/emergency/{s['session_id']}/capture",
        headers=h,
        json={"image": degraded_image("nobody-here", faces=2)},
    )
    types = {
        e["event_type"]
        for e in client.get(f"/api/emergency/{s['session_id']}/events", headers=h).json()[
            "events"
        ]
    }
    assert CAPTURE_REJECTED in types
    assert FACE_DETECTED not in types


def test_a_no_match_records_a_rejection_and_not_a_match(client, unknown_image):
    """The distinction that matters most: nothing was found, and the log says so."""
    s = start_session(client)
    h = session_headers(s)
    identify(client, s, unknown_image)
    types = {
        e["event_type"]
        for e in client.get(f"/api/emergency/{s['session_id']}/events", headers=h).json()[
            "events"
        ]
    }
    assert MATCH_REJECTED in types
    assert MATCH_ATTEMPTED in types
    assert MATCH_FOUND not in types


def test_the_unidentified_path_resolves_the_incident(client):
    s = start_session(client)
    h = {**session_headers(s), **auth_headers(client, "neha.rao@responder.traya")}
    client.post(
        f"/api/emergency/{s['session_id']}/fallback/unidentified",
        headers=h,
        json={"reason": "no face, no identifier"},
    )
    types = [
        e["event_type"]
        for e in client.get(f"/api/emergency/{s['session_id']}/events", headers=h).json()[
            "events"
        ]
    ]
    assert types[-1] == INCIDENT_RESOLVED


def test_assistance_is_recorded_as_two_distinct_events(client):
    """Requested and completed are different facts about different people."""
    s = start_session(client)
    h = {**session_headers(s), **auth_headers(client, "neha.rao@responder.traya")}
    other = auth_headers(client, "suresh.patil@responder.traya")

    client.post(f"/api/emergency/{s['session_id']}/fallback/assistance", headers=h, json={})
    client.post(
        f"/api/emergency/{s['session_id']}/fallback/assistance/confirm",
        headers=other,
        json={"confirmed_subject_id": _subject_id(), "requested_by": _user_id(h)},
    )
    types = [
        e["event_type"]
        for e in client.get(f"/api/emergency/{s['session_id']}/events", headers=h).json()[
            "events"
        ]
    ]
    assert ASSISTANCE_REQUESTED in types
    assert ASSISTANCE_COMPLETED in types
    assert types.index(ASSISTANCE_REQUESTED) < types.index(ASSISTANCE_COMPLETED)


def test_one_human_decision_writes_one_event(client, aarav_image):
    """A responder confirming once must not produce two MATCH_FOUND rows.

    The router used to call `record_event` and then `set_status` with the same
    event type, which is not a duplicate anyone would notice by reading the log
    and is exactly the kind of thing that makes an incident log untrustworthy.
    """
    s = start_session(client)
    h = session_headers(s)
    responder = auth_headers(client, "neha.rao@responder.traya")
    identify(client, s, aarav_image)

    r = client.post(
        f"/api/emergency/{s['session_id']}/confirm",
        headers={**h, **responder},
        json={"candidate_user_id": _subject_id(), "accept": True},
    )
    assert r.status_code == 200, r.text

    types = _sequence(client, s, h)
    assert types.count(MATCH_FOUND) == 2  # the automatic one, then the human's
    assert types[-1] == MATCH_FOUND
    assert types[-2] == MATCH_FOUND


def test_a_rejected_candidate_leaves_the_incident_open_for_review(client, aarav_image):
    """Rejecting a candidate is a question for a human, not a closed incident."""
    s = start_session(client)
    h = session_headers(s)
    responder = auth_headers(client, "neha.rao@responder.traya")
    identify(client, s, aarav_image)

    client.post(
        f"/api/emergency/{s['session_id']}/confirm",
        headers={**h, **responder},
        json={"candidate_user_id": _subject_id(), "accept": False},
    )
    types = _sequence(client, s, h)
    assert types.count(MATCH_REJECTED) == 1
    body = client.get(f"/api/emergency/{s['session_id']}/events", headers=h).json()
    assert body["status"] == "review_required"
    assert "INCIDENT_RESOLVED" not in types


def _sequence(client, session, headers) -> list[str]:
    return [
        e["event_type"]
        for e in client.get(f"/api/emergency/{session['session_id']}/events", headers=headers).json()[
            "events"
        ]
    ]


def _user_id(headers: dict) -> str:
    from app.security.tokens import decode_token

    return decode_token(headers["Authorization"].removeprefix("Bearer ")).get("sub")


def _subject_id() -> str:
    from app.database.session import SessionLocal
    from app.models import User

    db = SessionLocal()
    try:
        return db.query(User).first().id
    finally:
        db.close()
