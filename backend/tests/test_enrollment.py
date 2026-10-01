"""Guided face-enrollment tests.

The pose heuristic is deliberately covered only for the properties the flow
actually depends on (it degrades to "unknown" rather than rejecting), because
absolute yaw/pitch from luminance asymmetry is not a measurable claim.
"""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from app.services.demo.demo_images import render_face, to_base64
from app.services.identification.engine import estimate_pose, pose_step_key
from .conftest import make_user

IDENTITY = "guided-enroll-fixed-identity"


def b64(**kwargs) -> str:
    return to_base64(render_face(seed=7, identity=IDENTITY, **kwargs))


def posed(head_yaw: float) -> str:
    return b64(head_yaw=head_yaw)


def good() -> str:
    return b64()


def very_dark() -> str:
    from PIL import Image

    img = render_face(seed=7, identity=IDENTITY)
    return to_base64(Image.eval(img, lambda p: max(0, int(p * 0.18))))


def consent(client, headers):
    r = client.post(
        "/api/users/consents",
        headers=headers,
        json={"consent_type": "biometric", "granted": True},
    )
    assert r.status_code == 200


def start(client, headers):
    r = client.post("/api/biometric/enrollment/start", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def sample(client, headers, enrollment_id, image: str):
    return client.post(
        f"/api/biometric/enrollment/{enrollment_id}/sample",
        headers=headers,
        json={"images": [image]},
    )


# ------------------------------------------------------------------ consent
def test_guided_start_requires_consent(client):
    user = make_user(client)
    r = client.post("/api/biometric/enrollment/start", headers=user["headers"])
    assert r.status_code == 409


def test_guided_start_reports_pose_sequence(client):
    user = make_user(client)
    consent(client, user["headers"])
    state = start(client, user["headers"])
    assert state["status"] == "in_progress"
    assert state["current_step"] == 0
    assert state["total_steps"] == 5
    keys = [s["key"] for s in state["steps"]]
    assert keys == ["front", "left", "right", "up", "down"]
    assert state["current_instruction"]
    assert state["can_complete"] is False


def test_start_is_resumable(client):
    user = make_user(client)
    consent(client, user["headers"])
    first = start(client, user["headers"])
    sample(client, user["headers"], first["enrollment_id"], good())
    second = start(client, user["headers"])
    assert second["enrollment_id"] == first["enrollment_id"]
    assert second["accepted_samples"] == 1
    assert second["current_step"] == 1


# ------------------------------------------------------------------ sampling
def test_accepted_sample_advances_the_step(client):
    user = make_user(client)
    consent(client, user["headers"])
    state = start(client, user["headers"])
    r = sample(client, user["headers"], state["enrollment_id"], good())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["verdict"]["accepted"] is True
    assert body["verdict"]["step_key"] == "front"
    assert body["verdict"]["matched_step"] is True
    assert body["state"]["current_step"] == 1
    assert body["state"]["accepted_samples"] == 1


def test_wrong_pose_is_reported_but_not_refused(client):
    """Pose reading is advisory: it tells the person to keep turning rather
    than discarding a photo the quality gates already approved."""
    user = make_user(client)
    consent(client, user["headers"])
    state = start(client, user["headers"])
    sample(client, user["headers"], state["enrollment_id"], good())
    assert start(client, user["headers"])["current_step"] == 1  # "turn left"

    body = sample(
        client, user["headers"], state["enrollment_id"], good()
    ).json()  # another frontal shot
    verdict = body["verdict"]
    assert verdict["accepted"] is True
    assert verdict["step_key"] == "left"
    assert verdict["matched_step"] is False
    assert "pose_does_not_match" in verdict["guidance"]
    assert body["state"]["current_step"] == 2


def test_turned_capture_matches_the_turned_step(client):
    user = make_user(client)
    consent(client, user["headers"])
    state = start(client, user["headers"])
    sample(client, user["headers"], state["enrollment_id"], good())
    # The "turn left" step, with a capture that really is turned.
    body = sample(client, user["headers"], state["enrollment_id"], posed(0.9)).json()
    verdict = body["verdict"]
    assert verdict["accepted"] is True
    assert verdict["pose_confident"] is True
    assert verdict["matched_step"] is True
    assert verdict["observed_direction"] == "left"


def test_rejected_sample_reports_guidance_and_does_not_advance(client):
    user = make_user(client)
    consent(client, user["headers"])
    state = start(client, user["headers"])
    r = sample(client, user["headers"], state["enrollment_id"], b64(faces=0))
    body = r.json()
    verdict = body["verdict"]
    assert verdict["accepted"] is False
    assert "no_face_detected" in verdict["guidance"]
    assert body["state"]["current_step"] == 0
    assert body["state"]["accepted_samples"] == 0
    assert body["state"]["rejected_samples"] == 1


def test_blurry_capture_is_rejected(client):
    user = make_user(client)
    consent(client, user["headers"])
    state = start(client, user["headers"])
    body = sample(
        client, user["headers"], state["enrollment_id"], b64(blur=True)
    ).json()
    assert body["verdict"]["accepted"] is False
    assert "image_blurry" in body["verdict"]["guidance"]


def test_dark_capture_is_rejected(client):
    user = make_user(client)
    consent(client, user["headers"])
    state = start(client, user["headers"])
    body = sample(client, user["headers"], state["enrollment_id"], very_dark()).json()
    assert body["verdict"]["accepted"] is False
    assert "too_much_darkness" in body["verdict"]["guidance"]


def test_empty_sample_is_422(client):
    user = make_user(client)
    consent(client, user["headers"])
    state = start(client, user["headers"])
    r = client.post(
        f"/api/biometric/enrollment/{state['enrollment_id']}/sample",
        headers=user["headers"],
        json={"images": []},
    )
    assert r.status_code == 422


def test_sample_rejects_junk_image(client):
    user = make_user(client)
    consent(client, user["headers"])
    state = start(client, user["headers"])
    r = sample(client, user["headers"], state["enrollment_id"], "not base64!!!")
    assert r.status_code in (400, 422)


def test_complete_stores_one_centroid_not_the_raw_samples(client, db):
    """The stored template is the centroid of the samples, L2-normalised.

    Storing every sample means the matcher takes a max over N templates, and a
    max is not a description of the person - it is a description of the luckiest
    sample. The centroid is what was actually enrolled, so it is what is stored.
    """
    from app.models import BiometricEmbedding, BiometricProfile
    from app.security.crypto import decrypt_bytes

    user = make_user(client)
    consent(client, user["headers"])
    state = start(client, user["headers"])
    for _ in range(3):
        sample(client, user["headers"], state["enrollment_id"], good())

    r = client.post(
        f"/api/biometric/enrollment/{state['enrollment_id']}/complete",
        headers=user["headers"],
    )
    assert r.status_code == 200, r.text

    profile = (
        db.query(BiometricProfile)
        .filter_by(user_id=user["user"]["id"], status="enrolled")
        .one()
    )
    rows = db.query(BiometricEmbedding).filter_by(profile_id=profile.id).all()
    assert len(rows) == 1, f"expected a single centroid template, stored {len(rows)}"

    vector = np.frombuffer(decrypt_bytes(rows[0].embedding_blob), dtype=np.float64)
    assert float(np.linalg.norm(vector)) == pytest.approx(1.0, abs=1e-9), (
        "a centroid must be unit length, because the matcher uses cosine"
    )
    # num_samples still reports what the person contributed, not how many rows
    # that became.
    assert r.json()["num_samples"] == 3


def test_complete_reports_intra_person_spread(client):
    """Every accepted sample was individually fine; only they can disagree.

    The response carries how closely the person's own samples agreed, because
    that number is not recoverable from the stored template later and it is the
    first thing to look at when a match goes wrong.
    """
    user = make_user(client)
    consent(client, user["headers"])
    state = start(client, user["headers"])
    for _ in range(3):
        sample(client, user["headers"], state["enrollment_id"], good())

    r = client.post(
        f"/api/biometric/enrollment/{state['enrollment_id']}/complete",
        headers=user["headers"],
    )
    consistency = r.json()["consistency"]
    assert consistency["pairs"] == 3, "3 samples give 3 unordered pairs"
    assert consistency["min_pairwise"] <= consistency["mean_pairwise"]
    assert consistency["threshold"] > 0
    assert consistency["min_pairwise"] >= consistency["threshold"]


def test_complete_refuses_an_inconsistent_capture_set(client):
    """Four individually good photos of two different faces must not commit.

    Every sample here passes the per-image quality gates, which is exactly why
    this check has to exist: the gates cannot see that the images are of
    different people. Without this, an enrollment assembled carelessly becomes a
    template that represents nobody.
    """
    user = make_user(client)
    consent(client, user["headers"])
    state = start(client, user["headers"])

    # Two of one identity, two of another, each rendered to pass the gates.
    other = to_base64(render_face(seed=7, identity="a-completely-different-person"))
    for image in (b64(), b64(), other, other):
        s = sample(client, user["headers"], state["enrollment_id"], image)
        assert s.status_code == 200
        # Every sample must have been accepted on quality. If any were rejected
        # the 422 below would be the minimum-samples guard rather than the
        # consistency check, and the test would pass for the wrong reason.
        assert s.json()["verdict"]["accepted"], s.text

    r = client.post(
        f"/api/biometric/enrollment/{state['enrollment_id']}/complete",
        headers=user["headers"],
    )
    assert r.status_code == 422
    assert "same person" in r.text.lower() or "do not look like" in r.text.lower()

    status = client.get("/api/biometric/status", headers=user["headers"]).json()
    assert status["status"] != "enrolled", "an inconsistent set must not enroll"


# ------------------------------------------------------------------ retention
def test_complete_purges_the_raw_sample_vectors(client, db):
    """The pending vectors must not outlive the centroid built from them.

    Each accepted capture stored its own encrypted 128D descriptor. Those rows
    exist only to compute a centroid; leaving them behind would keep N extra
    biometric vectors at rest forever, per person, and the audit trail already
    has what it needs in the enrollment's per-sample reports.
    """
    from app.models import BiometricEnrollmentSample

    user = make_user(client)
    consent(client, user["headers"])
    state = start(client, user["headers"])
    for _ in range(3):
        sample(client, user["headers"], state["enrollment_id"], good())

    assert (
        db.query(BiometricEnrollmentSample)
        .filter_by(enrollment_id=state["enrollment_id"])
        .count()
        == 3
    )

    r = client.post(
        f"/api/biometric/enrollment/{state['enrollment_id']}/complete",
        headers=user["headers"],
    )
    assert r.status_code == 200, r.text

    remaining = (
        db.query(BiometricEnrollmentSample)
        .filter_by(enrollment_id=state["enrollment_id"])
        .count()
    )
    assert remaining == 0, f"{remaining} sample vector(s) outlived the template"


def test_complete_purges_rejected_samples_too(client, db):
    """A rejected capture's vector is purged on the same terms as an accepted one.

    A sample the engine refused is still someone's biometric, and it was still
    derived from their face. Retention cannot depend on the engine's opinion of
    the capture.
    """
    from app.models import BiometricEnrollmentSample

    user = make_user(client)
    consent(client, user["headers"])
    state = start(client, user["headers"])

    dark = to_base64(render_face(seed=11, dark=True))
    s = sample(client, user["headers"], state["enrollment_id"], dark)
    assert not s.json()["verdict"]["accepted"], s.text
    for _ in range(3):
        sample(client, user["headers"], state["enrollment_id"], good())

    r = client.post(
        f"/api/biometric/enrollment/{state['enrollment_id']}/complete",
        headers=user["headers"],
    )
    assert r.status_code == 200, r.text
    assert (
        db.query(BiometricEnrollmentSample)
        .filter_by(enrollment_id=state["enrollment_id"])
        .count()
        == 0
    )


def test_a_refused_set_keeps_its_samples_so_the_person_can_try_again(client, db):
    """Purging is tied to a committed template, not to a rejected attempt.

    The consistency guard is the one failure where the samples are the only
    diagnostic: the person cannot see their own pairwise scores, so deleting
    them would make an unexplained 422 impossible to investigate.
    """
    from app.models import BiometricEnrollmentSample

    user = make_user(client)
    consent(client, user["headers"])
    state = start(client, user["headers"])

    other = to_base64(render_face(seed=7, identity="a-completely-different-person"))
    for image in (b64(), b64(), other, other):
        sample(client, user["headers"], state["enrollment_id"], image)

    r = client.post(
        f"/api/biometric/enrollment/{state['enrollment_id']}/complete",
        headers=user["headers"],
    )
    assert r.status_code == 422
    assert (
        db.query(BiometricEnrollmentSample)
        .filter_by(enrollment_id=state["enrollment_id"])
        .count()
        == 4
    )


# ------------------------------------------------------------------ complete
def test_complete_requires_minimum_samples(client):
    user = make_user(client)
    consent(client, user["headers"])
    state = start(client, user["headers"])
    for _ in range(2):
        sample(client, user["headers"], state["enrollment_id"], good())
    r = client.post(
        f"/api/biometric/enrollment/{state['enrollment_id']}/complete",
        headers=user["headers"],
    )
    assert r.status_code == 422


def test_complete_enrolls_and_sets_status(client):
    user = make_user(client)
    consent(client, user["headers"])
    state = start(client, user["headers"])
    for _ in range(3):
        sample(client, user["headers"], state["enrollment_id"], good())

    r = client.post(
        f"/api/biometric/enrollment/{state['enrollment_id']}/complete",
        headers=user["headers"],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "enrolled"
    assert body["num_samples"] >= 3
    assert "front" in body["steps_completed"]

    status = client.get("/api/biometric/status", headers=user["headers"]).json()
    assert status["status"] == "enrolled"
    assert status["num_samples"] >= 3


def test_abandoned_enrollment_leaves_profile_untouched(client):
    user = make_user(client)
    consent(client, user["headers"])
    state = start(client, user["headers"])
    for _ in range(3):
        sample(client, user["headers"], state["enrollment_id"], good())
    r = client.request(
        "DELETE", f"/api/biometric/enrollment/{state['enrollment_id']}",
        headers=user["headers"],
    )
    assert r.status_code == 200
    status = client.get("/api/biometric/status", headers=user["headers"]).json()
    assert status["status"] != "enrolled"


def test_enrollment_is_scoped_to_owner(client):
    owner = make_user(client)
    consent(client, owner["headers"])
    state = start(client, owner["headers"])

    other = make_user(client)
    consent(client, other["headers"])
    r = sample(client, other["headers"], state["enrollment_id"], good())
    assert r.status_code == 404
    r = client.post(
        f"/api/biometric/enrollment/{state['enrollment_id']}/complete",
        headers=other["headers"],
    )
    assert r.status_code == 404


# ------------------------------------------------------------------ pose
def test_pose_is_low_confidence_on_featureless_input():
    flat = Image.new("RGB", (120, 120), (128, 128, 128))
    pose = estimate_pose(flat)
    assert pose.confident is False
    assert pose.reason
    # An unmeasurable pose must never masquerade as a frontal match.
    assert pose.is_frontal is False


def test_pose_is_low_confidence_on_tiny_input():
    pose = estimate_pose(Image.new("RGB", (8, 8), (30, 40, 90)))
    assert pose.confident is False
    assert pose.reason == "face_too_small"


def test_pose_estimate_separates_frontal_from_turned():
    """The threshold sits in the measured gap, not on a guessed constant."""
    from app.services.demo.demo_images import to_bytes
    from app.services.identification.engine import (
        TURNED_OFFSET,
        decode_image,
        detect_faces,
    )

    def offsets(head_yaw: float, identity: str) -> list[float]:
        out = []
        for seed in (7, 11, 23, 41):
            raw = to_bytes(render_face(seed=seed, identity=identity, head_yaw=head_yaw))
            img = decode_image(raw)
            faces, _ = detect_faces(img)
            out.append(estimate_pose(img, faces[0]).offset_x)
        return out

    for identity in ("frontal-gap-a", "frontal-gap-b", "frontal-gap-c"):
        frontal = offsets(0.0, identity)
        turned_right = offsets(0.9, identity)
        turned_left = offsets(-0.9, identity)

        assert max(abs(v) for v in frontal) < TURNED_OFFSET, identity
        assert min(turned_right) > TURNED_OFFSET, identity
        assert max(turned_left) < -TURNED_OFFSET, identity
        # The two directions are genuinely distinct, not noise around zero.
        assert min(turned_right) - max(turned_left) > 4 * TURNED_OFFSET, identity


def test_pitch_needs_a_baseline():
    """Vertical asymmetry is identity-dependent, so it must not self-classify."""
    from app.services.identification.engine import PoseEstimate, direction_against

    tilted = PoseEstimate(offset_x=0.0, offset_y=0.5, confident=True)
    assert direction_against(tilted, baseline=None) == "front"

    baseline = PoseEstimate(offset_x=0.0, offset_y=0.1, confident=True)
    assert direction_against(tilted, baseline=baseline) == "down"
    assert direction_against(
        PoseEstimate(offset_x=0.0, offset_y=-0.4, confident=True), baseline=baseline
    ) == "up"


def test_frontal_face_reads_as_frontal():
    from app.services.demo.demo_images import to_bytes
    from app.services.identification.engine import decode_image, detect_faces

    raw = to_bytes(render_face(seed=7, identity=IDENTITY))
    img = decode_image(raw)
    faces, _ = detect_faces(img)
    pose = estimate_pose(img, faces[0])
    assert pose.confident is True
    assert pose.is_frontal is True
    assert pose_step_key(pose) == "front"


def test_pose_step_key_reports_unknown_when_unmeasurable():
    from app.services.identification.engine import PoseEstimate

    blind = PoseEstimate(offset_x=0.0, offset_y=0.0, confident=False, reason="low_contrast")
    assert pose_step_key(blind) == "unknown"
    assert blind.is_frontal is False
