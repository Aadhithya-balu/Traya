-- 001_extensions.sql - TRAYA on Supabase
--
-- PASTE INTO THE SUPABASE SQL EDITOR AND RUN THIS FIRST.
-- It is the only file that must run before `alembic upgrade head`.
--
-- Why this file exists at all: Alembic creates tables, but it does not
-- create Postgres extensions. `CREATE EXTENSION` is DDL that has to run once
-- per database, and on a fresh Supabase project neither of these is enabled.
-- Verified on a fresh `pgvector/pgvector:pg16` database:
--
--   select extname from pg_extension;   ->  plpgsql only
--
-- `vector` is required by the plan for the future `face_embeddings` column.
-- `pgcrypto` supplies `gen_random_uuid()`, which is the default the ORM would
-- reach for on a Postgres-native schema.
--
-- Both are safe to re-run: `IF NOT EXISTS` makes the whole file idempotent.
-- Run it more than once by accident and nothing breaks.

create extension if not exists vector;
create extension if not exists pgcrypto;

-- Fail loudly rather than silently continuing without the extensions.
-- A bare `select version()` would pass; this cannot.
do $$
begin
  if not exists (select 1 from pg_extension where extname = 'vector') then
    raise exception 'TRAYA setup failed: the vector extension is not installed. Enable pgvector in the Supabase dashboard (Database -> Extensions) and re-run.';
  end if;
  if not exists (select 1 from pg_extension where extname = 'pgcrypto') then
    raise exception 'TRAYA setup failed: the pgcrypto extension is not installed.';
  end if;
end
$$;

-- The `roles` table is seeded by Alembic. The plan calls for `004_seed_roles.sql`
-- to re-seed it from SQL, but that would duplicate the Alembic seed in
-- migrations/versions/56a8e0eed1a8 and create a second source of truth for
-- the permission matrix. It is deliberately NOT done here. The permission
-- matrix is one of the best parts of this codebase and it should keep exactly
-- one place that defines it.
--
-- Verify afterwards:
--   select count(*) from roles;          -- expect 7
--   select count(*) from permissions;    -- expect 18
--
-- ---------------------------------------------------------------------------
-- READ THIS BEFORE ADDING A face_embeddings TABLE
-- ---------------------------------------------------------------------------
-- The migration plan maps `biometric_embeddings` to `face_embeddings` on
-- pgvector. That cannot be done yet, and the reason is not a missing project.
--
-- The application stores no vectors. `biometric_embeddings.embedding_blob` is a
-- `bytea` column holding a Fernet-encrypted numpy array
-- (app/services/identification/registry.py, recognition.py). The bytes are
-- ciphertext. A pgvector column stores plaintext float4, and you cannot insert
-- one into the other.
--
-- So adding `face_embeddings vector(320)` now would create a second, empty
-- table that no code reads, while the real data stayed in an encrypted column
-- that pgvector cannot index or search. That is the "aspirational schema"
-- failure: a table that proves the migration happened without the migration
-- having happened.
--
-- It also collides with a security decision. AGENTS.md section 3.27 states
-- embeddings are encrypted at rest and never returned to clients, and
-- ADR 0005 records that there is no re-encryption migration. Storing
-- plaintext vectors in a searchable column is a real change to that posture,
-- and it belongs to Phase 4 (RLS) where the access model is being decided --
-- not to a schema paste.
--
-- The extension is enabled here so Phase 5 can add the column in one step.
-- Nothing reads it yet, and that is the correct state.
