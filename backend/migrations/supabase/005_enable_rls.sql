-- 005: enable row level security on every application table.
--
-- Run AFTER `alembic upgrade head`.
--
-- This file is also executed by `backend/tests/test_rls.py`, so the invariant is
-- checked on every test run rather than only by this comment.
--
-- WHAT THIS DOES
-- Turns on RLS for all tables in `public`. RLS is deny-by-default: with no
-- policy, a non-owner role sees zero rows. Combined with `004_revoke_anon.sql`
-- this means the schema has no permissive path into it at all - a role needs an
-- explicit `GRANT` *and* a matching policy to read anything.
--
-- WHY IT IS SAFE TO RUN NOW, BEFORE THE POLICIES
-- Postgres exempts a table's owner from its own policies unless
-- `ALTER TABLE ... FORCE ROW LEVEL SECURITY` is also set. TRAYA connects with
-- `psycopg` as `postgres`, which owns these tables, so the application is
-- unaffected while the protection applies to every other role.
--
-- This file deliberately does NOT use FORCE. Forcing would extend RLS to the
-- owner too, and with no `caller_roles()` available yet (see the note below)
-- the application's own writes would be denied. Locking the app out of its own
-- database is not hardening. Phase 4's policy layer forces this deliberately,
-- per table, once the claim plumbing exists.
--
-- THE CLAIM PLUMBING IS THE PART THAT IS NOT DONE
-- `TARGET_ARCHITECTURE.md` specifies `caller_roles()` reading
-- `auth.jwt() -> 'app_metadata' -> 'roles'`. TRAYA has no Supabase Auth: it
-- signs and verifies its own JWTs with `SECRET_KEY` via PyJWT
-- (`app/security/tokens.py`). `auth.jwt()` therefore never has anything to read
-- in this architecture. Policies must be written against a claim source that
-- actually exists. Until that decision is made and implemented, enabling RLS is
-- the honest half of the work: it closes every path that is not the
-- application's own connection, and it does not pretend to authorize anyone.

-- Schema is resolved with `current_schema()` rather than hardcoded to `public`,
-- so this exact file is the single source of truth in two places: the Supabase
-- SQL editor, where `search_path` is `public`, and
-- `backend/tests/test_rls.py`, where the connection sets
-- `search_path=traya_test`. One file, so the test cannot pass against a copy of
-- the logic that has drifted from the thing actually deployed.

do $$
declare
    t record;
    missing text;
begin
    for t in
        select tablename from pg_tables where schemaname = current_schema()
    loop
        -- quote_ident(), not format() with an identifier placeholder. The
        -- format() form is correct Postgres and rejected by psycopg, which reads
        -- every percent sign as a parameter marker. Concatenation keeps this
        -- statement free of them.
        execute 'alter table ' || quote_ident(t.tablename) || ' enable row level security';
    end loop;

    -- Including `alembic_version`, which holds nothing but a version hash. It
    -- is enabled anyway so "RLS on every table" is literally true rather than
    -- true-except-one; the owner bypasses it, so Alembic is unaffected.
    select string_agg(tablename, ', ' order by tablename)
    into missing
    from pg_tables
    where schemaname = current_schema() and not rowsecurity;

    if missing is not null then
        -- USING MESSAGE, because RAISE's plain form takes a string literal and
        -- will not concatenate. No percent sign, so psycopg leaves it alone.
        raise exception using message = 'row level security not enabled on: ' || missing;
    end if;
end
$$;

-- Future tables must not arrive unprotected. `ALTER DEFAULT PRIVILEGES` cannot do
-- this: it only carries GRANT/REVOKE, and has no `enable row level security`
-- form, so that line is a syntax error, not a weaker protection. `alembic
-- upgrade` creates tables directly.
--
-- The guard is therefore `backend/tests/test_rls.py`, which asserts that every
-- table in `public` has RLS enabled. A new model that ships unprotected fails
-- CI instead of failing quietly.
