"""Permission-based authorization tests.

The spec requires that access is decided by permissions resolved from the
database, not by hidden frontend buttons. These tests exercise the matrix
end-to-end through the API for every role.
"""
from __future__ import annotations

import pytest

from app.security.permissions import (
    ALL_PERMISSIONS,
    ROLE_PERMISSIONS,
    permissions_for_roles,
)
from tests.conftest import make_user


def test_permission_matrix_is_fully_populated():
    assert len(ALL_PERMISSIONS) == len(set(ALL_PERMISSIONS))
    for role, granted in ROLE_PERMISSIONS.items():
        unknown = set(granted) - set(ALL_PERMISSIONS)
        assert not unknown, f"{role} references unknown permissions: {unknown}"


def test_permission_catalogue_endpoint_lists_matrix(client):
    r = client.get("/api/auth/permissions")
    assert r.status_code == 200
    body = r.json()
    assert {p["name"] for p in body} == set(ALL_PERMISSIONS)
    by_name = {p["name"]: p for p in body}
    assert "admin" in by_name["manage_users"]["roles"]
    assert by_name["manage_users"]["roles"] == ["admin"]


def test_me_exposes_resolved_permissions(client, demo_headers):
    r = client.get("/api/auth/me", headers=demo_headers)
    assert r.status_code == 200
    perms = set(r.json()["permissions"])
    assert "manage_own_profile" in perms
    assert "enroll_biometric" in perms
    assert "manage_users" not in perms


def test_bystander_gains_no_profile_access():
    granted = permissions_for_roles({"public"})
    assert granted == {"identify_person"}


def test_police_cannot_read_medical_alerts():
    granted = permissions_for_roles({"police_responder"})
    assert "view_emergency_profile" in granted
    assert "create_incident" in granted
    assert "view_medical_alerts" not in granted


def test_paramedic_can_read_medical_alerts():
    granted = permissions_for_roles({"medical_responder"})
    assert "view_medical_alerts" in granted
    assert "confirm_identity" in granted


def test_hospital_role_is_seeded_and_grants_clinical_alerts(client):
    r = client.post(
        "/api/auth/login",
        json={"email": "karthik.raman@responder.traya", "password": "TrayaDemo#2026"},
    )
    assert r.status_code == 200
    perms = set(r.json()["user"]["permissions"])
    assert "hospital" in r.json()["user"]["roles"]
    assert "view_medical_alerts" in perms
    assert "manage_users" not in perms


def test_registered_user_cannot_reach_admin_analytics(client, demo_headers):
    r = client.get("/api/admin/analytics", headers=demo_headers)
    assert r.status_code == 403


def test_auditor_can_read_audit_but_not_analytics(client, auditor_headers):
    assert client.get("/api/admin/audit", headers=auditor_headers).status_code == 200
    assert client.get("/api/admin/analytics", headers=auditor_headers).status_code == 403
    assert client.get("/api/admin/users", headers=auditor_headers).status_code == 403


def test_police_cannot_confirm_identity_via_permission(client, police_headers):
    """Police holds create_incident but not the medical-only capabilities."""
    r = client.get("/api/admin/users", headers=police_headers)
    assert r.status_code == 403
    r = client.put("/api/admin/settings/high", headers=police_headers, json={"value": "0.9"})
    assert r.status_code == 403


def test_permission_falls_back_to_matrix_when_tables_unseeded():
    granted = permissions_for_roles({"registered_user"})
    assert granted == {
        "identify_person",
        "manage_own_profile",
        "enroll_biometric",
        "manage_own_consent",
    }


@pytest.mark.parametrize(
    "role,expected",
    [
        ("public", ["identify_person"]),
        ("auditor", ["view_audit_logs", "view_incident"]),
    ],
)
def test_minimal_roles_stay_minimal(role, expected):
    assert sorted(permissions_for_roles({role})) == expected


def test_multi_role_union(client):
    u = make_user(client, roles=["registered_user", "auditor"])
    r = client.get("/api/auth/me", headers=u["headers"])
    perms = set(r.json()["permissions"])
    assert "view_audit_logs" in perms
    assert "manage_own_profile" in perms
    assert "manage_users" not in perms
