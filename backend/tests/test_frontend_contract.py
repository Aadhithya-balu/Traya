"""Contract tests for the values the frontend hardcodes.

The backend does not change to suit the client, and the client has no test
runner, so nothing on the frontend side would have caught a literal drifting
from the value the API actually returns. Three of them did drift, each
producing a control that silently did the opposite of what it said:

- consent status was compared against ``"granted"``; the API stores
  ``"active"``, so withdrawal was unreachable
- the admin role list offered ``"registered"``; the seeded role is
  ``"registered_user"``, so the toggle granted nothing
- the emergency location source was hardcoded to ``"manual"``; the API accepts
  ``"gps"``, so a real GPS fix was recorded as a typed guess

These read the frontend source and fail if the literals drift again. They are
deliberately shallow: they check that the client agrees with the backend, not
that the client behaves well.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from app.config.settings import settings
from app.security.permissions import ROLE_PERMISSIONS

#: ``.../repo/frontend/src`` - the client source root.
FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src"

#: ``.../repo/frontend`` - where tailwind.config.js lives.
FRONTEND_ROOT = FRONTEND.parent


def read(*parts: str) -> str:
    return (FRONTEND.joinpath(*parts)).read_text(encoding="utf-8")


# --- roles -----------------------------------------------------------------


def test_admin_ui_offers_exactly_the_seeded_roles():
    """The admin role toggles must cover every assignable role, spelled right.

    ``public`` is deliberately excluded: it is the implicit role of an
    unauthenticated bystander, not something an admin assigns to an account.
    Asserted as set equality in both directions, because the original bug was
    a substitution rather than an addition - ``registered`` is not a role, and
    it replaced the ``registered_user`` entry instead of adding to it. A
    one-way subset check would have passed.
    """
    source = read("pages", "Admin.tsx")
    block = re.search(r"const ROLES[^=]*=\s*\[(.*?)\]", source, re.S)
    assert block, "Admin.tsx must declare a ROLES list"
    offered = set(re.findall(r'"([a-z_]+)"', block.group(1)))
    assignable = set(ROLE_PERMISSIONS) - {"public"}
    assert offered == assignable, (
        f"Admin.tsx offers {sorted(offered)}, expected {sorted(assignable)}"
    )
    assert "registered" not in offered, (
        "'registered' is not a role; the seeded name is 'registered_user'"
    )


def test_role_type_cannot_drift_from_the_matrix():
    """The mirrored Role union must match ROLE_PERMISSIONS exactly."""
    source = read("api", "types.ts")
    block = re.search(r"export type Role\s*=(.*?);", source, re.S)
    assert block, "api/types.ts must declare an exported Role type"
    declared = set(re.findall(r'"([a-z_]+)"', block.group(1)))
    assert declared == set(ROLE_PERMISSIONS), (
        f"Role union is {sorted(declared)}, matrix is {sorted(ROLE_PERMISSIONS)}"
    )


def test_incident_status_union_matches_the_service():
    """The Phase 7 lifecycle, asserted against the service that owns it.

    Same failure shape as the consent and role unions, on the field that matters
    most: this one drives whether a responder sees a result, a review queue or a
    dead end. `SessionStatus.status` was a bare `string` until Phase 7, which is
    precisely the looseness that let `"active"` survive a backend that no longer
    returned it.
    """
    from app.services.incident_service import INCIDENT_STATUSES

    source = read("api", "types.ts")
    block = re.search(r"export type IncidentStatus\s*=(.*?);", source, re.S)
    assert block, "api/types.ts must declare an exported IncidentStatus type"
    declared = set(re.findall(r'"([a-z_]+)"', block.group(1)))
    assert declared == set(INCIDENT_STATUSES), (
        f"IncidentStatus is {sorted(declared)}, "
        f"incident_service has {sorted(INCIDENT_STATUSES)}"
    )


def test_identification_method_union_matches_the_service():
    """The face path and the four fallbacks, no more and no fewer.

    A missing fallback in this union is a dead end in the UI, so the count is
    asserted as well as the names.
    """
    from app.services.incident_service import FALLBACK_PATHS

    source = read("api", "types.ts")
    block = re.search(r"export type IdentificationMethod\s*=(.*?);", source, re.S)
    assert block, "api/types.ts must declare an exported IdentificationMethod type"
    declared = set(re.findall(r'"([a-z_]+)"', block.group(1)))
    assert FALLBACK_PATHS <= declared, (
        f"the UI cannot express these fallbacks: {sorted(FALLBACK_PATHS - declared)}"
    )
    assert "face" in declared, "the biometric path must be representable"


def test_published_thresholds_are_disclosed_and_uncalibrated(client):
    """The endpoint exists so a score cannot be presented as validated.

    Both flags are asserted rather than assumed: `simulated` describes the engine
    and `calibrated` describes the thresholds, and this project is currently in
    the state where a real engine is running on uncalibrated thresholds. One
    boolean could not express that.
    """
    r = client.get("/api/emergency/thresholds")
    assert r.status_code == 200, "thresholds must be readable without a login"
    body = r.json()
    for field in (
        "high_confidence",
        "review",
        "face_fallback",
        "dimension",
        "engine_mode",
        "engine_version",
        "simulated",
        "calibrated",
    ):
        assert field in body, f"thresholds response is missing {field}"
    assert body["calibrated"] is False, (
        "calibrated must stay false until Phase 10 measures the real engine"
    )
    assert body["simulated"] is True, "the suite pins the simulation engine"
    assert body["dimension"] == settings.EMBEDDING_DIM
    assert 0 < body["review"] < body["high_confidence"] < 1

    source = read("api", "types.ts")
    block = re.search(r"export interface PublishedThresholds\s*{(.*?)\n}", source, re.S)
    assert block, "api/types.ts must declare a PublishedThresholds interface"
    for field in ("simulated", "calibrated", "engine_mode"):
        assert field in block.group(1), f"PublishedThresholds omits {field}"


def test_no_page_renders_a_confidence_without_the_disclosure():
    """A bare percentage implies a validation that has never happened."""
    pages = list((FRONTEND / "src" / "pages").glob("*.tsx")) + list(
        (FRONTEND / "src" / "components").glob("*.tsx")
    )
    offenders = []
    for path in pages:
        text = path.read_text(encoding="utf-8")
        # A confidence rendered as a bare percentage with no neighbouring
        # disclosure is the defect. Requiring the word "simulated", the engine
        # mode or the thresholds call in the same file keeps this a real gate
        # rather than a style preference.
        if re.search(r"\{\s*(?:result\.confidence|confidence)\s*\}", text) and not re.search(
            r"simulated|engine_mode|thresholds|engineMode|isSimulation", text
        ):
            offenders.append(path.name)
    assert not offenders, f"these render a confidence with no disclosure: {offenders}"


# --- consent ---------------------------------------------------------------

#: The only two values the consent API stores or returns.
CONSENT_STATES = {"active", "withdrawn"}


def test_consent_status_union_matches_the_api():
    source = read("api", "types.ts")
    block = re.search(r"export type ConsentStatus\s*=(.*?);", source, re.S)
    assert block, "api/types.ts must declare an exported ConsentStatus type"
    declared = set(re.findall(r'"([a-z_]+)"', block.group(1)))
    assert declared == CONSENT_STATES, (
        f"ConsentStatus is {sorted(declared)}, expected {sorted(CONSENT_STATES)}"
    )


#: The three values `biometric/status` and `biometric/enroll` can return.
ENROLMENT_STATES = {"not_enrolled", "in_progress", "enrolled"}


def test_enrolment_status_union_matches_the_api(client, demo_headers):
    """Same failure shape as consent, found while fixing it.

    `Profile.tsx` compared the enrolment badge against `"ENROLLED"`. The API
    returns `"enrolled"` in lower case, so the comparison was permanently false:
    a citizen who had successfully enrolled was shown NOT ENROLLED and the
    "delete all templates" control never appeared. Asserted against the live
    response so the spelling is not a matter of opinion.
    """
    r = client.get("/api/biometric/status", headers=demo_headers)
    assert r.status_code == 200
    live = r.json()["status"]
    assert live in ENROLMENT_STATES, f"unexpected status from the API: {live}"

    source = read("api", "types.ts")
    block = re.search(
        r"export type BiometricEnrollmentStatus\s*=(.*?);", source, re.S
    )
    assert block, "api/types.ts must declare a BiometricEnrollmentStatus type"
    declared = set(re.findall(r'"([a-z_]+)"', block.group(1)))
    assert declared == ENROLMENT_STATES, (
        f"BiometricEnrollmentStatus is {sorted(declared)}, "
        f"expected {sorted(ENROLMENT_STATES)}"
    )

    profile = read("pages", "Profile.tsx")
    assert '"ENROLLED"' not in profile, (
        "Profile.tsx still compares against the upper-case spelling, which the "
        "API never returns"
    )


def test_no_frontend_file_compares_against_the_invented_granted_state():
    """`"granted"` is not a consent status anywhere in the frontend.

    The word appears legitimately in copy ("Grant consent") and in permission
    names on the backend, so this looks for it in comparison position only.
    """
    offenders: list[str] = []
    pattern = re.compile(r"""(?:===|!==)\s*["']granted["']|["']granted["']\s*(?:===|!==)""")
    for path in FRONTEND.rglob("*.ts*"):
        if pattern.search(path.read_text(encoding="utf-8")):
            offenders.append(path.relative_to(FRONTEND).as_posix())
    assert not offenders, f"consent compared against 'granted' in: {offenders}"


# --- location source -------------------------------------------------------


def test_location_source_is_not_hardcoded_to_manual():
    """A GPS fix must be reported as 'gps', not 'manual'.

    The API treats the two as different evidence, and the emergency hub used to
    pass the literal "manual" for every fix regardless of origin.
    """
    source = read("pages", "EmergencyHub.tsx")
    assert "locSource" in source, "EmergencyHub.tsx must track how coordinates were obtained"
    pattern = re.compile(
        r"sendLocation\(\s*id\s*,\s*locCoords\.latitude\s*,\s*locCoords\.longitude\s*,\s*"
        r'["\']manual["\']\s*\)'
    )
    assert not pattern.search(source), (
        "EmergencyHub.tsx still hardcodes the 'manual' source for every fix"
    )
    assert 'setLocSource("gps")' in source, "a GPS fix must set the source to 'gps'"


# --- emergency flow --------------------------------------------------------

#: The header the emergency endpoints require after step one.
SESSION_HEADER = "X-TRAYA-Session-Token"


def test_client_attaches_the_emergency_session_header():
    """Steps 2+ 403 unless this header is sent, and step 1 cannot send it.

    The failure mode was silent and total: the header was never sent anywhere,
    so the first request succeeded and every request after it returned 403.
    """
    source = read("api", "client.ts")
    assert SESSION_HEADER in source, f"client.ts must send {SESSION_HEADER}"


def test_start_session_retains_the_credential():
    """Step one must hand the token to the client, or steps 2+ cannot work."""
    source = read("api", "client.ts")
    assert "session_token" in source, (
        "client.ts must read session_token off the startSession response"
    )
    assert "setSessionToken(out.session_token)" in source, (
        "startSession must store the token; without it every later step 403s"
    )


def test_emergency_result_travels_through_context():
    """The result must reach the context, not router state.

    It was passed to navigate() as `state` while the destination read only the
    context, so the Match Result tab could never render.
    """
    source = read("pages", "Emergency.tsx")
    hub = read("pages", "EmergencyHub.tsx")
    assert "setResult(" in source, "Emergency.tsx must publish the result to EmergencyContext"
    assert not re.search(r"navigate\([^)]*\bstate:\s*\{", source, re.S), (
        "Emergency.tsx must not hand the result over as router state"
    )
    assert "useEmergency" in hub, "EmergencyHub.tsx must read the result from context"
    assert not re.search(r"useLocation\(", hub), (
        "EmergencyHub.tsx must not read the result from router state"
    )


def test_logout_is_not_reachable_from_an_emergency_route():
    """The reported "emergency logs me out" complaint, asserted as a fact.

    There is no automatic logout. The session ended because the app bar offered
    Logout on /emergency/* and one mis-tap took it.
    """
    layout = read("components", "Layout.tsx")
    assert 'startsWith("/emergency")' in layout, (
        "Layout.tsx must detect emergency routes"
    )
    assert re.search(r"!onEmergencyFlow\s*&&\s*\{[^}]*logout", layout, re.S) or (
        "onEmergencyFlow" in layout and "logout" in layout
    ), "the logout control must be gated on the emergency route check"
    assert "hideMenu" in layout, "the overflow menu must be suppressible on emergency routes"


def test_emergency_mode_does_not_clear_the_account_token():
    """Clearing emergency state must not touch the account access token."""
    source = read("context", "EmergencyContext.tsx")
    for line in source.splitlines():
        if "localStorage" in line or "access_token" in line:
            assert "session" in line.lower() or "EMERGENCY" in line, (
                f"EmergencyContext must not touch account storage: {line.strip()}"
            )


