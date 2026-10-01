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


def test_enrolled_templates_carry_the_active_engine_version(client, db):
    """The version written on enrollment must be the one the matcher looks for.

    This is the failure that a real engine introduces and the simulation cannot:
    `load_enrolled` filters on `get_engine().algo_version`, and enrollment used
    to write `settings.BIOMETRIC_ALGO_VERSION`. Those are the same string under
    simulation and *different* strings under the real engine (128D SFace vs the
    simulation's padded vector), so tagging an enrollment with the wrong one makes
    every template invisible to the matcher. Enrollment would succeed, the profile
    would read "enrolled", and no match would ever be returned.
    """
    from app.models import BiometricEmbedding, BiometricProfile
    from app.services.identification.engine import get_engine
    from app.services.identification.registry import load_enrolled

    user = make_user(client)
    grant_biometric_consent(client, user["headers"])
    r = client.post("/api/biometric/enroll", headers=user["headers"], json={"images": enroll_images()})
    assert r.status_code == 200

    engine_version = get_engine().algo_version
    assert r.json()["algo_version"] == engine_version

    profile = (
        db.query(BiometricProfile)
        .filter_by(user_id=user["user"]["id"], status="enrolled")
        .one()
    )
    assert profile.algo_version == engine_version

    rows = db.query(BiometricEmbedding).filter_by(profile_id=profile.id).all()
    assert rows, "enrollment stored no embeddings"
    assert {row.algo_version for row in rows} == {engine_version}

    # The point of the whole thing: the matcher must actually see them.
    matched = [p for p in load_enrolled(db) if p.user_id == user["user"]["id"]]
    assert len(matched) == 1, (
        "enrollment is invisible to load_enrolled, so this profile could never match"
    )


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
    email = "demo-enroll@fixed.test.traya"
    r = client.post(
        "/api/auth/register",
        json={"full_name": "Demo Enroll Fixed", "email": email, "password": "ValidPass#1"},
    )
    assert r.status_code == 201
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    grant_biometric_consent(client, headers)
    r = client.post("/api/demo/enroll", headers=headers, json={"samples": 3})
    assert r.status_code == 200
    assert r.json()["status"] == "enrolled"
