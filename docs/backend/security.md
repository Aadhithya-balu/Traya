[../README.md](../README.md) | [Backend index](README.md) | [API reference](api.md)

# Security: Roles, Permissions and Cryptography

## Authentication

Two credential types, both JWT (`HS256`, `app/security/tokens.py`):

| Token | Lifetime | Claims | Use |
|---|---|---|---|
| Access | `ACCESS_TOKEN_EXPIRE_MINUTES` (60 min) | `sub`, `type=access`, `iat`, `exp` | `Authorization: Bearer <jwt>` on every authenticated call. |
| Refresh | `REFRESH_TOKEN_EXPIRE_DAYS` (7 days) | `sub`, `type=refresh`, `iat`, `exp` | `POST /api/auth/refresh` only. A refresh token presented to a non-refresh endpoint is rejected. |

`get_current_user` returns 401 for a missing, expired, wrong-type or
signature-invalid token, or for a token whose subject is missing or
`is_active=False`. The role is **not** trusted from the token - it is loaded
from the database, so a revoked role takes effect immediately rather than at
token expiry.

## Emergency session tokens

Separate from JWTs, because the public flow has no user. See
[ADR 0002](../decisions/0002-session-token-authorization.md).

- `POST /api/emergency/start` returns a token **once**; only its SHA-256 is
  stored in `emergency_sessions.access_token_hash`.
- Presented as `X-TRAYA-Session-Token`, compared with
  `secrets.compare_digest` (constant time).
- A mismatch is 403 and writes a `session.access_denied` audit row.
- Sessions predating the token column were force-expired by migration
  `b32e84ef129d` rather than grandfathered.

## Roles

Seven roles, defined in `ROLE_DESCRIPTIONS` (`app/security/auth.py`).
`ALL_ROLES` derives from that map, so the list has exactly one source of truth.

| Role | Description |
|---|---|
| `public` | Bystander. Emergency-only access without an account. |
| `registered_user` | Registered person. Own profile, consent and medical data. |
| `medical_responder` | Paramedic / EMT. Emergency plus authorized medical information. |
| `police_responder` | Police / first responder. Identity, contacts and incidents. |
| `hospital` | Hospital staff. Authorized clinical alerts for incoming patients. |
| `auditor` | Auditor. Read-only access to the audit trail. |
| `admin` | Administrator. System administration, audited on every action. |

## Permissions

Eighteen permissions, defined in `PERMISSION_DESCRIPTIONS`
(`app/security/permissions.py`).

| Permission | Description |
|---|---|
| `identify_person` | Run face capture and request an identification. |
| `confirm_identity` | Accept or reject a candidate after human review. |
| `view_identity` | See the matched person's name and basic details. |
| `view_emergency_profile` | See the responder-facing emergency profile. |
| `view_medical_alerts` | See blood group, allergies and critical alerts. |
| `view_emergency_contact` | See and reach the emergency contacts. |
| `notify_contact` | Trigger an emergency-contact notification. |
| `create_incident` | Open a new incident record. |
| `update_incident` | Update incident status, notes and location. |
| `view_incident` | Read an incident's event log: what happened and how the person was identified. |
| `view_hospitals` | Query nearby hospitals and emergency departments. |
| `manage_own_profile` | Edit own profile, medical data and contacts. |
| `enroll_biometric` | Submit and re-enroll own face samples. |
| `manage_own_consent` | Grant or withdraw own consent. |
| `manage_users` | Activate, deactivate and list user accounts. |
| `manage_roles` | Assign or revoke roles. |
| `manage_settings` | Change system settings and thresholds. |
| `view_audit_logs` | Read the audit trail. |
| `view_analytics` | Read system-wide statistics. |

### The matrix

`ROLE_PERMISSIONS` in `app/security/permissions.py` is the compiled-in
authority. `RESPONDER_CORE` is the seven permissions shared by all three
responder roles.

| Role | Permissions |
|---|---|
| `public` | `identify_person` |
| `registered_user` | `identify_person`, `manage_own_profile`, `enroll_biometric`, `manage_own_consent` |
| `medical_responder` | `RESPONDER_CORE` + `confirm_identity`, `view_medical_alerts`, `create_incident`, `update_incident` |
| `police_responder` | `RESPONDER_CORE` + `confirm_identity`, `create_incident`, `update_incident` - **no** `view_medical_alerts` |
| `hospital` | `RESPONDER_CORE` + `view_medical_alerts`, `update_incident` - **no** `confirm_identity` |
| `auditor` | `view_audit_logs`, `view_incident` |
| `admin` | All 19 |

The deliberate asymmetries: police cannot see medical alerts, hospitals cannot
confirm identity, auditors cannot read a victim's records.

**`view_incident` is in `RESPONDER_CORE`** (Phase 7), so every responder role and
the auditor hold it. That is safe because the incident event log carries no
clinical detail - only which fallback was used and who acted. It is what lets a
responder at the scene answer "how was this person identified?" without also
being able to read the victim's medical record.

### Database is authoritative, static matrix is the fallback

`ensure_permission_matrix(db)` reconciles roles, permissions and the
`role_permissions` join table **on every application boot**. It is idempotent,
so changing the matrix is a code change, not a data migration.

`get_effective_permissions` prefers the database. It falls back to
`permissions_for_roles(...)` from the static map only if the database has
nothing for the user, so a fresh or partially-migrated database can never lock
everybody out. The consequence to remember: **editing the static map alone does
not change behaviour on a running system** - the seeded rows win.

### Enforcing a permission

```python
from app.security.auth import require_permission

@router.post("/something", dependencies=[Depends(require_permission("manage_users"))])
```

`require_permission` is **all-of** by default and takes several names;
`require_permission(..., any_of=True)` accepts any one. Failure is 403.
`require_roles` exists with OR semantics but is currently unused - prefer
permissions, since they are finer-grained and database-backed.

### Permissions not yet enforced

These are in the catalogue, granted to roles, and returned by
`GET /api/auth/permissions`, but **no endpoint checks them**:
`view_identity`, `view_emergency_contact`, `notify_contact`, `view_hospitals`,
`create_incident`, `update_incident`, `view_incident`.

Two consequences. `GET /api/hospitals/nearby` is public because `view_hospitals`
is unchecked, which is intentional for emergency routing. And
`IncidentRepository` is not wired into any router, so incident
create/update is modelled but not reachable. Do not read the matrix as a
description of what is currently enforced; read
[api.md](api.md#read-the-auth-column) for that.

### `view_medical_alerts` is checked, and Phase 7 found it was not

`view_medical_alerts` **was** in that unchecked list before Phase 7, and the
consequence was a live disclosure:

```
GET /api/emergency/{session_id}/medical-summary   session
```

authorized on `_get_active_session` alone, which accepts the public session
token. So anyone who could start an emergency and photograph a face that matched
could read that person's blood group, allergies, conditions and medications. The
endpoint now declares `require_permission("view_medical_alerts")`.

Three tests in `tests/test_identification.py` and
`tests/test_incident.py` exist specifically to hold it: the session token alone
is 401, a registered bystander is 403, and **a police responder is 403** - which
is the assertion that encodes the actual rule. An identification is necessary but
not sufficient; the role matrix, not the face match, is what opens the clinical
record. Police get `/responder-profile` instead, which is what they are there
for.

The same pattern is why every fallback endpoint requires
`require_permission("identify_person")` **and** the session: a bystander's
session token must not be enough to identify anyone or to record an incident as
unidentified.

## Password hashing

`app/security/password.py`, direct `bcrypt` with `gensalt(rounds=12)`.
`verify_password` returns `False` on any `ValueError`/`TypeError` rather than
raising, so a malformed stored hash cannot become a 500 or an auth oracle.
`passlib` is deliberately not used.

Registration additionally requires at least one uppercase letter and one digit
(`RegisterRequest`).

## Encryption at rest

`app/security/crypto.py`. Biometric embeddings are Fernet-encrypted; see
[ADR 0005](../decisions/0005-biometric-encryption-at-rest.md).

- `_fernet` is constructed at **import time**, so a bad key fails at startup
  rather than at first use.
- `decrypt_bytes` raises `ValueError("Unable to decrypt protected data")` on
  `InvalidToken` - never leaks the underlying reason.
- `settings.encryption_key` is a separate setting from `SECRET_KEY` so the two
  can be rotated independently. When `ENCRYPTION_KEY` is empty it is derived as
  a urlsafe-base64 SHA-256 of `SECRET_KEY`.
- **Rotating either key makes every existing embedding permanently
  undecryptable.** `RecognitionRepository` skips undecryptable blobs rather than
  failing, so the system degrades to "not enrolled" instead of breaking, but
  users must re-enroll.

## Rate limiting

`app/security/rate_limit.py`. An in-process `RateLimiter` (per-key `deque` with
a `threading.Lock`) applied by `RateLimitMiddleware`.

| Scope | Limit | Window |
|---|---|---|
| `/api/emergency/*` | `PUBLIC_IDENTIFY_LIMIT` = 10 | 60s |
| `/api/auth/*` | `AUTH_LIMIT` = 30 | 60s |

Exceeding a limit returns 429 with a `Retry-After` header and writes a
`rate_limited` audit row via `request.app.state.db_factory`. The limiter is
**bypassed entirely when `settings.TESTING` is true** or when
`RATE_LIMIT_ENABLED` is false.

Limitation: state is per-process. Behind more than one worker, the effective
limit multiplies by the worker count. The docstring says to back this with Redis
before scaling out - do that before production.

## Audit

See [ADR 0006](../decisions/0006-audit-on-every-sensitive-action.md).
`AuditRepository` is append-only: no update, no delete. `hash_ip` truncates a
SHA-256 to 32 characters so a request can be attributed to an address without
the trail storing it. `SENSITIVE_ACTIONS` in `app/services/audit_service.py`
enumerates the 33 action strings that must always be present.
