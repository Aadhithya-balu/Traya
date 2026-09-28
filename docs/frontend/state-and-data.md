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
| [`api/types.ts`](#api-types) | 24 interfaces |

---

## AuthContext

`context/AuthContext.tsx`. Owns the current user and the auth actions.

`useAuth()` throws if used outside `AuthProvider`, which turns a wiring mistake
into an immediate error rather than a silent `undefined`.

| Member | Type | Notes |
|---|---|---|
| `user` | `UserSummary \| null` | |
| `loading` | `boolean` | Starts `true`; route guards wait on it. |
| `login` | `(email, password) => Promise<void>` | Stores tokens, then sets the user. |
| `register` | `(payload) => Promise<void>` | Accepts 4 fields; `date_of_birth` is dropped even though the API and `UserSummary` both support it. |
| `logout` | `() => void` | Clears tokens and the user. |
| `isAuthed` | `boolean` | `!!user`. |
| `hasRole` | `(...roles: string[]) => boolean` | OR semantics. `false` for a null user. |
| `can` | `(permission: string) => boolean` | Reads `user.permissions`. `false` for a null user. |
| `refreshUser` | `() => Promise<void>` | Re-fetches `GET /auth/me`; a failure nulls the user. |

### Persistence

None in this file. It reads and writes `localStorage["traya_access"]` and
`localStorage["traya_refresh"]` indirectly through
[`api/client.ts`](#api-client). The context does check the raw key
`"traya_access"` directly on boot rather than calling `getTokens()`, so **the
storage key string is duplicated in two files**. Export the key from the client
and import it.

On boot: if there is no access token, `loading` goes false immediately;
otherwise `refreshUser()` runs and `loading` clears in `finally`.

**Token storage is `localStorage`,** so any XSS can read the access token. For
this product that is a deliberate trade-off - a responder in a hurry must stay
signed in, and a `httpOnly` cookie would require CSRF handling on a public
emergency API that uses a different credential. If the threat model changes,
this is the first thing to revisit.

`refreshUser` has a bare `catch` that nulls the user, so a transient network
blip makes the app look signed out while the tokens remain in storage.

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

### Current wiring is incomplete

- `setSession` and `clear` are **never called**, so `traya_emergency_session` is
  never written and a stale session is never reset. `EmergencyHub` therefore
  falls back to the route parameter on every load.
- `setResult` is never called with a real result, so
  `traya_emergency_result` is never written and `result` is always `null`. **This
  is the cause of the blank Match Result tab** - see
  [`EmergencyHub`](pages.md#emergencyhub).
- `clear()` has no "end session" UI, so `sessionStorage` accumulates across
  attempts in a tab.

### Storage sizing

`previewImage` is a **full-resolution base64 JPEG in `sessionStorage`**, which
browsers typically cap at about 5 MB. `useCamera` captures at 1080x1440 at
quality 0.9, which can produce a string well over 1 MB. It usually fits, but a
larger capture or a second attempt in the same tab can throw a quota error that
nothing catches. Either store the preview as a `Blob` in IndexedDB, or downscale
before encoding. This is a latent failure, not a hypothetical one.

## useCamera

`hooks/useCamera.ts` -> `useCamera`, `blobToBase64`, `fileToBase64`.

| Member | Type | Notes |
|---|---|---|
| `stream` | `MediaStream \| null` | Mirrored into a ref. |
| `error` | `string \| null` | Human-readable. |
| `capturing` | `boolean` | True only during the canvas encode. |
| `active` | `boolean` | `!!stream`. |
| `videoRef` | `RefObject<HTMLVideoElement \| null>` | **The consumer must attach it to a `<video>`.** |
| `start` | `() => Promise<void>` | Requests the **rear** camera. |
| `stop` | `() => void` | Stops all tracks. |
| `capture` | `() => Promise<string \| null>` | Canvas encode, returns base64. |

`start` requests `facingMode: { ideal: "environment" }` at 1080x1440 (3:4), which
matches the `aspect-[3/4]` framing guide in `Emergency`. `capture` falls back to
720x960 if `videoWidth`/`videoHeight` are 0. `play()` rejections are swallowed.
An unmount cleanup stops the stream, so the recording indicator does not stick.

`capture` returns `null` if `video.readyState < 2` or the 2D context is
unavailable, and the caller must handle that.

`NotAllowedError` is distinguished; `NotFoundError` and `NotReadableError` are
not, so a camera present-but-busy falls into the generic message. Error strings
are hardcoded English and not i18n keys.

`blobToBase64` strips the `data:...;base64,` prefix via `FileReader`;
`fileToBase64` delegates to it.

## useGeolocation

`hooks/useGeolocation.ts` -> `useGeolocation`, `Coords`.

`useGeolocation(enabled = true)` returns
`{ coords, error, loading, request }`, a one-shot high-accuracy fix with a 10
second timeout (`{ enableHighAccuracy: true, timeout: 10000 }`). No watch
position, so the location is a single snapshot.

The effect auto-requests when `enabled` is true. `EmergencyHub` passes
`enabled = false` and drives it manually, because it only wants a fix when the
user opens the Location tab.

`request` is a `useCallback` with a `[enabled]` dep that the body never reads -
vestigial, and it would be flagged by a real exhaustive-deps rule. Error strings
are English-only. Permission is detected via `err.code === err.PERMISSION_DENIED`,
which compares against an instance property; it works but is unconventional.

## api/client

`api/client.ts`. One `request<T>` core, 44 `api.*` methods, `ApiError`, and
token helpers.

### Token storage

`getTokens`, `setTokens`, `clearTokens` wrap
`localStorage["traya_access"]` and `localStorage["traya_refresh"]`.

`setTokens` only writes the refresh token when the response includes a truthy
one, so a response with an explicitly null refresh token leaves a stale value
behind.

### `request<T>()`

1. Prefixes `/api`.
2. Attaches `Authorization: Bearer <access>` when a token exists.
3. On **401**, except for `/auth/login` and `/auth/refresh`, performs a
   single-flight refresh via a module-level `refreshPromise`, then replays the
   original request once.
4. Returns `undefined` for 204.
5. Parses JSON only when the content type includes `application/json`.
6. Throws `ApiError(status, body.detail ?? res.statusText)` otherwise.

`ApiError` extends `Error` with `status: number` and `detail: string`, so pages
can show the backend's own message.

**Refresh weaknesses worth knowing before you rely on it.**

- The `refreshPromise` is not `.catch`-guarded and is cleared after `await`, so a
  rejected refresh leaves an unhandled rejection and every later 401 re-attempts
  it.
- On refresh failure the user is **not** logged out and the tokens are **not**
  cleared, so the app loops on 401s until the tab is closed.
- There is no `AbortController` or timeout, so a hung request never rejects and a
  `busy` spinner can latch on forever. On a phone on a poor connection this is
  a realistic failure.
- `options.headers` is merged with a plain object spread, so passing a `Headers`
  instance would be silently mangled.

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
`/emergency/{id}/timeline`.

**Hospitals** - `nearbyHospitals` GET `/hospitals/nearby`.

**Users** - `updateProfile` PUT `/users/profile`, `getMedical` GET
`/users/medical`, `updateMedical` PUT `/users/medical`, `listContacts` GET
`/users/contacts`, `addContact` POST `/users/contacts`, `deleteContact` DELETE
`/users/contacts/{id}`, `listFeatures` GET `/users/features`, `addFeature` POST
`/users/features`, `deleteFeature` DELETE `/users/features/{id}`, `listConsents`
GET `/users/consents`, `grantConsent` POST `/users/consents`, `withdrawConsent`
POST `/users/consents`, `biometricStatus` GET `/biometric/status`,
`enrollBiometric` POST `/biometric/enroll`, `deleteBiometric` DELETE
`/users/biometric`, `accessHistory` GET `/users/access-history`,
`notifications` GET `/users/notifications`.

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

## api/types

`api/types.ts`. 24 interfaces mirroring the Pydantic schemas.

| Interface | Purpose |
|---|---|
| `UserSummary` | The signed-in user. Carries `roles` and `permissions`. |
| `TokenResponse` | Access plus refresh token and the user. |
| `Quality` | Nested engine quality scores plus `reasons` and `reason_codes`. |
| `Candidate` | One ranked match: `user_id`, `confidence`, `rank`, `method`, `status`. |
| `IdentifyResult` | The full result, including `quality`, `face_count`, `engine_mode`, `demo_mode`. |
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
| `DemoScenario` | One demo scenario. |
| `DemoRun` | Session plus its `identification`. |
| `Analytics` | System-wide counters and the 13-day breakdown. |
| `AdminUser` | User list row with roles. |
| `AuditLog` | One audit row. |
| `Setting` | Key, value, description. |
| `HospitalAdmin` | Full hospital record for the admin console. |

### Known type hazards

- **`CaptureOut` is flat; `Quality` is nested.** `Emergency.tsx` bridges them
  with `as unknown as Quality` and gets `NaN` bars at runtime. The fix is one
  nested `quality` object on both backend responses, then delete the cast.
- **Every `status` field is a bare `string`.** The union
  `HIGH_CONFIDENCE | REVIEW_REQUIRED | ...` is duplicated in
  `StatusBadge.STATUS` and in `utils/format.STATUS_LABELS`, validated nowhere.
  Export one union from this file and import it in both places.
- `SessionStatus` is declared and returned by `api.sessionStatus`, which no page
  calls.
- `Candidate.user_id` is a UUID. The UI truncates it to 12 characters, which
  leaks no name but also gives a responder no way to act on a candidate who is
  not the top one.
