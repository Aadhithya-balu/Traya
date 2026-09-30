[README.md](README.md) | [Backend](backend/README.md) | [Frontend](frontend/README.md) |
[Operations](operations/README.md) | [Decisions](decisions/README.md)

# Architecture

How the pieces fit together. This page is the **narrative** layer: flow, and
the reasoning behind the flow. Every component, endpoint, table, function and
token is documented by name in the reference pages, which this page links to
rather than restates.

> **The biometric engine in this repository is a simulation.** It measures
> brightness similarity between images. It cannot identify a person, and
> measured impostor similarity reaches 0.817 - above the 0.62 review threshold.
> Nothing here is a production biometric. Read
> [ADR 0001](decisions/0001-simulation-biometric-engine.md) before trusting
> anything in this document about recognition quality.

## System overview

Two processes and one database.

```
browser ──> React SPA  (:5173 in dev, / in production)
              │  relative /api, Authorization: Bearer, 401 auto-refresh
              ▼
           FastAPI  (:8000)
              │  routers -> security -> services -> repositories -> SQLAlchemy
              ▼
      Supabase / PostgreSQL   (production)
      SQLite                  (development and demo fallback)
```

1. **FastAPI backend** (`backend/app`) - REST API, authentication and RBAC,
   the identification pipeline, emergency session management, medical and
   hospital lookups, admin and audit, demo and seed tooling.
2. **React SPA** (`frontend`) - citizen dashboard, emergency capture, responder
   hub, admin console and a demo playground, talking to the API through one
   typed client with automatic token refresh.

`main.py` serves `/api/*` as JSON **and** the built SPA from `frontend/dist` at
`/` and any non-API path, so production is a single origin. That is what lets
the JWT live in `localStorage` without a cross-origin problem.

## Backend layers

```
app/
  api/            HTTP routers. Auth checks, no business logic.
  security/       JWT, RBAC, password hashing, Fernet, rate limiting
  services/       Domain logic. The only place that knows what anything means.
  repositories/   Data access. The only layer that writes SQL.
  models/         SQLAlchemy ORM entities
  schemas/        Pydantic request/response models
  config/         pydantic-settings
  database/       engine, session factory, probe and fallback
  utils/          image validation, session codes
```

The rule that makes the codebase navigable: **dependencies point one way.**
Routers call services, services call repositories, repositories touch the
session. A service never imports a router, and a repository never makes a
policy decision.

- [API reference](backend/api.md) - all 47 endpoints across 7 routers.
- [Security](backend/security.md) - roles, permissions, tokens, crypto.
- [Services](backend/services.md) - every service module and its surface.
- [Repositories](backend/repositories.md) - every repository class and method.
- [Data model](backend/data-model.md) - every table, relationship and migration.
- [Configuration](backend/configuration.md) - every settings field.

## Request paths worth understanding

### A bystander identifying an unresponsive person

```
POST /api/emergency/start          -> session_id + access_token (plaintext, once)
POST /api/emergency/{id}/capture   X-TRAYA-Session-Token   -> quality verdict
POST /api/emergency/{id}/identify  X-TRAYA-Session-Token   -> IdentifyResult
```

The session id is **not** a credential. It is an identifier, and a session
token is minted with the session and returned exactly once; only its SHA-256
hash is stored. Every subsequent call needs `X-TRAYA-Session-Token`, so a
session id that leaks - in a URL, a log, a screenshot - is not enough to read
anybody's data. See
[ADR 0002](decisions/0002-session-token-authorization.md).

Guards short-circuit before matching: `NO_FACE`, `MULTIPLE_FACES` and
`POOR_QUALITY` persist an attempt and return without scoring anything.

### A responder escalating

```
POST /api/emergency/{id}/confirm                 (medical_responder)
GET  /api/emergency/{id}/medical-summary         completed session only
GET  /api/emergency/{id}/responder-profile       role-gated
POST /api/emergency/{id}/contact                  consent-gated, audited
```

`REVIEW_REQUIRED` is not a failure state. It is the design: a weak signal goes
to a human, and only human confirmation unlocks the medical profile.

### An administrator auditing

Every sensitive action writes an `audit_logs` row - login, profile and medical
changes, consent grants and withdrawals, enrolment, admin actions, account
deletion, and denied session access. Auditors read; they do not write. See
[ADR 0006](decisions/0006-audit-on-every-sensitive-action.md).

## The identification pipeline

`app/services/identification/pipeline.py`, six steps.

1. **Decode and detect.** `decode_image` validates magic bytes, then
   `detect_faces` returns boxes and a mode.
2. **Quality gate.** `analyze_quality` measures blur, lighting, contrast, face
   visibility and occlusion, and emits both human `reasons` and stable
   `reason_codes`. A capture is usable only when:

   ```
   image_quality_score   >= 0.50   = 0.40*blur + 0.35*lighting + 0.25*contrast
   face_visibility_score >= 0.45   = 0.55*min(1, density*1.15) + 0.45*size
   occlusion_score       <= 0.75   = 1 - density*0.85
   exactly one face in frame
   ```

3. **Tier 1, face.** Embed the face and score every enrolled profile. Profiles
   below the fallback threshold (0.60) are dropped.
4. **Tier 2, secondary features.** Optional text terms boost a profile that
   shares a visible feature, `+0.06 * match_ratio`.
5. **Tier 3, context.** Incident coordinates near a profile's home coordinates
   add a supporting `+0.05`.
6. **Decision.**

   ```
   best >= 0.82            -> HIGH_CONFIDENCE    (auto-accepted)
   best >= 0.62            -> REVIEW_REQUIRED    (a human decides)
   best <  0.62, matched   -> LOW_CONFIDENCE
   nothing >= 0.60         -> NO_MATCH
   ```

Tiers 2 and 3 are **supporting evidence, never identity proof.** A boost cannot
promote a candidate into `HIGH_CONFIDENCE` on its own, and a weak face score
plus fallback signals stays in `REVIEW_REQUIRED` with `fallback_used=True` so a
person decides rather than the system forcing an identity.

Thresholds and boosts are read from `system_settings` at runtime via
`thresholds_from_settings` and are editable in the admin console. **The seeded
database rows override the environment variables**, so changing
`HIGH_CONFIDENCE_THRESHOLD` in `.env` on a seeded database does nothing.

### What the simulation embedding actually is

Twelve explicit darkness features - skin tone, skin variance, hair darkness,
eye darkness left/centre/right, brow, mouth, beard, symmetry, face aspect,
overall luminance - scaled per feature and zero-padded to
`EMBEDDING_DIM = 320`. Similarity is L2 distance:

```
similarity = clamp(1 - ||a - b|| / 3.0, 0, 1)
```

Measured over the synthetic corpus: clean same-identity 0.986-0.995, degraded
same-identity 0.711-0.866, impostor 0.000-**0.817** with a mean of 0.309. **6 of
30 impostor pairs exceed the 0.62 review threshold, and two demo identities
collide at 0.817.** The impostor range overlaps the degraded same-identity
range. That is the whole reason this cannot identify anyone.

## Guided biometric enrolment

Two paths exist and they are not equivalent.

| | Bulk | Guided |
|---|---|---|
| Endpoints | `POST /users/biometric/enroll` | `/users/biometric/enrollment/*` |
| Samples | 2-4, any order | 5 ordered poses |
| Intermediate state | none | rows in `biometric_samples` |
| Expiry | n/a | 20 minutes (`ENROLLMENT_TTL_MINUTES`) |
| Guidance | none | per-step coaching from `GUIDANCE_BY_REASON` |
| Transaction | single | staged, then one atomic replace |
| UI | `Profile` uses this | **not wired to any page yet** |

`replace_embeddings` **deletes before it inserts**, so a revoked-and-re-enrolled
person can never be matched against an old template. Steps are defined by
`POSE_STEPS`; a sample is evaluated by `SampleVerdict`, which returns an
`as_dict` the coach reads.

Constants `ENROLLMENT_TTL_MINUTES = 20`, `MIN_ACCEPTED_SAMPLES = 3` and the
accepted-samples minimum live in the service, **not in settings**, so they are
not configurable without a code change. That is a deliberate simplification and
a documented limitation.

## Security design

| Concern | Where | Notes |
|---|---|---|
| Passwords | `security/password.py` | bcrypt. |
| JWTs | `security/tokens.py` | Access plus refresh, with a type claim. |
| Session token | `utils/helpers.py` | `secrets.token_urlsafe`; only the hash is stored. |
| RBAC | `security/permissions.py` | 18 permissions, 7 roles, dependency-driven. |
| Embeddings at rest | `security/crypto.py` | Fernet. See [ADR 0005](decisions/0005-biometric-encryption-at-rest.md). |
| Audit | `services/audit_service` | Append-only, `hash_ip` never raw. |
| Rate limiting | `security/rate_limit.py` | In-memory sliding window. |
| Uploads | `utils/image` | Magic bytes, size and MIME before any processing. |

**Authorization is enforced in Python, in one layer.** There is no row-level
security at the database; see [SQL assets](operations/README.md#sql-assets).
Every read already goes through a repository scoped by owner or session, so RLS
could be added without restructuring - but it is not there today.

`ENCRYPTION_KEY` empty means it is **derived from `SECRET_KEY`**. Rotating the
secret without setting the encryption key first makes every stored biometric
blob permanently undecryptable. That is the single most likely way to lose the
entire biometric database.

## Database

Supabase/PostgreSQL is the production target; SQLite is the development and demo
fallback. `app/database/service.py` probes the primary with a 3-second timeout
and, when a fallback is permitted and the probe fails, switches to the fallback
URL. See [ADR 0003](decisions/0003-supabase-primary-sqlite-fallback.md).

**Since Phase 3 the fallback is off by default, and there is nothing to
remember.** `DATABASE_ALLOW_FALLBACK` defaults to `False` and is additionally
refused when `DEMO_MODE=false`, so a PostgreSQL outage is a startup failure
rather than a quiet start writing emergency data to a local file. Opting back
in takes two variables and is the intended rollback, not a workaround.

Four migrations exist; `alembic check` is the one that catches model drift, and
`upgrade head` only proves the existing migrations run.

## Frontend

React 18, TypeScript, Vite, Tailwind, React Router. No UI library, no state
library, no i18n library, no data-fetching library - all four are hand-rolled
and documented.

One API client owns base URL, auth header, single-flight 401 refresh and error
shape. `AuthContext` owns the current user; `EmergencyContext` holds the in-flight
session in `sessionStorage` so a refresh does not lose the photo.

The capture screen is the product: camera-first, gallery as an equal path rather
than a hidden fallback, quality feedback before matching, and a session that
opens lazily so an abandoned attempt leaves no incident behind.

- [Routing and guards](frontend/routing.md), [pages](frontend/pages.md),
  [components](frontend/components.md),
  [state and data](frontend/state-and-data.md),
  [design system](frontend/design-system.md).

## Demo mode

`DEMO_MODE=true` (default) enables an idempotent seed, the `/api/demo/*`
endpoints and a deterministic synthetic face renderer with controllable noise,
blur, darkness, occlusion bands, multiple faces and no faces at all. Synthetic
images flow through the **real** pipeline, which is the point.

Every byte is fictional and must stay that way. Synthetic identity seeds must be
deterministic: the face feature space is small enough that arbitrary identity
strings collide. See
[Demo accounts](operations/README.md#demo-accounts).

## Testing

130 pytest cases against a throwaway SQLite database in the system temp dir,
isolated by setting `DATABASE_URL` before any `app` import. **No frontend test
runner exists** - frontend changes are verified by `tsc` and by reading the
diff. See [testing](operations/README.md#testing).

## Deployment

The frontend is a static build served from the same origin as the API. Before
production: replace `SECRET_KEY`, set `ENCRYPTION_KEY` explicitly, set
`DEBUG=false` and `DEMO_MODE=false`, point `DATABASE_URL` at Supabase, set
`CORS_ORIGINS`, terminate TLS, and keep the simulation disclosure visible - or
replace the engine behind the same interface with a real recogniser.

The full checklist, with the reasoning, is in
[production checklist](operations/README.md#production-checklist).

`BIOMETRIC_ENGINE=opencv` does **not** give you real face detection here: OpenCV
5.x ships no cascade data in this environment, so `detect_faces` falls back to
the simulator while appearing to take the real path.
