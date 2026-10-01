-- 007: row level security policies for a client-facing role.
--
-- Run AFTER `005_enable_rls.sql` and `006_claims.sql`.
--
-- ---------------------------------------------------------------- what this
-- does and does not cover
-- These policies are attached to `traya_api`, a NOLOGIN role created in
-- `006_claims.sql`. They do not govern TRAYA's own traffic: the application
-- connects as `postgres`, which owns these tables and is exempt from its own
-- policies without `FORCE ROW LEVEL SECURITY`. That is the migration plan's
-- item 5, "service-role connection for writes, scoped by permission in Python".
--
-- So this is a real barrier for any path that is not the application's own
-- connection - a browser client, the Supabase SDK, a future service - and it is
-- not a replacement for the Python permission matrix. Both layers exist. The
-- test suite proves the barrier holds; it cannot prove the app depends on it,
-- because the app does not.
--
-- ---------------------------------------------------------------- grants are
-- part of the policy
-- A policy filters rows. It does not grant the privilege to read them, and
-- schema `USAGE` has to come before a table grant means anything at all. Without
-- both, `traya_api` reads zero rows for the undignified reason that it cannot
-- reach the table, and "no leakage" stops being evidence of a working barrier.
-- That is not hypothetical: an early version of this file had no grants at all,
-- and the first symptom was `current_schema()` returning NULL after a role
-- switch, which reads like a missing migration rather than a missing grant.
--
-- Every grant is revoked as well as given, so re-running this file converges
-- rather than accumulates.
--
-- `current_schema()` rather than a literal `public`. This file is applied to
-- hosted `public` and to the test suite's throwaway schema; a hardcoded schema
-- silently grants the wrong one. `quote_ident` rather than `format` with a
-- percent specifier, because psycopg rejects percent sequences it does not own
-- even when the query takes no parameters. See `006_claims.sql`.
--
-- ---------------------------------------------------------------- three rules
-- carry the weight, from TARGET_ARCHITECTURE.md
--
-- 1. No policy grants any role direct read of the embedding tables. A stolen
--    token must not exfiltrate biometrics, so the vectors are unreadable to
--    everyone, including `admin`. Enrolment *status* lives in
--    `biometric_profiles` and stays readable; the vectors do not.
-- 2. Responder access to clinical data needs a live incident, not just a role -
--    and it is scoped to the incident's identified subject. See
--    `traya_auth.subject_in_active_incident`.
-- 3. A user sees their own rows and nobody else's.
--
-- Role-to-permission grants come from the seeded `role_permissions` table, so
-- this file and `app/security/permissions.py` cannot disagree: both read the
-- same matrix. Note what that matrix already gets right for the gate -
-- `police_responder` holds `view_emergency_profile` but NOT
-- `view_medical_alerts`, so rule 2 denies a police responder blood groups
-- without this file inventing a rule.
--
-- ---------------------------------------------------------------- idempotent
-- by construction
-- `CREATE POLICY` has no `OR REPLACE`, so a second run of this file fails on the
-- first existing name and the operator is left guessing how far it got. Every
-- policy is dropped first, in its own statement, so a re-run is a no-op. That is
-- also why this file is safe to apply by hand in the Supabase SQL editor, which
-- is how it reached the hosted project.
--
-- No percent signs, including in comments. psycopg reads each one as a parameter
-- marker and does not strip comments. See `005_enable_rls.sql`.

-- ---------------------------------------------------------------- grants
do $$
declare
    target text := current_schema();

    readable text[] := array[
        'users',
        'medical_profiles',
        'emergency_contacts',
        'biometric_profiles',
        'biometric_enrollments',
        'emergency_sessions',
        'audit_logs',
        'hospitals',
        'roles',
        'permissions'
    ];

    sealed text[] := array[
        'biometric_embeddings',
        'biometric_enrollment_samples'
    ];

    t text;
begin
    -- No usage, no tables. See the header.
    execute 'grant usage on schema ' || quote_ident(target) || ' to traya_api';

    foreach t in array readable loop
        execute 'revoke all on table ' || quote_ident(target) || '.' || quote_ident(t)
             || ' from traya_api';
        execute 'grant select on table ' || quote_ident(target) || '.' || quote_ident(t)
             || ' to traya_api';
    end loop;

    -- Writes only where a policy exists for them, so a granted privilege is
    -- never wider than the row filter behind it.
    execute 'grant update on table ' || quote_ident(target) || '.users to traya_api';
    execute 'grant insert, update, delete on table ' || quote_ident(target)
         || '.medical_profiles to traya_api';
    execute 'grant insert, update, delete on table ' || quote_ident(target)
         || '.emergency_contacts to traya_api';
    execute 'grant delete on table ' || quote_ident(target)
         || '.biometric_enrollments to traya_api';
    execute 'grant update on table ' || quote_ident(target)
         || '.emergency_sessions to traya_api';

    -- Rule 1. Revoked explicitly rather than merely omitted from `readable`, so
    -- a table that was once readable cannot stay readable across a re-run.
    foreach t in array sealed loop
        execute 'revoke all on table ' || quote_ident(target) || '.' || quote_ident(t)
             || ' from traya_api';
    end loop;
end
$$;

-- ---------------------------------------------------------------- users
drop policy if exists users_select_own on users;
create policy users_select_own on users
    for select to traya_api
    using (id = traya_auth.caller_id() or traya_auth.caller_has('manage_users'));

drop policy if exists users_update_own on users;
create policy users_update_own on users
    for update to traya_api
    using (id = traya_auth.caller_id() or traya_auth.caller_has('manage_users'))
    with check (id = traya_auth.caller_id() or traya_auth.caller_has('manage_users'));

-- ---------------------------------------------------------------- medical
-- profiles
-- Rule 2, and the sharpest edge in the file. The responder branch requires the
-- permission AND that this row's owner is the identified subject of a live
-- incident the caller is party to.
--
-- It is tempting to write `caller_has('view_medical_alerts') and
-- in_active_incident()` here, and that is a real data-exposure bug wearing a
-- plausible shape: it would hand every responder with any open incident the
-- blood group of every enrolled person in the system, for as long as the
-- incident stayed open. The test asserts the responder sees one record, not all
-- of them.
drop policy if exists medical_select on medical_profiles;
create policy medical_select on medical_profiles
    for select to traya_api
    using (
        user_id = traya_auth.caller_id()
        or traya_auth.caller_has('manage_users')
        or (
            traya_auth.caller_has('view_medical_alerts')
            and traya_auth.subject_in_active_incident(user_id)
        )
    );

drop policy if exists medical_insert_own on medical_profiles;
create policy medical_insert_own on medical_profiles
    for insert to traya_api
    with check (user_id = traya_auth.caller_id() or traya_auth.caller_has('manage_users'));

drop policy if exists medical_update on medical_profiles;
create policy medical_update on medical_profiles
    for update to traya_api
    using (user_id = traya_auth.caller_id()
           or traya_auth.caller_has('manage_users')
           or (traya_auth.caller_has('view_medical_alerts')
               and traya_auth.subject_in_active_incident(user_id)))
    with check (user_id = traya_auth.caller_id() or traya_auth.caller_has('manage_users'));

drop policy if exists medical_delete_own on medical_profiles;
create policy medical_delete_own on medical_profiles
    for delete to traya_api
    using (user_id = traya_auth.caller_id() or traya_auth.caller_has('manage_users'));

-- ---------------------------------------------------------------- contacts
-- Contacts are reachable by a responder holding `view_emergency_contact`
-- without an active-incident condition: the target design scopes these to
-- the permission alone, and during an incident the session may not be the
-- caller's own.
drop policy if exists contacts_select on emergency_contacts;
create policy contacts_select on emergency_contacts
    for select to traya_api
    using (
        user_id = traya_auth.caller_id()
        or traya_auth.caller_has('view_emergency_contact')
        or traya_auth.caller_has('manage_users')
    );

drop policy if exists contacts_insert_own on emergency_contacts;
create policy contacts_insert_own on emergency_contacts
    for insert to traya_api
    with check (user_id = traya_auth.caller_id() or traya_auth.caller_has('manage_users'));

drop policy if exists contacts_update_own on emergency_contacts;
create policy contacts_update_own on emergency_contacts
    for update to traya_api
    using (user_id = traya_auth.caller_id() or traya_auth.caller_has('manage_users')
           or traya_auth.caller_has('view_emergency_contact'))
    with check (user_id = traya_auth.caller_id() or traya_auth.caller_has('manage_users'));

drop policy if exists contacts_delete_own on emergency_contacts;
create policy contacts_delete_own on emergency_contacts
    for delete to traya_api
    using (user_id = traya_auth.caller_id() or traya_auth.caller_has('manage_users'));

-- ---------------------------------------------------------------- biometrics
-- Rule 1. There is deliberately no policy on `biometric_embeddings` or
-- `biometric_enrollment_samples` for any role, so RLS denies every statement
-- and the tables are unreadable through this path entirely. Grants are revoked
-- too: a policy without a grant is not a barrier, and a grant without a policy
-- would be a mistake waiting to happen.
--
-- Enrolment *status* is not a biometric template, so it stays readable: a
-- person needs to know whether they are enrolled, and a responder needs to know
-- whether a subject has usable biometrics.
drop policy if exists profile_select on biometric_profiles;
create policy profile_select on biometric_profiles
    for select to traya_api
    using (user_id = traya_auth.caller_id() or traya_auth.caller_has('manage_users'));

drop policy if exists enrollment_select_own on biometric_enrollments;
create policy enrollment_select_own on biometric_enrollments
    for select to traya_api
    using (user_id = traya_auth.caller_id() or traya_auth.caller_has('manage_users'));

-- A person may delete their own enrolment, which is the withdrawal path for
-- biometric data. Deleting the enrolment leaves the encrypted vectors in place
-- and that is handled by the service, not by this policy.
drop policy if exists enrollment_delete_own on biometric_enrollments;
create policy enrollment_delete_own on biometric_enrollments
    for delete to traya_api
    using (user_id = traya_auth.caller_id() or traya_auth.caller_has('manage_users'));

-- ---------------------------------------------------------------- incidents
drop policy if exists sessions_select on emergency_sessions;
create policy sessions_select on emergency_sessions
    for select to traya_api
    using (
        initiator_id = traya_auth.caller_id()
        or identified_user_id = traya_auth.caller_id()
        or traya_auth.caller_has('create_incident')
        or traya_auth.caller_has('manage_users')
    );

drop policy if exists sessions_update_own on emergency_sessions;
create policy sessions_update_own on emergency_sessions
    for update to traya_api
    using (initiator_id = traya_auth.caller_id() or traya_auth.caller_has('update_incident'))
    with check (initiator_id = traya_auth.caller_id() or traya_auth.caller_has('update_incident'));

-- ---------------------------------------------------------------- audit
-- Denied to everyone except a role holding `view_audit_logs`, which today is
-- `auditor` and `admin`. No owner path: a person's own actions are not readable
-- by that person.
drop policy if exists audit_select on audit_logs;
create policy audit_select on audit_logs
    for select to traya_api
    using (traya_auth.caller_has('view_audit_logs'));

-- ---------------------------------------------------------------- reference
-- data with no personal content, needed for the hospital picker and the
-- threshold view.
drop policy if exists hospitals_select on hospitals;
create policy hospitals_select on hospitals
    for select to traya_api
    using (true);

drop policy if exists roles_read on roles;
create policy roles_read on roles
    for select to traya_api
    using (true);

drop policy if exists permissions_read on permissions;
create policy permissions_read on permissions
    for select to traya_api
    using (true);
