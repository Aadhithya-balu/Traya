"""Authentication endpoint tests."""
from __future__ import annotations

from app.utils.helpers import validate_and_decode_image

from .conftest import auth_headers, login, make_user


def test_register_success(client):
    user = make_user(client)
    assert "id" in user["user"]
    assert user["user"]["email"].endswith("@test.traya")
    assert "registered_user" in user["user"]["roles"]


def test_register_returns_tokens(client):
    r = client.post(
        "/api/auth/register",
        json={
            "full_name": "Jane Doe",
            "email": "jane.doe@test.traya",
            "password": "JanePass#1",
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["user"]["email"] == "jane.doe@test.traya"


def test_register_weak_password(client):
    for password in ["abcdefgh", "ABCDEFGH", "abcdefg1", "short"]:
        r = client.post(
            "/api/auth/register",
            json={"full_name": "Weak Pass", "email": f"weak{password}@test.traya", "password": password},
        )
        assert r.status_code == 422, password


def test_register_duplicate_email(client):
    payload = {
        "full_name": "Duplicate User",
        "email": "dupe@test.traya",
        "password": "DupePass#1",
    }
    assert client.post("/api/auth/register", json=payload).status_code == 201
    r = client.post("/api/auth/register", json=payload)
    assert r.status_code == 409


def test_login_success(client):
    data = login(client, "aarav.kumar@demo.traya")
    assert data["user"]["email"] == "aarav.kumar@demo.traya"
    assert data["token_type"] == "bearer"


def test_login_wrong_password(client):
    r = client.post("/api/auth/login", json={"email": "aarav.kumar@demo.traya", "password": "wrong"})
    assert r.status_code == 401


def test_login_unknown_email(client):
    r = client.post("/api/auth/login", json={"email": "nobody@nowhere.traya", "password": "whatever1"})
    assert r.status_code == 401


def test_me_requires_auth(client):
    assert client.get("/api/auth/me").status_code == 401


def test_me_returns_current_user(client):
    headers = auth_headers(client, "aarav.kumar@demo.traya")
    r = client.get("/api/auth/me", headers=headers)
    assert r.status_code == 200
    assert r.json()["email"] == "aarav.kumar@demo.traya"


def test_refresh_flow(client):
    data = login(client, "aarav.kumar@demo.traya")
    assert data["refresh_token"]
    r = client.post("/api/auth/refresh", json={"refresh_token": data["refresh_token"]})
    assert r.status_code == 200
    body = r.json()
    assert body["access_token"]
    assert body["user"]["email"] == "aarav.kumar@demo.traya"


def test_refresh_bad_token(client):
    r = client.post("/api/auth/refresh", json={"refresh_token": "garbage"})
    assert r.status_code == 401


def test_inactive_user_cannot_login(client):
    user = make_user(client)
    r = client.patch(
        f"/api/admin/users/{user['user']['id']}/active",
        headers=auth_headers(client, "admin@traya.io"),
        params={"active": False},
    )
    assert r.status_code == 200
    r = client.post("/api/auth/login", json={"email": user["email"], "password": user["password"]})
    assert r.status_code == 403


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_validate_and_decode_image_rejects_junk():
    import pytest
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        validate_and_decode_image("not base64!!!")
    assert exc.value.status_code == 422
