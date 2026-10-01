"""Post-change check that the hosted project still works end to end.

Run after applying `006`/`007`, because those scripts change grants on a live
project and "the policies apply" is not the same claim as "the application still
works". Two things are checked:

1. The application, as the table owner, still serves its own traffic - which is
   the whole reason `FORCE ROW LEVEL SECURITY` is not enabled.
2. The Supabase anon key still reads nothing through PostgREST, which is the
   exposure `004_revoke_anon.sql` closed and which a later grant could reopen.
"""
import pathlib
import sys

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy import create_engine

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.config.settings import settings  # noqa: E402
from app.main import app  # noqa: E402

engine = create_engine(settings.DATABASE_URL)
failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


print("== the database the app is pointed at ==")
with engine.connect() as conn:
    db = conn.exec_driver_sql("select current_database()").scalar()
    version = conn.exec_driver_sql("show server_version").scalar()
check("connects", True, f"{db} on PostgreSQL {version}")

print("\n== the application, as table owner ==")
# `TestClient` rather than an httpx `ASGITransport`: the transport is async-only
# in the installed httpx, and the suite already drives the app this way, so the
# check exercises the same path the tests do.
with TestClient(app) as c:
    r = c.get("/api/health")
    body = r.json() if r.status_code == 200 else {}
    # The connection report is nested under `database`; the top level carries
    # `status`. Asserted against the nested keys because reading the top level
    # returns None for both and looks like a health check that failed to run.
    db_report = body.get("database") or {}
    check("health is 200", r.status_code == 200, str(r.status_code))
    check("status is ok", body.get("status") == "ok", str(body.get("status")))
    check(
        "reports a connected postgres",
        db_report.get("backend") in ("postgres", "supabase"),
        str(db_report.get("backend")),
    )
    check("not degraded", db_report.get("degraded") is False, str(db_report.get("degraded")))
    check(
        "sees all 22 tables",
        db_report.get("tables") == 22,
        str(db_report.get("tables")),
    )

    r = c.post(
        "/api/auth/login",
        json={"email": "admin@traya.io", "password": "TrayaDemo#2026"},
    )
    check("admin can log in", r.status_code == 200, str(r.status_code))
    token = r.json().get("access_token") if r.status_code == 200 else None

    if token:
        r = c.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        check("admin can read its own profile", r.status_code == 200, str(r.status_code))

        r = c.get("/api/admin/users", headers={"Authorization": f"Bearer {token}"})
        users = r.json() if r.status_code == 200 else []
        check("admin can still list users", r.status_code == 200, f"{len(users)} rows")

    # The emergency path end to end, because it is the flow that must not be
    # broken by anything touching medical or biometric tables.
    session_id = None
    try:
        r = c.post(
            "/api/emergency/start",
            json={"access_type": "public"},
            headers={"Authorization": f"Bearer {token}"} if token else {},
        )
        check("emergency session starts", r.status_code in (200, 201), str(r.status_code))
        session = r.json() if r.status_code in (200, 201) else {}
        # The response names it `session_id`; the path parameter wants the same
        # value. Accepting either keeps this script from depending on which name a
        # future edit chooses.
        session_id = session.get("session_id") or session.get("id")

        if session_id:
            from app.services.demo.demo_images import render_face, to_base64

            # `to_base64` takes a PIL image; `render_face` already returns one. An
            # earlier version round-tripped it through `to_bytes` first and got a
            # bytes object where an image was expected.
            image = to_base64(render_face("aarav-kumar-demo"))
            r = c.post(
                f"/api/emergency/{session_id}/identify",
                json={"image": image},
                headers={"Authorization": f"Bearer {token}"} if token else {},
            )
            body = r.json() if r.status_code == 200 else {}
            check("identification runs", r.status_code == 200, str(r.status_code))
            check(
                "and carries its simulation disclosure",
                body.get("engine_mode") is not None,
                f"engine_mode={body.get('engine_mode')}",
            )
    finally:
        # This script writes to the hosted project, and a diagnostic that leaves a
        # session and an attempt behind on every run is how a verification becomes
        # data. The attempts, candidates and locations carry ON DELETE CASCADE, so
        # one delete is enough; the audit rows that reference the session are left
        # alone, because the audit trail is append-only by design.
        if session_id:
            with engine.begin() as conn:
                conn.execute(
                    text("delete from emergency_sessions where id = :i"),
                    {"i": session_id},
                )
            print(f"  removed the session {session_id} it created")

print("\n== the anon key is still locked out ==")
anon = settings.SUPABASE_ANON_KEY
project = settings.SUPABASE_URL
if not anon or not project:
    check("anon key configured for this check", False, "SUPABASE_ANON_KEY or SUPABASE_URL unset")
else:
    rest = project.rstrip("/") + "/rest/v1/"
    with httpx.Client(timeout=20) as c:
        for table in ("users", "medical_profiles", "biometric_embeddings", "audit_logs"):
            r = c.get(
                rest + table,
                headers={"apikey": anon, "Authorization": f"Bearer {anon}"},
            )
            check(
                f"anon cannot read {table}",
                r.status_code in (401, 403),
                f"HTTP {r.status_code}",
            )

print()
if failures:
    print(f"FAILED {len(failures)}: {failures}")
    sys.exit(1)
print("hosted project still healthy")
