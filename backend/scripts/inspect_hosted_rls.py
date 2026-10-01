"""Inspect the hosted project's RLS state without changing anything."""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("TESTING", "0")

from sqlalchemy import create_engine, text  # noqa: E402

from app.config.settings import settings  # noqa: E402

engine = create_engine(settings.DATABASE_URL)

with engine.connect() as conn:
    print("database   :", conn.exec_driver_sql("select current_database()").scalar())
    print("schema     :", conn.exec_driver_sql("select current_schema()").scalar())
    print("server     :", conn.exec_driver_sql("show server_version").scalar())

    tables = conn.exec_driver_sql(
        "select count(*) from pg_tables where schemaname = current_schema()"
    ).scalar()
    rls = conn.exec_driver_sql(
        "select count(*) from pg_tables "
        "where schemaname = current_schema() and rowsecurity"
    ).scalar()
    print(f"tables     : {tables}, rowsecurity on: {rls}")

    print("\n-- policies currently defined --")
    for row in conn.exec_driver_sql(
        "select tablename, policyname, cmd from pg_policies "
        "where schemaname = current_schema() order by 1, 2"
    ).fetchall():
        print(f"  {row[0]:28} {row[1]:28} {row[2]}")

    print("\n-- traya_auth functions currently defined --")
    for row in conn.exec_driver_sql(
        "select p.proname, pg_get_function_identity_arguments(p.oid), p.prosecdef "
        "from pg_proc p join pg_namespace n on n.oid = p.pronamespace "
        "where n.nspname = 'traya_auth' order by 1"
    ).fetchall():
        print(f"  {row[0]:32} ({row[1]}) security_definer={row[2]}")

    print("\n-- traya_api grants on schema/tables --")
    print(
        "  usage on schema:",
        conn.exec_driver_sql(
            "select has_schema_privilege('traya_api', current_schema(), 'USAGE')"
        ).scalar(),
    )
    for row in conn.exec_driver_sql(
        "select tablename, has_table_privilege('traya_api', tablename, 'SELECT') "
        "from pg_tables where schemaname = current_schema() order by 1"
    ).fetchall():
        print(f"  {row[0]:28} select={row[1]}")

    print("\n-- sample users for the probe --")
    for row in conn.exec_driver_sql(
        "select u.id, u.email, u.is_active, "
        "(select string_agg(r.name, ',') from user_roles ur "
        " join roles r on r.id = ur.role_id where ur.user_id = u.id) as roles "
        "from users u order by u.created_at limit 12"
    ).fetchall():
        print(f"  {row[0]}  {row[1]:34} active={row[2]} roles={row[3]}")
