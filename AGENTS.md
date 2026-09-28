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
      database\       session, init_db, probe + Supabase/SQLite fallback (service.py)
      models\         SQLAlchemy models
      repositories\   the only layer that touches the database
      schemas\        Pydantic schemas
      security\       auth (JWT/roles), password, crypto (Fernet), rate_limit
      services\       demo (seed + synthetic image gen), identification (engine, pipeline,
                      registry, confidence), hospital, location, medical, notification, audit
      utils\          helpers (image decode, session codes)
      main.py         app factory, lifespan, health, SPA serving
    migrations\       Alembic (env.py, script.py.mako, versions\)
    tests\            pytest suite (130 tests)
    requirements.txt
    alembic.ini, pytest.ini, .env.example
  frontend\           React 18 + TypeScript + Vite 5 + Tailwind 3 (no UI library)
    src\pages\        Landing, Login, Register, Emergency, EmergencyHub, Demo, Dashboard, Profile, Admin, Privacy
    src\components\   Layout, Guards, Sheet, Tabs, StatusBadge, QualityPanel, icons
    src\context\      AuthContext, EmergencyContext
    src\hooks\        useCamera, useGeolocation
    src\api\          client.ts (relative /api), types.ts
    src\i18n\         index.tsx, strings.ts (en + ta, 20 namespaces)
    src\theme\        ThemeProvider.tsx
    vite.config.ts    base "./", dev proxy /api -> 127.0.0.1:8000
  scripts\            dev-all.mjs (root launcher), check-docs.mjs (docs enforcement)
  docs\               ARCHITECTURE.md + backend/ + frontend/ + operations/ + decisions/
  package.json        root: dev:all, docs:check, verify
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
| Documentation check | `npm run docs:check` (alias: `npm run verify`) |
| Backend tests | `cd backend; .venv\Scripts\python.exe -m pytest` |
| Run backend only | `cd backend; .venv\Scripts\python.exe -m uvicorn app.main:app --port 8000` |
| Run frontend only | `cd frontend; npm run dev` (http://localhost:5173) |
| Frontend typecheck | `cd frontend; npm run typecheck` (`tsc --noEmit`) |
| Frontend build | `cd frontend; npm run build` (runs `tsc --noEmit && vite build` → `frontend/dist`) |
| Migrate to head | `cd backend; .venv\Scripts\python.exe -m alembic upgrade head` |
| Migration drift check | `cd backend; .venv\Scripts\python.exe -m alembic check` |
| New migration | `cd backend; .venv\Scripts\python.exe -m alembic revision --autogenerate -m "..."` |
| Re-seed demo data | `cd backend; .venv\Scripts\python.exe -m app.services.demo.seed` |

Verification is mandatory after code changes: run the backend test suite for
backend changes, `npm run build` for frontend changes, and `npm run docs:check`
for **any** change that adds or renames a component. See
[the docs contract](docs/README.md#the-documentation-contract).

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
- Measured corpus results: clean same-identity 0.986-0.995, degraded
  same-identity 0.711-0.866, **impostor 0.000-0.817 (mean 0.309)**. 6 of 30
  impostor pairs exceed the 0.62 review threshold; two identities collide at
  0.817. Reference point: degraded (noise 0.30 + occlusion 0.30) aarav 0.687.
- `BIOMETRIC_ENGINE=opencv` does NOT give real detection here - it falls back
  to the simulator while appearing to take the real path.
- Thresholds (in DB, seeded): HIGH 0.82, REVIEW 0.62, FALLBACK_FACE 0.60,
  CONTEXT_BOOST 0.05, SECONDARY_FEATURE_BOOST 0.06. **Seeded DB rows override
  the env vars**, so editing `.env` on a seeded database does nothing.
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
- New queries go in `app/repositories/`, never in a router or a service.
  Repositories **flush but never commit** - the caller owns the transaction, so
  a domain write and its audit row land together. A repository that commits
  breaks that.
- New tables/columns require an Alembic migration (`alembic revision
  --autogenerate`) plus a check that the demo seed remains idempotent on the
  migrated schema.

## Frontend conventions

- **Monochrome design system.** Colours are CSS custom properties in
  `index.css`, mapped as the `ramp` object in `tailwind.config.js`:
  `canvas`, `surface`, `raised`, `line`, `text`, `muted`, `faint`, `accent`,
  plus `danger`, `warn`, `ok` and their `-fg` pairs. Light and dark share one
  class name; there are no `dark:*` variants. `ink-*`/`slate-*` were **removed** -
  do not reintroduce them.
- `theme.spacing` is **replaced**, not extended. `0.5` is 0.125rem and there is
  no `13`. Values outside the table produce nothing - the same silent failure
  as an opacity modifier on a ramp colour.
- Prefer a composed class from `@layer components` (`.btn`, `.card`, `.input`,
  `.badge`, `.tap`, `.eyebrow`, `.scroll-x`) over a long `className`.
- API calls go through `src/api/client.ts` (`api.*`) using relative `/api`
  paths; typed responses in `src/api/types.ts`. Auth state in `AuthContext`,
  emergency flow state in `EmergencyContext` (sessionStorage-backed, with a
  guarded `JSON.parse`).
- Mobile-responsive: `grid-cols-1 sm:grid-cols-2` patterns, mobile nav exists
  in `Layout.tsx`. Tables use `overflow-x-auto`. 44px minimum touch target via
  `.tap`.
- Every user-visible string is an i18n key in `src/i18n/strings.ts`. Five
  pages still hardcode English - see Known gaps.

## Documentation

Documentation is part of the definition of done, not an afterthought.

- `docs/README.md` is the index and states the contract. Read it before adding
  anything.
- **Every** router endpoint, ORM model, table, migration, repository method,
  service function, settings field, permission, role, page, UI component, icon,
  API client method and exported TypeScript type must be **named on its owning
  docs page**. Adding a component without adding it to the docs fails
  `npm run docs:check`, which is wired to `npm run verify`.
- Write the reason, not the obvious. "Never commits implicitly, so the domain
  write and its audit row share one transaction" prevents a future bug;
  "calls the database" is noise.
- Record the sharp edges. Every page, component and service documented here has
  at least one behaviour that will surprise a reasonable reader, and it is
  written down.
- Never document intent that is not implemented. Where a feature is incomplete
  or a component is dead code, the docs say so plainly. An aspirational doc is
  worse than no doc.
- Copy names, signatures and paths from source. When code and docs disagree,
  the code is right and the doc is a bug.
- Keep `# Heading` style, one H1 per page, and the breadcrumb line at the top
  linking to `docs/README.md`.

## Known gaps

Documented in full at [docs/README.md](docs/README.md#accuracy-status). The
short list, so you do not rediscover them:

1. **The biometric engine is a simulation.** Measured impostor similarity
   0.817, above the 0.62 review threshold. See [ADR 0001](docs/decisions/0001-simulation-biometric-engine.md).
2. `database/` (`schema.sql`, `indexes.sql`, `rls.sql`, `seed.sql`,
   `queries/*.sql`) **does not exist**. There is no row-level security;
   authorization is enforced in Python only.
3. `EmergencyHub`'s Match Result tab renders nothing, because `Emergency.tsx`
   never calls `setResult`/`setSession`. `SimulationNotice` is consequently
   never rendered anywhere.
4. Tailwind ramp colours have no `<alpha-value>`, so every `/opacity` utility on
   them (`bg-ok/15`, `bg-surface/95`) silently produces nothing.
5. `EmergencyHub`, `Profile`, `Admin`, `Demo` and `Privacy` are still on the
   removed `ink-*`/`slate-*` palette with hardcoded English.
6. `Admin` has an invalid role name (`registered`, not `registered_user`) and
   omits `hospital`.
7. `backend/.env.example` documents 20 of the 36 settings.
8. There is no frontend test runner.
