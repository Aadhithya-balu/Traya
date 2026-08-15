"""Biometric enrollment / status / deletion tests."""
from __future__ import annotations

from app.services.demo.demo_images import render_enrollment, to_base64

from .conftest import make_user


def enroll_images(identity: str = "test-identity", samples: int = 3) -> list[str]:
    return [to_base64(img) for img in render_enrollment(identity, samples=samples)]


def grant_biometric_consent(client, headers):
    r = client.post("/api/users/consents", headers=headers, json={"consent_type": "biometric", "granted": True})
    assert r.status_code == 200


def test_enroll_requires_consent(client):
    user = make_user(client)
    r = client.post("/api/biometric/enroll", headers=user["headers"], json={"images": enroll_images()})
    assert r.status_code == 409


def test_enroll_and_status_roundtrip(client):
    user = make_user(client)
    grant_biometric_consent(client, user["headers"])

    r = client.post("/api/biometric/enroll", headers=user["headers"], json={"images": enroll_images()})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "enrolled"
    assert body["num_samples"] >= 2

    status = client.get("/api/biometric/status", headers=user["headers"]).json()
    assert status["status"] == "enrolled"
    assert status["num_samples"] >= 2
    assert status["enrolled_at"] is not None


def test_enroll_insufficient_samples(client):
    user = make_user(client)
    grant_biometric_consent(client, user["headers"])
    r = client.post("/api/biometric/enroll", headers=user["headers"], json={"images": enroll_images(samples=1)})
    assert r.status_code == 422


def test_delete_biometric(client):
    user = make_user(client)
    grant_biometric_consent(client, user["headers"])
    client.post("/api/biometric/enroll", headers=user["headers"], json={"images": enroll_images()})

    r = client.delete("/api/users/biometric", headers=user["headers"])
    assert r.status_code == 204
    status = client.get("/api/biometric/status", headers=user["headers"]).json()
    assert status["status"] != "enrolled"


def test_demo_enroll_requires_consent(client):
    user = make_user(client)
    r = client.post("/api/demo/enroll", headers=user["headers"], json={"samples": 3})
    assert r.status_code == 409


def test_demo_enroll_works_with_consent(client):
    user = make_user(client)
    grant_biometric_consent(client, user["headers"])
    r = client.post("/api/demo/enroll", headers=user["headers"], json={"samples": 3})
    assert r.status_code == 200
    assert r.json()["status"] == "enrolled"
