[../README.md](../README.md) | [Backend index](README.md) | [Services](services.md)

# Configuration

All runtime configuration is `Settings` in `app/config/settings.py`, a
`pydantic-settings` `BaseSettings`. It reads `backend/.env` and ignores unknown
keys. `get_settings()` is `lru_cache`d and the module-level `settings` object is
created eagerly, so **`app.database.session` resolving the database at import
time is expected behaviour**, not a bug.

Copy `backend/.env.example` to `backend/.env` before first run.

## Application

| Field | Default | Effect |
|---|---|---|
| `APP_NAME` | `TRAYA` | Display name. |
| `APP_ENV` | `development` | Environment label. |
| `DEBUG` | `True` | Root log level `INFO` when true, else `WARNING`. Also enables the unhandled-exception log detail. |
| `API_PREFIX` | `/api` | Prefix for every router. |
| `CORS_ORIGINS` | localhost `:5173` and `:3000`, both IPv4 and IPv6 | Allowed origins. **Replace before deploying** - the defaults do not include your domain. |
| `DEMO_MODE` | `True` | Runs `seed_all` on boot and enables `POST /api/demo/run` and `POST /api/demo/enroll` (404 when off). **Set to `False` in production.** |
| `TESTING` | `False` | Disables rate limiting entirely. |

## Secrets

| Field | Default | Effect |
|---|---|---|
| `SECRET_KEY` | insecure dev placeholder | JWT signing key. **Must be set in production.** |
| `ENCRYPTION_KEY` | `""` | Fernet key for biometric embeddings. When empty it is derived as a urlsafe-base64 SHA-256 of `SECRET_KEY`. |

**Rotating either key makes every existing biometric embedding permanently
undecryptable.** There is no re-encryption migration. See
[ADR 0005](../decisions/0005-biometric-encryption-at-rest.md).

Never commit `.env`. Both values belong in the platform secret store, not in
`alembic.ini` or a compose file.

## Database

| Field | Default | Effect |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./traya.db` | Primary. Also the target `migrations/env.py` uses. |
| `DATABASE_FALLBACK_URL` | `""` | Secondary candidate tried after the primary fails to probe. |
| `DATABASE_ALLOW_FALLBACK` | `True` | Whether a failure may fall back to SQLite at all. **Set to `False` in production** so an unreachable primary is a startup failure, not a silent downgrade to an unbacked local file. |
| `DATABASE_PROBE_TIMEOUT_SECONDS` | `3.0` | Connect timeout when probing Postgres. |
| `SUPABASE_URL` | `""` | Project URL. |
| `SUPABASE_ANON_KEY` | `""` | Browser-safe key. |
| `SUPABASE_SERVICE_ROLE_KEY` | `""` | Server-only key. Never expose to the frontend. |

Resolution order and the degraded-mode contract are in
[ADR 0003](../decisions/0003-supabase-primary-sqlite-fallback.md).
`GET /api/health` reports the resolved backend, the `degraded` flag and the
reason, and masks the password in the URL.

## Authentication

| Field | Default | Effect |
|---|---|---|
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | Access token lifetime. |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Refresh token lifetime. |
| `JWT_ALGORITHM` | `HS256` | Signing algorithm. |

## Rate limiting

| Field | Default | Effect |
|---|---|---|
| `RATE_LIMIT_ENABLED` | `True` | Master switch. |
| `PUBLIC_IDENTIFY_LIMIT` | `10` | Requests per window on `/api/emergency/*`. |
| `PUBLIC_IDENTIFY_WINDOW_SECONDS` | `60` | Window for the above. |
| `AUTH_LIMIT` | `30` | Requests per window on `/api/auth/*`. |
| `AUTH_WINDOW_SECONDS` | `60` | Window for the above. Also drives idle-key cleanup at 10x. |

State is per-process, so the effective limit multiplies by the worker count. Move
this to Redis before scaling out.

## Uploads

| Field | Default | Effect |
|---|---|---|
| `MAX_UPLOAD_BYTES` | `6291456` (6 MiB) | Image size ceiling. Exceeding it is **413**. |
| `ALLOWED_IMAGE_MIMES` | `image/jpeg`, `image/png`, `image/webp` | Magic-byte allowlist. |

Both are read into module constants in `app/utils/helpers.py` **at import time**,
so changing them requires a process restart. Validation order is length pre-check,
strict base64 decode, size, minimum 16 bytes, magic bytes, then a real PIL
decode - so a corrupt file is rejected as 422 rather than crashing the decoder.

## Biometric engine

| Field | Default | Effect |
|---|---|---|
| `BIOMETRIC_ENGINE` | `auto` | `auto` uses Haar when available, else simulation; `simulation` forces simulation; `opencv` requires the cascade. **There is no value that means "trained model".** |
| `BIOMETRIC_ALGO_VERSION` | `traya-pseudo-embedding-v2` | Stored on every profile and embedding, so a future algorithm change is detectable. |
| `EMBEDDING_DIM` | `320` | Embedding length. The current engine zero-pads 12 real features to this. |

The version string says `pseudo` on purpose. Do not rename it to imply a real
recogniser. See [ADR 0001](../decisions/0001-simulation-biometric-engine.md).

## Confidence thresholds

| Field | Default | Effect |
|---|---|---|
| `HIGH_CONFIDENCE_THRESHOLD` | `0.82` | At or above this is `HIGH_CONFIDENCE`; the session auto-completes. |
| `REVIEW_THRESHOLD` | `0.62` | At or above this is `REVIEW_REQUIRED`; a human must confirm. |
| `FALLBACK_FACE_THRESHOLD` | `0.60` | Below this the face tier is not trusted; `fallback_used` is flagged. |
| `CONTEXT_BOOST` | `0.05` | Additive boost when a location fix is near the person's home. |
| `SECONDARY_FEATURE_BOOST` | `0.06` | Additive boost when supplied secondary features match. |

These five are also seeded into `system_settings`, and
`thresholds_from_settings` prefers the **database** value, falling back to these
defaults on any error. So editing a threshold through
`PUT /api/admin/settings/{key}` changes matching behaviour live, with no
restart - and survives a redeploy with the old value intact.

Because the engine is a simulation, these numbers describe a brightness
comparison. They are not validated biometric thresholds and must not be
presented as such.

## Sessions and retention

| Field | Default | Effect |
|---|---|---|
| `EMERGENCY_SESSION_MINUTES` | `30` | Emergency session lifetime. Expiry is persisted on read. |
| `SESSION_RETENTION_DAYS` | `90` | Declared retention for sessions. **Not yet applied to `audit_logs`, which have no retention job at all** - see [services](services.md#audit-service). |

## Derived properties

| Property | Meaning |
|---|---|
| `is_sqlite` | URL dialect is SQLite. |
| `is_postgres` | URL dialect is PostgreSQL. |
| `uses_supabase` | Postgres **and** `supabase` appears in the URL. |
| `effective_fallback_url` | `DATABASE_FALLBACK_URL`, or `sqlite:///./traya.db` when empty. |
| `masked_database_url` | URL with the password replaced by `***`, safe for health output. |
| `encryption_key` | `bytes` for Fernet; derived from `SECRET_KEY` when `ENCRYPTION_KEY` is empty. |

## Production checklist

1. `SECRET_KEY` and `ENCRYPTION_KEY` from a secret store. Never the defaults.
2. `DATABASE_ALLOW_FALLBACK=false` so an unreachable primary fails loudly.
3. `DATABASE_URL` pointing at Supabase/PostgreSQL, plus the three `SUPABASE_*`
   values if the frontend talks to Supabase directly.
4. `DEMO_MODE=false`. It seeds fictional citizens and opens two unauthenticated
   endpoints that run synthetic faces through the real pipeline.
5. `CORS_ORIGINS` set to the real origin(s).
6. `DEBUG=false` so unexpected exceptions are logged rather than narrated.
7. `CORS_ORIGINS`, `SECRET_KEY`, `ENCRYPTION_KEY` and `SUPABASE_SERVICE_ROLE_KEY`
   re-verified as absent from version control.
8. The [SQL assets](../operations/README.md#sql-assets) applied: Postgres RLS is
   not created by Alembic and is required for defence in depth.
9. A decision recorded about [ADR 0001](../decisions/0001-simulation-biometric-engine.md).
   Deploying this identification system as-is is unsafe, and no configuration
   flag changes that.
