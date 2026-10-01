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


# ------------------------------------------------------------------ Phase 4
#
# Gate item 5: "a test proves an attacker with a valid token cannot escalate to
# admin by changing the JWT payload (signature check rejects it)".
#
# The parenthetical names only the signature check, but the signature check is
# the easy half. The half worth testing is the one that survives a *valid*
# signature, because a token signed with the right key and a payload claiming
# `admin` is not an attack the signature layer can stop. TRAYA resolves roles
# from `user_roles` on every request, so that token is worth exactly the
# permissions its subject actually holds. Both halves are asserted, because
# removing either one is a plausible future change.


def _forged(claims: dict, key: str) -> str:
    import jwt

    from app.config.settings import settings

    return jwt.encode(claims, key, algorithm=settings.JWT_ALGORITHM)


def _claims_of(token: str) -> dict:
    import jwt

    from app.config.settings import settings

    return jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
        options={"verify_signature": False},
    )


def test_tampered_payload_is_rejected_by_the_signature_check(client):
    """Edit the payload, keep the original signature. 401, not 403.

    The distinction is the point: 403 would mean the token was accepted as
    authentic and the *authorization* layer stopped it, which is a weaker
    guarantee about the signature than it looks.
    """
    user = make_user(client)
    token = user["headers"]["Authorization"].split()[1]

    claims = _claims_of(token)
    claims["roles"] = ["admin"]
    claims["sub"] = "someone-else-entirely"

    forged = _forged(claims, "a-different-secret-entirely")

    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401, r.text


def test_alg_none_token_is_rejected(client):
    """The unsigned-token attack, which a naive decode would accept.

    `algorithms` is pinned on decode, so the library refuses `none` before it
    looks at the payload at all.
    """
    import jwt

    user = make_user(client)
    token = user["headers"]["Authorization"].split()[1]
    claims = _claims_of(token)
    claims["roles"] = ["admin"]

    unsigned = jwt.encode(claims, key="", algorithm="none")

    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {unsigned}"})
    assert r.status_code == 401, r.text


def test_correctly_signed_token_cannot_invent_a_role(client):
    """A valid signature over a lie still buys nothing.

    This is the escalation the gate is really about. The attacker holds the
    signing key - or believes they do - and sends a token the server considers
    authentic, claiming `admin`. The answer must come from `user_roles`, not from
    the payload, so the request is authenticated (not 401) and refused on
    authorization (403).
    """
    from app.config.settings import settings

    user = make_user(client)
    token = user["headers"]["Authorization"].split()[1]

    claims = _claims_of(token)
    claims["roles"] = ["admin"]
    claims["role"] = "admin"
    claims["permissions"] = ["manage_users"]

    correctly_signed = _forged(claims, settings.SECRET_KEY)

    r = client.get("/api/admin/users", headers={"Authorization": f"Bearer {correctly_signed}"})
    assert r.status_code == 403, r.text


def test_revoked_role_takes_effect_on_the_next_request(client):
    """Roles are read live, so a demotion is not a token that outlives it.

    Complements `caller_has`'s `is_active` check in
    `migrations/supabase/006_claims.sql`: there, a suspended account loses its
    permissions. Here the role itself is removed, and the already-issued token
    stops working immediately rather than at expiry.
    """
    user = make_user(client, roles=["auditor"])
    headers = user["headers"]
    user_id = user["user"]["id"]

    assert client.get("/api/admin/audit", headers=headers).status_code == 200

    # The endpoint rejects an empty role list, so the demotion names the default
    # role explicitly. That constraint is worth knowing: "remove every role" is
    # not a supported operation through the API.
    r = client.patch(
        f"/api/admin/users/{user_id}/roles",
        headers=auth_headers(client, "admin@traya.io"),
        json={"roles": ["registered_user"]},
    )
    assert r.status_code == 200, r.text

    r = client.get("/api/admin/audit", headers=headers)
    assert r.status_code == 403, "a demoted auditor kept access on an unexpired token"
