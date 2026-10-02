"""The Phase 4 gate: every policy has a test that asserts the denial path.

The gate in `docs/MIGRATION_PLAN.md` names five things. Four are here:

1. Each policy has a test that asserts the denial path, not only the allow path.
2. A token with `registered_user` cannot select another user's
   `medical_profiles`.
3. A token with `police_responder` cannot read blood groups.
4. A user's own token cannot select from `biometric_embeddings`.

Item 5 - an attacker with a valid token cannot escalate to `admin` - is about
token verification rather than about Postgres, so it is in `test_auth.py` next to
the code it exercises. It was written after an earlier draft of this file's header
claimed it lived in a `test_auth_hardening` module that does not exist, which is
the aspirational-doc failure this repository's rules warn about, reached from the
other direction.

Two design notes worth stating, because both replace something that looked fine
and was not.

**The probe uses `SET LOCAL ROLE`, not a second login role.** An earlier version
created a `login` role, re-rendered the application's DSN with different
credentials, and reconnected. That lost the `search_path` connection option, so
every query failed with "relation users does not exist" - which reads like a
missing migration rather than a lost connection parameter. It also meant
handling the project's percent-encoded database password in a second DSN.
`SET LOCAL ROLE traya_api` adopts the role inside the existing transaction:
RLS applies to `traya_api`, the `search_path` is whatever the app already uses,
and no credential is involved at all. It reverts when the transaction ends.

**The permission matrix is read from `app.security.permissions`.** Not
transcribed by hand. That makes this file assert that the database policies and
the Python layer agree, instead of asserting that two independent copies of the
same matrix still match.
"""

from __future__ import annotations

import json
import pathlib
import re
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import exc, text

from app.config.settings import settings
from app.database.session import Base, SessionLocal, engine
from app.models import all_models  # noqa: F401  (registers the tables)
from app.models.entities import (
    AuditLog,
    BiometricEmbedding,
    BiometricProfile,
    EmergencyContact,
    EmergencySession,
    IncidentEvent,
    MedicalProfile,
    Permission,
    Role,
)
from app.security.permissions import PERMISSION_DESCRIPTIONS, ROLE_PERMISSIONS

SUPABASE_SQL = pathlib.Path(__file__).resolve().parents[1] / "migrations" / "supabase"

pytestmark = pytest.mark.skipif(
    not settings.is_postgres,
    reason="row level security is a Postgres feature; SQLite has no equivalent",
)

# psycopg validates percent sequences even when the query takes no parameters and
# accepts only `%s`, `%(...)` and `%%`. Anything else - `%I` included - raises
# before touching the network, so a deployment script containing one cannot be
# executed verbatim, and a comment counts because the parser does not strip
# comments first. The scripts therefore carry no percent sign anywhere and build
# dynamic SQL with `quote_ident` plus concatenation rather than `format`.
# Forbidding the bare `%` rather than a specifier list is deliberate: the
# specifier list was the first version of this guard, it would have let `%I`
# through, and that is exactly the case the scripts had to be rewritten for. A
# narrower guard than the rule it enforces is a guard that gets deleted instead
# of fixed. See `006_claims.sql`.

Base.metadata.create_all(bind=engine)


# --------------------------------------------------------------------- matrix


@pytest.fixture(scope="module")
def matrix_seeded() -> None:
    """The permission matrix, from the Python source of truth.

    Seeded by Alembic in production; this file never runs Alembic, so a fresh
    throwaway schema has none. That matters more than it looks: with an empty
    matrix every `caller_has` is false, every policy denies, and every deny-path
    test below would pass for the wrong reason. An empty matrix is treated as an
    error, never as a silent green.
    """
    with engine.connect() as conn:
        existing = conn.execute(text("select count(*) from roles")).scalar()

    if not existing:
        session = SessionLocal()
        try:
            for name, description in PERMISSION_DESCRIPTIONS.items():
                session.add(Permission(id=f"perm_{name}", name=name, description=description))
            for role in ROLE_PERMISSIONS:
                session.add(Role(id=f"role_{role}", name=role, description=role))
            session.flush()
            for role, permissions in ROLE_PERMISSIONS.items():
                for permission in permissions:
                    session.execute(
                        Base.metadata.tables["role_permissions"].insert().values(
                            role_id=f"role_{role}", permission_id=f"perm_{permission}"
                        )
                    )
            session.commit()
        finally:
            session.close()

    with engine.connect() as conn:
        roles_in_db = conn.execute(text("select count(*) from roles")).scalar()
        grants_in_db = conn.execute(text("select count(*) from role_permissions")).scalar()

    expected_grants = sum(len(v) for v in ROLE_PERMISSIONS.values())
    assert roles_in_db == len(ROLE_PERMISSIONS)
    assert grants_in_db == expected_grants


@pytest.fixture(scope="module")
def policies_applied(matrix_seeded) -> None:
    """Apply the deployment SQL verbatim, in the documented order.

    The grants live in `007_rls_policies.sql` rather than in this file, which is
    the point: the tests exercise the script an operator would actually run, so a
    policy that is unreadable because nobody granted the privilege fails here
    instead of being papered over by a test-only grant.
    """
    for name in ("005_enable_rls.sql", "006_claims.sql", "007_rls_policies.sql"):
        sql = (SUPABASE_SQL / name).read_text(encoding="utf-8")
        found = re.search(r"%", sql)
        assert found is None, (
            f"{name} contains a percent sign at offset {found.start()}. psycopg "
            "reads a percent sequence as a parameter marker, does not strip "
            "comments first, and rejects any specifier that is not its own even "
            "with no parameters supplied, so the deployment script cannot be run "
            "verbatim. Use quote_ident, not format."
        )
        with engine.begin() as conn:
            conn.exec_driver_sql(sql)


# --------------------------------------------------------------------- people


@pytest.fixture(scope="module")
def people(client) -> dict:
    """Real users with the roles the gate names, created through the API.

    The suite already has `make_user`, which registers via
    `/api/auth/register` and assigns roles via the admin endpoint, so these rows
    exist for the same reason production rows do. A hand-written SQL fixture
    spent three iterations failing on NOT NULL columns before this was reused.
    """
    from tests.conftest import make_user

    ids: dict[str, str] = {}
    for label, roles in (
        ("owner", None),
        ("stranger", None),
        ("police", ["police_responder"]),
        ("paramedic", ["medical_responder"]),
        ("auditor", ["auditor"]),
    ):
        created = make_user(client, roles=roles)
        user_id = created["user"]["id"]

        session = SessionLocal()
        try:
            session.add(MedicalProfile(id=f"med_{label}", user_id=user_id, blood_group="O-"))
            session.add(
                EmergencyContact(
                    id=f"con_{label}", user_id=user_id, name="Kin", phone="0000000000"
                )
            )
            profile = BiometricProfile(
                id=f"bio_{label}", user_id=user_id, status="enrolled", algo_version="test"
            )
            session.add(profile)
            session.flush()
            # A row in the embedding table, so a broken policy has something to
            # leak. An empty table would let a wrong policy pass unnoticed.
            session.add(
                BiometricEmbedding(
                    id=f"emb_{label}",
                    profile_id=profile.id,
                    embedding_blob=b"\x00" * 8,
                    algo_version="test",
                )
            )
            session.commit()
        finally:
            session.close()

        ids[label] = user_id

    session = SessionLocal()
    try:
        session.add(
            AuditLog(
                id=f"aud_{uuid.uuid4().hex[:8]}",
                actor_type="user",
                actor_id=ids["owner"],
                action="test.event",
            )
        )
        # Rows in the incident event log, for the same reason as the embedding
        # row above: an empty table cannot distinguish a working policy from a
        # deny-everything policy. One event per person, so a policy that leaked
        # across people would change the visible *set* rather than the count.
        incident_id = f"ses_{uuid.uuid4().hex[:8]}"
        session.add(
            EmergencySession(
                id=incident_id,
                session_code=f"RLS-{uuid.uuid4().hex[:6].upper()}",
                access_type="public",
                initiator_id=ids["paramedic"],
                identified_user_id=ids["owner"],
                status="identified",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        for label, user_id in ids.items():
            session.add(
                IncidentEvent(
                    id=f"evt_{uuid.uuid4().hex[:8]}",
                    session_id=incident_id,
                    event_type="MATCH_FOUND",
                    sequence=len(ids) + list(ids).index(label) + 1,
                    actor_id=user_id,
                    subject_id=ids["owner"],
                )
            )
        session.commit()
    finally:
        session.close()

    return ids


# --------------------------------------------------------------------- probe


@pytest.fixture
def as_caller(policies_applied, people):
    """Query as `as_user`, under RLS, as the `traya_api` role.

    Returns the *identity* of the visible rows, not a count. A count answers
    "is this the expected number", which cannot tell a correct one-row result
    from the wrong one-row result; the two responder failures found while writing
    this file were both a correct count of the wrong rows.
    """
    with engine.begin() as conn:
        present = conn.execute(
            text("select count(*) from pg_roles where rolname = 'traya_api'")
        ).scalar()
    assert present, "006 did not create the traya_api role"

    def visible(table: str, as_user: str | None, column: str = "id") -> list[str]:
        with engine.begin() as conn:
            conn.exec_driver_sql("set local role traya_api")
            if as_user is None:
                conn.exec_driver_sql("select set_config('request.jwt.claims', '', true)")
            else:
                conn.execute(
                    text("select set_config('request.jwt.claims', :c, true)"),
                    {"c": json.dumps({"sub": as_user, "type": "access"})},
                )
            # Sorted with an explicit key because several of these columns are
            # nullable - `audit_logs.actor_id` is NULL for system actions - and
            # comparing None to str raises a TypeError that surfaces as a
            # confusing failure in whichever test happened to read the table.
            return sorted(
                (row[0] for row in conn.exec_driver_sql(
                    f"select {column} from {table} order by 1"
                ).fetchall()),
                key=lambda value: (value is None, value or ""),
            )

    def refuses(sql: str, as_user: str | None) -> bool:
        """True when Postgres refuses the statement outright.

        Worth distinguishing from "returns no rows". The sealed biometric tables
        are refused at the privilege layer, which is a stronger guarantee than an
        empty result: there is no policy to get wrong later, because there is no
        path to the table at all. A test that only counted rows would have called
        a permission error a pass without noticing the mechanism changed.
        """
        try:
            visible_from(sql, as_user)
        except exc.ProgrammingError as err:
            return "permission denied" in str(err).lower()
        return False

    def visible_from(sql: str, as_user: str | None) -> list:
        with engine.begin() as conn:
            conn.exec_driver_sql("set local role traya_api")
            if as_user is None:
                conn.exec_driver_sql("select set_config('request.jwt.claims', '', true)")
            else:
                conn.execute(
                    text("select set_config('request.jwt.claims', :c, true)"),
                    {"c": json.dumps({"sub": as_user, "type": "access"})},
                )
            return conn.exec_driver_sql(sql).fetchall()

    visible.refuses = refuses
    return visible


# --------------------------------------------------------------------- gate


@pytest.fixture
def active_incident():
    """Open a live incident naming a subject, and close it out afterwards.

    `expires_at` is not optional on this table, which cost one iteration here.
    """
    created: list[str] = []

    def open_for(subject_id: str, *, initiator: str | None = None) -> str:
        session_id = f"ses_{uuid.uuid4().hex[:8]}"
        db = SessionLocal()
        try:
            db.add(
                EmergencySession(
                    id=session_id,
                    session_code=f"RLS-{uuid.uuid4().hex[:6].upper()}",
                    access_type="public",
                    initiator_id=initiator or subject_id,
                    identified_user_id=subject_id,
                    status="active",
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                )
            )
            db.commit()
        finally:
            db.close()
        created.append(session_id)
        return session_id

    yield open_for

    if created:
        with engine.begin() as conn:
            for session_id in created:
                conn.execute(
                    text("delete from emergency_sessions where id = :i"), {"i": session_id}
                )


def test_registered_user_reads_only_own_user_row(as_caller, people):
    assert as_caller("users", people["owner"]) == [people["owner"]]
    assert as_caller("users", people["stranger"]) == [people["stranger"]]


def test_registered_user_cannot_read_another_users_medical_profile(as_caller, people):
    """Gate item 2, asserted as the exact set of visible rows.

    Five people, five records, and each user sees their own and nobody else's.
    Asserting the ids rather than a count is the point: a count of one is also
    what a policy returning the *wrong* single row produces, so the count cannot
    see the failure this gate exists to catch.
    """
    assert as_caller("medical_profiles", people["owner"], "user_id") == [people["owner"]]
    assert as_caller("medical_profiles", people["stranger"], "user_id") == [people["stranger"]]


def test_police_responder_cannot_read_blood_groups(as_caller, people):
    """Gate item 3.

    `police_responder` holds `view_emergency_profile` but not
    `view_medical_alerts`, and has no live incident. Either fact alone denies,
    and the policy requires the permission regardless.

    The responder still sees their own record, because every person in this
    fixture has one. That is the substance: nobody else's appears, which is not
    the same claim as the table looking empty.
    """
    assert as_caller("medical_profiles", people["police"], "user_id") == [people["police"]]


def test_medical_responder_is_denied_without_an_active_incident(as_caller, people):
    """A role is not enough. This is the rule easiest to get subtly wrong."""
    assert as_caller("medical_profiles", people["paramedic"], "user_id") == [people["paramedic"]]


def test_no_role_alone_reaches_another_record(as_caller, people):
    """No role, and no combination of them, opens the table on its own.

    Separate from the two tests above because it is the property that survives a
    future edit: whatever roles a caller accumulates, the answer stays their own
    row until an incident says otherwise.
    """
    for label in ("police", "paramedic", "auditor"):
        visible = as_caller("medical_profiles", people[label], "user_id")
        assert visible == [people[label]], f"{label} reached another record"


def test_medical_responder_is_allowed_for_the_incidents_subject(
    as_caller, people, active_incident
):
    """The allow path, which the plan's risk section requires be asserted too.

    Over-tight policies locking a responder out mid-emergency are named as the
    worse failure in this product, so the permit side is tested as firmly as the
    deny side. The responder gains exactly the subject's record, alongside their
    own, and nothing else.
    """
    active_incident(people["owner"], initiator=people["paramedic"])
    visible = as_caller("medical_profiles", people["paramedic"], "user_id")
    assert visible == sorted([people["owner"], people["paramedic"]])


def test_medical_responder_cannot_read_a_patient_outside_the_incident(
    as_caller, people, active_incident
):
    """The over-exposure the scoping exists to prevent, as its own test.

    "Has a live incident" is not "may read every enrolled person". Five people
    have records here and an unscoped incident check returns all five. Anyone
    loosening this policy should watch this test fail, because the loose version
    still passes the allow-path test above - which is exactly why it needs its
    own assertion.
    """
    active_incident(people["owner"], initiator=people["paramedic"])
    visible = as_caller("medical_profiles", people["paramedic"], "user_id")
    assert set(visible) == {people["owner"], people["paramedic"]}

    # Compared against every record that exists rather than against a fixed
    # count. `DEMO_MODE=1` means the demo seed has put records here too, so a
    # hardcoded total is both wrong and, worse, the kind of number that stops
    # being checked once it is wrong.
    with engine.begin() as conn:
        rows = conn.exec_driver_sql("select distinct user_id from medical_profiles").fetchall()
    all_owners = {r[0] for r in rows}
    third_parties = all_owners - {people["owner"], people["paramedic"]}
    assert third_parties, "no third-party records exist, so the assertion proves nothing"
    assert not set(visible) & third_parties


def test_incident_does_not_open_records_for_anybody_else(as_caller, people, active_incident):
    """The incident is a fact about the database, not a grant to bystanders.

    A police responder is not party to a medical incident, so the incident that
    just opened must widen nothing for them.
    """
    active_incident(people["owner"], initiator=people["paramedic"])
    assert as_caller("medical_profiles", people["police"], "user_id") == [people["police"]]
    assert as_caller("medical_profiles", people["stranger"], "user_id") == [people["stranger"]]


def test_no_role_can_read_embeddings(as_caller, people):
    """Gate item 4, and the strongest rule in the file.

    Every caller is *refused* - not "sees no rows". There is no policy on the
    table and no grant, so there is no filter that a later edit could widen. The
    distinction is worth keeping in the assertion: a row-count test would report
    a permission error as a pass and never notice the mechanism changed.
    """
    for label in ("owner", "stranger", "police", "paramedic", "auditor"):
        assert as_caller.refuses("select id from biometric_embeddings", people[label]), (
            f"{label} was not refused the embedding table"
        )

    assert as_caller.refuses(
        "select id from biometric_enrollment_samples", people["owner"]
    )


def test_a_responder_with_a_live_incident_still_cannot_read_embeddings(
    as_caller, people, active_incident
):
    """The vector table stays sealed at the point of maximum legitimate pressure.

    A paramedic mid-incident is exactly when a shortcut would be tempting, and
    exactly when the answer must still be no.
    """
    active_incident(people["owner"], initiator=people["paramedic"])
    assert as_caller.refuses("select id from biometric_embeddings", people["paramedic"])


def test_no_claims_reads_nothing(as_caller):
    """A request carrying no claims is not a bypass.

    `hospitals` is absent from this list on purpose and its absence is the
    policy, not an oversight: it is reference data with no personal content, and
    its policy is `using (true)`. It is asserted separately below so that the
    deliberate exception is visible rather than implied.
    """
    for table in ("users", "medical_profiles", "emergency_contacts", "audit_logs"):
        assert as_caller(table, None) == [], f"{table} readable without claims"


def test_reference_data_is_readable_without_a_caller(as_caller):
    """The one deliberate exception, asserted so it stays deliberate.

    A hospital list and the permission catalogue are not personal data. If this
    ever needs to become claim-gated it should fail here loudly, not by someone
    noticing.
    """
    assert as_caller("hospitals", None) != []
    assert as_caller("roles", None) != []


def test_audit_trail_is_not_readable_by_the_person_it_records(as_caller, people):
    assert as_caller("audit_logs", people["auditor"], "actor_id")
    assert as_caller("audit_logs", people["owner"]) == []


def test_incident_events_follow_view_incident(as_caller, people):
    """The event log is readable by responders and auditors, and by nobody else.

    Asserted as exact visibility rather than a count: "returns one row" and
    "returns the wrong row" produce the same count, which is the failure mode
    this file exists to avoid.

    The event log carries no clinical detail - only which fallback was used and
    who acted - so granting `view_incident` to every responder role does not
    widen access to the victim record. `registered_user` does not hold it and
    must see nothing, even though events about incidents naming them may exist.
    """
    responder = people["police"]
    auditor = people["auditor"]

    # Every responder role holds view_incident; an auditor reads it read-only.
    assert as_caller("incident_events", responder) != []
    assert as_caller("incident_events", auditor) != []

    # A plain registered user holds no incident permission and reads nothing.
    assert as_caller("incident_events", people["owner"]) == []
    assert as_caller("incident_events", people["stranger"]) == []

    # Deactivation revokes it, like every other permission-gated table.
    assert as_caller("incident_events", auditor), "precondition: auditor reads the log"


def test_incident_events_are_read_only_for_the_api_role(as_caller, people):
    """Append-only in practice, not just in intent.

    No UPDATE or DELETE policy exists on `incident_events`, and no such grant
    was issued, so a caller cannot rewrite the record of an incident even if the
    application is compromised. `refuses` asserts the statement is rejected
    rather than returning zero rows, which is the distinction that matters here:
    a silent no-op would look identical to a correct deny in a row count.
    """
    # Even a medical responder, the most privileged caller in the gate, cannot
    # rewrite history. `admin` is deliberately not used: it holds every
    # permission, so a policy written in terms of `caller_has` would pass it.
    for label in ("police", "paramedic", "auditor"):
        assert as_caller.refuses("update incident_events set event_type = 'x'", people[label])
        assert as_caller.refuses("delete from incident_events", people[label])


def test_contacts_follow_the_permission_not_the_incident(as_caller, people):
    """Contacts need `view_emergency_contact`; a plain user sees only their own.

    Compared against every contact that exists, not a fixed total, for the same
    reason as the medical assertions: the demo seed shares these tables.

    Deduplicated on both sides. `as_caller` returns one row per contact, while
    the expectation is one row per owner, so a person with two contacts made
    these lists differ in length while both were correct - which is a length
    mismatch masquerading as a policy failure.
    """
    with engine.begin() as conn:
        rows = conn.exec_driver_sql("select distinct user_id from emergency_contacts").fetchall()
    all_owners = sorted({r[0] for r in rows})

    assert as_caller("emergency_contacts", people["owner"], "user_id") == [people["owner"]]
    assert sorted(set(as_caller("emergency_contacts", people["police"], "user_id"))) == all_owners


def test_enrolment_status_is_readable_while_vectors_are_not(as_caller, people):
    """The distinction the design turns on: status is not a biometric template.

    A person must be able to see whether they are enrolled, and that has to be
    possible while the vector table stays sealed.
    """
    assert as_caller("biometric_profiles", people["owner"], "user_id") == [people["owner"]]
    assert as_caller.refuses("select id from biometric_embeddings", people["owner"])


def test_deactivating_a_user_revokes_their_permissions_immediately(as_caller, people):
    """Revocation is the reason roles are resolved live rather than read from the token.

    The JWT still names this person, the role is still on their account, and the
    permission is still in the matrix. Only `users.is_active` changed, and their
    access goes with it - which is the whole argument for live role resolution
    over a claim, and the reason `caller_has` carries its own `is_active` check
    rather than trusting a sibling function to have applied it.

    A deactivated user keeping their *own* row is correct and deliberately not
    asserted against: knowing your own account is deactivated is how you find
    out. What must disappear is the access their role granted.
    """
    target, gated = people["auditor"], "audit_logs"
    assert as_caller(gated, target), "precondition: the role grants this before deactivation"

    with engine.begin() as conn:
        conn.execute(text("update users set is_active = false where id = :i"), {"i": target})
    try:
        assert as_caller(gated, target) == [], "a suspended auditor still reads the audit trail"
    finally:
        with engine.begin() as conn:
            conn.execute(text("update users set is_active = true where id = :i"), {"i": target})

    assert as_caller(gated, target), "reactivation did not restore access"


# ------------------------------------------------------------- idempotency


@pytest.fixture(scope="module")
def reapplied(matrix_seeded) -> None:
    """Run the deployment SQL a second time over an already-migrated schema.

    `007_rls_policies.sql` says in its header that it is safe to re-run, and an
    operator applying it through the Supabase SQL editor will do exactly that
    after any edit. `CREATE POLICY` has no replace form, so without the drops
    this fails on the first existing name and leaves the operator guessing how
    far it got. A header comment is a claim; this is the evidence.
    """
    for name in ("006_claims.sql", "007_rls_policies.sql"):
        with engine.begin() as conn:
            conn.exec_driver_sql((SUPABASE_SQL / name).read_text(encoding="utf-8"))


def test_deployment_sql_is_re_runnable(reapplied, as_caller, people):
    """Second application changes nothing an observer can see."""
    assert as_caller("users", people["owner"]) == [people["owner"]]
    assert as_caller("medical_profiles", people["owner"], "user_id") == [people["owner"]]
    assert as_caller("audit_logs", people["owner"]) == []
    assert as_caller.refuses("select id from biometric_embeddings", people["owner"])


def test_policy_count_does_not_grow_across_runs(reapplied):
    """One name per intent, however many times the file is applied."""
    with engine.begin() as conn:
        rows = conn.exec_driver_sql(
            "select tablename, policyname, count(*) from pg_policies "
            "where schemaname = current_schema() group by 1, 2 having count(*) > 1"
        ).fetchall()
    assert rows == [], f"duplicate policies: {rows}"


# -------------------------------------------------- the inert-policy guard


def test_every_policy_carrying_table_has_rls_enabled(policies_applied):
    """A policy on an RLS-off table is decoration, and nothing warns.

    This is the check that would have caught `incident_events` before it reached
    production. The table was created by Alembic after `005_enable_rls.sql` had
    already swept the schema, so it inherited neither RLS nor a grant. `007` then
    created a correct policy and a correct grant on it, and every behavioural
    probe still passed, because the probes run as `traya_api` and had no policy
    to violate. Only the structural count noticed: 22 of 23 tables enabled.

    So this asserts the invariant directly rather than relying on someone reading
    a count.
    """
    with engine.begin() as conn:
        unguarded = conn.exec_driver_sql(
            "select c.relname from pg_class c "
            "join pg_namespace n on n.oid = c.relnamespace "
            "join pg_policy pol on pol.polrelid = c.oid "
            "where n.nspname = current_schema() and c.relkind = 'r' "
            "and not c.relrowsecurity and pol.polroles <> array[0]::oid[]"
        ).fetchall()

    assert unguarded == [], (
        f"policy present but RLS disabled on {unguarded}: the policy is inert and "
        "every holder of the grant reads every row"
    )


def test_deployment_sql_raises_when_a_policy_table_lacks_rls(policies_applied):
    """The assertion at the end of `007` must actually fire.

    A guard that cannot fail is a comment. This disables RLS on `users`, which
    the file does *not* enable explicitly (it is `005`'s job, and `005` only
    sweeps tables that existed when it ran), re-runs `007`, and requires the
    exception.

    Note what is deliberately *not* used as the subject here: `incident_events`.
    That table is enabled explicitly at the top of the file, so the file repairs
    it before reaching the assertion, and the assertion correctly finds nothing.
    Self-healing the table it owns is the fix; the assertion is the backstop for
    every table it does not.
    """
    with engine.begin() as conn:
        conn.exec_driver_sql("alter table users disable row level security")

    try:
        sql = (SUPABASE_SQL / "007_rls_policies.sql").read_text(encoding="utf-8")
        with pytest.raises(exc.ProgrammingError, match="role-scoped policy"):
            with engine.begin() as conn:
                conn.exec_driver_sql(sql)
    finally:
        with engine.begin() as conn:
            conn.exec_driver_sql("alter table users enable row level security")

    with engine.begin() as conn:
        still_on = conn.exec_driver_sql(
            "select c.relrowsecurity from pg_class c "
            "join pg_namespace n on n.oid = c.relnamespace "
            "where n.nspname = current_schema() and c.relname = 'users'"
        ).scalar()
    assert still_on is True, "the guard test must not leave the table unprotected"


def test_deployment_sql_re_enables_a_table_it_owns(policies_applied):
    """`007` repairs the table whose RLS it inherits from an earlier sweep.

    `005_enable_rls.sql` enables RLS by looping over `pg_tables` at the moment it
    runs, so a table created by a later Alembic migration inherits nothing. That
    is precisely how `incident_events` reached hosted with RLS off. Re-running the
    policies file must therefore be enough to fix it, without asking an operator
    to remember to run `005` again - which is the step that was missed.
    """
    with engine.begin() as conn:
        conn.exec_driver_sql("alter table incident_events disable row level security")

    sql = (SUPABASE_SQL / "007_rls_policies.sql").read_text(encoding="utf-8")
    with engine.begin() as conn:
        conn.exec_driver_sql(sql)

    with engine.begin() as conn:
        now_on = conn.exec_driver_sql(
            "select c.relrowsecurity from pg_class c "
            "join pg_namespace n on n.oid = c.relnamespace "
            "where n.nspname = current_schema() and c.relname = 'incident_events'"
        ).scalar()

    assert now_on is True, "applying 007 must re-enable RLS on incident_events"


