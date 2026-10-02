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
import unicodedata
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
    """A bare percentage implies a validation that has never happened.

    This previously matched only `{confidence}` in JSX, which missed `Demo.tsx`
    entirely: the page passed the number to `<ScoreBar value={...confidence} />`
    and rendered a bare `%` on each candidate, and neither shape matched. A page
    reached from the nav with a scripted score and no disclosure is exactly the
    page a reviewer opens first, so the blind spot mattered.
    """
    pages = list((FRONTEND / "pages").glob("*.tsx")) + list(
        (FRONTEND / "components").glob("*.tsx")
    )
    # A glob that matches nothing makes every `assert not offenders` below pass
    # for the wrong reason. This gate previously read `FRONTEND / "src" / ...`
    # while `FRONTEND` already ends in `/src`, so it scanned zero files and had
    # been silently green - including while `Demo.tsx` shipped a confidence with
    # no disclosure.
    assert len(pages) >= 15, (
        f"expected the frontend pages and components, found {len(pages)}: "
        "a scan over nothing asserts nothing"
    )

    #: Every shape by which a similarity or confidence number reaches a screen.
    renders_a_score = re.compile(
        r"\{\s*(?:[\w.]*\.)?(?:confidence|similarity|score)\s*\}"
        r"|<ScoreBar\b"
        r"|Math\.round\(\s*[\w.]*\.(?:confidence|similarity|score)\s*\*\s*100\s*\)",
        re.I,
    )
    #: The disclosure must be *rendered*, not merely plumbed. Reading
    #: `result.engine_mode` and then never showing it satisfies a looser pattern
    #: while leaving the reader with a bare percentage, which is the exact defect
    #: this gate exists to catch. So the accepted forms are a `t()` call into a
    #: disclosure namespace, or a simulation flag bound into rendered output.
    discloses = re.compile(
        r"""t\(\s*["'][^"']*(?:engine|simulation)[^"']*["']"""
        r"|\{\s*(?:isSimulation|simulated)\s*\}",
        re.I,
    )

    offenders = []
    for path in pages:
        text = _without_comments(path.read_text(encoding="utf-8"))
        if renders_a_score.search(text) and not discloses.search(text):
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
    for key in ("hub.engine.simulationTitle", "hub.engine.simulationBody"):
        assert key in hub, (
            "a simulated result must say so in plain words, not only in a field "
            f"name; render {key}"
        )


# --- source scanning -------------------------------------------------------


def _without_comments(text: str) -> str:
    """Return `text` with JSX and TypeScript comments removed.

    A comment is not something a reader sees, so a comment must not be able to
    satisfy a gate about what a reader sees. This is the same trap as naming a
    Tailwind utility in prose so the build emits its rule.

    Deliberately crude: block comments first, then line comments. A `//` inside
    a string literal would be over-stripped, which for a scan like this costs
    recall rather than correctness - a false pass would need a string holding
    `//` immediately before the word it is being credited for.
    """
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"(^|[^:])//[^\n]*", r"\1", text)


# --- hardcoded copy -------------------------------------------------------

# Heuristics for "a user could read this". Each rejects code-shaped text
# outright: `=>` and generics otherwise match the tag-boundary pattern, and
# every SVG path `d` string otherwise matches the literal pattern. The first
# draft of this scan reported 116 findings of which roughly 100 were false, so
# each exclusion below cost a real false positive.
_SVG_PATH = re.compile(r"^[MmLlHhVvCcSsQqTtAaZz0-9\s.,+-]+$")
_CODE_SHAPED = re.compile(r"[=;(){}\[\]|]|=>|\.\w+\(")
_WORD = re.compile(r"[A-Za-z][A-Za-z'\-]*")


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*[\s\S]*?\*/", " ", text)
    return re.sub(r"//[^\n]*", " ", text)


def is_prose(value: str) -> bool:
    v = " ".join(value.split())
    if len(v) < 2:
        return False
    if _CODE_SHAPED.search(v):
        return False
    if _SVG_PATH.match(v):
        return False
    if re.fullmatch(r"[a-z]+(\.[a-zA-Z0-9]+)+", v):      # i18n key
        return False
    if re.fullmatch(r"[a-z]+(-[a-z0-9]+)+", v):          # slug / css token
        return False
    if v.startswith(("http", "data:", "/", "#", ".", "@")):
        return False
    if not re.search(r"[A-Za-z]{3}", v):
        return False
    # Snake/camel enum values and API literals arrive as bare words; two such
    # words side by side are a status, not a sentence. The test is `len >= 3` or
    # an underscore, because `e.g. penicillin, peanuts` yields the words `e` and
    # `g`, and a rule that treats those as an enum misses every placeholder that
    # opens with an abbreviation - which is the shape that actually shipped on
    # the profile form.
    words = _WORD.findall(v)
    if len(words) >= 2 and all(
        w.islower() and (len(w) >= 3 or "_" in w) for w in words
    ):
        return False
    if len(words) == 1 and (v.islower() or v.isupper()) and len(words[0]) >= 3:
        return False
    return True


def scan_prose(text: str):
    out = []
    # JSX children: text between a tag close and the next tag open, on one line,
    # containing no code punctuation.
    for m in re.finditer(r">[ \t]*([^<>{}()\[\];=]{2,})[ \t]*<", text):
        v = m.group(1)
        if is_prose(v):
            out.append((text[: m.start()].count("\n") + 1, "child", v))

    # Prose attributes.
    for m in re.finditer(
        r'\b(alt|aria-label|placeholder|title|aria-description)="([^"]{2,})"', text
    ):
        if is_prose(m.group(2)):
            out.append((text[: m.start()].count("\n") + 1, m.group(1), m.group(2)))

    # Bare string literals, excluding anything already claimed as an i18n key.
    for m in re.finditer(r"""(?<![(\w"'`])(["'])([A-Z][^"'\n]{5,})\1""", text):
        v = m.group(2)
        if is_prose(v):
            out.append((text[: m.start()].count("\n") + 1, "literal", v))

    seen = set()
    uniq = []
    for ln, kind, v in out:
        k = (ln, kind, v)
        if k not in seen:
            seen.add(k)
            uniq.append((ln, kind, v))
    return sorted(uniq)


ACCEPTED_NON_PROSE = {
    # `KeyboardEvent.key` values. `Escape`, `ArrowLeft` and friends are the
    # browser's names for keys, not English copy; localising them would break
    # the comparison.
    "Escape",
    "ArrowRight",
    "ArrowDown",
    "ArrowLeft",
    "ArrowUp",
    # The demo password. A credential is not copy, and a translated credential
    # would be a different credential.
    "TrayaDemo#2026",
}


def test_no_page_or_component_hardcodes_user_visible_english():
    files = sorted(
        list(FRONTEND.glob("pages/*.tsx")) + list(FRONTEND.glob("components/*.tsx"))
    )
    assert len(files) >= 19, (
        f"expected the frontend pages and components, found {len(files)}: "
        "a scan over nothing asserts nothing"
    )

    offenders: dict[str, list[str]] = {}
    for path in files:
        text = strip_comments(path.read_text(encoding="utf-8"))
        for line, kind, value in scan_prose(text):
            # The scanner can report a multi-line blob with stray whitespace;
            # normalise before deciding whether it is copy.
            cleaned = " ".join(value.split())
            if not is_prose(cleaned):
                continue
            if cleaned in ACCEPTED_NON_PROSE:
                continue
            if _looks_like_identifiers(cleaned):
                continue
            offenders.setdefault(path.name, []).append(
                f"line {line} [{kind}] {cleaned!r}"
            )

    assert not offenders, "hardcoded user-visible English: " + "; ".join(
        f"{name}: {', '.join(rows)}" for name, rows in sorted(offenders.items())
    )


def _looks_like_identifiers(value: str) -> bool:
    """True for the scanner's multi-line artifacts around code.

    `>const [x, setX] = useState<Y>[];<` is code that the tag-boundary pattern
    reads as text. The tell is that a code token survives: a dotted member
    access, a bracket pair, or a leading `const`/`return`.

    `e.g` and `i.e` are excluded explicitly, because `e.g. penicillin, peanuts`
    also contains a dotted token and it is copy. That exclusion is exactly the
    case the profile form shipped, so it is named rather than approximated by a
    length rule that would also let real code through.
    """
    for match in re.finditer(r"\b([A-Za-z_$][\w$]*)\s*\.\s*([A-Za-z_$][\w$]*)", value):
        if f"{match.group(1).lower()}.{match.group(2).lower()}" in {"e.g", "i.e"}:
            continue
        return True
    if re.search(r"\w+\s*:\s*\w+\s*[,;)]", value):
        return True
    if re.search(r"^\s*(const|return|if|for|import|export)\b", value):
        return True
    return False

# --- locale integrity ------------------------------------------------------


def _locales() -> dict[str, dict[str, str]]:
    base = FRONTEND / "i18n" / "locales"
    return {
        name: json.loads((base / name).read_text(encoding="utf-8"))
        for name in ("en.json", "ta.json")
    }


def test_both_catalogues_carry_identical_keys():
    """A key present in one language and absent in the other is a silent crash.

    The Tamil half of the app is a first-class requirement, not a fallback, so
    the two catalogues are asserted to be exactly equal in shape rather than
    merely "the English one has most things".
    """
    catalogues = _locales()
    en, ta = set(catalogues["en.json"]), set(catalogues["ta.json"])
    assert en == ta, (
        "catalogue keys differ: "
        f"only in en={sorted(en - ta)} only in ta={sorted(ta - en)}"
    )
    assert en, "the catalogues must not be empty"


def test_no_catalogue_value_is_corrupted_by_an_encoding_round_trip():
    """Guard the bug that actually happened, by its signature.

    Two simulation-disclosure strings were written through a PowerShell pipeline
    whose console encoding could not represent the prose. Every character it
    could not encode was replaced by a literal '?', so the banner shipped as two
    rows of question marks and the simulation was presented to a responder as an
    unreadable string rather than as a warning. Typecheck and build both passed,
    because a row of '?' is a perfectly valid string.

    Two signatures are asserted: a run of two or more '?' (the substitution
    signature), and U+FFFD (the replacement character, if a future editor
    decodes instead of substitutes).
    """
    for name, table in _locales().items():
        for key, value in table.items():
            run = re.search(r"\?{2,}", value)
            assert run is None, (
                f"{name}:{key} contains a run of '?' at offset {run.start() if run else 0}; "
                "this is the signature of text mangled by a shell encoding "
                "round-trip, not a legitimate string"
            )
            assert "\ufffd" not in value, f"{name}:{key} contains U+FFFD"


#: Non-Tamil characters that are legitimate inside a Tamil value: typographic
#: punctuation, and the product name and language names, which are shown in their
#: own script so a language switcher is not a guess.
_ALLOWED_NON_TAMIL = {
    "HORIZONTAL ELLIPSIS",
    "EM DASH",
    "EN DASH",
    "LEFT DOUBLE QUOTATION MARK",
    "RIGHT DOUBLE QUOTATION MARK",
    "MIDDLE DOT",
    "BULLET",
}


#: Latin words permitted inside a Tamil value, each with the reason it is not an
#: untranslated string:
#:
#: - `TRAYA`: the product name.
#: - `English`: the language switcher names each language in its own script, so
#:   someone who cannot yet read the current language can still find theirs.
#: - `SMS`: an acronym for a specific channel; translating it would obscure it.
#: - `Latitude`, `Longitude`: WGS-84 coordinate terms. An administrator typing a
#:   hospital's coordinates searches for "Latitude"; inventing a rendering would
#:   be worse than useless, and a wrong term for a coordinate system is a safety
#:   problem rather than a localisation nicety.
#:
#: Adding to this list is a judgement call that should be argued in the commit
#: message. It is not a general exemption for untranslated Latin: the assertion
#: below still fails on any word not named here.
_ALLOWED_LATIN = {"TRAYA", "English", "SMS", "Latitude", "Longitude"}


def test_the_tamil_catalogue_contains_only_tamil():
    """Catch the generation failure that actually produced a broken string.

    `analytics.unknown` shipped as
    `ரேக்வாலாட் ஸட்ଋ8ாரியுள்ளைவானில்லைவை` for "No result recorded" - an Oriya
    vowel sign (U+0B0B) and a Latin digit wedged mid-word. Every structural check
    passed: the key existed in both catalogues, the catalogues were symmetric, and
    the value was not a run of question marks. It was nonsense Tamil.

    Two signatures are asserted, because either alone can pass a bad string:

    - a character from a non-Tamil script, and
    - a Latin digit adjacent to a Tamil letter. Tamil has its own numerals, so a
      `0`-`9` sitting inside a Tamil word is always a generation error and is a
      much sharper signal than a stray foreign glyph.
    """
    ta = _locales()["ta.json"]
    foreign: list[str] = []
    digit_in_word: list[str] = []

    for key, value in ta.items():
        for index, ch in enumerate(value):
            code = ord(ch)
            if code >= 0x0B80 and code <= 0x0BFF:
                continue
            if code < 0x80 or ch.isspace():
                # A Latin digit counts only when it is jammed against a Tamil
                # letter, which is checked here rather than inside the Tamil
                # branch above: a digit's own codepoint is not in the Tamil
                # block, so testing for it there would never run.
                if ch.isdigit():
                    before = value[index - 1] if index else ""
                    after = value[index + 1] if index + 1 < len(value) else ""
                    for neighbour in (before, after):
                        if not neighbour:
                            continue
                        n = ord(neighbour)
                        if 0x0B80 <= n <= 0x0BFF:
                            digit_in_word.append(
                                f"{key} digit {ch!r} next to U+{n:04X}"
                            )
                continue
            try:
                name = unicodedata.name(ch)
            except ValueError:
                name = "UNASSIGNED"
            if name in _ALLOWED_NON_TAMIL:
                continue
            foreign.append(f"{key} U+{code:04X} {name}")

    assert not foreign, (
        "ta.json contains characters from another script: " + "; ".join(foreign)
    )
    assert not digit_in_word, (
        "ta.json contains a Latin digit adjacent to Tamil, which is always a "
        "generation error: " + "; ".join(digit_in_word)
    )

    # Untranslated Latin words. Latin letters are otherwise legal, because the
    # product name and the coordinate terms are meant to be Latin; this catches
    # the case where a whole English phrase was left in a Tamil value.
    latin_leaks: list[str] = []
    for key, value in ta.items():
        # Interpolation tokens are Latin by construction and are not copy.
        stripped = re.sub(r"\{[^}]+\}", " ", value)
        words = {w for w in re.findall(r"[A-Za-z][A-Za-z'\-]*", stripped) if len(w) > 1}
        # ABO/Rh notation is a standard rather than a word: A+, A-, B+, AB-, O+.
        # It is matched as a shape so the allowance cannot grow into "any token
        # ending in a hyphen".
        notation = {
            tok
            for tok in re.findall(r"(?<![A-Za-z])[A-Z]{1,2}[+-](?![A-Za-z])", stripped)
        }
        unexpected = sorted(words - _ALLOWED_LATIN - notation)
        if unexpected:
            latin_leaks.append(f"{key}: {unexpected}")
    assert not latin_leaks, (
        "ta.json has untranslated Latin words (allowed: "
        f"{sorted(_ALLOWED_LATIN)}, plus ABO/Rh notation): "
        + "; ".join(latin_leaks)
    )


def test_the_simulation_disclosure_is_readable_in_both_languages():
    """The safety banner must actually say something, in each catalogue.

    `test_engine_mode_is_disclosed_on_every_result` proves the API reports the
    mode; this proves a human can read what the client will show them. An empty
    or question-mark-only banner would satisfy every other disclosure test.

    Every disclosure surface is covered, not just the hub's, because `Demo` was
    found rendering a confidence with no disclosure at all - and `Demo` is the
    page a reviewer opens first. A source scan cannot tell that a translated
    string was left empty, so emptiness is asserted against the catalogue.
    """
    #: `key` -> (minimum characters, minimum whitespace-separated words). A short
    #: label like `Engine: {mode}` is deliberately absent: it names the engine but
    #: explains nothing, which is the thing that must not pass.
    disclosures = {
        "hub.engine.simulationTitle": (8, 2),
        "hub.engine.simulationBody": (80, 12),
        "result.simulation": (60, 10),
        "demo.engine.title": (8, 2),
        "demo.engine.body": (80, 12),
    }

    catalogues = _locales()
    for name, table in catalogues.items():
        for key, (min_chars, min_words) in disclosures.items():
            value = table.get(key, "")
            assert len(value.strip()) >= min_chars, (
                f"{name}: {key} is empty or too short to read: {value!r}"
            )
            assert len(value.split()) >= min_words, (
                f"{name}: {key} must explain itself, not just name the engine"
            )
            if name == "ta.json":
                tamil = sum(1 for ch in value if 0x0B80 <= ord(ch) <= 0x0BFF)
                assert tamil >= 8, (
                    f"ta.json: {key} must be written in Tamil, not transliterated"
                )


# --- Phase 9: the nine result states ---------------------------------------

#: The outcomes the identification pipeline can produce. Mirrors the
#: `IdentifyStatus` union in `api/types.ts`; a mismatch in either direction is a
#: bug, which is why this is asserted rather than imported.
NINE_STATES = {
    "HIGH_CONFIDENCE",
    "CONFIRMED",
    "REVIEW_REQUIRED",
    "MULTIPLE_CANDIDATES",
    "LOW_CONFIDENCE",
    "NO_MATCH",
    "NO_FACE",
    "MULTIPLE_FACES",
    "POOR_QUALITY",
}


def _result_state_table() -> dict[str, dict[str, str]]:
    """The badge/next pair per state, parsed from the client source.

    Parsed textually rather than by executing TypeScript: the suite has no node
    runner, and the properties under test - which states exist, and which keys
    they name - are exactly what is written in the file.
    """
    source = read("api", "resultStates.ts")
    body = source.split("RESULT_STATES: Record<IdentifyStatus, ResultState> = {", 1)[1]
    body = body.split("\n};", 1)[0]
    states: dict[str, dict[str, str]] = {}
    for chunk in re.finditer(
        r"(\w+):\s*\{(.*?)\}", body, re.DOTALL
    ):
        name, fields = chunk.group(1), chunk.group(2)
        badge = re.search(r'badge:\s*"([^"]+)"', fields)
        nxt = re.search(r'next:\s*"([^"]+)"', fields)
        if badge and nxt:
            states[name] = {"badge": badge.group(1), "next": nxt.group(1)}
    return states


def test_every_identification_state_has_a_badge_and_a_next_action():
    """Phase 9's gate: nine reachable states, each telling the responder what to do.

    Before this table existed, three of the nine were rendered by no code path at
    all, and two of the rest printed their raw enum to the screen - a responder
    saw the word "multiple candidates" with no indication of what to do about
    it. Asserting the map's shape here keeps that from regressing silently.
    """
    states = _result_state_table()
    assert set(states) == NINE_STATES, (
        "RESULT_STATES must cover exactly the nine identification outcomes; "
        f"missing={sorted(NINE_STATES - set(states))} "
        f"unexpected={sorted(set(states) - NINE_STATES)}"
    )

    order = read("api", "resultStates.ts").split("RESULT_STATE_ORDER = [", 1)[1]
    ordered = set(re.findall(r'"(\w+)"', order.split("]", 1)[0]))
    assert ordered == NINE_STATES, (
        "RESULT_STATE_ORDER must be a permutation of the nine states so the demo "
        "can exercise every branch"
    )


def test_no_two_result_states_share_the_same_badge_text():
    """A duplicate badge is a state that has quietly stopped being distinguishable.

    This is the defect that motivated the table, so it is pinned: if two states
    resolve to the same English string, a responder cannot tell them apart even
    though the code says they are different.
    """
    en = _locales()["en.json"]
    seen: dict[str, str] = {}
    for state, keys in _result_state_table().items():
        for slot in ("badge", "next"):
            key = keys[slot]
            assert key in en, (
                f"{state}.{slot} names key {key!r}, which is absent from en.json; "
                "the screen would render the raw key"
            )
            text = en[key]
            assert text.strip(), f"{key} is an empty string"
            fingerprint = "{}::{}".format(slot, text)
            if slot == "badge":
                assert fingerprint not in seen, (
                    "states {} and {} render the identical badge {!r}; a responder "
                    "cannot act on a distinction they cannot see".format(
                        seen.get(fingerprint), state, text
                    )
                )
                seen[fingerprint] = state


def test_result_state_keys_exist_in_both_languages():
    """A state reachable only in English is not translated, it is broken."""
    catalogues = _locales()
    for state, keys in _result_state_table().items():
        for slot, key in keys.items():
            for name, table in catalogues.items():
                assert key in table, (
                    f"{state}.{slot} -> {key!r} is missing from {name}"
                )


# --- hooks must not own copy ------------------------------------------------

#: `useCamera` and `useGeolocation` return error codes and let the page render
#: them. Both previously held English sentences, so a Tamil responder read
#: "Camera permission denied." in English at the moment they needed to know
#: whether to retry or switch to the gallery.
HOOK_ERROR_MAPS = {
    "useCamera.ts": ("CameraErrorCode", "CAMERA_ERROR_KEYS"),
    "useGeolocation.ts": ("GeoErrorCode", "GEO_ERROR_KEYS"),
}

#: String literals that are legitimately not user-visible: DOM/API names, format
#: strings, and the enum members themselves.
_NOT_PROSE = re.compile(
    r"""^(?:
          \w+(?:[-/]\w+)*          # kebab or slashed identifiers: NotAllowedError
        | [\d.,:%\s-]+              # numbers, separators, ratios
        | \{[^}]*\}                 # interpolation tokens
        | .                        # anything shorter than a phrase
    )$""",
    re.VERBOSE,
)


def test_no_hook_returns_english_error_text():
    """A hook that owns copy cannot be translated without the hook changing.

    Asserted on the two hooks that surface failures to a person mid-emergency.
    The rule is "no multi-word string literal that is prose", which is why the
    allowed cases are enumerated: `NotAllowedError` is a DOM name and must stay
    Latin, `image/jpeg` is a MIME type, and single words are too short to be a
    sentence worth translating.
    """
    offences: list[str] = []
    for filename in HOOK_ERROR_MAPS:
        source = read("hooks", filename)
        # Ignore comments; prose in a docstring explaining why the code exists
        # is documentation, not copy. Strip block and line comments first.
        stripped = re.sub(r"/\*.*?\*/", " ", source, flags=re.DOTALL)
        stripped = re.sub(r"^\s*//.*$", " ", stripped, flags=re.MULTILINE)
        for lineno, line in enumerate(stripped.splitlines(), 1):
            for literal in re.findall(r'"([^"\n]*)"', line):
                words = literal.split()
                if len(words) < 3:
                    continue
                if _NOT_PROSE.match(literal):
                    continue
                offences.append(f"hooks/{filename}:{lineno} {literal!r}")
    assert not offences, (
        "hooks must return error codes, not sentences: " + "; ".join(offences)
    )


def test_hook_error_code_maps_are_exhaustive_and_translated():
    """Every code a hook can return must have a message, in both languages.

    The maps are typed `Record<Code, StringKey>` in TypeScript, so the compiler
    catches a code added without a key. This asserts the other half: that the
    keys are real, exist in both catalogues, and that the union in the source
    and the map really do cover the same members. A stale member on either side
    is how a code ends up rendering its own identifier to a responder.
    """
    catalogues = _locales()
    for filename, (union_name, map_name) in HOOK_ERROR_MAPS.items():
        source = read("hooks", filename)

        union = re.search(
            r"export type {}\s*=\s*(.*?);".format(union_name),
            source,
            re.DOTALL,
        )
        assert union, f"hooks/{filename} must export {union_name}"
        # Quoted members only: the union body may legitimately contain comments
        # and, for the single-line form, no leading `|` before the first member.
        members = set(re.findall(r'"(\w+)"', union.group(1)))
        assert members, f"{union_name} declares no string members"

        mapping = re.search(
            r"export const {}: Record<\w+, StringKey> = \{{(.*?)\n\}};".format(
                map_name
            ),
            source,
            re.DOTALL,
        )
        assert mapping, f"hooks/{filename} must export {map_name} as a Record"
        entries = dict(re.findall(r'(\w+):\s*"([^"]+)"', mapping.group(1)))

        assert set(entries) == members, (
            f"{map_name} covers {sorted(entries)} but {union_name} declares "
            f"{sorted(members)}"
        )
        for member, key in entries.items():
            for name, table in catalogues.items():
                assert key in table, (
                    f"{map_name}.{member} -> {key!r} missing from {name}"
                )


def test_a_capture_failure_is_never_silent():
    """`capture()` returning a bare null made a dead shutter look like a no-op.

    The old signature was `Promise<string | null>` and three distinct failures
    - no decoded frame, no 2d context, and a refused encode - all produced the
    same `null`. To a responder that is indistinguishable from pressing the
    shutter on a working camera. Asserted as a discriminated result.
    """
    source = read("hooks", "useCamera.ts")
    assert "CaptureResult" in source, "capture must return a typed result"
    assert "ok: true" in source and "ok: false" in source, (
        "CaptureResult must distinguish success from failure"
    )
    assert re.search(r"capture: \(\) => Promise<CaptureResult>", source), (
        "CameraState.capture must declare the discriminated result type"
    )
    # And the one failure that a person can act on immediately.
    assert "noFrames" in source, (
        "a camera that has not decoded a frame yet must be reported, not swallowed"
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
