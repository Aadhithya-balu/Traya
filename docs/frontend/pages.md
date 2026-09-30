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

**complete** = design tokens, i18n keys, and layout respects the shell.
**legacy** = colour is migrated but strings are still hardcoded English.
Phase 1 moved every page off the removed `ink-*`/`slate-*` palette, so
**colour is no longer what makes a page legacy** — see
[design-system.md](design-system.md#the-palette-migration-is-done-the-hardcoded-english-is-not).
What is left is the i18n work, and on `EmergencyHub` and `Profile` that is
substantial.

| Page | Colour | Strings | Phase 1 also fixed |
|---|---|---|---|
| `EmergencyHub` | done | **hardcoded** | result plumbing, GPS source, engine disclosure |
| `Profile` | done | **hardcoded** | consent + enrolment vocabulary |
| `Admin` | done | **hardcoded** | role names |
| `Demo` | done | **hardcoded** | — |
| `Privacy` | done | **hardcoded** | invisible headings |

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

**Both functional bugs are fixed. The remaining problem on this page is that it
is still legacy in every other respect.**

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

- Every user-visible string is a literal. Five tabs' worth of labels, error
  strings and confirmations. This is the largest i18n debt in the codebase.
- The page wraps itself in `mx-auto max-w-5xl` while `Layout` already
  constrains `<main>` to `max-w-2xl`, so the two fight. Remove the page-level
  container when migrating.
- It is the largest file in the frontend at 553 lines and holds three
  sub-components inline. Phase 9 rewrites it; Phase 2 only migrates the
  strings.

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

**Fixed in Phase 1.** Both vocabulary mismatches were real, and both failed
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

Still open, and none of it is small:

- Every label, button and error string is a literal.
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

`pages/Privacy.tsx` -> `Privacy`. Route: `/privacy`. **Legacy.**

Static: six privacy principles (`PRINCIPLES`) plus a role-based-access list and
a synthetic-data disclaimer. No API calls, no state, no imports beyond React.

The colour problem is fixed — it used `text-white` on the light canvas and
`text-accent-400` five times, neither of which resolved, so its headings were
effectively invisible. What remains is worse than styling: **every string is a
hardcoded literal, including the `privacy.title` i18n key that exists and is
never used**, and the page states the project's privacy principles without a
single one of them coming from the i18n catalogue. For a page whose entire
content is claims about data handling, that is the wrong place to leave English
literals in the source.

This page should be rewritten, not restyled.
