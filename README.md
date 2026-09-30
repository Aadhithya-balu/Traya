# TRAYA

TRAYA is a full-stack platform for **AI-assisted emergency victim identification
and rapid response**. A responder photographs an unresponsive person at the
scene; TRAYA checks the photo, searches pre-enrolled citizen records, and
surfaces the person's medical profile, emergency contacts and nearby hospitals so
a verified responder can act.

> ### The face engine in this repository is a simulation
>
> It compares **brightness patterns between images**. It does not identify
> people, and it is not a biometric.
>
> Measured over the synthetic corpus, impostor similarity reaches **0.817** -
> above the 0.62 review threshold. **6 of 30 impostor pairs would be sent to a
> human for review, and two demo identities collide outright.** A bystander in an
> emergency pressing "identify" gets a number, and that number is not an
> identity.
>
> Every result carries `engine_mode` and `demo_mode`, and the UI is required to
> disclose it. This is a defect the product does not have a fix for yet; see
> [ADR 0001](docs/decisions/0001-simulation-biometric-engine.md) and the
> [production checklist](docs/operations/README.md#production-checklist).

- **Backend** - FastAPI, SQLAlchemy 2.0, PostgreSQL/Supabase with a SQLite
  fallback, JWT + session-token auth, RBAC, Fernet-encrypted biometric
  embeddings, append-only audit trail.
- **Frontend** - React 18 + TypeScript + Vite: camera-first emergency capture,
  responder hub, citizen dashboard and profile, admin console, demo playground.
  English and Tamil, light and dark, mobile-first.
- **Documentation** - every endpoint, table, migration, service, repository,
  setting, page and component is documented by name, and
  `npm run docs:check` fails the build when that drifts.

## Documentation

Start at **[docs/README.md](docs/README.md)**. It is the index and states the
maintenance contract.

| Page | Covers |
| --- | --- |
| [Architecture](docs/ARCHITECTURE.md) | How the pieces fit together, and the three flows worth understanding. |
| [API reference](docs/backend/api.md) | All 47 endpoints across 7 routers. |
| [Security](docs/backend/security.md) | 7 roles, 18 permissions, tokens, crypto, rate limits. |
| [Data model](docs/backend/data-model.md) | Every table, relationship and migration. |
| [Services](docs/backend/services.md) | Every service module, including the engine and its limits. |
| [Repositories](docs/backend/repositories.md) | Every repository class and method. |
| [Configuration](docs/backend/configuration.md) | Every settings field and its default. |
| [Frontend](docs/frontend/README.md) | Routing, pages, components, state, design system. |
| [Operations](docs/operations/README.md) | Running, testing, seeding, migrating, deploying. |
| [Decisions](docs/decisions/README.md) | ADRs 0001-0006: why the system is the way it is. |

## Quick start

```bash
npm run dev:all
```

One command. Builds the frontend if needed, then starts the API on `:8000` and
Vite on `:5173`, and stops both on Ctrl-C.

Open <http://localhost:5173>. Sign in as `aarav.kumar@demo.traya` /
`TrayaDemo#2026`, or just press **Start emergency** - the capture screen works
without an account, because a bystander in an emergency will not have one.

<details>
<summary>Running the two halves separately</summary>

Backend, from `backend/`:

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows (or: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env            # Windows (cp on *nix) - optional, see below
python -m alembic upgrade head
python -m app.services.demo.seed
python -m uvicorn app.main:app --port 8000
```

OpenAPI docs are at <http://localhost:8000/docs>.

`.env` is optional only because every setting has a default that works for the
demo. It was also *silently* optional for most of this project's life:
`BASE_DIR` resolved to `backend/app`, so the app looked for a `.env` in a
directory that never had one and ignored any file you put in `backend/`.
Fixed in Phase 3, with `tests/test_settings_path.py` holding the path in place.
If you configure anything, you need this file — see
[docs/backend/configuration.md](docs/backend/configuration.md).

Frontend, from `frontend/`:

```bash
npm install
npm run dev                       # http://localhost:5173, proxies /api -> :8000
```

</details>

## Demo accounts

All demo accounts share the password `TrayaDemo#2026`.

| Role | Email | Notes |
| --- | --- | --- |
| Citizen, enrolled | `aarav.kumar@demo.traya` | Full medical profile and contacts. |
| Citizen, enrolled | `priya.sharma@demo.traya` | |
| Citizen, enrolled | `rohan.verma@demo.traya` | |
| Citizen, enrolled | `meera.iyer@demo.traya` | |
| Police responder | `neha.rao@responder.traya` | |
| Police responder | `suresh.patil@responder.traya` | |
| Administrator | `admin@traya.io` | Full console. |
| Auditor | `auditor@traya.io` | Read-only audit access. |

The **Demo** page exercises six scenarios through the real pipeline:
`high_confidence`, `low_confidence` (review required), `no_match`,
`multiple_faces`, `poor_quality`, `gps_unavailable`.

**Every byte of demo data is fictional and must stay that way.** No real names,
addresses, phone numbers or medical histories.

## Testing

```powershell
cd backend; .venv\Scripts\python.exe -m pytest
```

130 tests against a fresh throwaway SQLite database in the system temp dir:
auth, RBAC, users, biometrics, guided enrollment, identification flows,
emergency sessions, demo scenarios, admin and engine units.

`npm run docs:check` verifies the documentation still matches the code.

There is **no frontend test runner**. Frontend changes are verified by
`npm run typecheck` and `npm run build` only.

## Configuration

Full reference: [configuration.md](docs/backend/configuration.md).

| Env var | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./traya.db` | `postgresql+psycopg://...` for production. |
| `DATABASE_ALLOW_FALLBACK` | `true` | Fall back to SQLite if the primary probe fails. |
| `SECRET_KEY` | dev placeholder | Signs every JWT. **Replace before production.** |
| `ENCRYPTION_KEY` | derived from `SECRET_KEY` | Encrypts embeddings. **Set explicitly** - rotating `SECRET_KEY` without it makes stored embeddings permanently unreadable. |
| `BIOMETRIC_ENGINE` | `auto` | `simulation` in practice. `opencv` has no cascade data available and falls back to the simulator. |
| `DEMO_MODE` | `true` | **Set `false` in production** - gates synthetic data and the demo endpoints. |

`backend/.env.example` documents 20 of the 36 settings; see
[operations](docs/operations/README.md#env-example-is-incomplete).

## Before deploying

The non-negotiables are in
[production checklist](docs/operations/README.md#production-checklist). The two
that matter most:

1. **A real recogniser, or an honest label.** Either replace the engine behind
   the existing interface, or keep the simulation disclosure impossible to
   miss. Shipping the current engine as identification is the failure mode this
   repository most needs to avoid.
2. **HTTPS, and a real `SECRET_KEY`.** Access tokens live in `localStorage` for
   60 minutes. Over plain HTTP they are readable by anything on the network.
