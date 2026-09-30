[../README.md](../README.md) | [Backend index](README.md) | [Services](services.md)

# Configuration

All runtime configuration is `Settings` in `app/config/settings.py`, a
`pydantic-settings` `BaseSettings`. It reads `backend/.env` and ignores unknown
keys. `get_settings()` is `lru_cache`d and the module-level `settings` object is
created eagerly, so **`app.database.session` resolving the database at import
time is expected behaviour**, not a bug.

Copy `backend/.env.example` to `backend/.env` before first run.

**The path was wrong until Phase 3, and every setting in it was ignored.**
`BASE_DIR` was `Path(__file__).resolve().parent.parent`, which from
`app/config/settings.py` resolves to `backend/app`, so `env_file` pointed at
`backend/app/.env` — a path that has never existed. The file was documented,
recommended in this page and in the README, and read by nobody. Every value
fell through to the class defaults, including `DATABASE_URL` and `SECRET_KEY`,
so the app behaved identically with and without a `.env`. It is now
`parents[2]`, which is `backend/`.

This is the same failure mode as a mistyped Tailwind class: no error, a build
that passes, and a setting that looks applied and is not. `test_env_file_is_where_the_docs_say`
now asserts the resolved path is the backend root and that the directory
exists, so it cannot regress silently.

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

This is not hypothetical: the 12 embeddings in the dev `traya.db` were encrypted
with the key derived from the *default* `SECRET_KEY`, precisely because
`ENCRYPTION_KEY` was empty and the `.env` was never being read. Generating a
fresh `SECRET_KEY` without pinning `ENCRYPTION_KEY` first would have destroyed
them on the next seed. The `backend/.env` created in Phase 3 pins
`ENCRYPTION_KEY` to the value those rows actually use — verified by decrypting
all 12 through `app.security.crypto` — so `SECRET_KEY` can now be rotated
freely. **If you are starting a new deployment, set `ENCRYPTION_KEY` explicitly
before anything is enrolled.**

Never commit `.env`. Both values belong in the platform secret store, not in
`alembic.ini` or a compose file.

## Database

| Field | Default | Effect |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./traya.db` | Primary. Also the target `migrations/env.py` uses. |
| `DATABASE_FALLBACK_URL` | `""` | Secondary candidate tried after the primary fails to probe. |
| `DATABASE_ALLOW_FALLBACK` | `False` | Whether a failed primary may degrade to SQLite. **Default `False` since Phase 3**: pointing `DATABASE_URL` at Supabase and losing the network is now a startup failure, not a silent downgrade to an unbacked local file. Also refused outright when `DEMO_MODE=false`, so the flag alone cannot authorise data loss in production. Opt back in with `DATABASE_ALLOW_FALLBACK=true` — that is the rollback path, and it is one env var rather than a code change. |
| `DATABASE_PROBE_TIMEOUT_SECONDS` | `3.0` | Connect timeout when probing Postgres. |
| `SUPABASE_URL` | `""` | Project URL. |
| `SUPABASE_ANON_KEY` | `""` | Browser-safe key. **Reads nothing on the hosted project** - `004_revoke_anon.sql` revokes its `public` grants, and a request with it returns `401 42501`. It is kept configured because the dashboard and any future client-side path expect it, not because the app uses it. |
| `SUPABASE_SERVICE_ROLE_KEY` | `""` | Server-only key. Never expose to the frontend. Note the app does **not** use it either: it authenticates to Postgres with `psycopg` as `postgres`, so the key is recorded rather than wired. |
| `SUPABASE_PROJECT_REF` | `""` | The 20-character project ref. **Declared but unread.** Phase 4 needs it to author RLS and storage policies. It exists as a field rather than a loose line in `.env` because `extra="ignore"` drops unknown keys silently: a key the app never reads is a key someone will believe is wired up. |

Resolution order and the degraded-mode contract are in
[ADR 0003](../decisions/0003-supabase-primary-sqlite-fallback.md).
`GET /api/health` reports the resolved backend, the `degraded` flag and the
reason, and masks the password in the URL.

**Why the fallback is off by default, and why the flag is not sufficient.**
The old default was `True`, so the "fail loudly" guarantee held only for
deployments that remembered to opt in — and the failure it guards against is
one where nothing is obviously wrong. A Supabase outage produced a fully
working app, green health checks at the HTTP layer, emergency data in a local
file, and a single `logger.warning` nobody reads. Two conditions now have to
agree before any fallback happens: the flag is on, **and** `DEMO_MODE` is on.
`DEMO_MODE=false` is the production switch, and it outranks the flag, so
setting `DATABASE_ALLOW_FALLBACK=true` on a production deployment does not
re-enable data loss — it just produces a loud refusal and a startup error.

Zero-config demo is unaffected. When `DATABASE_URL` is already SQLite,
`initialize` returns before the fallback is ever consulted, so the default
change touches no SQLite-primary path. `test_sqlite_primary_never_consults_the_fallback`
exists to hold that.

Note that the fallback is not the same thing as the demo. The demo can run on
Postgres; the fallback is what happens when Postgres is gone. Conflating them
is what made the old default dangerous.

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
3. `DATABASE_URL` pointing at Supabase/PostgreSQL, plus the four `SUPABASE_*`
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
