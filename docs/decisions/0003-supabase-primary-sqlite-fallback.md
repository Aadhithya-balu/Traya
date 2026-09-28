[../README.md](../README.md) | [Decisions](README.md)

# ADR 0003: Supabase/PostgreSQL is primary, SQLite is an explicit fallback

- **Status:** Accepted
- **Date:** 2026-08-15
- **Affects:** `app/database/service.py`, `app/database/session.py`, `app/main.py`, `app/config/settings.py`

## Context

TRAYA targets Supabase for hosted Postgres, but the demo, the test suite and a
first-time contributor's machine all need to run with zero configuration. Two
databases means two places for behaviour to diverge.

The failure mode that matters: silently falling back to SQLite in production
would mean an incident running against a local file that is not backed up, not
audited with Postgres row-level security, and not shared with responders. That is
worse than being down.

## Decision

1. `DatabaseService` resolves a backend at startup, in priority order:
   Supabase/PostgreSQL, then the fallback URL, then SQLite.
2. Each non-SQLite candidate is **probed** with `SELECT 1` and a
   `DATABASE_PROBE_TIMEOUT_SECONDS` connect timeout. A URL that is configured but
   unreachable is not silently accepted.
3. Fallback to SQLite happens **only** when `DATABASE_ALLOW_FALLBACK` is true.
4. `DatabaseStatus` records `backend`, `degraded`, `reason` and `detail`, and
   `/api/health` reports it verbatim. Degraded mode is loud, not silent.
5. `GET /api/health` never raises. It reports `disconnected` rather than 500ing,
   so monitoring can distinguish "down" from "unreachable".
6. `migrations/env.py` takes its URL from `settings.DATABASE_URL`, so Alembic
   always targets the same database the app resolved.

## Consequences

**Good.** Zero-config demo and tests work. Production is explicit: set
`DATABASE_ALLOW_FALLBACK=false` and an unreachable primary is a startup failure
rather than a quiet data-loss event. Health output tells an operator which
backend is live.

**Costs.** Two dialects to keep honest. `compare_type=True` is set in Alembic so
column-type drift is caught rather than ignored. Anything using PostgreSQL-only
features would break the SQLite path, so the schema stays portable - which is
also why Row-Level Security is applied from a SQL asset rather than relied upon
in the ORM, and why [the SQL assets](../operations/README.md#sql-assets) are a
required part of a production deployment.
