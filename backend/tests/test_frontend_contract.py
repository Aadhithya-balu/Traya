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


# --- Phase 8: the four auth states ------------------------------------------


def test_auth_context_declares_four_distinct_states():
    """`loading`, `authenticated`, `unauthenticated` and `error` must all exist.

    A boolean is the defect. `error` is the state that keeps a dropped
    connection from rendering as a logout, and it is the one that gets dropped
    when someone simplifies the type.
    """
    source = read("context", "AuthContext.tsx")
    union = re.search(r"type\s+AuthStatus\s*=(.*?);", source, re.S)
    assert union, "AuthContext must declare an explicit AuthStatus union"
    for state in ("loading", "authenticated", "unauthenticated", "error"):
        assert f'"{state}"' in union.group(1), f"AuthStatus is missing {state!r}"


def test_a_transient_auth_failure_never_redirects_to_login():
    """The Phase 8 gate: a network failure shows a retry, not a logged-out screen.

    This is the defect that produced the reported complaint in the first place,
    in its subtlest form. `AuthContext` was already correct - it moved to `error`
    and kept the tokens - and the guard threw that away by testing
    `!isAuthed`, which is true in the `error` state too.
    """
    guards = read("components", "Guards.tsx")
    assert 'status === "error"' in guards, (
        "Guards.tsx must branch on the transient error state explicitly"
    )
    assert "refreshUser" in guards, "the transient state must offer a retry"
    assert "common.retry" in guards, "the retry must be a real, labelled control"

    # The navigation must be unreachable from the error branch. Asserted by
    # position: the only Navigate calls sit after the error branch returns.
    error_at = guards.index('status === "error"')
    for nav in re.finditer(r"<Navigate", guards):
        assert nav.start() > error_at, (
            "a Navigate must not be reachable from the transient-error branch"
        )


def test_the_guards_render_no_hardcoded_english():
    """Phase 9 item 3 names `Guards.tsx` explicitly."""
    guards = read("components", "Guards.tsx")
    assert "useI18n" in guards
    text = re.sub(r"//.*|/\*[\s\S]*?\*/", "", guards)
    assert "Loading" not in text, "Guards.tsx must not hardcode user-visible English"
    assert "Try again" not in text


# --- simulation disclosure -------------------------------------------------


def test_engine_mode_is_disclosed_on_every_result(client, demo_headers):
    """A simulation must never be presentable as a biometric.

    Asserted on the wire, not on the client source, because the disclosure is a
    property of the response a responder actually receives. The API reports
    `engine_mode`, `demo_mode` and `algo_version` on every result; the client
    type keeps all three, and the result screen renders them above the
    confidence bar.
    """
    r = client.post(
        "/api/emergency/start", json={"access_type": "public"}, headers=demo_headers
    )
    assert r.status_code == 200
    session = r.json()

    from tests.conftest import degraded_image

    identify = client.post(
        f"/api/emergency/{session['session_id']}/identify",
        headers={
            "X-TRAYA-Session-Token": session["session_token"],
            **demo_headers,
        },
        json={"image": degraded_image("aarav-kumar-demo", faces=2)},
    )
    assert identify.status_code == 200
    body = identify.json()

    # Present even on the cheapest path (multi-face rejection returns early,
    # before any scoring), so it cannot be omitted by a future early return.
    assert body["engine_mode"] == "simulation", (
        "the current engine must self-report as the simulation it is"
    )
    assert body["demo_mode"] is True
    assert body["algo_version"], "a score must be traceable to the engine build"


def test_result_screen_renders_the_disclosure():
    """The client must keep the fields and show them, not merely receive them."""
    source = read("api", "types.ts")
    for field in ("engine_mode", "demo_mode", "algo_version"):
        assert field in source, f"IdentifyResult must expose {field}"
    hub = read("pages", "EmergencyHub.tsx")
    assert "engine_mode" in hub, (
        "the result screen must surface which engine produced the match"
    )
    assert "Simulated match" in hub, (
        "a simulated result must say so in plain words, not only in a field name"
    )


# --- design-system traps ---------------------------------------------------

#: Any numbered Tailwind colour outside the ramp. The theme is monochrome plus
#: three semantic hues, so `text-slate-400` and `bg-amber-500/15` cannot
#: resolve to anything and emit no CSS at all.
OFF_RAMP = re.compile(
    r"(?<![\w-])(?:bg|text|border|ring|from|to|via|divide|placeholder|fill|stroke|shadow|"
    r"outline|decoration|accent|caret)-(?:ink|slate|amber|emerald|zinc|neutral|stone|red|"
    r"green|blue|yellow|orange|purple|pink|gray|grey|white|black)-\d{2,3}(?![\w-])"
)


def _off_ramp_offenders(extensions: tuple[str, ...]) -> dict[str, list[str]]:
    offenders: dict[str, list[str]] = {}
    for ext in extensions:
        for path in sorted(FRONTEND.rglob(f"*{ext}")):
            found = sorted(set(OFF_RAMP.findall(path.read_text(encoding="utf-8"))))
            if found:
                offenders[path.relative_to(FRONTEND).as_posix()] = found
    return offenders


def test_no_component_uses_an_off_ramp_colour():
    """Every colour in a component must come from the semantic ramp.

    The failure is silent by construction: an unknown colour class is not an
    error to Tailwind, it is simply absent from the stylesheet. That is how six
    pages ended up rendering with no background on their cards, no tint on any
    status badge, and no visible border anywhere. A test is the only thing that
    can catch a class that does not exist.
    """
    offenders = _off_ramp_offenders((".tsx",))
    assert not offenders, (
        "colour utilities outside the ramp:\n" + json.dumps(offenders, indent=2)
    )


def test_class_strings_do_not_contain_off_ramp_colours():
    """The same rule for class strings held in data, not in JSX.

    `utils/format.ts` builds the status badge tints as strings in a lookup
    table, so a component-level scan cannot see them. Three of those classes
    were invented and had never rendered.
    """
    offenders = _off_ramp_offenders((".ts",))
    assert not offenders, (
        "off-ramp colours in class strings:\n" + json.dumps(offenders, indent=2)
    )


def test_every_opacity_modifier_on_a_ramp_colour_resolves():
    """`<alpha-value>` must be present in the tailwind colour definitions.

    This is the mechanism behind the whole bug: a colour declared as a bare
    `var(--c-danger)` builds fine, but `bg-danger/10` then produces no rule, so
    the app bar and tab bar ended up with no background and content scrolled
    visibly underneath both. Asserted against the config and the stylesheet so
    the tokens cannot silently regress.
    """
    config = (FRONTEND_ROOT / "tailwind.config.js").read_text(encoding="utf-8")
    assert "<alpha-value>" in config, (
        "ramp colours must contain <alpha-value> or every opacity modifier "
        "compiles to nothing"
    )
    css = (FRONTEND / "index.css").read_text(encoding="utf-8")
    names = re.findall(r'"([a-z-]+)",', config.split("].map")[0])
    for name in names:
        assert f"--c-{name}-rgb:" in css, f"--c-{name}-rgb is missing from index.css"


def test_spacing_uses_only_values_in_the_theme_table():
    """`theme.spacing` is `replace`, not `extend`, so gaps are unvalidated.

    `mt-5.5` and `mt-13` are not errors; they compile to nothing, exactly like
    an unknown colour. Asserted on the table in the config so a new page cannot
    reintroduce the silent failure.
    """
    config = (FRONTEND_ROOT / "tailwind.config.js").read_text(encoding="utf-8")
    table = re.search(r"spacing:\s*\{(.*?)\n    \}", config, re.S)
    assert table, "tailwind.config.js must declare a spacing table"
    allowed = set(re.findall(r"^\s*[\"']?([\w.-]+)[\"']?:", table.group(1), re.M))
    bad: dict[str, list[str]] = {}
    # `translate` is here because that is where the failure actually landed:
    # `-translate-x-5.5` compiled to nothing and the theme toggle knob never
    # visibly moved. The earlier version of this pattern omitted `translate`, so
    # it could not have caught the bug it was written for.
    pattern = re.compile(
        r"(?<![\w-])(?:m|p|gap|space-[xy]|w|h|top|left|right|bottom|inset"
        r"|translate-[xy]|scroll-m[xy]|scroll-mt|scroll-mb)-(\d+(?:\.\d+)?)(?![\w-])"
    )
    for path in sorted(FRONTEND.rglob("*.tsx")):
        text = _strip_comments(path.read_text(encoding="utf-8"))
        used = {u for u in pattern.findall(text) if u not in allowed and u != "0"}
        if used:
            bad[path.relative_to(FRONTEND).as_posix()] = sorted(used)
    assert not bad, (
        "spacing values outside theme.spacing (they compile to nothing):\n"
        + json.dumps(bad, indent=2)
    )


def _strip_comments(text: str) -> str:
    """Drop `//` and `/* */` comments before scanning a source file.

    Both this module and index.css now explain these traps in prose, and a
    pattern that matches `5.5` inside a comment fails on the documentation of
    its own bug.
    """
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"^\s*//[^\n]*$", "", text, flags=re.M)
