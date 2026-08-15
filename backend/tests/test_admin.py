"""Admin-only endpoint tests: RBAC, analytics, users, settings, audit, hospitals."""
from __future__ import annotations

from .conftest import auth_headers, make_user


def test_analytics_requires_admin(client):
    user = make_user(client)
    assert client.get("/api/admin/analytics", headers=user["headers"]).status_code == 403


def test_analytics_as_admin(client, admin_headers):
    r = client.get("/api/admin/analytics", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total_users"] >= 8
    assert body["total_enrolled"] >= 4
    assert body["total_sessions"] >= 0
    assert "identifications_by_day" in body
    assert "status_breakdown" in body


def test_admin_users_list(client, admin_headers):
    r = client.get("/api/admin/users", headers=admin_headers)
    assert r.status_code == 200
    emails = {u["email"] for u in r.json()}
    assert "aarav.kumar@demo.traya" in emails
    assert "admin@traya.io" in emails


def test_role_assignment(client, admin_headers):
    user = make_user(client)
    r = client.patch(
        f"/api/admin/users/{user['user']['id']}/roles",
        headers=admin_headers,
        json={"roles": ["registered_user", "medical_responder"]},
    )
    assert r.status_code == 200
    assert "medical_responder" in r.json()["roles"]


def test_role_assignment_requires_admin(client):
    user = make_user(client)
    r = client.patch(
        f"/api/admin/users/{user['user']['id']}/roles",
        headers=user["headers"],
        json={"roles": ["admin"]},
    )
    assert r.status_code == 403


def test_set_active(client, admin_headers):
    user = make_user(client)
    r = client.patch(f"/api/admin/users/{user['user']['id']}/active", headers=admin_headers, params={"active": False})
    assert r.status_code == 200
    assert r.json()["is_active"] is False


def test_audit_accessible_to_auditor(client, auditor_headers):
    r = client.get("/api/admin/audit", headers=auditor_headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_audit_forbidden_for_registered(client):
    user = make_user(client)
    assert client.get("/api/admin/audit", headers=user["headers"]).status_code == 403


def test_settings_list_and_update(client, admin_headers):
    r = client.get("/api/admin/settings", headers=admin_headers)
    assert r.status_code == 200
    keys = {s["key"] for s in r.json()}
    assert {"high", "review", "face_fallback"} <= keys

    r = client.put("/api/admin/settings/high", headers=admin_headers, json={"value": "0.80"})
    assert r.status_code == 200
    assert r.json()["value"] == "0.80"


def test_hospitals_admin_crud(client, admin_headers):
    r = client.get("/api/admin/hospitals", headers=admin_headers)
    assert r.status_code == 200
    before = len(r.json())
    assert before == 9

    r = client.post(
        "/api/admin/hospitals",
        headers=admin_headers,
        json={
            "name": "Test Trauma Centre",
            "address": "Test Address",
            "phone": "+91 11 0000 0000",
            "latitude": 28.6,
            "longitude": 77.2,
            "emergency_available": True,
            "availability_verified": True,
        },
    )
    assert r.status_code == 201
    created = r.json()
    assert created["name"] == "Test Trauma Centre"

    r = client.delete(f"/api/admin/hospitals/{created['id']}", headers=admin_headers)
    assert r.status_code == 204

    r = client.get("/api/admin/hospitals", headers=admin_headers)
    assert len(r.json()) == before


def test_admin_sessions(client, admin_headers):
    r = client.get("/api/admin/sessions", headers=admin_headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)
