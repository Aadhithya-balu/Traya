# TRAYA Architecture

## System overview

TRAYA is a two-part system:

1. **FastAPI backend** (`backend/app`) — REST API, authentication & RBAC, the
   identification pipeline, emergency session management, medical/hospital
   lookups, admin & audit services, demo/seed tooling.
2. **React SPA** (`frontend`) — citizen dashboard, emergency capture wizard,
   responder hub, admin console and a demo playground, talking to the API
   through a typed client (`src/api/client.ts`) with automatic token refresh.

The backend is layered so each concern is isolated:

```
app/
  api/          HTTP routers (auth, users, biometric, emergency, demo, admin, hospitals)
  config/       pydantic-settings based configuration (env / .env)
  database/     engine, session factory, Base
  models/       SQLAlchemy ORM entities
  schemas/      pydantic request/response models
  security/     auth (JWT + RBAC), password hashing, Fernet crypto, rate limiting, tokens
  services/
    identification/  engine (detection+quality+embedding), pipeline, confidence, registry
    demo/            synthetic face renderer + seeder
    medical/         medical profile aggregation for responders
    location/        nearby-hospital resolution
    notification/    notification creation
    audit_service/   write-audit helpers
  utils/        shared helpers (image validation, session codes)
```

## Data model

| Table | Purpose |
| --- | --- |
| `users` | Citizens + platform accounts (email, phone, DOB, active flag, roles via `user_roles`) |
| `roles`, `user_roles` | Role-based access control (registered_user, medical_responder, admin, auditor) |
| `biometric_profiles` | One active enrollment per user (status, sample count, algorithm version) |
| `biometric_embeddings` | Encrypted embedding vectors linked to a profile |
| `medical_profiles` | Blood group, allergies, conditions, medications, emergency notes, preferred hospital, home coordinates |
| `emergency_contacts` | Named contacts with `relation`, priority; max 10 per user |
| `visible_features` | Secondary identifying features (birthmarks, scars, tattoos) |
| `consents` | Explicit consent records with status + version history |
| `emergency_sessions` | Per-incident sessions (code, status, outcome, confidence category, timestamps) |
| `identification_attempts` | Quality/result record for each identification attempt |
| `identification_candidates` | Ranked candidate identities per attempt + confirmation state |
| `locations` | Incident location history |
| `hospitals` | Directory used by the responder hub (admin CRUD) |
| `system_settings` | Runtime-tunable confidence thresholds |
| `notifications` | User-facing notifications |
| `audit_logs` | Immutable action trail (actor, action, resource, session, IP) |

Relationships are set up on the ORM; `app.models.__init__.all_models` is the
single import that registers every table on `Base.metadata` (used by both
`init_db()` and Alembic autogenerate).

## Biometric engine

The engine (`app/services/identification/engine.py`) has two modes:

- **`opencv`** — attempts real Haar-cascade face detection when OpenCV is
  available and functional.
- **`simulation`** — the default in this environment (opencv-python 5.x ships
  without the cascade data). Detection is replaced by a skin-tone HSV mask
  over connected components; faces are blobs that are face-sized, not touching
  the frame borders and not huge.

### Quality model

A capture is `usable_for_matching` only when **all** gates pass:

```
image_quality_score >= 0.50
  = 0.40 * blur_score + 0.35 * lighting_score + 0.25 * contrast_score
face_visibility_score >= 0.45
  = 0.55 * min(1, density*1.15) + 0.45 * size_score     (density = skin/box)
occlusion_score  <= 0.75
  = 1 - density*0.85
exactly one face in frame
```

Rejection reasons are surfaced verbatim (blurry, dark/bright, multiple faces,
obstructed, face too small).

### Embedding & similarity

The simulation embedding is a deterministic, **interpretable demo vector**, not
a production biometric:

- A face crop is median-filtered and resized to a `16x16` luminance grid.
- 12 explicit features are extracted: skin tone, skin variance, hair darkness,
  left/center/right eye darkness, brow, mouth, beard, symmetry, face aspect and
  overall luminance.
- Each feature is scaled by an approximate unit-variance weight and the vector
  is zero-padded to `EMBEDDING_DIM=320`.

Similarity uses L2 distance:

```
similarity = clamp(1 - ||a - b|| / 3.0, 0, 1)
```

Because the features are luminance/darkness-based, the vector is **stable for
the same identity** (mild noise/lighting changes barely move it) and **distinct
across identities**, while deliberate degradations (occlusion band, heavy noise)
shift it controllably. Verified discrimination: same-identity >= 0.90, clean
aarav vs unknown max ~0.37.

## Identification pipeline

`app/services/identification/pipeline.py` implements the multi-tier flow:

1. **Decode + detect** — face boxes + quality report.
2. **Guards** — `MULTIPLE_FACES`, `NO_FACE`, `POOR_QUALITY` short-circuit with
   a persisted attempt and no matching.
3. **Tier 1 (face)** — embed the face and score every enrolled profile
   (`load_enrolled`); profiles below the face-fallback threshold (0.60) are
   dropped.
4. **Tier 2 (secondary features)** — optional text terms boost a profile when
   they match the user's `visible_features` (`+0.06 * match_ratio`).
5. **Tier 3 (context)** — incident coordinates near a profile's home add a
   supporting `+0.05` boost. Supporting evidence only — never identity proof.
6. **Decision** — top candidate decides status:

```
best >= 0.82           -> HIGH_CONFIDENCE   (auto-accepted)
best >= 0.62           -> REVIEW_REQUIRED   (needs human confirmation)
best <  0.62, matched  -> LOW_CONFIDENCE
no profile >= 0.60     -> NO_MATCH
```

Thresholds and boosts come from `system_settings` at runtime
(`thresholds_from_settings`) and are editable in the admin console.

Trauma-aware behaviour: a weak face score combined with fallback signals keeps
the status in `REVIEW_REQUIRED` (`fallback_used=True`) so a human decides
rather than the system forcing an identity.

### Level 4 — human confirmation

A `medical_responder` can confirm or reject a candidate
(`POST /api/emergency/{id}/confirm`). Accepting sets the session to
`completed` with `confidence_category=HUMAN_CONFIRMED` and unlocks the medical
profile, responder view and contact actions.

## Emergency session lifecycle

1. `POST /api/emergency/start` creates an `EmergencySession` (code + expiry).
2. `POST /api/emergency/{id}/capture` validates & stores the image, returns the
   quality verdict.
3. `POST /api/emergency/{id}/identify` runs the pipeline and persists attempt +
   candidates.
4. A high-confidence result completes the session immediately; otherwise a
   responder confirms.
5. `GET /api/emergency/{id}/medical-summary`, `/responder-profile` and
   `/contact` are gated behind a completed identification + role checks.

Sessions expire per `EMERGENCY_SESSION_MINUTES`; retention is configured via
`SESSION_RETENTION_DAYS`.

## Security design

- **Passwords** — bcrypt (`app/security/password.py`).
- **Tokens** — signed JWTs (`app/security/tokens.py`): short-lived access +
  refresh token pair, with token-type claims.
- **RBAC** — dependency-driven role checks per router; admin/auditor/responder
  endpoints enforce their own authorization (403 for authenticated users
  without the role, 401 for anonymous).
- **Biometric data** — embeddings are encrypted at rest with Fernet
  (`app/security/crypto.py`); the key is derived from `ENCRYPTION_KEY` or the
  app `SECRET_KEY`.
- **Audit trail** — every sensitive action writes an `audit_logs` row (login,
  profile/medical changes, consents, biometric enroll/delete, admin actions,
  account deletion). Auditors have read-only access.
- **Rate limiting** — in-memory sliding-window limiter for login and public
  identification (`app/security/rate_limit.py`).
- **Account lifecycle** — self-service deletion soft-deletes (anonymises email,
  deactivates) and disables logins.
- **Uploads** — base64 images validated for magic bytes, size and MIME before
  any processing.

## Demo mode

`DEMO_MODE=true` (default) enables:

- **Seeding** (`app/services/demo/seed.py`, idempotent): 8 users, 4 with
  enrolled biometrics, 9 hospitals; run with
  `python -m app.services.demo.seed`.
- **`/api/demo/*`** — scenario runner (`high_confidence`, `low_confidence`,
  `no_match`, `multiple_faces`, `poor_quality`, `gps_unavailable`),
  direct-enroll helper and session trigger.
- **Synthetic renderer** (`app/services/demo/demo_images.py`) — deterministic
  faces derived from a seed string, with controllable noise, blur, darkness,
  occlusion bands, multiple faces or none.

All demo accounts use password `TrayaDemo#2026`.

## Testing

87 pytest cases in `backend/tests` run against a throwaway SQLite DB in the
system temp dir (isolated by setting `DATABASE_URL` before any app import).
See `backend/pytest.ini` and `tests/conftest.py` for the harness and helpers.

## Migrations

Alembic is wired so `DATABASE_URL` is read from application settings
(`migrations/env.py`). Generate a migration with:

```bash
python -m alembic revision --autogenerate -m "message"
python -m alembic upgrade head
```

`init_db()` (create-all) remains for throwaway/dev databases; migrations are
the production path.

## Deployment notes

- Set `DATABASE_URL` to a PostgreSQL DSN, `SECRET_KEY`/`ENCRYPTION_KEY` to
  strong random values, and `DEMO_MODE=false` in production.
- `BIOMETRIC_ENGINE=opencv` with a compatible OpenCV build enables real face
  detection; the simulation embedding must be replaced by a production model
  for real-world use.
- The frontend is a static Vite build served behind the same origin as the API
  (the dev server proxies `/api` to port 8000).
