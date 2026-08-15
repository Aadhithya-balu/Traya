# TRAYA — Agent Rules & Project Context

AI-assisted emergency victim identification platform. A single photo of an
unresponsive person flows through real quality checks, biometric matching,
medical alerting, contact notification and hospital routing.

This file is the authoritative context for AI agents working in this repo.
Read it before making changes. It is a live document: update it when project
facts change.

## Repo layout

```
C:\Traya\
  backend\            FastAPI + SQLAlchemy + Alembic (Python)
    app\
      api\            routers: auth, users, emergency, demo, biometric, hospitals, admin
      config\         pydantic-settings (settings.py)
      database\       session, init_db
      models\         SQLAlchemy models
      schemas\        Pydantic schemas
      security\       auth (JWT/roles), password, crypto (Fernet), rate_limit
      services\       demo (seed + synthetic image gen), identification (engine, pipeline,
                      registry, confidence), hospital, location, medical, notification, audit
      utils\          helpers (image decode, session codes)
      main.py         app factory, lifespan, health, SPA serving
    migrations\       Alembic (env.py, script.py.mako, versions\a8c4ffbe90bd_initial_schema.py)
    tests\            pytest suite (87 tests)
    requirements.txt
    alembic.ini, pytest.ini, .env.example
  frontend\           React 18 + TypeScript + Vite 5 + Tailwind 3 (no UI library)
    src\pages\        Landing, Login, Register, Emergency, EmergencyHub, Demo, Dashboard, Profile, Admin, Privacy
    src\components\   Layout, Guards, StatusBadge, QualityPanel
    src\context\      AuthContext, EmergencyContext
    src\api\          client.ts (relative /api), types.ts
    vite.config.ts    base "./", dev proxy /api -> localhost:8000
  scripts\dev-all.mjs Root launcher for backend + frontend
  docs\ARCHITECTURE.md
  README.md
  AGENTS.md           (this file)
```

## Stack & environment

- OS: Windows, PowerShell 5.1. Never use `&&`; use `cmd1; if ($?) { cmd2 }`.
- Backend: Python 3.14.2, venv at `backend\.venv`. Import via
  `.venv\Scripts\python.exe` (resolves to `C:\Python314\python.exe`).
- Frontend: Node v24, npm 11.6.2. Vite dev binds `localhost` (IPv6 `::1`);
  uvicorn binds `127.0.0.1` (IPv4). When probing, use explicit hosts.
- DB: SQLite by default (`sqlite:///./traya.db`); Postgres supported via
  `DATABASE_URL` + `psycopg`. Dev DB file `backend\traya.db` is gitignored.

## Commands

Run these from the repo root unless noted.

| Task | Command |
|---|---|
| Run everything (dev) | `npm run dev:all` — backend :8000 + vite :5173; builds frontend once if `dist` missing |
| Backend tests | `cd backend; .venv\Scripts\python.exe -m pytest` |
| Run backend only | `cd backend; .venv\Scripts\python.exe -m uvicorn app.main:app --port 8000` |
| Run frontend only | `cd frontend; npm run dev` (http://localhost:5173) |
| Frontend typecheck | `cd frontend; npm run typecheck` (`tsc --noEmit`) |
| Frontend build | `cd frontend; npm run build` (runs `tsc --noEmit && vite build` → `frontend/dist`) |
| Migrate to head | `cd backend; .venv\Scripts\python.exe -m alembic upgrade head` |
| New migration | `cd backend; .venv\Scripts\python.exe -m alembic revision --autogenerate -m "..."` |
| Re-seed demo data | `cd backend; .venv\Scripts\python.exe -m app.services.demo.seed` |

Verification is mandatory after code changes: run the backend test suite and
`npm run build` (backend touches only the suite; frontend touches build).

## App URLs

- `http://localhost:5173` — Vite dev server (hot reload, proxies `/api`).
- `http://localhost:8000` — FastAPI. `/api/*` JSON; it ALSO serves the built
  frontend from `frontend/dist` at `/` and any non-API path (`main.py` SPA
  catch-all). Rebuild the frontend to see new UI here.

## Demo data & accounts

- Demo password for ALL demo accounts: `TrayaDemo#2026`
- `aarav.kumar@demo.traya`, `priya.sharma@demo.traya`, `rohan.verma@demo.traya`,
  `meera.iyer@demo.traya` (registered users, enrolled biometrics, medical data)
- `neha.rao@responder.traya`, `suresh.patil@responder.traya` (responders)
- `admin@traya.io`, `auditor@traya.io`
- All demo data is FICTIONAL and must stay that way. Emails ending `.local` are
  rejected by pydantic EmailStr; demo uses `.demo.traya` / `.responder.traya`.

## Identification engine (critical)

- `opencv-python` 5.x ships no cascade data, so the engine runs in
  SIMULATION mode. Face detection is simulated; quality gates are real.
- Embedding = 12 explicit darkness-based features padded to 320 dims.
- `similarity = clamp(1 - ||a - b|| / 3.0, 0, 1)`.
- Verified reference points: clean same-identity >= 0.90; clean aarav 0.995;
  degraded (noise 0.30 + occlusion 0.30) aarav 0.687.
- Thresholds (in DB, seeded): HIGH 0.82, REVIEW 0.62, FALLBACK_FACE 0.60,
  CONTEXT_BOOST 0.05, SECONDARY_FEATURE_BOOST 0.06.
- Statuses: `HIGH_CONFIDENCE`, `REVIEW_REQUIRED`, `LOW_CONFIDENCE`,
  `NO_MATCH`, `NO_FACE`, `MULTIPLE_FACES`, `POOR_QUALITY`.

## Hard-won rules (read these; violations cause flakes/bugs)

1. **Synthetic face seeds must be deterministic.** The face feature space is
   small, so arbitrary identity strings can collide (observed `unknown-person-X9`
   vs `test-identity` = 0.807). Demo no-match identity is
   `enroll-demo-charlie-99` (max 0.436 vs random faces). Never introduce a new
   random UUID-based identity into enrollment — it made the suite flaky.
   `app/api/demo.py` seeds the demo-enroll face from `user.email`, and
   `test_demo_enroll_works_with_consent` uses a fixed account, on purpose.
2. **Do not add comments to code unless the user asks.**
3. **No emojis** in code, docs, or replies unless the user asks.
4. **pytest env vars** (`TESTING=1`, `DEMO_MODE=1`, `DATABASE_URL`) must be set
   at the very top of `tests/conftest.py`, before any `app` import. The suite
   uses a fresh temp SQLite DB (`%TEMP%\traya_test.db`), removed per run.
5. **`TestClient.delete()` has no `json=` kwarg.** Use
   `client.request("DELETE", url, headers=..., json=...)`.
6. **`pytest.ini` sets `addopts = -q`.** Passing another `-q` yields `-qq`,
   which suppresses the `N passed` summary line. Judge success by `$LASTEXITCODE`
   / dots (no `F`/`E`), not by the missing summary.
7. **Frontend layout routes render via `<Outlet />`**, not `{children}`. `App.tsx`
   declares `<Route element={<Layout />}>`; `Layout.tsx` must render
   `<Outlet />` in `<main>` or every page is blank.
8. **Windows process hygiene.** `uvicorn --reload` spawns orphaned
   `multiprocessing-fork` workers (`C:\Python314\python.exe -c spawn_main...`)
   that inherit the listening socket and survive parent kills, holding port 8000.
   `dev-all.mjs` deliberately runs uvicorn WITHOUT `--reload`. If the port is
   stuck, kill processes whose commandline matches `uvicorn app.main:app`.
9. **Seed idempotency.** `app/services/demo/seed.py` `seed_all(skip_if_seeded=True)`
   runs at startup and returns immediately when demo data exists, keeping cold
   boots ~3s (fresh-DB first boot ~7s: one-time biometric render). `seed_biometric`
   clears stale embeddings before re-enrolling.
10. **Security.** Biometric embeddings are encrypted at rest (Fernet) and never
    returned to clients. Never log or commit secrets. `SECRET_KEY`/`ENCRYPTION_KEY`
    come from `.env` (see `.env.example`).

## Backend conventions

- FastAPI routers under `app/api/`, registered in `app/api/__init__.py` as
  `api_router`, mounted at prefix `/api` in `main.py`.
- Auth via `Depends(get_current_user)` + role helpers in `app/security/auth.py`
  (`ALL_ROLES`, `ROLE_DESCRIPTIONS`). Rate limiting via `RateLimitMiddleware`.
- DB access via `SessionLocal`/`get_db`; identification via
  `app/services/identification/pipeline.py::run_identification`.
- New tables/columns require an Alembic migration (`alembic revision
  --autogenerate`) plus a check that the demo seed remains idempotent on the
  migrated schema.

## Frontend conventions

- Tailwind utility classes only; custom theme via `tailwind.config` (accent =
  teal, `ink-*` = dark navy, `slate-*` = neutrals, `danger-*`, `warn-*`).
- API calls go through `src/api/client.ts` (`api.*`) using relative `/api`
  paths; typed responses in `src/api/types.ts`. Auth state in `AuthContext`,
  emergency flow state in `EmergencyContext` (sessionStorage-backed, with a
  guarded `JSON.parse`).
- Mobile-responsive: `grid-cols-1 sm:grid-cols-2` patterns, mobile nav exists
  in `Layout.tsx`. Tables use `overflow-x-auto`.

## Docs

- `README.md` — project overview and quickstart.
- `docs/ARCHITECTURE.md` — pipeline, quality gates, embedding, security, demo mode.
