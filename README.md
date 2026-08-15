# TRAYA

TRAYA is a full-stack platform for **AI-assisted emergency victim identification and rapid response**. A first responder photographs an unconscious or unidentified person at the scene; TRAYA matches the face against pre-enrolled citizen biometrics, surfaces the victim's medical profile, emergency contacts and nearby hospitals, and lets a verified responder confirm the identity before responders act.

- **Backend** — FastAPI + SQLAlchemy 2.0, PostgreSQL (SQLite for local dev/tests), JWT auth + RBAC, Fernet-encrypted biometric embeddings, full audit trail.
- **Frontend** — React 18 + TypeScript + Vite: emergency capture wizard, response hub, citizen dashboard/profile, admin console, demo playground.
- **Demo-first** — synthetic citizen data and a deterministic simulation face engine ship out of the box so the entire flow is exercisable without a camera or a trained model.

## Repository layout

```
backend/    FastAPI application, models, services, tests, Alembic migrations
frontend/   React + TypeScript + Vite SPA
docs/       Architecture and design documentation
```

## Quick start

### Backend

Requires Python 3.11+.

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate            # Windows (or: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env            # Windows (cp on *nix); tweak as needed
python -m alembic upgrade head    # create the schema
python -m app.services.demo.seed  # seed 8 citizens, 4 enrolled, 9 hospitals
uvicorn app.main:app --reload     # http://localhost:8000
```

The OpenAPI docs are served at `http://localhost:8000/docs`.

### Frontend

Requires Node 18+ and npm.

```bash
cd frontend
npm install
npm run dev                       # http://localhost:5173 (proxies /api -> :8000)
```

Production build: `npm run build` (type-checks via `tsc --noEmit` first).

## Demo accounts

All demo accounts share the password `TrayaDemo#2026`.

| Role                | Email                         |
| ------------------- | ----------------------------- |
| Citizen (enrolled)  | `aarav.kumar@demo.traya`      |
| Citizen (enrolled)  | `priya.sharma@demo.traya`     |
| Citizen (enrolled)  | `rohan.verma@demo.traya`      |
| Citizen (enrolled)  | `meera.iyer@demo.traya`       |
| Citizen (not enrolled) | `suresh.patil@demo.traya`  |
| Medical responder   | `neha.rao@responder.traya`    |
| Medical responder   | `rohan.verma@responder.traya` |
| Administrator       | `admin@traya.io`              |
| Auditor             | `auditor@traya.io`            |

The **Demo** page in the UI and `POST /api/demo/run` exercise six realistic scenarios: `high_confidence`, `low_confidence` (review required), `no_match`, `multiple_faces`, `poor_quality`, and `gps_unavailable`.

## Testing

```bash
cd backend
.venv\Scripts\python.exe -m pytest
```

The suite runs against a fresh throwaway SQLite database in the system temp dir (87 tests: auth, users, biometrics, identification flows, emergency sessions, demo scenarios, admin/RBAC, and engine unit tests).

## Migrations

```bash
cd backend
.venv\Scripts\python.exe -m alembic revision --autogenerate -m "describe change"
.venv\Scripts\python.exe -m alembic upgrade head
```

`DATABASE_URL` is read from application settings (`app/config/settings.py`), so migrations follow the same `.env`/environment configuration as the app.

## Key configuration

| Env var | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./traya.db` | `postgresql+psycopg://...` for production |
| `SECRET_KEY` | dev placeholder | JWT signing; derive encryption key if `ENCRYPTION_KEY` unset |
| `BIOMETRIC_ENGINE` | `auto` | `simulation` or `opencv` |
| `DEMO_MODE` | `true` | Enables demo endpoints and auto-seed on startup |

See `docs/ARCHITECTURE.md` for the identification pipeline, confidence model, security design and data model.
