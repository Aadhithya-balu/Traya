[../README.md](../README.md) | [Backend docs](api.md) | [Security](security.md)

# Backend Component Index

The FastAPI application. FastAPI + SQLAlchemy 2.0 + Alembic, no ORM magic, no
DI container. Each layer has one job.

## Layers

```
app/main.py            app factory, lifespan, health, SPA serving
app/api/               HTTP routers - validate, authorize, delegate, respond
app/services/          domain logic - the rules live here
app/repositories/      data access - no business rules, no implicit commits
app/models/            SQLAlchemy models and association tables
app/schemas/           Pydantic request/response contracts
app/security/          auth, RBAC, password, crypto, rate limiting
app/database/          backend resolution, session factory, declarative base
app/config/            settings
app/utils/             image validation, session codes, token helpers
```

The dependency direction is strictly one-way: `api -> services -> repositories
-> models`. A repository never imports a service; a service never imports a
router.

## Component pages

| Page | Covers |
|---|---|
| [api.md](api.md) | Every HTTP endpoint, grouped by router, with auth, schemas and status codes. |
| [security.md](security.md) | The 7 roles, the 18 permissions, the matrix, session tokens, password hashing, encryption, rate limiting. |
| [data-model.md](data-model.md) | Every table, relationship and index, plus the full migration chain. |
| [services.md](services.md) | Every service module: identification engine, pipeline, guided enrollment, medical, location, notification, demo, audit. |
| [repositories.md](repositories.md) | Every repository class and method, and the one contract they all share. |
| [configuration.md](configuration.md) | Every settings field with its default and effect. |

## Entry point

`app/main.py` builds the `FastAPI` app:

- **Lifespan**: `init_db()` -> `app.state.db_factory = SessionLocal` -> if
  `DEMO_MODE`, `seed_all(skip_if_seeded=True)` (failures are logged, never
  fatal) -> serve -> clear `db_factory`.
- **Middleware order**, outermost first: `RateLimitMiddleware`, then
  `CORSMiddleware`.
- **Routers**: `api_router` from `app/api/__init__.py` mounted at
  `prefix=settings.API_PREFIX` (`/api`).
- **Static**: if `frontend/dist/assets` exists it is mounted at `/assets`; a
  catch-all `GET /{full_path:path}` serves `dist/index.html` for everything else,
  so the SPA and API share an origin in production.
- **Logging** is configured inline: `INFO` when `DEBUG`, else `WARNING`.

## Conventions

- A router declares its dependencies as `Depends(...)` and contains no business
  logic. Anything a router does that is not validation, authorization or
  serialization belongs in a service.
- A repository takes a `Session` and **never commits implicitly**. The caller
  owns the transaction, so a domain write and its audit row commit together.
- A new table or column requires an Alembic migration
  (`alembic revision --autogenerate`) plus a check that the demo seed is still
  idempotent on the migrated schema. Run `alembic check` to prove the models and
  migrations have not drifted.
- Every new endpoint gets a test in `backend/tests/`, and every new public
  function gets a row in [services.md](services.md) or
  [repositories.md](repositories.md). `npm run docs:check` fails otherwise.

## Related

- [Operations: local dev, seeding, testing](../operations/README.md)
- [Architecture overview](../ARCHITECTURE.md)
