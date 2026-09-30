-- 004: revoke the public anon key's read access to application tables.
--
-- Numbered 004, not 003, because the migration plan reserves `003_functions.sql`
-- for helper functions. That file was never written - the seed belongs to
-- Alembic, not to SQL - but reusing its number would leave two different
-- meanings of `003` in the same documentation.
--
-- Run this AFTER `alembic upgrade head`. It assumes the schema exists.
--
-- WHY THIS IS NEEDED
-- Supabase grants the `anon` role SELECT on every table in `public` by default.
-- `anon` is the key that ships in the frontend bundle and is meant to be
-- public, so before this file ran, anyone holding the project's URL and anon
-- key could read every row of every application table through PostgREST.
--
-- Measured on the hosted project before this change, with the anon key alone:
--
--   users                 HTTP 200  3 rows  (real email addresses)
--   biometric_embeddings  HTTP 200  1 row   (7026 chars of ciphertext)
--   audit_logs            HTTP 200  1 row
--   medical_profiles      HTTP 200  1 row
--
-- The biometric ciphertext being readable is the sharp edge. Encryption at
-- rest is only worth anything if access to the ciphertext is controlled; a
-- downloadable blob plus an offline key-guessing attack is a different threat
-- model than a stolen database file. `SECURITY_MODEL.md` treats the
-- encryption as a control, so the anon grant has to go for that control to mean
-- anything. The application never returns embeddings to clients by design
-- (AGENTS.md 3.27) - that promise was being undercut at the database layer.
--
-- This is a GRANT REVOCATION, not RLS. It is the correct minimal step for the
-- present architecture and it is fully reversible. RLS policies, which are the
-- real Phase 4 work, are a different mechanism and are deliberately not here:
-- enabling RLS with no policy denies everything, including the application's
-- own service-role traffic, so it needs the policy set designed first.
--
-- TRAYA connects with `psycopg` as the `postgres` role, which owns these
-- tables. It does not use the Supabase client SDK, `anon`, or `authenticated`,
-- so revoking them cannot break the application. Verified: the full emergency
-- flow still returned 200 with an accepted match after this ran.
--
-- `authenticated` is intentionally left alone. Nothing uses it today, and its
-- access should be decided by the Phase 4 policy set rather than guessed here.

revoke all privileges on all tables in schema public from anon;
revoke all privileges on all sequences in schema public from anon;

-- New tables created by later migrations must not be readable either. Without
-- this, `alembic upgrade` on a future version re-opposes `anon` to each new
-- table by default and the exposure returns silently.
alter default privileges in schema public revoke all on tables from anon;
alter default privileges in schema public revoke all on sequences from anon;

do $$
declare
    remaining integer;
begin
    select count(*) into remaining
    from information_schema.role_table_grants
    where table_schema = 'public' and grantee = 'anon';

    if remaining > 0 then
        raise exception 'anon still holds % table grant(s) in public', remaining;
    end if;
end
$$;

-- Owner grants are untouched, so the application and the service role are
-- unaffected. This assertion exists so a future partial run fails loudly.
do $$
declare
    owner_grants integer;
begin
    select count(*) into owner_grants
    from information_schema.role_table_grants
    where table_schema = 'public' and grantee = 'postgres';

    if owner_grants = 0 then
        raise exception 'postgres holds no grants in public; refusing to continue';
    end if;
end
$$;
