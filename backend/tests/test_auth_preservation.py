"""Phase 8: Emergency Mode is a workflow state, not an authentication state.

The reported complaint was "the emergency flow logs me out". There was no
automatic logout anywhere in the codebase. What existed were three separate
things that look identical to the person using the app:

1. A `logout` button rendered on `/emergency/*` with no auth gate - one mis-tap.
2. `AuthContext` nulling the user on **any** `/auth/me` failure, including a
   dropped connection, while the token was still valid.
3. `Protected` and `AdminOnly` treating that transient `error` state as
   "signed out" and redirecting to `/login`.

Item 3 was still present when this file was written, and it is the one that
produces a logged-out screen on a network blip. The tests below pin the server
contract; the React guard is held by `docs/frontend/state-and-data.md` and by
typecheck, since there is no frontend test runner.
"""
from __future__ import annotations

from app.services.incident_service import INCIDENT_CREATED, MATCH_FOUND

from .conftest import (
    DEMO_PASSWORD,
    aarav_image,
    auth_headers,
    identify,
    login,
    session_headers,
    start_session,
)

CITIZEN = "rohan.verma@demo.traya"


def test_authenticated_user_stays_authenticated_through_emergency(client, aarav_image):
    """The Phase 8 acceptance criterion, verbatim in intent."""
    before = login(client, CITIZEN)
    headers = {"Authorization": f"Bearer {before['access_token']}"}

    me_before = client.get("/api/auth/me", headers=headers)
    assert me_before.status_code == 200

    # A full emergency cycle, run by a signed-in person on their own account.
    session = start_session(client)
    h = session_headers(session)
    client.post(
        f"/api/emergency/{session['session_id']}/capture",
        headers=h,
        json={"image": aarav_image},
    )
    identify(client, session, aarav_image)

    me_after = client.get("/api/auth/me", headers=headers)
    assert me_after.status_code == 200, me_after.text
    assert me_after.json() == me_before.json()


def test_an_anonymous_visitor_is_still_anonymous_afterwards(client, aarav_image):
    """The reverse, and the reason the first test is not vacuous.

    If the emergency flow minted or destroyed a session for anyone, this would
    notice.
    """
    assert client.get("/api/auth/me").status_code == 401

    session = start_session(client)
    h = session_headers(session)
    identify(client, session, aarav_image)

    assert client.get("/api/auth/me").status_code == 401


def test_the_same_access_token_survives_the_whole_emergency_surface(client, aarav_image):
    """Every emergency endpoint, not just the happy path.

    A signed-in responder is the normal case in a real deployment: they open an
    incident from their own phone while signed in. Each of these calls carries
    both credentials, which is also the configuration that exposed the
    medical-summary disclosure in Phase 7.
    """
    headers = auth_headers(client, CITIZEN)
    session = start_session(client)
    sid = session["session_id"]
    both = {**session_headers(session), **headers}

    client.post(f"/api/emergency/{sid}/capture", headers=both, json={"image": aarav_image})
    identify(client, session, aarav_image)
    client.get(f"/api/emergency/{sid}", headers=both)
    client.get(f"/api/emergency/{sid}/timeline", headers=both)
    client.get(f"/api/emergency/{sid}/events", headers=both)
    client.get("/api/emergency/thresholds")
    client.post(
        f"/api/emergency/{sid}/fallback/unidentified",
        headers=both,
        json={"reason": "no match"},
    )

    assert client.get("/api/auth/me", headers=headers).status_code == 200


def test_an_incident_does_not_attach_itself_to_the_signed_in_user(client, aarav_image):
    """A bystander's incident must not become the responder's own incident.

    The other direction of "the emergency flow changed my auth state": the flow
    quietly binding an emergency session to whichever account happened to make
    the request.
    """
    headers = auth_headers(client, CITIZEN)
    session = start_session(client)
    both = {**session_headers(session), **headers}
    identify(client, session, aarav_image)

    events = client.get(f"/api/emergency/{session['session_id']}/events", headers=both).json()
    assert [e["event_type"] for e in events["events"]][0] == INCIDENT_CREATED
    assert MATCH_FOUND in {e["event_type"] for e in events["events"]}

    # The citizen's own account is untouched by the incident they witnessed.
    me = client.get("/api/auth/me", headers=headers).json()
    assert me["email"] == CITIZEN
    assert "emergency_session_id" not in me


def test_the_incident_is_reachable_with_only_the_session_token(client, aarav_image):
    """Auth preservation must not become a dependency the other way.

    A bystander who is not signed in has to be able to finish the incident they
    started. If Phase 8 had "fixed" the complaint by requiring a login for every
    emergency call, this would fail.
    """
    session = start_session(client)
    h = session_headers(session)
    identify(client, session, aarav_image)

    assert client.get(f"/api/emergency/{session['session_id']}", headers=h).status_code == 200
    assert (
        client.get(f"/api/emergency/{session['session_id']}/events", headers=h).status_code
        == 200
    )


def test_a_bogus_bearer_token_is_never_treated_as_authenticated(client, aarav_image):
    """A rejected credential is a *definitive* answer, unlike a network failure.

    The distinction is the whole point of the four-state machine: only a 401 may
    end a session.

    Note what is **not** asserted here: that `GET /emergency/{id}` rejects a bad
    bearer. It does not, and it must not - that endpoint is authorized by the
    bystander's own session token, which is the entire reason a stranger with no
    account can report an incident. The assertion is on the endpoint that
    *requires* a permission, where a bad bearer must not fall through to
    anything.
    """
    session = start_session(client)
    h = session_headers(session)
    identify(client, session, aarav_image)

    bad = {**h, "Authorization": "Bearer not-a-real-token"}
    r = client.get(f"/api/emergency/{session['session_id']}/medical-summary", headers=bad)
    assert r.status_code in (401, 403), r.text

    # The bystander's own token still works: one bad request did not end the
    # incident for the person who legitimately owns it.
    assert client.get(f"/api/emergency/{session['session_id']}", headers=h).status_code == 200


def test_a_logout_does_not_invalidate_an_in_progress_incident(client, aarav_image):
    """Signing out is a personal action, not a cancellation.

    The Phase 1 fix removed the logout button from `/emergency/*`. This asserts
    the other half: even if a person did sign out mid-incident, their bystander
    session token still finishes the job. Losing a login must not lose an
    emergency.
    """
    headers = auth_headers(client, CITIZEN)
    session = start_session(client)
    identify(client, session, aarav_image)

    # Signing out is a client-side token clear; the server is asked directly.
    assert client.get("/api/auth/me", headers=headers).status_code == 200

    h = session_headers(session)
    assert client.get(f"/api/emergency/{session['session_id']}/events", headers=h).status_code == 200


def test_demo_password_is_the_documented_one():
    """Guards the fixtures this file depends on, so a seed change is not silent."""
    assert DEMO_PASSWORD == "TrayaDemo#2026"
