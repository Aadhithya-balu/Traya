"""Pytest fixtures and helpers for the TRAYA backend test suite.

IMPORTANT: environment variables must be set BEFORE any ``app`` module is
imported, because the pydantic settings singleton is created at import time.

Set ``TRAYA_TEST_DATABASE_URL`` to run the whole suite against a real Postgres
instead of SQLite. It exists because SQLite cannot falsify a Postgres claim:
it has no ``vector`` extension, no row-level security, and a different
behaviour for a handful of type comparisons. Phase 3 is the phase where that
difference starts to matter, so the gate items are checked against Postgres:

    docker run -d --name traya-pg -p 54329:5432 \\
      -e POSTGRES_PASSWORD=traya_local_dev -e POSTGRES_USER=postgres \\
      -e POSTGRES_DB=traya pgvector/pgvector:pg16

    cd backend
    $env:TRAYA_TEST_DATABASE_URL="postgresql+psycopg://postgres:traya_local_dev@127.0.0.1:54329/traya_test"
    .venv\\Scripts\\python.exe -m pytest

The database must exist but be disposable — the suite creates and drops its own
schema. Leave it unset and everything runs on a temp SQLite file as before.
"""
from __future__ import annotations

import base64
import os
import tempfile
import uuid

_TEST_PG_URL = os.environ.get("TRAYA_TEST_DATABASE_URL", "")

# The Postgres runs happen in here, never in `public`.
_TEST_SCHEMA = "traya_test"

_TEST_DB = os.path.join(tempfile.gettempdir(), "traya_test.db")

if _TEST_PG_URL:
    # SQLite gets a clean slate for free: the file is deleted, so the next run
    # starts from nothing. Postgres has no equivalent, and skipping the reset
    # makes the suite fail on the *second* run against the same database with
    # `409 duplicate email` - a green first run hiding a suite that only works
    # once.
    #
    # It runs in a THROWAWAY SCHEMA, never `public`. `DROP SCHEMA public CASCADE`
    # would work, and on a real Supabase project it would delete the entire
    # application schema. One mis-set environment variable away from destroying
    # production is not a reset mechanism. `search_path` is a connection option
    # so the application code, which never names a schema, still resolves
    # everything inside it.
    import psycopg

    # SQLAlchemy's `+psycopg` is a dialect name, not a libpq driver name.
    # psycopg.connect() parses the string itself and chokes on it. The URL is
    # already percent-encoded, so it must not be quoted a second time.
    _pg_url = _TEST_PG_URL.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(_pg_url, autocommit=True) as _pg:
        _pg.execute(f"DROP SCHEMA IF EXISTS {_TEST_SCHEMA} CASCADE")
        _pg.execute(f"CREATE SCHEMA {_TEST_SCHEMA}")

    # Point the app's connections at the throwaway schema, and keep pgbouncer in
    # transaction mode working: `options` is passed to libpq, not interpreted.
    _sep = "&" if "?" in _TEST_PG_URL else "?"
    _TEST_PG_URL = (
        f"{_TEST_PG_URL}{_sep}options=-csearch_path%3D{_TEST_SCHEMA}"
    )
elif os.path.exists(_TEST_DB):
    os.remove(_TEST_DB)

os.environ["TESTING"] = "1"
os.environ["DEMO_MODE"] = "1"
os.environ["DATABASE_URL"] = _TEST_PG_URL or "sqlite:///" + _TEST_DB.replace("\\", "/")
# The suite tests the *simulation* engine, deliberately and in full. Most of it
# drives `render_face`, a synthetic drawing that YuNet correctly refuses to find
# a face in, so a real-engine default would fail 39 tests for the uninteresting
# reason that the fixtures are not photographs. The real engine has its own
# module, tests/test_real_engine.py, which pins BIOMETRIC_ENGINE=yunet itself and
# skips when the model weights are absent. Setting this here - at the top of
# conftest, before any app import - is what keeps the two suites from leaking
# into each other.
os.environ["BIOMETRIC_ENGINE"] = "simulation"

import pytest
from fastapi.testclient import TestClient

from app.database.session import SessionLocal
from app.main import app
from app.services.demo.demo_images import render_face, to_base64, to_bytes

DEMO_PASSWORD = "TrayaDemo#2026"


@pytest.fixture(scope="session")
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db():
    """A session on the test database, for assertions the API cannot express.

    A fresh session per test, so a test that writes rows cannot leak state into
    the next one. The API calls in a test go through the app's own session, so
    anything read here must already be committed - which is exactly the
    property the enrollment-version test depends on.
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# --------------------------------------------------------------------------
# API helpers
# --------------------------------------------------------------------------

def login(client: TestClient, email: str, password: str = DEMO_PASSWORD) -> dict:
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def auth_headers(client: TestClient, email: str, password: str = DEMO_PASSWORD) -> dict:
    data = login(client, email, password)
    return {"Authorization": f"Bearer {data['access_token']}"}


def make_user(client: TestClient, roles: list[str] | None = None) -> dict:
    """Register a fresh, unique user; optionally assign extra roles via admin."""
    uid = uuid.uuid4().hex[:10]
    email = f"{uid}@test.traya"
    password = "ValidPass#1"
    payload = {"full_name": f"Test User {uid[:6]}", "email": email, "password": password}
    r = client.post("/api/auth/register", json=payload)
    assert r.status_code == 201, r.text
    data = r.json()
    headers = {"Authorization": f"Bearer {data['access_token']}"}
    user = data["user"]
    if roles:
        r = client.patch(
            f"/api/admin/users/{user['id']}/roles",
            headers=auth_headers(client, "admin@traya.io"),
            json={"roles": roles},
        )
        assert r.status_code == 200, r.text
    return {"email": email, "password": password, "headers": headers, "user": user}


def clean_image(identity: str = "aarav-kumar-demo") -> str:
    return to_base64(render_face("capture-live", identity=identity))


def degraded_image(identity: str = "aarav-kumar-demo", **kwargs) -> str:
    return to_base64(render_face("capture-live", identity=identity, **kwargs))


def start_session(client: TestClient) -> dict:
    r = client.post("/api/emergency/start", json={"access_type": "public"})
    assert r.status_code == 200, r.text
    return r.json()


def session_headers(session: dict) -> dict:
    """Auth headers for a bystander emergency session.

    Emergency sessions are authorized by their own access token, not by a
    login, so every session-scoped call must carry it.
    """
    return {"X-TRAYA-Session-Token": session["session_token"]}


def identify(client: TestClient, session: dict, image: str, **extra) -> dict:
    body = {"image": image, **extra}
    r = client.post(
        f"/api/emergency/{session['session_id']}/identify",
        headers=session_headers(session),
        json=body,
    )
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------------
# Seeded identities (from app.services.demo.seed)
# --------------------------------------------------------------------------

@pytest.fixture(scope="session")
def demo_user(client: TestClient) -> dict:
    return login(client, "aarav.kumar@demo.traya")


@pytest.fixture(scope="session")
def demo_headers(client: TestClient) -> dict:
    return auth_headers(client, "aarav.kumar@demo.traya")


@pytest.fixture(scope="session")
def responder_headers(client: TestClient) -> dict:
    return auth_headers(client, "neha.rao@responder.traya")


@pytest.fixture(scope="session")
def admin_headers(client: TestClient) -> dict:
    return auth_headers(client, "admin@traya.io")


@pytest.fixture(scope="session")
def auditor_headers(client: TestClient) -> dict:
    return auth_headers(client, "auditor@traya.io")


@pytest.fixture(scope="session")
def police_headers(client: TestClient) -> dict:
    return auth_headers(client, "suresh.patil@responder.traya")


@pytest.fixture(scope="session")
def hospital_headers(client: TestClient) -> dict:
    return auth_headers(client, "karthik.raman@responder.traya")


# --------------------------------------------------------------------------
# Shared image fixtures
# --------------------------------------------------------------------------

@pytest.fixture()
def aarav_image() -> str:
    return clean_image("aarav-kumar-demo")


@pytest.fixture()
def unknown_image() -> str:
    return clean_image("enroll-demo-charlie-99")
