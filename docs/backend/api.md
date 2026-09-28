[../README.md](../README.md) | [Backend index](README.md)

# HTTP API Reference

Every endpoint TRAYA exposes. All paths are relative to the `/api` prefix set by
`settings.API_PREFIX`, so a route declared as `prefix="/auth"` at `POST /login`
is reachable at `POST /api/auth/login`.

## How to read this

**Auth** column values:

| Value | Meaning |
|---|---|
| `public` | No credential required. |
| `session` | `X-TRAYA-Session-Token` matching the session, **or** a responder JWT holding `identify_person`. |
| `bearer` | A signed-in user (`Authorization: Bearer <jwt>`). |
| `permission: X` | A signed-in user holding permission `X` via `require_permission`. |

Per [ADR 0002](../decisions/0002-session-token-authorization.md), a session id
never authorizes access on its own. `session.access_denied` is audited on every
rejected attempt.

---

## `app/api/auth.py` - prefix `/auth`

Handles registration, login, refresh and identity. Registered in
`app/api/__init__.py` and mounted at `/api/auth`.

| Endpoint | Auth | Request | Response | Notes |
|---|---|---|---|---|
| `POST /api/auth/register` | `public` | `RegisterRequest` | `TokenResponse` (201) | 409 on duplicate email (lowercased). Grants `registered_user`. Audits `user.registered`. |
| `POST /api/auth/login` | `public` | `LoginRequest` | `TokenResponse` | 401 on bad credentials (audits `auth.failed`), 403 if `is_active` is false. |
| `POST /api/auth/refresh` | `public` | `RefreshRequest` | `TokenResponse` | Requires a token of `type == "refresh"`, else 401. Re-issues both tokens. |
| `GET /api/auth/me` | `bearer` | - | `UserSummary` | Includes `permissions` resolved from the database. |
| `GET /api/auth/permissions` | `public` | - | `PermissionOut[]` | Returns all 18 permissions with description and the roles holding each. **Intentionally public** so the access model is inspectable. Calls `ensure_permission_matrix` first. |

---

## `app/api/users.py` - prefix `/users`

Citizen self-service: profile, medical data, contacts, visible features, consent
and their own access history. `MAX_CONTACTS = 10`.

| Endpoint | Auth | Request | Response | Notes |
|---|---|---|---|---|
| `GET /api/users/profile` | `permission: manage_own_profile` | - | `dict` | Untyped; see known gaps. |
| `PUT /api/users/profile` | `permission: manage_own_profile` | `UpdateProfileRequest` | `dict` | |
| `GET /api/users/medical` | `permission: manage_own_profile` | - | `MedicalProfileOut` | |
| `PUT /api/users/medical` | `permission: manage_own_profile` | `MedicalProfileIn` | `MedicalProfileOut` | Validates blood group. |
| `GET /api/users/contacts` | `permission: manage_own_profile` | - | `EmergencyContactOut[]` | Primary first, then name. |
| `POST /api/users/contacts` | `permission: manage_own_profile` | `EmergencyContactIn` | `EmergencyContactOut` (201) | 400 when the 10-contact cap is hit. |
| `PUT /api/users/contacts/{contact_id}` | `permission: manage_own_profile` | `EmergencyContactIn` | `EmergencyContactOut` | `is_primary` de-duplicated via `clear_primary_contacts`. |
| `DELETE /api/users/contacts/{contact_id}` | `permission: manage_own_profile` | - | 204 | |
| `GET /api/users/features` | `permission: manage_own_profile` | - | `VisibleFeatureOut[]` | Newest first. |
| `POST /api/users/features` | `permission: manage_own_profile` | `VisibleFeatureIn` | `VisibleFeatureOut` (201) | `feature_type` regex `scar\|tattoo\|birthmark\|mark`. |
| `DELETE /api/users/features/{feature_id}` | `permission: manage_own_profile` | - | 204 | |
| `GET /api/users/consents` | `permission: manage_own_consent` | - | `ConsentOut[]` | Newest first. |
| `POST /api/users/consents` | `permission: manage_own_consent` | `ConsentIn` | `ConsentOut` | Grant or withdraw. |
| `GET /api/users/biometric-status` | `permission: enroll_biometric` | - | `BiometricStatusOut` | Never returns embeddings. |
| `DELETE /api/users/biometric` | `permission: enroll_biometric` | - | 204 | |
| `DELETE /api/users/account` | `permission: manage_own_profile` | `DeleteAccountRequest` (JSON body) | 204 | **Soft** delete: sets `is_active=False` and rewrites the email to `{id}@deleted.traya`. Use `client.request("DELETE", ...)` in tests - `TestClient.delete()` has no `json=` kwarg. |
| `GET /api/users/access-history` | `bearer` | `limit` (1-200, default 50) | `TimelineEventOut[]` | Who accessed this person's data. |
| `GET /api/users/notifications` | `bearer` | - | `dict[]` | Hardcoded limit 30, untyped. |

---

## `app/api/biometric.py` - prefix `/biometric`

Two paths: the legacy bulk endpoint and the coached guided enrollment flow.
Both require active biometric consent.

| Endpoint | Auth | Request | Response | Notes |
|---|---|---|---|---|
| `POST /api/biometric/enroll` | `permission: enroll_biometric` | `BiometricEnrollRequest` (1-8 images) | `dict` | **Legacy.** 409 without active consent, 422 with fewer than 2 usable images. Images are decoded, embedded, then discarded; only encrypted embeddings persist. |
| `GET /api/biometric/status` | `permission: enroll_biometric` | - | `BiometricStatusOut` | |
| `POST /api/biometric/enrollment/start` | `permission: enroll_biometric` | - | `dict` | Resumes an in-progress enrollment, or abandons a stale one. 409 without consent. |
| `POST /api/biometric/enrollment/{enrollment_id}/sample` | `permission: enroll_biometric` | `BiometricEnrollRequest` (only `images[0]` used) | `{verdict, state}` | 404 not owner, 409 not in progress, 410 expired. |
| `POST /api/biometric/enrollment/{enrollment_id}/complete` | `permission: enroll_biometric` | - | `dict` | 422 with fewer than 3 accepted samples. Replaces embeddings atomically. |
| `DELETE /api/biometric/enrollment/{enrollment_id}` | `permission: enroll_biometric` | - | `dict` | Marks the enrollment `abandoned`. Not a row delete. |

Guidance codes come from the engine's own `reason_codes`, so the engine stays the
single source of truth for whether a capture is usable. Pose is advisory: a pose
mismatch is reported and the step advances, it does not reject.

---

## `app/api/emergency.py` - prefix `/emergency`

The public emergency flow. All session sub-paths accept either the session
token or a responder JWT.

| Endpoint | Auth | Request | Response | Notes |
|---|---|---|---|---|
| `POST /api/emergency/start` | `public` | `EmergencyStartRequest?` (optional body) | `EmergencyStartOut` | Returns a session id **and** an access token, once. `access_type="public"`, `initiator_id=None`, device id hashed. Optional lat/lng stores a `Location` with `source="manual"`. |
| `GET /api/emergency/{session_id}` | `session` | - | `SessionStatusOut` | 404 unknown, 410 expired or aborted. Expiry is **persisted** on read. |
| `POST /api/emergency/{session_id}/capture` | `session` | `CaptureRequest` | `CaptureOut` | Quality gate only; does not match. |
| `POST /api/emergency/{session_id}/identify` | `session` | `IdentifyRequest` | `IdentifyOut` | Carries `engine_mode` and `demo_mode`. |
| `POST /api/emergency/{session_id}/confirm` | `permission: confirm_identity` + session | `ConfirmRequest` | `dict` | Human confirmation of a candidate. |
| `GET /api/emergency/{session_id}/medical-summary` | `session` | - | `dict` | **403** unless `status == "completed"` and `identified_user_id` is set. Public subset only. |
| `GET /api/emergency/{session_id}/responder-profile` | `permission: view_emergency_profile` + session | - | `dict` | Extends the public summary. |
| `POST /api/emergency/{session_id}/contact` | `session` | `ContactActionIn` | `ContactActionOut` | `call`, `sms` or `share_location`. Logs, it does not send. |
| `POST /api/emergency/{session_id}/location` | `session` | `LocationIn` | `LocationOut` | `source` must reflect reality: `gps` or `manual`. |
| `GET /api/emergency/{session_id}/timeline` | `session` | - | `TimelineEventOut[]` | Chronological audit for the session. |

Rate limited to 10 requests per 60s per IP by `RateLimitMiddleware`, which
returns 429 with a `Retry-After` header and writes a `rate_limited` audit row.

---

## `app/api/hospitals.py` - prefix `/hospitals`

| Endpoint | Auth | Query | Response | Notes |
|---|---|---|---|---|
| `GET /api/hospitals/nearby` | `public` | `lat` (-90..90), `lng` (-180..180), `radius_km` (1-500, default 50) | `HospitalNearbyOut[]` | Returns `[]` when nothing is within range. Haversine distance with a 40 km/h travel-time estimate. |

Note: `view_hospitals` exists in the permission catalogue but is **not enforced
here**. Emergency routing needs to work for a bystander, so this endpoint is
public by design; the permission remains meaningful for authenticated surfaces.

---

## `app/api/admin.py` - prefix `/admin`

Administrator and auditor console. Every endpoint is permission-gated.

| Endpoint | Auth | Request | Response | Notes |
|---|---|---|---|---|
| `GET /api/admin/analytics` | `permission: view_analytics` | - | `AnalyticsOut` | 13-day identifications-by-day, outcome breakdown, average elapsed ms from audit `details`. |
| `GET /api/admin/audit` | `permission: view_audit_logs` | `action?`, `session_id?`, `limit` (1-500, def 100), `offset` | `AuditLogOut[]` | |
| `GET /api/admin/users` | `permission: manage_users` | `limit`, `offset` | `UserAdminOut[]` | |
| `PATCH /api/admin/users/{user_id}/roles` | `permission: manage_roles` | `RoleAssignmentIn` | `UserAdminOut` | 400 on unknown role names. **400 if an admin removes their own `admin` role** - self-lockout guard. |
| `PATCH /api/admin/users/{user_id}/active` | `permission: manage_users` | `active: bool = True` (query) | `UserAdminOut` | **400 if an admin disables their own account.** |
| `GET /api/admin/sessions` | `permission: view_analytics` | `limit` | `dict[]` | |
| `GET /api/admin/settings` | `permission: manage_settings` | - | `SettingOut[]` | Includes the confidence thresholds. |
| `PUT /api/admin/settings/{key}` | `permission: manage_settings` | `SettingIn` | `SettingOut` | Changing a threshold changes matching behaviour live. |
| `GET /api/admin/hospitals` | `permission: manage_users` | - | `HospitalAdminOut[]` | Hospital CRUD is gated on `manage_users`; there is no dedicated hospital permission yet. |
| `POST /api/admin/hospitals` | `permission: manage_users` | `HospitalAdminIn` | `HospitalAdminOut` (201) | |
| `PUT /api/admin/hospitals/{hospital_id}` | `permission: manage_users` | `HospitalAdminIn` | `HospitalAdminOut` | |
| `DELETE /api/admin/hospitals/{hospital_id}` | `permission: manage_users` | - | 204 | |

---

## `app/api/demo.py` - prefix `/demo`

Synthetic-data playground. `POST /run` and `POST /enroll` return **404** when
`DEMO_MODE` is false.

| Endpoint | Auth | Request | Response | Notes |
|---|---|---|---|---|
| `GET /api/demo/scenarios` | `public` | - | `DemoScenarioOut[]` | 6 scenarios. |
| `POST /api/demo/run` | `public` | `DemoRunRequest` | `DemoRunOut` | Runs synthetic images through the **real** pipeline. Creates an `access_type="demo"` session when none is supplied. |
| `POST /api/demo/enroll` | `permission: enroll_biometric` | `DemoEnrollRequest` (2-6 samples, default 3) | `dict` | 409 without consent, 422 with fewer than 2 usable samples. |

| Scenario | Identity seed | Degradation | Expected outcome |
|---|---|---|---|
| `high_confidence` | `aarav-kumar-demo` | none | `HIGH_CONFIDENCE` |
| `low_confidence` | `aarav-kumar-demo` | `noise 0.30, occluded 0.30` | `REVIEW_REQUIRED` |
| `no_match` | `enroll-demo-charlie-99` | none | `NO_MATCH` |
| `multiple_faces` | `aarav-kumar-demo` | `faces: 2` | `MULTIPLE_FACES` |
| `poor_quality` | `aarav-kumar-demo` | dark, blur, `occluded 0.5` | `POOR_QUALITY` |
| `gps_unavailable` | `aarav-kumar-demo` | none, no location | match without a context boost |

**Identity seeds must stay deterministic.** The face feature space is small, so
arbitrary identity strings collide. `enroll-demo-charlie-99` was chosen because
its maximum similarity to any enrolled demo face is 0.436. Introducing a random
UUID-based identity into enrollment makes the test suite flaky. The demo-enroll
face is seeded from `user.email`, and the enrollment test uses a fixed account
for exactly this reason.

---

## `app/main.py` - endpoints on the app itself

| Endpoint | Auth | Response | Notes |
|---|---|---|---|
| `GET /api/health` | `public` | `status`, `app`, `mode`, `database`, `state`, `recognition` | Reports the resolved database backend, `degraded` flag, and `recognition.engine` / `recognition.simulation`. **Never raises** - reports `disconnected` instead. |
| `GET /{full_path:path}` | `public` | SPA | `include_in_schema=False`. Serves `frontend/dist`. 404s if the dist is missing or the path starts with `api`, and blocks path traversal via `relative_to`. |

---

## Request validation and error codes

| Code | Raised when |
|---|---|
| 401 | Missing, expired, malformed or wrong-type JWT; bad credentials. |
| 403 | Authenticated but lacking a permission; session token mismatch; medical summary before a completed match; admin self-lockout. |
| 404 | Unknown route, session, user, contact, feature, enrollment, candidate or demo scenario. |
| 409 | Duplicate email, active session already completed, enrollment not in progress, missing active biometric consent. |
| 410 | Session expired or aborted; enrollment past its 20-minute TTL. |
| 413 | Image larger than `MAX_UPLOAD_BYTES` (6 MiB). |
| 422 | Schema validation failure, bad base64, unsupported image format, undecodable image, too few usable samples. |
| 429 | Rate limit exceeded. Carries `Retry-After`. |
| 500 | Unhandled error. Body is always `{"detail": "Internal server error"}`; details go to the log, never to the client. |
