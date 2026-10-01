"""Apply 006/007 to the hosted project and verify the barrier as a non-owner.

Three properties of this script are deliberate and worth stating, because the
obvious simpler version of each is wrong.

**The probe is a real `LOGIN` role, not `SET LOCAL ROLE`.** The test suite can
`SET LOCAL ROLE` because its connection is a local superuser. The hosted
application role is not a superuser and is deliberately not a member of
`traya_api` - granting it that membership would hand the application a second,
narrower identity to confuse the picture with. So the probe gets its own
throwaway `LOGIN` role, granted `traya_api`, dropped at the end. That is the only
honest way to check a non-owner path on a project where you do not hold
superuser.

**The one write is reversible and pre-cleaned.** Verifying the incident allow
path needs a live `emergency_sessions` row, and the probe role has no business
inserting one. The row is written by the owner connection, with a fixed id, and
removed in a `finally`. The same id is deleted before the insert, so a previous
run that died mid-way leaves nothing behind on the next one.

**Nothing here is a test of the Python layer.** The application connects as the
table owner and bypasses these policies entirely, by design. What is verified
here is the deployed SQL, against real rows, through a role that does not own
them.
"""
import pathlib
import secrets
import sys
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ProgrammingError

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.config.settings import settings  # noqa: E402

SQL = pathlib.Path(__file__).resolve().parents[1] / "migrations" / "supabase"

owner_engine = create_engine(settings.DATABASE_URL)

REGISTERED = "b5af2c56-97ee-4ad3-9727-b70fe8d66b44"
OTHER_REGISTERED = "74f28b2d-c732-47d9-a733-07273b2c8c18"
MEDICAL = "e6140a6c-aa67-405e-9adb-76b8add27422"
POLICE = "6c6037fc-5dd6-4e54-8308-e48b5ed64c44"
AUDITOR = "5ec5852a-9b94-4445-9beb-66acd3f78f4c"

PROBE_ROLE = f"traya_rls_probe_{uuid.uuid4().hex[:8]}"
PROBE_PASSWORD = secrets.token_urlsafe(24)
PROBE_SESSION_ID = "ses_rlsprobe"

failures: list[str] = []


def check(label: str, got, want) -> None:
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: got {got!r}, want {want!r}")
    if not ok:
        failures.append(label)


def check_true(label: str, value) -> None:
    check(label, bool(value), True)


print("== applying 006 and 007 ==")
for name in ("006_claims.sql", "007_rls_policies.sql"):
    with owner_engine.begin() as conn:
        conn.exec_driver_sql((SQL / name).read_text(encoding="utf-8"))
    print(f"  applied {name}")

print("== removing helpers the current 006 no longer creates ==")
with owner_engine.begin() as conn:
    for fn in ("caller_roles", "in_active_incident"):
        conn.exec_driver_sql(f"drop function if exists traya_auth.{fn}()")
        print(f"  dropped traya_auth.{fn}()")

print(f"== creating probe role {PROBE_ROLE} ==")
with owner_engine.begin() as conn:
    conn.exec_driver_sql(f'create role {PROBE_ROLE} login password \'{PROBE_PASSWORD}\'')
    conn.exec_driver_sql(f"grant traya_api to {PROBE_ROLE}")

url = make_url(settings.DATABASE_URL)

# Supabase's transaction pooler routes on the username, which has to carry the
# tenant: `postgres.<project-ref>`. Connecting as a bare role name fails with
# "no tenant identifier provided" before authentication is even attempted, which
# looks like a network problem and is not one. The ref is taken from the
# application's own URL rather than hardcoded.
username = url.username or ""
ref = username.split(".", 1)[1] if "." in username else None
if not ref:
    print("FATAL: could not derive the project ref from DATABASE_URL's username")
    sys.exit(1)

probe_engine = create_engine(
    url.set(username=f"{PROBE_ROLE}.{ref}", password=PROBE_PASSWORD).render_as_string(
        hide_password=False
    )
)


def _as(conn, subject: str | None) -> None:
    if subject is None:
        conn.exec_driver_sql("select set_config('request.jwt.claims', '', true)")
    else:
        conn.execute(
            text("select set_config('request.jwt.claims', :c, true)"),
            {"c": '{"sub": "%s", "type": "access"}' % subject},
        )


def visible(table: str, subject: str | None, column: str = "id") -> list:
    with probe_engine.begin() as conn:
        _as(conn, subject)
        return sorted(
            (r[0] for r in conn.exec_driver_sql(f"select {column} from {table}").fetchall()),
            key=lambda v: (v is None, v or ""),
        )


def refused(sql: str, subject: str | None) -> bool:
    try:
        with probe_engine.begin() as conn:
            _as(conn, subject)
            conn.exec_driver_sql(sql)
        return False
    except ProgrammingError as err:
        return "permission denied" in str(err).lower()


try:
    print("\n== identity: a user sees their own row only ==")
    check("users as registered user", visible("users", REGISTERED), [REGISTERED])
    check("users as another registered user", visible("users", OTHER_REGISTERED), [OTHER_REGISTERED])

    print("\n== clinical: a role alone reaches nobody else's record ==")
    # Stated as "nobody else's" rather than as an exact set. The demo responder
    # accounts have no medical profile of their own, so the honest claim is not
    # "sees exactly one row" - it is "sees no row that is not theirs". An exact
    # expectation here would be asserting a fact about the demo seed.
    for label, who in (("police_responder", POLICE), ("medical_responder", MEDICAL)):
        got = visible("medical_profiles", who, "user_id")
        check_true(f"{label} reaches no other person's record", set(got) <= {who})

    print("\n== clinical: the incident opens exactly the subject ==")
    with owner_engine.connect() as conn:
        subject_has_record = conn.execute(
            text("select count(*) from medical_profiles where user_id = :i"),
            {"i": REGISTERED},
        ).scalar()
    check_true(
        "precondition: the incident subject has a medical record",
        subject_has_record,
    )

    with owner_engine.begin() as conn:
        conn.execute(
            text("delete from emergency_sessions where id = :i"), {"i": PROBE_SESSION_ID}
        )
        conn.execute(
            text(
                "insert into emergency_sessions "
                "(id, session_code, access_type, initiator_id, identified_user_id, "
                "status, created_at, expires_at, identification_method) "
                "values (:i, 'RLSPROBE', 'public', :me, :them, 'active', "
                "now(), now() + interval '1 hour', '[]'::json)"
            ),
            {"i": PROBE_SESSION_ID, "me": MEDICAL, "them": REGISTERED},
        )
    try:
        got = visible("medical_profiles", MEDICAL, "user_id")
        check_true("the incident subject is now readable", REGISTERED in got)
        check_true(
            "and nobody else is", set(got) <= {REGISTERED, MEDICAL}
        )
        check_true(
            "police, not party to the incident, gains nothing",
            set(visible("medical_profiles", POLICE, "user_id")) <= {POLICE},
        )
        check_true(
            "plain registered user, not party, gains nothing",
            set(visible("medical_profiles", REGISTERED, "user_id")) <= {REGISTERED},
        )
    finally:
        with owner_engine.begin() as conn:
            conn.execute(
                text("delete from emergency_sessions where id = :i"), {"i": PROBE_SESSION_ID}
            )
        print("  removed the probe session")

    print("\n== biometrics: sealed at the privilege layer ==")
    for label, who in (
        ("registered user", REGISTERED),
        ("medical responder", MEDICAL),
        ("police responder", POLICE),
        ("auditor", AUDITOR),
    ):
        check(
            f"biometric_embeddings refused to {label}",
            refused("select id from biometric_embeddings", who),
            True,
        )
    check(
        "biometric_enrollment_samples refused",
        refused("select id from biometric_enrollment_samples", REGISTERED),
        True,
    )

    print("\n== status readable, vectors not ==")
    check_true(
        "biometric_profiles as the record's owner",
        visible("biometric_profiles", REGISTERED, "user_id") == [REGISTERED],
    )

    print("\n== audit ==")
    check_true("auditor can read audit_logs", visible("audit_logs", AUDITOR))
    check("a plain user cannot read the audit trail", visible("audit_logs", REGISTERED), [])

    print("\n== no claims is not a bypass ==")
    for table in ("users", "medical_profiles", "emergency_contacts", "audit_logs"):
        check(f"{table} with no claims", visible(table, None), [])

    print("\n== the one deliberate exception ==")
    check_true("hospitals readable with no claims", visible("hospitals", None))
    check_true("roles readable with no claims", visible("roles", None))

    print("\n== a deactivated account loses its permissions ==")
    with owner_engine.begin() as conn:
        conn.execute(
            text("update users set is_active = false where id = :i"), {"i": AUDITOR}
        )
    try:
        check("suspended auditor loses the audit trail", visible("audit_logs", AUDITOR), [])
    finally:
        with owner_engine.begin() as conn:
            conn.execute(
                text("update users set is_active = true where id = :i"), {"i": AUDITOR}
            )
    check_true("auditor access restored", visible("audit_logs", AUDITOR))

    print("\n== structural checks ==")
    with owner_engine.connect() as conn:
        check(
            "no duplicate policies",
            conn.exec_driver_sql(
                "select tablename, policyname, count(*) from pg_policies "
                "where schemaname = current_schema() group by 1, 2 having count(*) > 1"
            ).fetchall(),
            [],
        )
        rls = conn.exec_driver_sql(
            "select count(*) from pg_tables where schemaname = current_schema() and rowsecurity"
        ).scalar()
        total = conn.exec_driver_sql(
            "select count(*) from pg_tables where schemaname = current_schema()"
        ).scalar()
        check(f"rowsecurity on every table ({rls}/{total})", rls, total)
        check(
            "helpers present, table readers SECURITY DEFINER",
            sorted(
                conn.exec_driver_sql(
                    "select p.proname, p.prosecdef from pg_proc p "
                    "join pg_namespace n on n.oid = p.pronamespace "
                    "where n.nspname = 'traya_auth'"
                ).fetchall()
            ),
            sorted(
                [
                    ("caller_claims", False),
                    ("caller_has", True),
                    ("caller_id", False),
                    ("subject_in_active_incident", True),
                ]
            ),
        )
        check(
            "traya_api still cannot reach the vectors",
            conn.exec_driver_sql(
                "select has_table_privilege('traya_api', 'biometric_embeddings', 'SELECT')"
            ).scalar(),
            False,
        )
finally:
    probe_engine.dispose()
    with owner_engine.begin() as conn:
        conn.exec_driver_sql(f"revoke traya_api from {PROBE_ROLE}")
        conn.exec_driver_sql(f"drop role if exists {PROBE_ROLE}")
    print(f"\n== dropped probe role {PROBE_ROLE} ==")

print()
if failures:
    print(f"FAILED {len(failures)} check(s):")
    for item in failures:
        print(f"  - {item}")
    sys.exit(1)
print("all hosted checks passed")
