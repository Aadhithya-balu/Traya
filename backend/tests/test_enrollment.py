"""Guided face-enrollment tests.

The pose heuristic is deliberately covered only for the properties the flow
actually depends on (it degrades to "unknown" rather than rejecting), because
absolute yaw/pitch from luminance asymmetry is not a measurable claim.
"""
from __future__ import annotations

import numpy as np
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
