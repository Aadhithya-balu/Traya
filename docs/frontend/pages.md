[../README.md](../README.md) | [Frontend index](README.md) | [Routing](routing.md)

# Pages

Every screen, what it does, what it calls, and what it holds. Route paths are
covered in [routing.md](routing.md).

| Page | Route | State | Migrations |
|---|---|---|---|
| [`Landing`](#landing) | `/` | none | complete |
| [`Login`](#login) | `/login` | form | complete |
| [`Register`](#register) | `/register` | form | complete |
| [`Emergency`](#emergency) | `/emergency` | 4-stage flow | complete |
| [`EmergencyHub`](#emergencyhub) | `/emergency/:sessionId` | 5 tabs | complete |
| [`Dashboard`](#dashboard) | `/dashboard` | summary | complete |
| [`Profile`](#profile) | `/profile` | 6 sections | complete |
| [`Demo`](#demo) | `/demo` | scenarios | complete |
| [`Admin`](#admin) | `/admin` | 5 tabs | complete |
| [`Privacy`](#privacy) | `/privacy` | none | complete |
| [`Connect`](#connect) | `/connect` | form | complete |

**complete** = design tokens, i18n keys, and layout respects the shell.
**legacy** = colour is migrated but strings are still hardcoded English.
Phase 1 moved every page off the removed `ink-*`/`slate-*` palette, so
**colour is no longer what makes a page legacy** — see
[design-system.md](design-system.md#the-palette-migration-is-done-and-so-is-the-string-migration).

**Phase 9 closed the string half.** Every page now resolves its user-visible
copy through `t()`, and `test_no_page_or_component_hardcodes_user_visible_english`
fails the build if one reintroduces a literal. The **legacy** markers below are
therefore stale for `EmergencyHub`, `Profile`, `Admin`, `Demo` and `Privacy`:
what remains for those pages is layout and desktop behaviour, not translation.

| Page | Colour | Strings | Also fixed |
|---|---|---|---|
| `EmergencyHub` | done | done | result plumbing, GPS source, engine disclosure |
| `Profile` | done | done | consent + enrolment vocabulary; guided enrolment (Phase 6); unlabelled inputs |
| `Admin` | done | done | role names; `public` role had no label |
| `Demo` | done | done | simulation disclosure rendered unconditionally |
| `Privacy` | done | done | invisible headings |

---

## Landing

`pages/Landing.tsx` -> `Landing`. Stateless, no API calls.

Hero, six feature cards (`FEATURES`) and three numbered steps (`STEPS`), then
CTAs to `/emergency`, `/demo` and `/register`. `STEPS` reuses three of the
`landing.f*` feature keys, so the "how it works" strip and the feature grid are
the same content in two arrangements - if you edit one, check the other.

Note: `FEATURES` and `STEPS` both reference `landing.f1`, `landing.f3` and
`landing.f4`. Splitting them into separate keys is a pending cleanup.

## Login

`pages/Login.tsx` -> `Login`. Route: `/login`.

| State | Purpose |
|---|---|
| `email`, `password` | Form fields. |
| `error` | `ApiError.detail`, so the message comes from the backend. |
| `busy` | Disables submit. |

Calls `useAuth().login`, then `navigate("/dashboard", { replace: true })`.

Includes a demo-account panel with `DEMO_ACCOUNTS` and
`DEMO_PASSWORD = "TrayaDemo#2026"`, so the product is explorable without
reading the docs. **Those emails duplicate the list in `AGENTS.md` and
`docs/operations/README.md`** - three sources for one fact. Treat
[operations/README.md](../operations/README.md#demo-accounts) as canonical.

The panel's own labels are i18n keys (`auth.demo.*`), with `{password}` carried
as an interpolation rather than concatenated. The password itself stays a
literal in `DEMO_PASSWORD`, because it is a credential that has to match the
seed, not copy.

## Register

`pages/Register.tsx` -> `Register`. Route: `/register`.

State: `fullName`, `email`, `password`, `phone`, `error`, `busy`, plus a derived
`problem` (`useMemo`) and `passwordOk`.

`passwordProblem(password)` returns the first unmet rule token - `"8+"`,
`"A-Z"`, `"0-9"` - and submit is disabled while `problem` is truthy. This
**duplicates the server rule** in `RegisterRequest` (at least 8 characters, one
uppercase, one digit). A client/server divergence silently blocks submission
instead of showing the server's message; if you change one, change both.

Navigates to `/profile` on success.

## Emergency

`pages/Emergency.tsx` -> `Emergency`. Route: `/emergency`. **The primary screen
of the product.**

Four stages, `type Stage = "intro" | "capture" | "review" | "working"`:

| Stage | What the user sees | Available action |
|---|---|---|
| `intro` | What will happen, and a warning that this is a simulation. | Start camera, or pick from the gallery. |
| `capture` | Live preview at 3:4 with a face-shaped guide, and a shutter button. | Shutter, back, or fall back to the gallery. |
| `review` | The photo, plus `QualityPanel` if the server graded it. | Retake, or use the photo. |
| `working` | A pulse and a short message. | Wait. |

State: `stage`, `imageB64`, `quality`, `error`, `busy`; refs `fileRef`; and
`useCamera()`.

Three calls, in sequence, inside `checkAndIdentify`:

1. `api.startSession("public")`
2. `api.capture(sessionId, imageB64)` - quality gate only
3. `api.identify(sessionId, imageB64)` - the match

Design decisions:

- **The session opens lazily, at the point the photo exists.** An abandoned
  attempt does not leave a session in the incident log.
- **No `secondary_features` and no lat/lng are sent** from this screen. Both
  default to empty/null. Sending a location here would be a privacy decision
  this page has not earned.
- **The camera is the primary path and the gallery is a peer, not a fallback
  hidden behind a link.** A responder with a denied camera permission can still
  finish the job.
- `useEffect(() => () => camera.stop(), [camera.stop])` releases the camera on
  unmount, so the browser's recording indicator does not stay on.
- `useCamera` requests `facingMode: "environment"` (the rear camera), because a
  responder is photographing the person in front of them, not themselves.

## EmergencyHub

`pages/EmergencyHub.tsx` -> `EmergencyHub`. Route: `/emergency/:sessionId`.
**The largest page in the app.** Four tabs
(`type Tab = "result" | "medical" | "contact" | "location"`), three
local sub-components (`MatchResultSection`, `PublicMedicalSummary`,
`ResponderExtras`), and local state.

Calls: `api.medicalSummary`, `api.responderProfile` (role-gated),
`api.nearbyHospitals`, `api.sendLocation`, `api.contactAction`,
`api.confirm`, plus `useGeolocation(false)`.

**The audit `Timeline` tab was removed.** An audit trail is not what a responder
at the scene needs, and it was the one tab whose content a normal user could not
act on. The session log is now reachable only from `Profile`, as an opt-in
activity log, so it still exists for the person whose data it is.

**Both functional bugs are fixed, and Phase 9 closed the strings.** The page is
no longer legacy. What remains is desktop layout and breakpoint behaviour, which
is unverified — no browser run has happened.

1. ~~**The Match Result tab renders nothing.**~~ `Emergency.tsx` now calls
   `setSession` and `setResult` after `identify`, and navigates without a
   `state:` argument. The tab body renders and confirm-identity is reachable.
   Asserted by `test_emergency_result_travels_through_context`.
2. ~~**GPS fixes are logged as `source: "manual"`.**~~ The page tracks
   `locSource` as `"gps" | "manual"`, set to `"gps"` by the geolocation effect
   and to `"manual"` only by `useManualCoords`. Asserted by
   `test_location_source_is_not_hardcoded_to_manual`.

**Added in Phase 1: `EngineDisclosure`.** The result section now renders a
non-dismissible notice above the confidence bar when `engine_mode` is
`simulation` or `demo`, in the words *"Simulated match — not a biometric"*, with
the mode and algorithm version. It previously displayed a percentage with
nothing saying where the number came from, which is the single worst thing this
page could do. For a real engine it degrades to a one-line provenance note.

Also still true, and worth knowing before you touch this page:

- Phase 9 put every user-visible string on `hub.*`, closing the largest i18n
  debt in the codebase.
- The page wraps itself in `mx-auto max-w-5xl` while `Layout` already
  constrains `<main>` to `max-w-2xl`, so the two fight. Remove the page-level
  container when migrating.
- It is the largest file in the frontend and holds three sub-components inline.

## Dashboard

`pages/Dashboard.tsx` -> `Dashboard`. Route: `/dashboard`, behind `Protected`.

Four stat tiles (enrolment status, contact count, sample count, consent ratio),
an enrol CTA to `/profile` when not enrolled, the consent list, and the last six
access-history events.

Four calls in one `Promise.all`: `api.biometricStatus`, `api.listConsents`,
`api.listContacts`, `api.accessHistory`. Parallel, because a summary screen
should not serialise four independent requests on a phone. A `cancelled` flag
guards `setState` after unmount.

**Inconsistent status vocabulary across pages.** This page checks
`biometric.status === "enrolled"` and `consent.status === "active"`, while
`Profile` compares against `"ENROLLED"` and `"granted"`. One of each pair is
wrong, so the dashboard and the profile can show opposite states for the same
user. Normalise on the lowercase backend values.

Also note the effect's dependency array is `[t]`. `t` is a `useCallback` whose
identity changes with the locale, so **switching language re-fetches all four
endpoints**. Harmless, but it should depend on nothing instead.

## Profile

`pages/Profile.tsx` -> `Profile`. Route: `/profile`, behind `Protected`.

Seven sections: basic info, medical profile, emergency contacts (add/remove),
visible features (add/remove), biometric consent grant/withdraw, biometric
enrolment (guided capture, delete), and the opt-in activity log.

Twelve calls: `getMedical`, `listContacts`, `listFeatures`, `listConsents`,
`biometricStatus` on load; then `updateProfile`, `updateMedical`, `addContact`,
`deleteContact`, `addFeature`, `deleteFeature`, `grantConsent`/`withdrawConsent`,
`deleteBiometric`.

The activity log is a thirteenth call, `accessHistory`, and it is **deliberately
not** part of the page load: it fires only when the person opens the panel. An
audit trail is a "check if you want" surface, not something to put in front of
someone, and the emergency hub no longer shows one at all.

### Localized in Phase 9, along with the unlabelled inputs

The page carried roughly forty hardcoded English strings, so it is now fully on
`profile.*`. Two defects fixed with it:

- **Every input in the basic-information and medical forms had a `<label>` with
  no `htmlFor` and no matching `id`.** A label that is not associated with its
  control is not a label: clicking it focuses nothing, and a screen reader
  announces an unlabelled edit field. Every field now has a matching `id`, and
  the contact and feature forms use `sr-only` labels rather than relying on the
  placeholder, because the accessible name of a placeholder-only input is not
  announced by several readers.
- **The consent status rendered the raw enum** (`active` / `withdrawn`) inside
  otherwise Tamil copy. It now goes through `CONSENT_STATUS_LABELS`, typed as a
  total map over `ConsentStatus`, so a third status fails the typecheck instead
  of leaking English.

The success flash is `role="status"` and the error is `role="alert"`, so a
confirmation does not interrupt the assertive channel an error needs.

Two sharp edges remain, both consequences of not rewriting the page:

- **Deleting templates still asks for confirmation** via `window.confirm` with
  `enroll.delete.confirm`. It is the only revoke path and it is irreversible, but
  `window.confirm` is a browser dialog in a design system that otherwise has a
  `Sheet` for exactly this.
- **A completed enrolment keeps the wizard mounted only until the parent updates
  `bio`.** `EnrollWizard` shows its own completion card from the response; the
  parent then flips to the enrolled block. Two success surfaces, briefly.

Remaining issues to address when migrating:

- `medical` state is **write-only**: it is set on load and after save and never
  read, so a stale read is impossible but the state is dead weight.
- Allergies, conditions and medications are entered as comma-separated strings,
  so a value containing a comma cannot be represented.
- `flash()` uses a bare `setTimeout` with no cleanup, which warns under
  StrictMode if the component unmounts within 3 seconds.

**Fixed in Phase 6: enrolment is guided, and the upload path is gone.** The
2-4 file input, its 4-image cap and the `enrollBiometric` client method were
deleted. Enrolment is now a *Start face enrollment* button that mounts
[`EnrollWizard`](components.md#enrollwizard), which
drives the four guided calls and shows the engine's own reason codes. This also
retires three defects at once: the "2-4" label promised a minimum the page never
enforced, the 4-image cap silently discarded images on a 3 MB failure, and the
person had no idea which pose was being asked for. The section still shows the
consent requirement, and renders the start button only when consent is `active`.

Fixed in Phase 1.** Both vocabulary mismatches were real, and both failed
silently:

- **Consent could never be withdrawn.** The toggle compared against `"granted"`;
  the API stores `"active"`, so the condition was permanently false and the
  button always granted. Note the sibling branch in the same function already
  used `"withdrawn"` — one string in the file was right and one was wrong.
- **`"ENROLLED"` vs the API's `"enrolled"`.** The badge therefore always read
  NOT ENROLLED, and the "delete all templates" block — the only way to revoke a
  biometric — never rendered, for a citizen who had successfully enrolled.

Both fields are now unions (`ConsentStatus`, `BiometricEnrollmentStatus`)
rather than bare `string`, asserted in
`test_frontend_contract.py` against `live responses from /users/consents and
/biometric/status`.

## Demo

`pages/Demo.tsx` -> `Demo`. Route: `/demo`.

A grid of scenario buttons from `api.demoScenarios()`; selecting one calls
`api.demoRun(id, 28.6139, 77.209)` and renders the synthetic input, the
identification outcome, a `ScoreBar`, method badges, candidates and
`QualityPanel`. Two calls, four pieces of state.

Synthetic images flow through the **real** pipeline, which is the point: the
demo exercises production code paths, not a mock.

**Localized in Phase 9, and the disclosure is now unconditional.** `Demo` renders
`LiveStatus` for the outcome, `NextAction` for what to do about it, and a
`DemoEngineDisclosure` that is not conditional on any score. The point of this
page is to show what the pipeline does, so a page whose disclosure disappears
when the demo happens to look convincing is the wrong page: the notice reads the
`engine_mode` and `algo_version` off the response and says the pipeline did not
detect a face. Errors, section headings and score captions are now `demo.*`.

Five orphaned keys were removed from the catalogues in the same pass, because a
key no page renders is a translation that will silently rot.

Issues: Delhi coordinates are hardcoded here while `DEMO_COORDS` in
`utils/format.ts` exists for exactly this and is unused, and the same literals
appear again in `EmergencyHub`. `api.demoEnroll` is never called, so the
demo-enroll endpoint is unreachable from the UI. Scenario buttons use `card` as
their base class with a `hover:` rule on a removed token, so there is no hover
feedback at all.

## Admin

`pages/Admin.tsx` -> `Admin`. Route: `/admin`, behind `AdminOnly`.

Five tabs (`type Tab = "analytics" | "users" | "settings" | "hospitals" | "audit"`):
analytics (four tiles, identifications by day, outcome breakdown), users (toggle
active, toggle each of five roles), settings (edit on blur), hospitals (list plus
add form), and the audit log.

Ten calls: `adminAnalytics`, `adminUsers`, `adminSettings`, `adminHospitals`,
`adminAudit` on load, then `adminSetRoles`, `adminSetActive`,
`adminUpdateSetting`, `adminAddHospital`.

**Fixed in Phase 1.** `ROLES` was
`["registered", "medical_responder", "police_responder", "auditor", "admin"]`.
`"registered"` is not a role — the seeded name is `registered_user` — so
`RoleAssignmentIn` rejected it with a 400 and the chip did nothing, while
`hospital` was missing entirely and could not be provisioned through the UI at
all. `ROLES` is now typed as `Role[]` and holds all six assignable roles;
`public` is excluded because it is the implicit role of an unauthenticated
bystander, not something an admin assigns. Asserted as set equality against
`ROLE_PERMISSIONS` in both directions, because the original bug was a
substitution and a subset check would have passed.

**Localized in Phase 9.** Tabs, tile captions, the outcome breakdown, role
names, form labels, settings rows, hospital fields, audit columns and every
error path are now `admin.*` / `role.*` keys.

There are now **two** role maps, and they disagree on purpose, which is a trap:

- `ROLES` is the assignable set — six roles, and `public` is not in it.
- `ROLE_LABELS` is a total map over the `Role` type, so it must include
  `public`, because the audit log renders the role of a row whose subject was
  never assigned a role.

Writing `ROLES` alone and indexing `ROLE_LABELS[role]` produced a typecheck
error the moment an audit row carried `public`. Both maps are typed, so the two
constraints are checked rather than remembered.

Still open, and none of it is small:

- Data loads per tab and is **never refetched** on re-select, so changes made
  elsewhere go stale.
- There is no refresh affordance, so a mistyped setting can only be corrected by
  guessing the old value.
- `api.adminSessions` exists but is never called, so there is no
  session-management screen.
- Granting or revoking `admin` by chip click has no confirmation.
- `fail` is declared after the effect that closes over it. It works only because
  effect bodies run after render, which is fragile — a small refactor breaks it.

## Privacy

`pages/Privacy.tsx` -> `Privacy`. Route: `/privacy`.

Static: six privacy principles (`PRINCIPLES`) plus a role-based-access list and
a synthetic-data disclaimer. No API calls, no state.

The colour problem is fixed — it used `text-white` on the light canvas and
`text-accent-400` five times, neither of which resolved, so its headings were
effectively invisible.

**Rewritten in Phase 9.** Every string, including the heading, now resolves
through `privacy.*`, so the `privacy.title` key that existed and was never used
is finally rendered. For a page whose entire content is claims about data
handling, English literals in the source were the wrong thing to leave behind —
a privacy notice is not the page to ship partially translated.

## Connect

`pages/Connect.tsx` -> `Connect`. Route: `/connect`. No guard; no auth needed.

The screen that points a packaged build at a backend. A Capacitor app cannot run
the Python service and has no same-origin `/api`, so the device must be told
where a running server lives. The value is saved in `localStorage` under
`traya_api_base` and read by `getApiBase()` on every request, so a shipped APK
can be re-pointed with no rebuild and holds no server secret - only a URL.

State: `url`, `busy`, `error`, `report`. `report` is the `HealthReport` returned
by `checkConnection(withScheme(url))`, and the base is saved **only after**
`/api/health` answers, so a typo cannot leave the app pointed at a dead host. The
field is a text input, not `type="url"`, because a person types
`192.168.1.10:8000` and the browser would reject the missing scheme before
submit; `withScheme` prepends `http://` when the scheme is absent.

On a native platform with no base configured, `Layout` redirects here on first
run. The More sheet's **Server settings** row and the link under the landing page
reach it afterwards. This page is the reason `client.ts` exposes `getApiBase`,
`setApiBase`, `clearApiBase`, `getDefaultApiBase`, `normalizeApiBase` and
`checkConnection`; see [state-and-data.md](state-and-data.md#the-backend-base-is-a-runtime-setting).
