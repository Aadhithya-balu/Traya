"""Pytest fixtures and helpers for the TRAYA backend test suite.

IMPORTANT: environment variables must be set BEFORE any ``app`` module is
imported, because the pydantic settings singleton is created at import time.
"""
from __future__ import annotations

import base64
import os
import tempfile
import uuid

_TEST_DB = os.path.join(tempfile.gettempdir(), "traya_test.db")
if os.path.exists(_TEST_DB):
    os.remove(_TEST_DB)

os.environ["TESTING"] = "1"
os.environ["DEMO_MODE"] = "1"
os.environ["DATABASE_URL"] = "sqlite:///" + _TEST_DB.replace("\\", "/")

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.demo.demo_images import render_face, to_base64, to_bytes

DEMO_PASSWORD = "TrayaDemo#2026"


@pytest.fixture(scope="session")
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


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


def identify(client: TestClient, session_id: str, image: str, **extra) -> dict:
    body = {"image": image, **extra}
    r = client.post(f"/api/emergency/{session_id}/identify", json=body)
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


# --------------------------------------------------------------------------
# Shared image fixtures
# --------------------------------------------------------------------------

@pytest.fixture()
def aarav_image() -> str:
    return clean_image("aarav-kumar-demo")


@pytest.fixture()
def unknown_image() -> str:
    return clean_image("enroll-demo-charlie-99")
