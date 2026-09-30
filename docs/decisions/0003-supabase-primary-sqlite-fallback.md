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
3. Fallback to SQLite happens **only** when `DATABASE_ALLOW_FALLBACK` is true
   **and** `DEMO_MODE` is true. `DATABASE_ALLOW_FALLBACK` defaults to `False`
   (changed in Phase 3; it was `True`), and `DEMO_MODE=false` outranks the flag.
   Two conditions rather than one, because either alone is a way to lose an
   incident quietly: a permissive default that production inherits, or a stray
   env var that re-authorises data loss on a production deployment.
4. `DatabaseStatus` records `backend`, `degraded`, `reason` and `detail`, and
   `/api/health` reports it verbatim. Degraded mode is loud: the fallback logs
   at `ERROR` and states what is lost, because a `WARNING` among a boot log is
   not read by anyone at 3am.
5. `GET /api/health` never raises. It reports `disconnected` rather than 500ing,
   so monitoring can distinguish "down" from "unreachable". Backend *resolution*
   is inside that guarantee, not just the probe — with the fallback off and a
   dead primary, resolution itself raises, and an endpoint that 500s on the
   condition it exists to report is worse than useless.
6. `migrations/env.py` takes its URL from `settings.DATABASE_URL`, so Alembic
   always targets the same database the app resolved.

## Consequences

**Good.** Zero-config demo and tests work, because the fallback is only
consulted when the primary is *not* SQLite. Production is now the default, not
a deployment chore: an unreachable primary is a startup failure out of the box,
and the rollback is `DATABASE_ALLOW_FALLBACK=true`. Health output tells an
operator which backend is live, and answers even when the answer is bad.

**Costs.** Two dialects to keep honest. `compare_type=True` is set in Alembic so
column-type drift is caught rather than ignored. Anything using PostgreSQL-only
features would break the SQLite path, so the schema stays portable - which is
also why Row-Level Security is applied from a SQL asset rather than relied upon
in the ORM, and why [the SQL assets](../operations/README.md#sql-assets) are a
required part of a production deployment.

**Cost of the stricter rule.** A deployment that genuinely wants
best-effort availability now has to say so, in two variables. That is
deliberate: an emergency identification system that silently stops being
auditable during an outage is not more available, it is just less
accountable, and the moment to discover that should not be during an
incident.
