"""User profile / medical / contacts / features / consents tests."""
from __future__ import annotations

from .conftest import make_user


def test_update_profile(client):
    user = make_user(client)
    r = client.put(
        "/api/users/profile",
        headers=user["headers"],
        json={"full_name": "Updated Name", "phone": "+91 90000 00001", "date_of_birth": "1995-05-05"},
    )
    assert r.status_code == 200
    me = client.get("/api/auth/me", headers=user["headers"]).json()
    assert me["full_name"] == "Updated Name"
    assert me["phone"] == "+91 90000 00001"


def test_medical_profile_roundtrip(client):
    user = make_user(client)
    r = client.put(
        "/api/users/medical",
        headers=user["headers"],
        json={
            "blood_group": "O+",
            "allergies": ["Penicillin", "Peanuts"],
            "conditions": ["Epilepsy"],
            "medications": [],
            "emergency_notes": "Wears medical ID bracelet.",
            "preferred_hospital": "City Care Multispeciality Hospital",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["blood_group"] == "O+"
    assert set(body["allergies"]) == {"Penicillin", "Peanuts"}

    fetched = client.get("/api/users/medical", headers=user["headers"]).json()
    assert fetched["blood_group"] == "O+"
    assert "Epilepsy" in fetched["conditions"]


def test_medical_invalid_blood_group(client):
    user = make_user(client)
    r = client.put(
        "/api/users/medical",
        headers=user["headers"],
        json={"blood_group": "Z-"},
    )
    assert r.status_code == 422


def test_contacts_crud(client):
    user = make_user(client)
    payload = {"name": "Sam Doe", "relation": "Brother", "phone": "+91 98800 12345", "is_primary": True}
    r = client.post("/api/users/contacts", headers=user["headers"], json=payload)
    assert r.status_code == 201
    contact = r.json()
    assert contact["name"] == "Sam Doe"

    listed = client.get("/api/users/contacts", headers=user["headers"]).json()
    assert len(listed) == 1
    assert listed[0]["relation"] == "Brother"

    r = client.delete(f"/api/users/contacts/{contact['id']}", headers=user["headers"])
    assert r.status_code == 204
    assert client.get("/api/users/contacts", headers=user["headers"]).json() == []


def test_visible_features_crud(client):
    user = make_user(client)
    payload = {"feature_type": "birthmark", "description": "Small birthmark on left cheek", "body_location": "Face"}
    r = client.post("/api/users/features", headers=user["headers"], json=payload)
    assert r.status_code == 201
    feature = r.json()

    r = client.post("/api/users/features", headers=user["headers"], json={"feature_type": "scar", "description": "Thin scar"})
    assert r.status_code == 201
    assert len(client.get("/api/users/features", headers=user["headers"]).json()) == 2

    r = client.delete(f"/api/users/features/{feature['id']}", headers=user["headers"])
    assert r.status_code == 204


def test_feature_type_validation(client):
    user = make_user(client)
    r = client.post("/api/users/features", headers=user["headers"], json={"feature_type": "dragon", "description": "A dragon tattoo"})
    assert r.status_code == 422


def test_consents_grant_and_withdraw(client):
    user = make_user(client)
    assert client.get("/api/users/consents", headers=user["headers"]).json() == []

    r = client.post("/api/users/consents", headers=user["headers"], json={"consent_type": "biometric", "granted": True})
    assert r.status_code == 200
    assert r.json()["status"] == "active"

    consents = client.get("/api/users/consents", headers=user["headers"]).json()
    assert len(consents) == 1
    assert consents[0]["consent_type"] == "biometric"

    r = client.post("/api/users/consents", headers=user["headers"], json={"consent_type": "biometric", "granted": False})
    assert r.status_code == 200
    assert r.json()["status"] == "withdrawn"


def test_access_history(client):
    user = make_user(client)
    r = client.get("/api/users/access-history", headers=user["headers"])
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_account_deletion(client):
    user = make_user(client)
    r = client.request("DELETE", "/api/users/account", headers=user["headers"], json={"password": user["password"]})
    assert r.status_code == 204
    me = client.get("/api/auth/me", headers=user["headers"])
    assert me.status_code == 401


def test_profile_requires_auth(client):
    assert client.get("/api/users/profile").status_code == 401
