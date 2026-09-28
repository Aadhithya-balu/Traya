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
| [`EmergencyHub`](#emergencyhub) | `/emergency/:sessionId` | 5 tabs | **legacy** |
| [`Dashboard`](#dashboard) | `/dashboard` | summary | complete |
| [`Profile`](#profile) | `/profile` | 6 sections | **legacy** |
| [`Demo`](#demo) | `/demo` | scenarios | **legacy** |
| [`Admin`](#admin) | `/admin` | 5 tabs | **legacy** |
| [`Privacy`](#privacy) | `/privacy` | none | **legacy** |

**complete** = new design tokens, i18n, layout respects the shell.
**legacy** = still carries the removed `ink-*`/`slate-*` palette and hardcoded
English. See [design-system.md](design-system.md#legacy-pages) for what that
means visually.

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

The panel's own labels are hardcoded English, not i18n keys.

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
**Legacy, and the largest un-migrated file.** 553 lines, five tabs
(`type Tab = "result" | "medical" | "contact" | "location" | "timeline"`), three
local sub-components (`MatchResultSection`, `PublicMedicalSummary`,
`ResponderExtras`), and ten pieces of state.

Calls: `api.medicalSummary`, `api.responderProfile` (role-gated),
`api.timeline`, `api.nearbyHospitals`, `api.sendLocation`, `api.contactAction`,
`api.confirm`, plus `useGeolocation(false)`.

**Two functional bugs, both worth knowing before you touch this page.**

1. **The Match Result tab renders nothing.** It reads `result` from
   `useEmergency()`, but `Emergency.tsx` only calls `setPreview` - it never calls
   `setResult` or `setSession`. So `traya_emergency_result` is never written,
   `result` is always `null`, the tab body is empty, the header badge falls
   through to `NO_MATCH`, and the confirm-identity button can never appear. The
   result is passed via router `state` instead, and this page never reads
   `useLocation().state`. **Fix by calling `setResult` and `setSession` in
   `Emergency.tsx`** (or by reading the router state here) - the context
   methods already exist and already persist to `sessionStorage`.
2. **GPS fixes are logged as `source: "manual"`.** `api.sendLocation` is always
   called with `"manual"` even when the coordinates came from the geolocation
   API. The context tier of the match engine trusts `source`, so this makes a
   GPS-derived boost indistinguishable from a typed-in one in the audit trail.

Also: the page wraps itself in `mx-auto max-w-5xl` while `Layout` already
constrains `<main>` to `max-w-2xl`, so the two fight. Remove the page-level
container when migrating.

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

`pages/Profile.tsx` -> `Profile`. Route: `/profile`, behind `Protected`. **Legacy.**

Six sections: basic info, medical profile, emergency contacts (add/remove),
visible features (add/remove), biometric consent grant/withdraw, and biometric
enrolment (upload 2-4 samples, enroll, delete).

Thirteen calls: `getMedical`, `listContacts`, `listFeatures`, `listConsents`,
`biometricStatus` on load; then `updateProfile`, `updateMedical`, `addContact`,
`deleteContact`, `addFeature`, `deleteFeature`, `grantConsent`/`withdrawConsent`,
`enrollBiometric`, `deleteBiometric`.

Issues to address when migrating:

- It uses the **legacy** `POST /biometric/enroll` bulk endpoint, not the guided
  enrollment endpoints. The guided flow in
  [services.md](../backend/services.md#guided-biometric-enrollment) exists on the
  backend and is unwired on the frontend.
- Enrolment images are capped at 4 but the label says "2-4" and **no minimum is
  enforced**; submit only disables at zero, so enrollment fires with one image
  and the server rejects it.
- The per-file 3 MB cap returns on the first oversized file, silently discarding
  images already collected.
- `medical` state is **write-only**: it is set on load and after save and never
  read, so a stale read is impossible but the state is dead weight.
- Allergies, conditions and medications are entered as comma-separated strings,
  so a value containing a comma cannot be represented.
- `flash()` uses a bare `setTimeout` with no cleanup, which warns under
  StrictMode if the component unmounts within 3 seconds.
- Same `"ENROLLED"`/`"granted"` vocabulary mismatch as `Dashboard`.

## Demo

`pages/Demo.tsx` -> `Demo`. Route: `/demo`. **Legacy.**

A grid of scenario buttons from `api.demoScenarios()`; selecting one calls
`api.demoRun(id, 28.6139, 77.209)` and renders the synthetic input, the
identification outcome, a `ScoreBar`, method badges, candidates and
`QualityPanel`. Two calls, four pieces of state.

Synthetic images flow through the **real** pipeline, which is the point: the
demo exercises production code paths, not a mock.

Issues: Delhi coordinates are hardcoded here while `DEMO_COORDS` in
`utils/format.ts` exists for exactly this and is unused, and the same literals
appear again in `EmergencyHub`. `api.demoEnroll` is never called, so the
demo-enroll endpoint is unreachable from the UI. Scenario buttons use `card` as
their base class with a `hover:` rule on a removed token, so there is no hover
feedback at all.

## Admin

`pages/Admin.tsx` -> `Admin`. Route: `/admin`, behind `AdminOnly`. **Legacy.**

Five tabs (`type Tab = "analytics" | "users" | "settings" | "hospitals" | "audit"`):
analytics (four tiles, identifications by day, outcome breakdown), users (toggle
active, toggle each of five roles), settings (edit on blur), hospitals (list plus
add form), and the audit log.

Ten calls: `adminAnalytics`, `adminUsers`, `adminSettings`, `adminHospitals`,
`adminAudit` on load, then `adminSetRoles`, `adminSetActive`,
`adminUpdateSetting`, `adminAddHospital`.

Module constant `ROLES = ["registered", "medical_responder", "police_responder",
"auditor", "admin"]`. **`"registered"` is not a real role** - the actual name is
`registered_user`, and `hospital` is missing. `RoleAssignmentIn` rejects unknown
names with 400, so toggling that chip fails server-side. Fix before use.

Also: data loads per tab and is **never refetched** on re-select, so changes
made elsewhere go stale; there is no refresh affordance, so a mistyped setting
can only be corrected by guessing the old value; `api.adminSessions` exists but
is never called, so there is no session-management screen; and granting or
revoking `admin` by chip click has no confirmation.

`fail` is declared after the effect that closes over it. It works only because
effect bodies run after render, which is fragile - a small refactor would break
it.

## Privacy

`pages/Privacy.tsx` -> `Privacy`. Route: `/privacy`. **Legacy, and the
worst-styled page in the repository.**

Static: six privacy principles (`PRINCIPLES`) plus a role-based-access list and
a synthetic-data disclaimer. No API calls, no state, no imports beyond React.

It uses `text-white` on the now-light canvas, so its headings are effectively
invisible, and `text-accent-400` five times, a token that no longer exists. The
`privacy.title` i18n key exists and is never used. This page should be
rewritten, not restyled.
