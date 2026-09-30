[../README.md](../README.md) | [Operations index](README.md)

# Operations

Running TRAYA: prerequisites, local development, the test suite, the demo
corpus, database operations, and what production deployment actually requires.

| Concern | Section |
|---|---|
| Prerequisites | [prerequisites](#prerequisites) |
| One command | [running everything](#running-everything) |
| Running the pieces | [running the pieces](#running-the-pieces) |
| Environment | [environment](#environment) |
| Tests | [testing](#testing) |
| Demo accounts | [demo-accounts](#demo-accounts) |
| Migrations | [database migrations](#database-migrations) |
| Seed and demo corpus | [seed-and-demo-corpus](#seed-and-demo-corpus) |
| Hand-written SQL | [sql-assets](#sql-assets) |
| Production checklist | [production checklist](#production-checklist) |
| Known environment traps | [environment traps](#environment-traps) |

---

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Python | 3.14.2 | The venv resolves to `C:\Python314\python.exe`. |
| Node | 24 | npm 11.6.2. |
| `psycopg` | 3.x | Only needed for PostgreSQL. Installed from `requirements.txt`. |

Windows and PowerShell 5.1. **PowerShell 5.1 does not support `&&`.** Chain with:

```powershell
cmd1; if ($?) { cmd2 }
```

## Running everything

From the repository root:

```powershell
npm run dev:all
```

`scripts/dev-all.mjs` builds the frontend if `frontend/dist` is missing, then
starts uvicorn on `:8000` and Vite on `:5173`, with prefixed, colour-coded log
lines and a single Ctrl-C that stops both.

| URL | What it serves |
|---|---|
| `http://localhost:5173` | Vite dev server, hot reload, proxies `/api` to the backend. |
| `http://localhost:8000` | FastAPI. `/api/*` as JSON, **and** the built frontend from `frontend/dist` at `/` and any non-API path. |

Because `main.py` has an SPA catch-all, `http://localhost:8000` shows the real
UI too - but only after a `npm run build`. In day-to-day development use
`:5173`; use `:8000` to check that the production build and the SPA fallback
actually work.

## Running the pieces

| Task | Command |
|---|---|
| Backend only | `cd backend; .venv\Scripts\python.exe -m uvicorn app.main:app --port 8000` |
| Frontend only | `cd frontend; npm run dev` |
| Frontend typecheck | `cd frontend; npm run typecheck` |
| Frontend build | `cd frontend; npm run build` |
| Backend tests | `cd backend; .venv\Scripts\python.exe -m pytest` |
| Migration to head | `cd backend; .venv\Scripts\python.exe -m alembic upgrade head` |
| Autogenerate a migration | `cd backend; .venv\Scripts\python.exe -m alembic revision --autogenerate -m "..."` |
| Migration drift check | `cd backend; .venv\Scripts\python.exe -m alembic check` |
| Re-seed demo data | `cd backend; .venv\Scripts\python.exe -m app.services.demo.seed` |
| Documentation check | `npm run docs:check` |

Verification after a change: backend changes need the pytest suite, frontend
changes need `npm run build`, and **documentation or configuration changes need
`npm run docs:check`**. `npm run build` runs `tsc --noEmit` first, so a
successful build is a successful typecheck.

## Environment

`backend/.env`, copied from `backend/.env.example`. Pydantic reads it with
`extra="ignore"`, so an unknown key is silently dropped rather than failing
loudly - and a **misspelled key fails silently into its default**, which for
`SECRET_KEY` or `ENCRYPTION_KEY` is a security problem, not a typo.

**The file itself was never read until Phase 3.** `BASE_DIR` was
`Path(__file__).resolve().parent.parent`, which from `app/config/settings.py`
resolves to `backend/app`, so `env_file` pointed at `backend/app/.env` — a path
that has never existed. Anyone who followed the setup instructions above
produced a file the application ignored, and nothing said so: the app behaved
identically with and without one because every value fell back to its class
default. It is now `parents[2]`, which is `backend/`, and
`backend/tests/test_settings_path.py` asserts the path, proves a file there is
loaded through `Settings`, and fails if `backend/.env` is ever tracked by git.

If you are configuring anything at all, `.env` is not optional. If you are only
running the SQLite demo, it still is, because the defaults work.

Full field reference: [configuration.md](../backend/configuration.md).

### `.env.example` is incomplete

It documents 20 of the 37 settings. It is **missing** every setting added since
it was written:

`DATABASE_FALLBACK_URL`, `DATABASE_ALLOW_FALLBACK`,
`DATABASE_PROBE_TIMEOUT_SECONDS`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`,
`SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_PROJECT_REF`, `JWT_ALGORITHM`,
`RATE_LIMIT_ENABLED`, `PUBLIC_IDENTIFY_LIMIT`,
`PUBLIC_IDENTIFY_WINDOW_SECONDS`, `AUTH_LIMIT`, `AUTH_WINDOW_SECONDS`,
`MAX_UPLOAD_BYTES`, `ALLOWED_IMAGE_MIMES`, `BIOMETRIC_ALGO_VERSION`,
`EMBEDDING_DIM`, `TESTING`, `API_PREFIX`.

A new developer who copies the example gets none of the rate limiting, upload
limits, Supabase wiring or probe timeouts. **Bring the example back in line with
`settings.py`** - and consider having the docs check compare the two, since a
drifting example is worse than no example.

### Values that must change before production

| Setting | Why |
|---|---|
| `SECRET_KEY` | The shipped default is literally `CHANGE_ME_...`. It signs every JWT. |
| `ENCRYPTION_KEY` | Empty means it is **derived from `SECRET_KEY`**, so rotating the secret silently makes every stored biometric blob undecryptable. Set it explicitly. |
| `DEBUG` | Must be `False`. |
| `DEMO_MODE` | Must be `False`. It gates synthetic data, synthetic images and the demo endpoints. |
| `DATABASE_URL` | Must point at Supabase/PostgreSQL. |
| `DATABASE_ALLOW_FALLBACK` | Already `False` by default since Phase 3. Leave it. Turning it on re-authorises writing emergency data to a local file during an outage — see [SECURITY_MODEL.md](../SECURITY_MODEL.md) T4. |
| `CORS_ORIGINS` | Replace the four dev origins with the real ones. |
| `BIOMETRIC_ENGINE` | Leave `auto` or set `simulation` - see below. |

### The biometric engine switch

`BIOMETRIC_ENGINE` is `auto`, `simulation` or `opencv`. **`opencv` does not work
in this environment**: OpenCV 5.x ships no cascade data, so `detect_faces` falls
back to the simulator anyway. Setting `opencv` does not make this a real
recogniser; it only makes the code path look real. See
[ADR 0001](../decisions/0001-simulation-biometric-engine.md).

## Testing

```powershell
cd backend; .venv\Scripts\python.exe -m pytest
```

207 tests pass, with 8 `StarletteDeprecationWarning`s from
`HTTP_422_UNPROCESSABLE_ENTITY`.

`pytest.ini` sets `addopts = -q`, so **passing another `-q` yields `-qq` and
suppresses the `N passed` summary line.** Judge success by the exit code and the
absence of `F`/`E` characters, not by a missing summary:

```powershell
.venv\Scripts\python.exe -m pytest; $LASTEXITCODE
```

`tests/conftest.py` sets `TESTING=1`, `DEMO_MODE=1` and `DATABASE_URL` **at the
very top of the file, before any `app` import**, because pydantic reads the
environment at import time. Moving an import above those assignments silently
runs the whole suite against the developer's real database. The suite uses a
fresh temp SQLite file at `%TEMP%\traya_test.db`, removed per run.

### Running the suite against real Postgres

SQLite cannot falsify a Postgres claim. It has no `vector` extension, no
row-level security, and differs on some type comparisons, so a green SQLite run
says nothing about the production target. Set `TRAYA_TEST_DATABASE_URL` and the
whole suite runs on Postgres instead:

```powershell
docker run -d --name traya-pg -p 54329:5432 `
  -e POSTGRES_PASSWORD=traya_local_dev -e POSTGRES_USER=postgres `
  -e POSTGRES_DB=traya pgvector/pgvector:pg16

cd backend
$env:TRAYA_TEST_DATABASE_URL="postgresql+psycopg://postgres:traya_local_dev@127.0.0.1:54329/traya_test"
.venv\Scripts\python.exe -m pytest
Remove-Item Env:\TRAYA_TEST_DATABASE_URL
```

The database must exist but be disposable. In this mode `conftest.py` drops and
recreates the `public` schema before importing the app, so the run starts clean.
That step is not optional decoration: SQLite gets a clean slate for free by
deleting a file, Postgres does not, and without the reset the suite **passes
once and then fails** with `409 duplicate email` on every subsequent run. A green
first run is not evidence of an idempotent suite. Unset the variable and nothing
changes.

All 207 tests pass on both, verified in Phase 3 — and on Postgres that was
confirmed across three consecutive runs, not one. The equality is the useful
result: the schema stays genuinely portable, which is what lets the SQLite
rollback path exist at all.

There is **no frontend test runner.** No component test, no hook test, no
snapshot. Every frontend change is currently verified only by `tsc` and by
reading the diff.

`TestClient.delete()` has no `json=` keyword. Use
`client.request("DELETE", url, headers=..., json=...)`.

## Demo accounts

All demo accounts share one password: **`TrayaDemo#2026`**.

| Email | Role |
|---|---|
| `aarav.kumar@demo.traya` | `registered_user` |
| `priya.sharma@demo.traya` | `registered_user` |
| `rohan.verma@demo.traya` | `registered_user` |
| `meera.iyer@demo.traya` | `registered_user` |
| `neha.rao@responder.traya` | `medical_responder` |
| `suresh.patil@responder.traya` | `police_responder` |
| `admin@traya.io` | `admin` |
| `auditor@traya.io` | `auditor` |

The four registered users have enrolled biometrics, medical profiles and
emergency contacts, so the match path has something to match against.

**Every byte of demo data is fictional and must stay that way.** No real name,
real address, real phone number or real medical history.

Domains are `.demo.traya` and `.responder.traya` rather than `.local`,
because pydantic's `EmailStr` rejects `.local` as a special-use domain.

The same list appears in `AGENTS.md`, in `docs/frontend/pages.md` and in
`frontend/src/pages/Login.tsx`. **Four copies.** Make this page canonical and
have the other three point at it, or the copies will drift - as the test count
in `AGENTS.md` already has.

## Database migrations

Four migrations, in order:

| Revision | Adds |
|---|---|
| `a8c4ffbe90bd` | Initial schema. |
| `56a8e0eed1a8` | Permission matrix and the `hospital` role. |
| `b32e84ef129d` | Emergency session access token. |
| `c74d0b1e8fa2` | Guided biometric enrollment. |

```powershell
cd backend
.venv\Scripts\python.exe -m alembic upgrade head
.venv\Scripts\python.exe -m alembic check   # no new operations => models match migrations
```

`alembic check` is the one that matters. `upgrade head` succeeding only proves
the *existing* migrations run; `check` is what proves the ORM models and the
migration history have not diverged. Run both before committing a model change.

New tables and columns require a migration plus a check that the demo seed is
still idempotent on the migrated schema.

## Seed and demo corpus

```powershell
cd backend; .venv\Scripts\python.exe -m app.services.demo.seed
```

`seed_all(skip_if_seeded=True)` also runs at startup and **returns immediately
when demo data already exists**, which is what keeps a cold boot at about 3
seconds. A fresh database takes about 7 seconds, because the first boot has to
render the synthetic biometric images once.

Seeded content: roles, permissions, confidence thresholds (HIGH 0.82, REVIEW
0.62, FALLBACK_FACE 0.60, CONTEXT_BOOST 0.05, SECONDARY_FEATURE_BOOST 0.06), 4
citizens, `DEMO_RESPONDERS`, 9 hospitals and demo settings.

`seed_biometric` clears stale embeddings before re-enrolling, so re-seeding is
safe. But **synthetic identity seeds must be deterministic.** The face feature
space is small, and arbitrary identity strings collide: `unknown-person-X9`
against `test-identity` once scored 0.807, which is above the review threshold.
The demo no-match identity is `enroll-demo-charlie-99` for exactly this reason.
Never introduce a random UUID-based identity into enrollment - it made the suite
flaky.

## SQL assets

`database/` does not exist yet. The plan is:

| File | Contents |
|---|---|
| `database/schema.sql` | The full schema, hand-maintained and reviewed. |
| `database/indexes.sql` | Indexes Alembic does not create for you. |
| `database/rls.sql` | Row-level security policies for PostgreSQL. |
| `database/seed.sql` | Reference seed data, distinct from the Python seed. |
| `database/queries/*.sql` | The verification queries used to check a deployment. |

Until those exist, Alembic is the only schema source of truth, and there is no
RLS at all. **Row-level security is not implemented** - authorization is
enforced in Python by `require_permission` and the session-token check, which is
a single layer rather than two. For a system holding medical data, defence in
depth at the database is worth having, and the app is structured to allow it:
every read already goes through a repository scoped by owner or session.

`docs/backend/configuration.md` links here, and
[ADR 0003](../decisions/0003-supabase-primary-sqlite-fallback.md) assumes these
files exist. **They are the largest documentation inaccuracy in the repository
right now**, and it is a missing-file inaccuracy rather than a wrong statement.

## Production checklist

Everything on this list is a hard blocker, not advice.

1. `SECRET_KEY` replaced with a long random value.
2. `ENCRYPTION_KEY` set explicitly, and **not** derived from `SECRET_KEY`.
3. `DEBUG=false`, `DEMO_MODE=false`.
4. `DATABASE_URL` pointing at Supabase/PostgreSQL; `alembic upgrade head` run
   against it.
5. `CORS_ORIGINS` set to the real origins.
6. `BIOMETRIC_ENGINE=simulation` and the simulation disclosure visible on every
   result - or a real recogniser behind the same interface.
7. HTTPS everywhere, including for the SPA, so the JWT is never in cleartext.
8. `backend/.env` and any key material out of git. The dev `traya.db` is
   gitignored; a database full of encrypted embeddings should never be
   committed either.
9. Rate limits reviewed for the expected request volume, and the public
   identify limit low enough to make enumeration expensive.
10. Real email, SMS or push delivery configured, or the notification path
    acknowledged as write-only.

**Items 6 and 7 are the ones that matter most.** A 60-minute JWT in
`localStorage` on a plain-HTTP deployment is the difference between a demo and a
liability.

## Environment traps

**IPv4 and IPv6.** Vite binds `localhost`, which resolves to `::1` here. Uvicorn
binds `127.0.0.1`, which is IPv4. The Vite proxy target is therefore written as
`127.0.0.1` explicitly. Probing `localhost:8000` works; probing `::1:8000` does
not.

**Orphaned uvicorn workers hold port 8000.** `uvicorn --reload` spawns
`multiprocessing-fork` children that inherit the listening socket and survive a
kill of the parent, so the port stays occupied and the next start fails with
"address already in use". `dev-all.mjs` deliberately runs uvicorn **without**
`--reload`. If the port is stuck, find the holder by command line:

```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -match 'uvicorn app.main:app' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

**`-q` double-passing hides the test summary.** See [testing](#testing).

**Windows process hygiene generally.** `Stop-Process` on the parent is not
enough when a spawn-based child exists; match on the command line, not on the
port.

**`extra="ignore"` in `SettingsConfigDict`.** A typo in a `.env` key is ignored
rather than reported. Verify a new setting took effect by printing it from
`app.main`'s health or status output, not by assuming.

**Seeded thresholds win over the environment.** The confidence thresholds are
admin-configurable rows in the database, and the seeded rows override
`HIGH_CONFIDENCE_THRESHOLD` and friends. Changing the environment variable on a
seeded database appears to do nothing. That is not a bug - it is the
"effective permissions fall back only when the table is empty" pattern applied
to thresholds - but it surprises people every time.
