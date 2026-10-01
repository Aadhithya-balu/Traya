[../README.md](../README.md) | [Decisions](README.md)

# ADR 0007: RLS policies read `request.jwt.claims`; roles are resolved live

- **Status:** Accepted
- **Date:** 2026-10-01
- **Affects:** `backend/migrations/supabase/006_claims.sql`, `backend/migrations/supabase/007_rls_policies.sql`, `backend/tests/test_rls_policies.py`, `app/security/tokens.py`

## Context

[TARGET_ARCHITECTURE.md](../TARGET_ARCHITECTURE.md#row-level-security) specifies
policies written against `auth.jwt() -> 'app_metadata' -> 'roles'`. TRAYA has no
Supabase Auth. It signs its own JWTs with PyJWT
(`app/security/tokens.py`), and those tokens carry only `sub`, `type`, `iat` and
`exp` - there is no `app_metadata` for a policy to read. Writing the policies to
the letter of that spec would mean writing them against fiction.

There is a second, less visible mismatch. The application connects to Supabase as
`postgres`, which owns every table. A table owner is exempt from its own row
level security policies unless `FORCE ROW LEVEL SECURITY` is set, and the
migration plan explicitly keeps the application on an owner connection with
Python-side authorization. So these policies govern **every path that is not the
application's own connection** - a browser client, the Supabase SDK, a future
service - and the tests prove the barrier holds, not that the application depends
on it. That limitation is deliberate and is restated in `007`'s header so nobody
later reads the policies as the thing protecting production traffic.

## Decision

1. **Policies read `request.jwt.claims`, not `auth.jwt()`.** That is the setting
   PostgREST writes and the one a manual `set_config` writes, so the same policies
   hold whichever path eventually sets them.
2. **Roles are resolved from the database on every policy evaluation**, not read
   from the token. This is a deliberate improvement over the target design.
3. **`traya_auth.caller_has` and `traya_auth.subject_in_active_incident` are
   `SECURITY DEFINER`** with `search_path` pinned to the schema they were applied
   to, and execute granted to `traya_api` only.
4. **Clinical access is scoped to the incident's identified subject.**
   `subject_in_active_incident(p_user_id)` is the only responder gate on
   `medical_profiles`.
5. **The vector tables are refused at the privilege layer**: no grant to
   `traya_api` and no policy for any role.

## Why roles are resolved live

A role inside a signed JWT is a cached authorization decision. Demote a responder
who has lost accreditation and their token still says `medical_responder` until
it expires - up to `ACCESS_TOKEN_EXPIRE_MINUTES` of retained access that no
revocation can reach. Resolving through `user_roles` makes revocation immediate,
and it keeps the seeded `roles` / `role_permissions` tables as the single source
of truth, which `TARGET_ARCHITECTURE.md` already asks for.

The cost is one indexed join per policy evaluation, which is the right trade
against stale privilege. `caller_has` therefore carries its own `is_active`
check: an earlier draft relied on a sibling function to apply it, so deactivating
an account removed the role from one helper while every policy kept passing.

## Why the helpers are SECURITY DEFINER

`005_enable_rls.sql` enables RLS on **every** table, and a table with RLS on and
no policy returns nothing to a non-owner. A `SECURITY INVOKER` `caller_has`
therefore reads zero rows and returns `false` forever, and every
permission-gated policy silently denies. That failure mode is the dangerous one:
a barrier that denies everything wears the evidence of a working barrier, and it
passes any test that only asserted denials.

The alternative - granting `traya_api` SELECT on `user_roles` so it can do the
join itself - publishes the entire role matrix, letting any client enumerate
which users are police or medical responders. As `SECURITY DEFINER` the functions
run as the owner, read what they need, and return a boolean.

`search_path` is pinned per function because a `SECURITY DEFINER` function that
inherits the caller's `search_path` can be redirected at a table the caller
controls. The schema cannot be hardcoded - these scripts run against hosted
`public` and the test suite's throwaway schema - so it is discovered with
`current_schema()` and quoted with `quote_ident`.

## Why clinical access is scoped to the subject

`TARGET_ARCHITECTURE.md` requires "an active incident" and does not say whose
records. The loose reading - permission AND any active incident - hands every
responder who has ever opened an incident the blood group of every enrolled
person in the system, for as long as the incident stays open. That is a real
exposure wearing a plausible shape, so the gate is
`view_medical_alerts` AND `identified_user_id` of a live incident the caller is
party to. `test_medical_responder_cannot_read_a_patient_outside_the_incident`
exists to fail loudly if that is ever loosened.

## Consequences

**Good.** Revocation is immediate at the database layer as well as in Python. A
correctly signed token claiming `admin` buys nothing, because roles come from the
database. The embedding tables are unreachable rather than merely unreadable, so
there is no filter that a later edit could widen.

**Costs, stated plainly.**

- `traya_api` is `NOLOGIN` and nothing uses it yet. The policies are a real,
  tested barrier for a client path that does not exist, and the application
  bypasses them by owning the tables. Anyone reading this as "production is now
  protected by RLS" has misread it.
- A client path will need a login role granted `traya_api` and a transaction that
  sets `request.jwt.claims` from TRAYA's JWT. That plumbing is not written.
- The scripts contain no percent signs anywhere, including comments, and use
  `quote_ident` rather than `format`. psycopg validates percent sequences even
  with no parameters supplied and rejects any specifier that is not its own, so
  `format` cannot be executed through the driver at all. This is enforced by
  `tests/test_rls_policies.py`.
- `006` creates `traya_api` because it is the file that grants execute on the
  helpers to it. `007` keeps an existence check for standalone runs.

## Supersedes

Nothing. `TARGET_ARCHITECTURE.md`'s `auth.jwt()` / `app_metadata` sketch is
narrowed rather than replaced, and the page says so.
