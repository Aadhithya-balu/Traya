[../README.md](../README.md) | [Frontend index](README.md) | [Components](components.md)

# State, Data and Types

How the frontend holds state, talks to the API, and describes what comes back.

| File | Exports |
|---|---|
| [`context/AuthContext.tsx`](#authcontext) | `AuthProvider`, `useAuth` |
| [`context/EmergencyContext.tsx`](#emergencycontext) | `EmergencyProvider`, `useEmergency` |
| [`hooks/useCamera.ts`](#usecamera) | `useCamera`, `blobToBase64`, `fileToBase64` |
| [`hooks/useGeolocation.ts`](#usegeolocation) | `useGeolocation` |
| [`api/client.ts`](#api-client) | `api`, `ApiError`, `getTokens`, `setTokens`, `clearTokens` |
| [`api/types.ts`](#api-types) | 31 interfaces |

---

## AuthContext

`context/AuthContext.tsx`. Owns the current user and the auth actions.

`useAuth()` throws if used outside `AuthProvider`, which turns a wiring mistake
into an immediate error rather than a silent `undefined`.

| Member | Type | Notes |
|---|---|---|
| `user` | `UserSummary \| null` | |
| `status` | `"loading" \| "authenticated" \| "unauthenticated" \| "error"` | The real state. See below. |
| `loading` | `boolean` | `status === "loading"`. Kept for the guards. |
| `login` | `(email, password) => Promise<void>` | Stores tokens, then sets the user. |
| `register` | `(payload) => Promise<void>` | Accepts 4 fields; `date_of_birth` is dropped even though the API and `UserSummary` both support it. |
| `logout` | `() => void` | Clears tokens and the user. |
| `isAuthed` | `boolean` | `!!user`. |
| `hasRole` | `(...roles: string[]) => boolean` | OR semantics. `false` for a null user. |
| `can` | `(permission: string) => boolean` | Reads `user.permissions`. `false` for a null user. |
| `refreshUser` | `() => Promise<void>` | Re-fetches `GET /auth/me`. |

### Why `status` exists, and what "emergency logs me out" actually was

`refreshUser` previously had a bare `catch` that nulled the user, so **any**
failure to reach `GET /auth/me` looked identical to a revoked session: the
access token stayed in `localStorage` and the UI went signed out. Combined with
a reachable Logout button on `/emergency/*` (`Layout.tsx`), that produced the
reported complaint. There is no automatic logout anywhere in the codebase.

The state machine now separates the four cases:

| Response | `status` | Effect |
|---|---|---|
| 200 | `authenticated` | user set |
| 401 / 403 | `unauthenticated` | **tokens cleared** - the credential really is dead |
| network failure, timeout, 5xx | `error` | user kept, tokens kept |
| no token on boot | `unauthenticated` | |

Only a definitive rejection from the server ends a session. A responder on a
poor connection in a basement now sees an error state, not a login screen, and
the emergency flow is unaffected either way because the session token lives in
`sessionStorage` and `EmergencyContext` never touches the account tokens.

### Persistence

None in this file. It reads and writes `localStorage["traya_access"]` and
`localStorage["traya_refresh"]` indirectly through
[`api/client.ts`](#api-client). The context does check the raw key
`"traya_access"` directly on boot rather than calling `getTokens()`, so **the
storage key string is duplicated in two files**. Export the key from the client
and import it.

On boot: if there is no access token, `status` becomes `unauthenticated`
immediately; otherwise `refreshUser()` runs and the state resolves in `finally`.

**Token storage is `localStorage`,** so any XSS can read the access token. For
this product that is a deliberate trade-off - a responder in a hurry must stay
signed in, and a `httpOnly` cookie would require CSRF handling on a public
emergency API that uses a different credential. If the threat model changes,
this is the first thing to revisit.

`can` is **defined but never called** - see
[routing.md](routing.md#client-side-role-and-permission-checks).

## EmergencyContext

`context/EmergencyContext.tsx`. Holds the in-flight emergency session so a page
refresh does not lose the photo or the result.

`useEmergency()` throws if used outside `EmergencyProvider`.

| Member | Type |
|---|---|
| `sessionId` | `string \| null` |
| `result` | `IdentifyResult \| null` |
| `previewImage` | `string \| null` |
| `setSession` | `(id: string) => void` |
| `setResult` | `(result: IdentifyResult, preview: string \| null) => void` |
| `setPreview` | `(preview: string \| null) => void` |
| `clear` | `() => void` |

### Persistence

All in `sessionStorage`, deliberately not `localStorage` - an emergency session
should not outlive the browser tab.

| Key | Value |
|---|---|
| `traya_emergency_session` | Session id. |
| `traya_emergency_result` | `JSON.stringify(IdentifyResult)`. |
| `traya_emergency_preview` | Raw base64 of the photo. |

The result is parsed behind a `try`/`catch` that removes the corrupt key and
returns `null` rather than throwing, so a half-written or manually-edited entry
degrades to "no result" instead of a white screen.

### Current wiring

`Emergency.tsx` now writes through the context, so the result reaches the hub:

```typescript
const result = await api.identify(session.session_id, imageB64);
setSession(session.session_id);
setResult(result, imageB64);
navigate(`/emergency/${session.session_id}`);   // no `state:` argument
```

It previously passed the result to `navigate()` as router `state` while
`EmergencyHub` read only this context, so the Match Result tab rendered nothing
and the responder could never reach the confirm action. Context is also the
right home for it: it survives a reload of the hub, which router state does not.

`clear()` still has no "end session" UI, so `sessionStorage` accumulates across
attempts in a tab. It is now called when an emergency session is replaced, so at
most one attempt is retained.

### Storage sizing

`previewImage` is a **full-resolution base64 JPEG in `sessionStorage`**, which
browsers typically cap at about 5 MB. `useCamera` captures at 1080x1440 at
quality 0.9, which can produce a string well over 1 MB. It usually fits, but a
larger capture or a second attempt in the same tab can throw a quota error that
nothing catches. Either store the preview as a `Blob` in IndexedDB, or downscale
before encoding. This is a latent failure, not a hypothetical one.

## useCamera

`hooks/useCamera.ts` -> `useCamera`, `blobToBase64`, `fileToBase64`,
`CameraErrorCode`, `CaptureResult`, `CAMERA_ERROR_KEYS`.

| Member | Type | Notes |
|---|---|---|
| `stream` | `MediaStream \| null` | Mirrored into a ref. |
| `error` | `CameraErrorCode \| null` | A **code**, not prose. Map it with `CAMERA_ERROR_KEYS`. |
| `capturing` | `boolean` | True only during the canvas encode. |
| `active` | `boolean` | `!!stream`. |
| `videoRef` | `RefObject<HTMLVideoElement \| null>` | **The consumer must attach it to a `<video>`.** |
| `start` | `() => Promise<void>` | Requests the **rear** camera. |
| `stop` | `() => void` | Stops all tracks. |
| `capture` | `() => Promise<CaptureResult>` | Never `null`; see below. |

`start` requests `facingMode: { ideal: "environment" }` at 1080x1440 (3:4), which
matches the `aspect-[3/4]` framing guide in `Emergency`. `capture` falls back to
720x960 if `videoWidth`/`videoHeight` is 0. `play()` rejections are swallowed.
An unmount cleanup stops the stream, so the recording indicator does not stick.

### `error` is a code, and `capture` cannot return `null`

Both were changed in Phase 9 and both had the same defect: the hook produced
English, so the hook could not be translated. `error` now yields a
`CameraErrorCode` and `capture` yields a discriminated `CaptureResult`:

```ts
type CaptureResult =
  | { ok: true; data: string }
  | { ok: false; code: CameraErrorCode };
```

`capture` previously returned `Promise<string | null>`, and both call sites
treated `null` as "nothing to report" - a failed capture produced no message at
all, so the button simply stopped working. A result object makes the failure
impossible to drop: `ok: false` must be handled.

`CAMERA_ERROR_KEYS` maps every code to an i18n key, and it is exhaustive over
`CameraErrorCode`, so adding a code without a translation is a typecheck
failure. `test_hook_error_code_maps_are_exhaustive_and_translated` asserts the
same thing from the other side, by scanning the catalogues.

`NotFoundError` and `NotReadableError` are distinguished, so a camera that is
present but busy no longer collapses into the generic message.

`blobToBase64` strips the `data:...;base64,` prefix via `FileReader`;
`fileToBase64` delegates to it.

## useGeolocation

`hooks/useGeolocation.ts` -> `useGeolocation`, `Coords`, `GeoErrorCode`,
`GEO_ERROR_KEYS`.

`useGeolocation(enabled = true)` returns
`{ coords, error, loading, request }`, a one-shot high-accuracy fix with a 10
second timeout (`{ enableHighAccuracy: true, timeout: 10000 }`). No watch
position, so the location is a single snapshot.

`error` is a `GeoErrorCode` mapped through `GEO_ERROR_KEYS`, for the same reason
`useCamera.error` is a code: a raw English string here is English the Tamil UI
cannot avoid.

The effect auto-requests when `enabled` is true. `EmergencyHub` passes
`enabled = false` and drives it manually, because it only wants a fix when the
user opens the Location tab.

`request` is a `useCallback` with a `[enabled]` dep that the body never reads -
vestigial, and it would be flagged by a real exhaustive-deps rule. Permission is
detected via `err.code === err.PERMISSION_DENIED`, which compares against an
instance property; it works but is unconventional.

## api/client

`api/client.ts`. One `request<T>` core, 44 `api.*` methods, `ApiError`, and
token helpers.

### Two token stores, and they are not interchangeable

| Helper | Backing store | Holds |
|---|---|---|
| `getTokens` / `setTokens` / `clearTokens` | `localStorage` | the account access and refresh tokens |
| `getSessionToken` / `setSessionToken` / `clearSessionToken` | `sessionStorage` | the emergency session credential |

The split is deliberate and load-bearing. The emergency token is scoped to one
attempt in one tab, so it dies with the tab. The account tokens must outlive it,
so they do not. Conflating them is how "the emergency flow logs me out" starts:
`EmergencyContext` must never call `clearTokens`, and
`test_emergency_mode_does_not_clear_the_account_token` asserts it does not.

`setTokens` only writes the refresh token when the response includes a truthy
one, so a response with an explicitly null refresh token leaves a stale value
behind.

### `request<T>()`

1. Prefixes `/api`.
2. Attaches `Authorization: Bearer <access>` when a token exists.
3. Attaches `X-TRAYA-Session-Token` when the path is under `/emergency/` **and is
   not** `/emergency/start`. Step one issues the credential, so it cannot send
   it; every step after it must, or the backend returns 403.
4. On **401**, except for `/auth/login` and `/auth/refresh`, performs a
   single-flight refresh via a module-level `refreshPromise`, then replays the
   original request once.
5. Returns `undefined` for 204.
6. Parses JSON only when the content type includes `application/json`.
7. Throws `ApiError(status, detail)`, or `ApiError(0, ..., isNetwork: true)` when
   the request never reached the server.

`ApiError` extends `Error` with `status: number` and `detail: string`, so pages
can show the backend's own message. `isNetwork` is the addition: "the server
could not be reached" and "the server rejected you" are different facts to a
person in an emergency, and the previous code surfaced both as an opaque
`TypeError`. `Emergency.tsx` now distinguishes them, and a 403 specifically
becomes the expired-session message rather than a raw backend string.

**Refresh weaknesses, before and after.**

Fixed in this pass:

- The `refreshPromise` is now `.catch`-guarded and cleared in a `finally`, so a
  rejected refresh no longer leaves an unhandled rejection and does not wedge
  every later 401 onto a dead promise.
- There is now an `AbortController` with a timeout and a caller-supplied `signal`.
  A hung request rejects instead of latching a `busy` spinner forever, which on
  a phone on a poor connection was a realistic failure.

Still true, and deliberate:

- On refresh failure the user is **not** logged out and the tokens are **not**
  cleared. A transport blip must not end a session, and the app no longer loops
  because of the `finally`. If the token is genuinely dead the UI shows the
  error and the person can retry. Signing out on a failed refresh is a policy
  decision, not a bug fix - see [SECURITY_MODEL.md](../SECURITY_MODEL.md).
- `options.headers` is merged with a plain object spread, so passing a `Headers`
  instance would be silently mangled. No caller does.

### Method index

Paths are relative to `/api`.

**Auth** - `login` POST `/auth/login`, `register` POST `/auth/register`,
`me` GET `/auth/me`.

**Emergency** - `startSession` POST `/emergency/start`, `sessionStatus` GET
`/emergency/{id}`, `capture` POST `/emergency/{id}/capture`, `identify` POST
`/emergency/{id}/identify`, `confirm` POST `/emergency/{id}/confirm`,
`medicalSummary` GET `/emergency/{id}/medical-summary`, `responderProfile` GET
`/emergency/{id}/responder-profile`, `contactAction` POST `/emergency/{id}/contact`,
`sendLocation` POST `/emergency/{id}/location`, `timeline` GET
`/emergency/{id}/timeline`, `incidentEvents` GET `/emergency/{id}/events`,
`thresholds` GET `/emergency/thresholds`.

**Fallback** (Phase 7) - `fallbackByIdentifier` POST
`/emergency/{id}/fallback/emergency-identifier`, `fallbackManualEntry` POST
`/emergency/{id}/fallback/manual-entry`, `fallbackRequestAssistance` POST
`/emergency/{id}/fallback/assistance`, `fallbackConfirmAssistance` POST
`/emergency/{id}/fallback/assistance/confirm`, `fallbackUnidentified` POST
`/emergency/{id}/fallback/unidentified`.

Two of these are wired and must not be conflated. `timeline` is the **audit
trail** (`audit_logs`), readable with the session token and useful with
`view_audit_logs`; `incidentEvents` is the **operational record**
(`incident_events`), also readable with the session token and answering "how was
this person identified?". `thresholds` is the third distinct thing: unauthenticated,
no user data, and it exists so a confidence score cannot be rendered as validated.

Every fallback method requires an authenticated responder *and* the session token.
A caller must handle **403 as a normal outcome**, not an error - a police
responder is a legitimate caller of `medicalSummary` who will be refused it and
routed to `responderProfile` instead. `fallbackUnidentified` returning success is
not a failure of the call: it is the system recording that nobody was identified,
which is a supported result and the reason the method exists.

**Hospitals** - `nearbyHospitals` GET `/hospitals/nearby`.

**Users** - `updateProfile` PUT `/users/profile`, `getMedical` GET
`/users/medical`, `updateMedical` PUT `/users/medical`, `listContacts` GET
`/users/contacts`, `addContact` POST `/users/contacts`, `deleteContact` DELETE
`/users/contacts/{id}`, `listFeatures` GET `/users/features`, `addFeature` POST
`/users/features`, `deleteFeature` DELETE `/users/features/{id}`, `listConsents`
GET `/users/consents`, `grantConsent` POST `/users/consents`, `withdrawConsent`
POST `/users/consents`, `biometricStatus` GET `/biometric/status`,
`startEnrollment` POST `/biometric/enrollment/start`,
`submitEnrollmentSample` POST `/biometric/enrollment/{id}/sample`,
`completeEnrollment` POST `/biometric/enrollment/{id}/complete`,
`cancelEnrollment` DELETE `/biometric/enrollment/{id}`, `deleteBiometric` DELETE
`/users/biometric`, `accessHistory` GET `/users/access-history`,
`notifications` GET `/users/notifications`.

**Enrollment is four calls, not one, and the client holds no progress.** The old
`enrollBiometric` posted 2-4 images in a single request and is gone from the
client; the backend still serves `POST /biometric/enroll` for the demo seed and
its tests. `startEnrollment`, `submitEnrollmentSample`, `completeEnrollment` and
`cancelEnrollment` replace it because the wizard's state is **server** state: the
person's current step, how many samples are accepted and their own pose baseline
all live on the enrollment row. The client renders `EnrollmentState` and never
computes it, so a reload, a second device or a lost network cannot desynchronise
the person from their own progress. `submitEnrollmentSample` takes a single
image - the person is coached one capture at a time - and returns the engine's
`verdict` alongside the new state.

**Demo** - `demoScenarios` GET `/demo/scenarios`, `demoRun` POST `/demo/run`,
`demoEnroll` POST `/demo/enroll`.

**Admin** - `adminAnalytics` GET `/admin/analytics`, `adminAudit` GET
`/admin/audit`, `adminUsers` GET `/admin/users`, `adminSetRoles` PATCH
`/admin/users/{id}/roles`, `adminSetActive` PATCH `/admin/users/{id}/active`,
`adminSessions` GET `/admin/sessions`, `adminSettings` GET `/admin/settings`,
`adminUpdateSetting` PUT `/admin/settings/{key}`, `adminHospitals` GET
`/admin/hospitals`, `adminAddHospital` POST `/admin/hospitals`.

**Four methods are defined but never called:** `sessionStatus`, `notifications`,
`demoEnroll`, `adminSessions`. They are not dead weight necessarily - the admin
sessions endpoint and demo enrollment are both genuinely useful screens that
nobody has built - but nothing depends on them today.

Seven methods return `Record<string, unknown>` or `Record<string, unknown>[]`,
which gives callers no help at all. Typing them against the corresponding Pydantic
schemas is a cheap, high-value cleanup.

`adminSetActive` passes `active` as a query parameter rather than a body, unlike
every other PATCH. That is a backend inconsistency, not a client choice.

## api/resultStates

`api/resultStates.ts`. **New in Phase 9.** The nine identification outcomes and
the instruction a responder should follow for each.

| Export | Kind | Purpose |
|---|---|---|
| `ResultTone` | type | `"go" \| "decide" \| "lookAgain" \| "retake" \| "neutral"`. Mapped onto the palette by `StatusBadge`. |
| `ResultState` | interface | `{ badge: StringKey, next: StringKey, tone: ResultTone }`. |
| `RESULT_STATES` | `Record<IdentifyStatus, ResultState>` | The map. Keyed on `IdentifyStatus`. |
| `analyticsBadge` | function | Resolves an `AnalyticsStatus`, including the `unknown` member a report bucket can carry. Returns `null` only if called with something outside the union. |
| `RESULT_STATE_ORDER` | readonly tuple | The same nine in the order a responder meets them, for exercising every branch. |

This is what makes Phase 9's "every result state reachable, each with a working
next action" true **by construction** rather than by review. Keying on
`IdentifyStatus` means the compiler rejects a state added to the pipeline with
no responder instruction here.

`analyticsBadge` is deliberately separate rather than folded into
`RESULT_STATES`. Folding `unknown` in would mean either weakening the key type
to a string - giving up the exhaustiveness that is the entire value of the table
- or special-casing inside a map whose guarantee is that it cannot need one. An
analytics row describes a bucket in a report, not something a responder is
looking at, so it gets a neutral tone and no instruction.

Two things are deliberately **not** in the table:

- **Severity.** Colour is not information. A responder deciding whether to act
  should be reading the instruction, not judging an amber swatch, and tone is
  the channel that fails hardest for colour-blind users and in sunlight.
- **Confidence.** `NO_FACE` and `MULTIPLE_FACES` have no score at all, so a
  percentage beside a photo with no usable face would be a lie of omission.

Asserted from pytest by
`test_every_identification_state_has_a_badge_and_a_next_action`,
`test_no_two_result_states_share_the_same_badge_text` and
`test_result_state_keys_exist_in_both_languages`, which parse this file
textually - the suite has no node runner, and the properties under test are
exactly what is written in the source.

## api/types

`api/types.ts`. 31 interfaces mirroring the Pydantic schemas.

| Interface | Purpose |
|---|---|
| `UserSummary` | The signed-in user. Carries `roles` and `permissions`. |
| `TokenResponse` | Access plus refresh token and the user. |
| `Role` | The seven seeded roles. Mirrors `ROLE_PERMISSIONS`; asserted equal by `backend/tests/test_frontend_contract.py`. |
| `ConsentStatus` | `"active" \| "withdrawn"`. **Not** `"granted"`. |
| `BiometricEnrollmentStatus` | `"not_enrolled" \| "in_progress" \| "enrolled"`. **Not** `"ENROLLED"`. |
| `QualityScores` | The quality fields, scores nullable. The shape `QualityPanel` accepts. |
| `Quality` | The same fields, scores non-null, plus `reasons` and `reason_codes`. |
| `Candidate` | One ranked match: `user_id`, `confidence`, `rank`, `method`, `status`. |
| `IdentifyResult` | The full result: `quality`, `face_count`, `engine_mode`, `demo_mode`, `algo_version`. |
| `EmergencyStartOut` | Session id, access type, expiry, and **`session_token`**. |
| `CaptureOut` | **Flat** quality scores from the capture endpoint. |
| `SessionStatus` | Session state and outcome. |
| `PublicSummary` | What anyone with session access may see. |
| `ResponderProfile` | Extends `PublicSummary` with notes, features and all contacts. |
| `TimelineEvent` | `{ at, action, details }`. |
| `ContactAction` | The logged contact action and its timestamp. |
| `HospitalNearby` | Distance, travel time and availability as stored. |
| `EmergencyContact` | A saved contact. |
| `MedicalProfile` | The citizen's own medical data. |
| `VisibleFeature` | A scar, tattoo, birthmark or mark. |
| `Consent` | Type, status, version, timestamps. **No `id`** - key on type plus version. |
| `BiometricStatus` | Status, enrolment time, sample count, algorithm version. |
| `EnrollmentStep` | One coached pose: `index`, `key`, `pose`, `done`. `done` is the server's view. |
| `EnrollmentState` | Progress: `enrollment_id`, `status`, `current_step`, `total_steps`, `accepted_samples`, `rejected_samples`, `min_samples`, `steps`, `current_instruction`, `can_complete`. |
| `SampleVerdict` | One capture's verdict: `accepted`, `guidance`, `quality_score`, `face_count`, `step_index`, `step_key`, `matched_step`, `observed_direction`, `pose_offset_x`/`_y`, `pose_confident`. |
| `ConsistencyReport` | `min_pairwise`, `mean_pairwise`, `pairs`, `threshold` from `complete`. |
| `EnrollmentComplete` | What `complete` returns: status, `num_samples`, `algo_version`, `enrolled_at`, `steps_completed`, `consistency`. |
| `DemoScenario` | One demo scenario. |
| `DemoRun` | Session plus its `identification`. |
| `Analytics` | System-wide counters and the 13-day breakdown. |
| `AdminUser` | User list row with roles. |
| `AuditLog` | One audit row. |
| `Setting` | Key, value, description. |
| `HospitalAdmin` | Full hospital record for the admin console. |
| `IncidentEvent` | One incident log entry: `sequence`, `event_type`, `actor_id`, `subject_id`, `fallback_used`, `details`, `at`. Carries **no clinical detail**, which is what makes it safe for every responder role to read. |
| `IncidentTimeline` | `{ session_id, status, events }`. Ordered by `sequence`, not `at`. |
| `FallbackResult` | What a fallback resolved to: `method`, `identified`, `resolved`, optional `subject_name`, `awaiting_second_party`, `reason`. `identified: false` with `resolved: true` is the unidentified path working, not an error. |
| `PublishedThresholds` | `high_confidence`, `review`, `face_fallback`, `dimension`, `engine_mode`, `engine_version`, **`simulated`**, **`calibrated`**, `note`. |

### `IncidentStatus` and `IdentificationMethod`

Two unions added in Phase 7, and they replace a bare `string` on the field that
matters most.

`SessionStatus.status` was typed `string`, which is the fourth instance of the
defect below and the most consequential: it is what decides whether a responder
sees a result, a review queue, or a dead end. It is now `IncidentStatus` - the ten
values in `app/services/incident_service.py`, asserted equal to that set by
`test_incident_status_union_matches_the_service`. The vocabulary changed with it:
`active` became `created` / `identifying` / `review_required` / `no_match`
depending on how far the attempt got, and `completed` became `identified` or
`resolved`, because an unidentified person at a hospital entrance is not a
success. `expired` and `aborted` were already written by the repository and are
kept, so all four terminal states are representable.

`IdentificationMethod` is `face` plus the four fallback paths.
`test_identification_method_union_matches_the_service` asserts the four are all
present, because **a missing fallback in this union is a dead end in the UI** -
the backend can offer a path the frontend cannot express.

`PublishedThresholds.simulated` and `.calibrated` are separate booleans on
purpose. This project is currently in a state one boolean cannot express: a real
recogniser running on thresholds that have never been measured against it.
`calibrated` is hardcoded `false` in the response and
`test_published_thresholds_are_disclosed_and_uncalibrated` asserts it stays false
until Phase 10 produces a measurement.

### Types that exist because a literal had drifted

Four interfaces here are not descriptions of the API. Each was added to make a
specific class of silent mismatch a compile error, and each is worth reading
before changing a field back to `string`.

**`Role`** mirrors `ROLE_PERMISSIONS`. `Admin.tsx` shipped a role called
`registered`; the seeded name is `registered_user`, so the toggle granted
nothing and `hospital` could not be provisioned at all. Because `ROLES` was a
plain `string[]`, TypeScript had no opinion. `test_admin_ui_offers_exactly_the_seeded_roles`
asserts set equality in both directions, so the list cannot drift again.

**`ConsentStatus`** is `"active" | "withdrawn"`. `Profile.tsx` compared against
`"granted"`, which the API never returns, so the condition was permanently
false: the button always granted and consent could never be withdrawn. The
field was `status: string`, so again nothing complained. Note the trap in the
sibling branch at `Profile.tsx` - it already compared against `"withdrawn"`,
which is why the bug survived review: one string in the file was right and one
was wrong, and the type could not tell them apart.

**`BiometricEnrollmentStatus`** is lowercase. `Profile.tsx` compared against
`"ENROLLED"` while the API returns `"enrolled"` (`api/biometric.py:106`,
`services/biometric/enrollment.py:316`), so a citizen who had successfully
enrolled was shown **NOT ENROLLED** and the "delete all templates" control -
the only way to revoke a biometric - never rendered. Found while fixing consent,
and the same shape of bug: a bare `string` and one wrong comparison.

**`QualityScores`** exists because `CaptureOut` and `Quality` disagree. The
backend declares all five scores as `float | None = None`, so the keys are
always present and may only be null. The client had them as `?: number | null`,
inventing a third state that is not on the wire, and bridged the gap with
`as unknown as Quality` in `Emergency.tsx` - which rendered `NaN` width bars
whenever a score was null. `QualityPanel` now takes `QualityScores` and prints
`--` for a missing score.

**`EmergencyStartOut`** carries `session_token`. The backend issued a token at
`emergency.py:180` and then required it as `X-TRAYA-Session-Token` on every
later step; the client had no field for it, so step 1 returned 200 and every
step after it returned 403. The product did not work at all.

### Still open

- **Most `status` fields are bare `string`.** The union
  `HIGH_CONFIDENCE | REVIEW_REQUIRED | ...` is duplicated in
  `StatusBadge.STATUS` and in `utils/format.STATUS_LABELS`, validated nowhere.
  Export one union from this file and import it in both places.
- `SessionStatus` is declared and returned by `api.sessionStatus`, which no page
  calls.
- `Candidate.user_id` is a UUID. The UI truncates it to 12 characters, which
  leaks no name but also gives a responder no way to act on a candidate who is
  not the top one.
