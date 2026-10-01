-- 006: claim helpers for the row level security policies.
--
-- Run AFTER `alembic upgrade head` and after `005_enable_rls.sql`.
--
-- ---------------------------------------------------------------- claim source
-- `TARGET_ARCHITECTURE.md` specifies
--
--   auth.jwt() -> 'app_metadata' -> 'roles'
--
-- TRAYA has no Supabase Auth. It signs its own JWTs with `SECRET_KEY` via
-- PyJWT (`app/security/tokens.py`), and those tokens carry only
-- `sub`, `type`, `iat` and `exp`. There is no `app_metadata`, so `auth.jwt()`
-- has nothing to read and a policy written to that spec would be written
-- against fiction.
--
-- These helpers read `request.jwt.claims` instead. That is the setting both
-- Supabase's PostgREST and a manual `set_config` write, so the same policies
-- hold whichever path eventually sets them. See ADR 0007.
--
-- ---------------------------------------------------------------- roles are
-- not in the token, on purpose
-- The target design reads roles out of the JWT. TRAYA does not, and this is a
-- security improvement rather than a shortcut.
--
-- A role in a signed JWT is a cached authorization decision. Demote a
-- responder who has lost accreditation and their token still says
-- `medical_responder` until it expires, which is up to
-- `ACCESS_TOKEN_EXPIRE_MINUTES` of retained access that no revocation can
-- reach. Resolving roles live through `user_roles` makes revocation immediate,
-- and the seeded `roles` / `role_permissions` / `permissions` tables stay the
-- single source of truth, which is what `TARGET_ARCHITECTURE.md` already asks
-- for: "The role model carries over from ROLE_PERMISSIONS, which is already the
-- single source of truth."
--
-- The cost is one indexed join per policy evaluation. That is the right trade
-- against stale privilege.
--
-- ---------------------------------------------------------------- the two
-- table-reading helpers are SECURITY DEFINER, and that is load bearing
--
-- `caller_has` and `subject_in_active_incident` read `user_roles`, `roles`,
-- `role_permissions`, `permissions`, `users` and `emergency_sessions`. Two facts
-- force the decision:
--
-- - `005_enable_rls.sql` enables RLS on every table, and a table with RLS on
--   and no policy returns nothing to a non-owner. So a SECURITY INVOKER
--   `caller_has` reads zero rows and returns false forever, and every
--   permission-gated policy silently denies. That is the failure mode worth
--   naming: a barrier that denies everything, wearing the evidence of a
--   working barrier, and it passes any test that only checked denials.
-- - The alternative, granting `traya_api` SELECT on `user_roles` so it can do
--   the join itself, publishes the whole role matrix. Any client could
--   enumerate which users are police or medical responders, which is
--   operational information nobody asked to publish.
--
-- As DEFINER they run as the table owner, read what they need, and return a
-- boolean. The caller learns only the answer.
--
-- `search_path` is pinned per function to the schema this script was applied
-- to. A DEFINER function that inherits the caller's `search_path` can be
-- redirected at a table the caller controls, which would turn "reads the real
-- role table" into "reads whatever you named". The schema cannot be hardcoded
-- because this script runs against hosted `public` and against the test suite's
-- throwaway schema, so it is discovered at run time and quoted with
-- `quote_ident`.
--
-- `quote_ident` rather than `format` with a percent specifier, and that is not a
-- style preference. psycopg validates percent sequences even when the query
-- takes no parameters, and accepts only its own three placeholder specifiers, so
-- `format` and its identifier specifier cannot be executed through the driver at
-- all - it raises "only ... are allowed as placeholders, got ...". These scripts
-- have to run verbatim through psycopg and through the Supabase SQL editor, so
-- they contain no percent signs anywhere, comments included.
--
-- `caller_claims` and `caller_id` stay SECURITY INVOKER: they read no table,
-- only a session setting.
--
-- ---------------------------------------------------------------- why there is
-- no `caller_roles` function
-- An earlier draft exposed the caller's effective roles as a helper. No policy
-- uses it, because a policy needs a yes or no, not a list - and a function that
-- exists only to be queried directly is attack surface with no caller. The role
-- list is available to anyone entitled to it by joining `user_roles` themselves.

create schema if not exists traya_auth;

-- Created here, not in `007`, because this file is the one that grants execute
-- on the helpers to it. `NOLOGIN`: it is a privilege set, not an account. The
-- application connects as the table owner and bypasses policies entirely, so
-- nothing needs to log in as this role yet; a future client path becomes a
-- login role granted membership, which is a grant and not a migration.
do $$
begin
    if not exists (select 1 from pg_roles where rolname = 'traya_api') then
        create role traya_api nologin;
    end if;
end
$$;

-- The raw claims, or NULL when unset.
--
-- `nullif(..., '')` is load-bearing and was not obvious. Casting an empty
-- string to jsonb raises "invalid input syntax for type json", so a session
-- whose claims were cleared - or never set - produced a 500 from inside a
-- policy instead of a denial. Policies must fail closed, and a function that
-- raises on a missing claim is the opposite of that.
--
-- Malformed *non-empty* claims still raise. That is deliberate: it means the
-- caller put something there that is not JSON, which is a programming error
-- worth surfacing loudly, and it still returns no data, so it cannot leak.
create or replace function traya_auth.caller_claims()
returns jsonb
language sql
stable
as $$
    select nullif(current_setting('request.jwt.claims', true), '')::jsonb
$$;

-- The caller's user id, or NULL when there are no claims. NULL rather than an
-- exception: every policy must fail closed, and a function that raises turns a
-- missing claim into a 500 instead of a denial.
--
-- Returns text, not uuid. Every id column in this schema is `character varying`
-- - `users.id`, `user_roles.user_id`, `emergency_sessions.identified_user_id`
-- and the rest - so a uuid return type fails to compare at all with
-- "operator does not exist: character varying = uuid". Verified against the
-- schema rather than assumed, which is the only reason it is not that now.
create or replace function traya_auth.caller_id()
returns text
language sql
stable
as $$
    select coalesce(
        traya_auth.caller_claims() ->> 'sub',
        traya_auth.caller_claims() ->> 'user_id'
    )
$$;

do $$
declare
    target text := current_schema();
    q text := '$fn$';
begin
    -- Whether the caller holds a permission.
    --
    -- The `is_active` check is not optional and its absence was a real defect.
    -- An earlier draft read the role join without it, so deactivating an
    -- account left every `caller_has` policy still passing: the account was
    -- suspended and the policies did not notice. A suspended responder has to be
    -- denied, and the check has to live here rather than being assumed from a
    -- sibling function.
    execute 'create or replace function traya_auth.caller_has(p_permission text) '
         || 'returns boolean language sql stable security definer '
         || 'set search_path = pg_catalog, ' || quote_ident(target)
         || ' as ' || q || $fn$
            select exists (
                select 1
                from user_roles ur
                join role_permissions rp on rp.role_id = ur.role_id
                join permissions p on p.id = rp.permission_id
                where ur.user_id = traya_auth.caller_id()
                  and p.name = p_permission
                  and exists (select 1 from users u where u.id = ur.user_id and u.is_active)
            )
            $fn$ || q;

    -- Whether `p_user_id` is the identified subject of a live incident the
    -- caller is party to.
    --
    -- This exists instead of a bare "is the caller in an active incident" test
    -- in the clinical policy because those are different questions. The loose
    -- one hands every responder who has ever opened an incident the medical
    -- records of every enrolled person in the system, for as long as the
    -- incident stays open. `TARGET_ARCHITECTURE.md` requires "an active
    -- incident" and does not say whose records; the identified subject is the
    -- only reading that does not turn the gate into a formality.
    execute 'create or replace function '
         || 'traya_auth.subject_in_active_incident(p_user_id text) '
         || 'returns boolean language sql stable security definer '
         || 'set search_path = pg_catalog, ' || quote_ident(target)
         || ' as ' || q || $fn$
            select exists (
                select 1
                from emergency_sessions s
                where s.status = 'active'
                  and s.identified_user_id = p_user_id
                  and (s.identified_user_id = traya_auth.caller_id()
                       or s.initiator_id = traya_auth.caller_id())
            )
            $fn$ || q;
end
$$;

-- Only the role the policies are written for. `grant ... to public` would let
-- any role evaluate these, which is harmless while they return the caller's own
-- claims and not worth the wider surface once they are executable by others.
revoke all on function traya_auth.caller_claims() from public;
revoke all on function traya_auth.caller_id() from public;
revoke all on function traya_auth.caller_has(text) from public;
revoke all on function traya_auth.subject_in_active_incident(text) from public;

grant usage on schema traya_auth to traya_api;
grant execute on function traya_auth.caller_claims() to traya_api;
grant execute on function traya_auth.caller_id() to traya_api;
grant execute on function traya_auth.caller_has(text) to traya_api;
grant execute on function traya_auth.subject_in_active_incident(text) to traya_api;
