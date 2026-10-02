"""Row level security must be on, and it must actually filter.

`AGENTS.md` and `TARGET_ARCHITECTURE.md` both claim RLS protects the data. In
Phase 3 the measurement was the opposite: `rowsecurity` was true on 0 of 22
tables, and the anon key read `users`, `biometric_embeddings`, `audit_logs` and
`medical_profiles` in full. A test is the only thing that stops a claim like
that from quietly becoming false again when someone adds a model.

These run against the throwaway `traya_test` schema, never `public`.

What is deliberately NOT tested here: the policy layer. `caller_roles()` in
`TARGET_ARCHITECTURE.md` reads `auth.jwt()`, and TRAYA has no Supabase Auth - it
signs its own JWTs with `SECRET_KEY` (`app/security/tokens.py`), so `auth.jwt()`
has nothing to read. There is no claim source to write policies against yet, and
asserting one would be asserting fiction. These tests cover the part that is
true today: RLS is enabled, and it denies a role that has been explicitly
granted SELECT.
"""

from __future__ import annotations

import pathlib
import re
import uuid

import pytest
from sqlalchemy.engine import make_url

from app.config.settings import settings
from app.database.session import Base, engine
from app.models import all_models  # noqa: F401  (registers the tables)

SUPABASE_SQL = pathlib.Path(__file__).resolve().parents[1] / "migrations" / "supabase"
ENABLE_RLS = SUPABASE_SQL / "005_enable_rls.sql"
REVOKE_ANON = SUPABASE_SQL / "004_revoke_anon.sql"

pytestmark = pytest.mark.skipif(
    not settings.is_postgres,
    reason="row level security is a Postgres feature; SQLite has no equivalent",
)

PROBE_PASSWORD = "probe_only_not_a_real_credential"

# Tables appear via `init_db()` on application startup, which a single-file run
# never reaches. Creating them here keeps this file runnable on its own; without
# it the assertions pass vacuously against an empty schema, or fail with
# "relation does not exist" depending on ordering.
Base.metadata.create_all(bind=engine)


def test_deployment_sql_files_are_tracked():
    assert ENABLE_RLS.exists(), "005_enable_rls.sql is the guard for every new table"
    assert REVOKE_ANON.exists(), "004_revoke_anon.sql closes the anon key's reads"


def test_every_table_has_row_level_security_enabled():
    with engine.begin() as conn:
        conn.exec_driver_sql(ENABLE_RLS.read_text(encoding="utf-8"))

    with engine.connect() as conn:
        unprotected = conn.exec_driver_sql(
            "select tablename from pg_tables "
            "where schemaname = current_schema() and not rowsecurity"
        ).scalars().all()

    assert not unprotected, f"row level security not enabled on: {unprotected}"


def test_alembic_version_table_is_also_protected():
    """Exempting it would make 'every table' true-except-one.

    `alembic_version` is created by Alembic rather than `create_all`, so it is
    absent from the throwaway schema. The deployed project is where it exists,
    and there the loop covers it because nothing is filtered out. Assert the
    source property here, and the observable result on the hosted project.
    """
    sql = ENABLE_RLS.read_text(encoding="utf-8")

    assert "tablename <> 'alembic_version'" not in sql, "alembic_version must not be excluded"
    assert "and not rowsecurity" in sql


def test_deployment_sql_contains_no_percent_sign_anywhere():
    """Not even in a comment, which is the mistake this file actually made.

    psycopg scans the whole statement text for parameter placeholders and does
    not strip comments first, so a comment explaining the placeholder syntax
    reintroduces the exact error it was warning about. This file had `%I` in a
    comment and failed to execute while the comment-stripped version of this
    same test passed, which is how the mistake survived one iteration.

    `AGENTS.md` records the same class of bug for the Tailwind content scanner:
    do not name a class in a comment, because a name in prose is a rule that
    gets emitted. The mechanism differs, the lesson does not.

    Checked across every file in `migrations/supabase/`, not just the ones the
    test suite executes. `001` and `002` are one-shot hosted setup and `004` is
    never run by a script, but all of them are pasted into the Supabase SQL
    editor by hand, which is how this directory reached production. The psycopg
    restriction applies identically on that path, and a file nothing executes is
    exactly where the mistake hides: `004` carried a `raise exception` format
    specifier for months without anything noticing.
    """
    files = sorted(SUPABASE_SQL.glob("*.sql"))
    assert files, f"no deployment SQL found under {SUPABASE_SQL}"

    offenders = []
    for path in files:
        sql = path.read_text(encoding="utf-8")
        if "%" in sql:
            offenders.append(f"{path.name} at offset {sql.index('%')}")

    assert not offenders, (
        f"percent sign found in {offenders}. psycopg reads a percent sequence "
        "as a parameter marker, does not strip comments first, and rejects any "
        "specifier it does not own even with no parameters supplied. Use "
        "quote_ident and string concatenation, not format or percent specifiers."
    )


def test_enable_rls_file_is_schema_agnostic():
    """A hardcoded 'public' would pass in CI and do nothing when deployed.

    On Supabase `current_schema()` is `public`; in this suite `search_path` is
    `traya_test`. If someone hardcodes a schema, the test starts exercising a
    table nobody deploys, so pin the property rather than the outcome.
    """
    sql = ENABLE_RLS.read_text(encoding="utf-8")

    assert "current_schema()" in sql
    assert "schemaname = 'public'" not in sql
    assert "schema public" not in sql


def test_a_granted_non_owner_role_sees_no_rows():
    """The denial path, asserted against the database rather than through FastAPI.

    Revoking `anon` only proves that one role holds no grants. This proves RLS
    itself filters: the probe role is granted SELECT on every table, exactly the
    access the anon role used to have implicitly, and must still read nothing.
    """
    role = f"traya_rls_test_{uuid.uuid4().hex[:8]}"

    with engine.connect() as conn:
        schema = conn.exec_driver_sql("select current_schema()").scalar()

    with engine.begin() as conn:
        conn.exec_driver_sql(f"create role {role} login password '{PROBE_PASSWORD}'")
        # Granted on the schema this suite actually created. Hardcoding `public`
        # would grant nothing here and the test would pass for the wrong reason.
        conn.exec_driver_sql(f'grant usage on schema "{schema}" to {role}')
        conn.exec_driver_sql(f'grant select on all tables in schema "{schema}" to {role}')

    try:
        probe_url = make_url(settings.DATABASE_URL).set(
            username=role, password=PROBE_PASSWORD
        )

        import psycopg

        # make_url keeps the password percent-encoded; psycopg wants a plain libpq
        # DSN, so the SQLAlchemy-only `+psycopg` marker comes off and the
        # encoding is left intact.
        dsn = probe_url.render_as_string(hide_password=False).replace("+psycopg", "", 1)
        with psycopg.connect(dsn, connect_timeout=10) as connection:
            for table in ("users", "biometric_embeddings", "medical_profiles", "audit_logs"):
                visible = connection.execute(f"select count(*) from {table}").fetchone()[0]
                assert visible == 0, (
                    f"{table} returned {visible} rows to a role holding SELECT; "
                    "RLS is not filtering"
                )
    finally:
        with engine.begin() as conn:
            conn.exec_driver_sql(
                f'revoke all privileges on all tables in schema "{schema}" from {role}'
            )
            conn.exec_driver_sql(f'revoke all privileges on schema "{schema}" from {role}')
            conn.exec_driver_sql(f"drop role if exists {role}")
