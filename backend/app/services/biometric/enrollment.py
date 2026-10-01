"""Guided face enrollment.

A single uploaded photo is a weak biometric: it captures one expression under
one lighting condition. Enrollment here is a short, coached sequence. The
camera asks for a front view, then slight left, right, up and down, and each
capture is graded on the real quality gates before being kept.

Design rules this module follows:

* A sample is never accepted on pose alone. Blur, darkness, face size and
  multi-face checks gate first; pose only labels which step it satisfies.
* A low-confidence pose estimate is treated as "unknown", never as a reason
  to reject a good capture.
* Pending samples stay encrypted at rest, exactly like stored templates.
* Pending samples are purged in the same transaction that stores the template.
  After `complete` the enrollment row keeps quality and pose reports for audit
  but holds no vector, so the person's raw per-pose embeddings do not outlive
  the centroid derived from them.
* Nothing is written to the live profile until ``complete`` is called, so an
  abandoned enrollment cannot leave a half-built identity behind.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta

import numpy as np
from fastapi import HTTPException, status as http_status
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.models import BiometricEnrollment, BiometricEnrollmentSample, BiometricProfile, User
from app.repositories.profile import ProfileRepository
from app.security.crypto import decrypt_bytes, encrypt_bytes
from app.services.audit_service import log_user_action
from app.services.identification.engine import PoseEstimate, direction_against, get_engine
from app.services.identification.registry import serialize_embedding
from app.utils.helpers import validate_and_decode_image

logger = logging.getLogger("traya.enrollment")

ENROLLMENT_TTL_MINUTES = 20
MIN_ACCEPTED_SAMPLES = 3

# The coached sequence. Order matters: the frontal capture anchors the
# template, the angled ones broaden it.
POSE_STEPS: list[dict] = [
    {"key": "front", "instruction": "Look straight at the camera", "pose": "front"},
    {"key": "left", "instruction": "Turn your head slightly to your left", "pose": "yaw_left"},
    {"key": "right", "instruction": "Turn your head slightly to your right", "pose": "yaw_right"},
    {"key": "up", "instruction": "Tilt your head slightly up", "pose": "pitch_up"},
    {"key": "down", "instruction": "Tilt your head slightly down", "pose": "pitch_down"},
]

STEP_KEYS = [s["key"] for s in POSE_STEPS]
STEP_INSTRUCTIONS = {s["key"]: s["instruction"] for s in POSE_STEPS}

# Engine reason codes mapped to user-facing guidance codes. The engine is the
# single source of truth for whether a capture is usable; this table only
# decides what the person is told, so a capture is never accepted by the
# pipeline and rejected by the wizard for the same image.
GUIDANCE_BY_REASON = {
    "no_face": "no_face_detected",
    "multiple_faces": "multiple_faces_detected",
    "blurry": "image_blurry",
    "too_dark": "too_much_darkness",
    "face_too_small": "face_too_far",
    "occluded": "face_covered",
    "low_quality": "look_at_camera",
}

GUIDANCE = {
    "no_face": "no_face_detected",
    "multiple_faces": "multiple_faces_detected",
    "look_at_camera": "look_at_camera",
    "pose_mismatch": "pose_does_not_match",
    "accepted": "sample_accepted",
}


@dataclass
class SampleVerdict:
    accepted: bool
    guidance: list[str] = field(default_factory=list)
    quality_score: float = 0.0
    face_count: int = 0
    step_index: int = 0
    step_key: str = "front"
    matched_step: bool = False
    observed_direction: str = "front"
    pose_offset_x: float | None = None
    pose_offset_y: float | None = None
    pose_confident: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def guidance_for(detection) -> list[str]:
    """Map engine detection output onto user-facing guidance codes."""
    quality = detection.quality
    if len(detection.faces) > 1:
        return [GUIDANCE["multiple_faces"]]
    if not detection.faces:
        return [GUIDANCE["no_face"]]

    codes = [GUIDANCE_BY_REASON[c] for c in quality.reason_codes if c in GUIDANCE_BY_REASON]
    if not codes and not quality.usable_for_matching:
        codes.append(GUIDANCE["look_at_camera"])
    return codes


def start_enrollment(db: Session, user: User) -> BiometricEnrollment:
    """Begin (or restart) a guided enrollment for this user."""
    repo = ProfileRepository(db)
    if not repo.active_consent(user.id, "biometric"):

        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="Biometric consent is required before enrolling. Please review and grant consent first.",
        )

    open_enrollment = (
        db.query(BiometricEnrollment)
        .filter(
            BiometricEnrollment.user_id == user.id,
            BiometricEnrollment.status == "in_progress",
        )
        .order_by(BiometricEnrollment.created_at.desc())
        .first()
    )
    if open_enrollment is not None:
        if not _is_stale(open_enrollment):
            return open_enrollment
        open_enrollment.status = "abandoned"
        db.flush()

    enrollment = BiometricEnrollment(
        user_id=user.id,
        status="in_progress",
        current_step=0,
        total_steps=len(POSE_STEPS),
        accepted_samples=0,
        rejected_samples=0,
        algo_version=get_engine().algo_version,
        sample_reports=[],
    )
    db.add(enrollment)
    db.commit()
    return enrollment


def add_sample(
    db: Session, user: User, enrollment_id: str, image_b64: str
) -> tuple[BiometricEnrollment, SampleVerdict]:
    """Grade one capture and, if it passes, keep it against the current step."""
    enrollment = db.get(BiometricEnrollment, enrollment_id)
    if enrollment is None or enrollment.user_id != user.id:

        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Enrollment not found"
        )
    if enrollment.status != "in_progress":

        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="This enrollment is no longer active",
        )
    if _is_stale(enrollment):
        enrollment.status = "expired"
        db.commit()

        raise HTTPException(
            status_code=http_status.HTTP_410_GONE,
            detail="This enrollment has expired. Please start again.",
        )

    raw = validate_and_decode_image(image_b64, "image")
    engine = get_engine()
    detection = engine.process(raw)

    step_index = min(enrollment.current_step, len(POSE_STEPS) - 1)
    expected_key = STEP_KEYS[step_index]
    pose = engine.pose(raw, detection.faces[0] if detection.faces else None)

    verdict = SampleVerdict(
        accepted=False,
        quality_score=detection.quality.image_quality_score,
        face_count=len(detection.faces),
        step_index=step_index,
        step_key=expected_key,
        observed_direction=pose.direction,
        pose_offset_x=round(pose.offset_x, 4),
        pose_offset_y=round(pose.offset_y, 4),
        pose_confident=pose.confident,
    )
    codes = guidance_for(detection)
    if codes:
        verdict.guidance = codes
        enrollment.rejected_samples += 1
        _record_report(enrollment, verdict)
        db.commit()
        return enrollment, verdict

    # Pose is advisory, not a gate. The quality gates above are measured and
    # decide usability; the pose reading only tells us whether the person
    # actually followed the instruction. Blocking on it would mean refusing a
    # perfectly usable photo because a luminance-asymmetry proxy disagrees, so
    # a mismatch is reported back as guidance and the step still advances.
    observed_key = direction_against(pose, _baseline_for(enrollment, pose))
    verdict.matched_step = (not pose.confident) or observed_key == expected_key
    if not verdict.matched_step:
        verdict.guidance = [GUIDANCE["pose_mismatch"]]

    vector = engine.embed(raw, detection.faces[0])
    db.add(
        BiometricEnrollmentSample(
            enrollment_id=enrollment.id,
            step_index=step_index,
            step_key=expected_key,
            embedding_blob=encrypt_bytes(serialize_embedding(vector)),
            quality_score=detection.quality.image_quality_score,
            pose_offset_x=pose.offset_x,
            pose_offset_y=pose.offset_y,
            accepted=True,
        )
    )
    enrollment.accepted_samples += 1
    verdict.accepted = True
    if not verdict.guidance:
        verdict.guidance = [GUIDANCE["accepted"]]
    if step_index == 0 and enrollment.baseline_offset_y is None:
        # The first accepted capture is the front view; keep it as this
        # person's reference for the up and down steps.
        enrollment.baseline_offset_x = pose.offset_x
        enrollment.baseline_offset_y = pose.offset_y
    if step_index < len(POSE_STEPS) - 1:
        enrollment.current_step = step_index + 1
    _record_report(enrollment, verdict)
    db.commit()
    return enrollment, verdict


def _baseline_for(enrollment: BiometricEnrollment, pose: PoseEstimate) -> PoseEstimate | None:
    """This person's own front-facing reading, when one has been captured."""
    if enrollment.baseline_offset_y is None:
        return None
    return PoseEstimate(
        offset_x=enrollment.baseline_offset_x or 0.0,
        offset_y=enrollment.baseline_offset_y,
        confident=pose.confident,
    )


def normalized(vector: np.ndarray) -> np.ndarray:
    """Unit-length vector, or zeros if it has no direction to speak of.

    A zero vector has no meaningful normalisation, and dividing by its norm would
    produce NaNs that propagate silently into every score computed later. This
    should not happen for a real descriptor, but the failure mode of an exception
    deep in the matcher is worse than a vector that scores nothing.
    """
    norm = float(np.linalg.norm(vector))
    if norm == 0.0:
        return np.zeros_like(vector)
    return vector / norm


def consistency_report(vectors: list[np.ndarray], engine) -> dict:
    """How much this person's own samples agree with each other.

    Every number here is measured on the samples this enrollment actually
    collected, and every one is reported rather than only the pass/fail, because
    a person whose intra-person similarity is 0.7 when the gate wants 0.62 has
    enrolled a template that will match badly, and the operator should be able to
    see that rather than discover it during an emergency.
    """
    if len(vectors) < 2:
        return {
            "min_pairwise": 1.0,
            "mean_pairwise": 1.0,
            "pairs": 0,
            "threshold": settings.ENROLLMENT_MIN_SELF_SIMILARITY,
        }
    pairs = [
        engine.similarity(vectors[i], vectors[j])
        for i in range(len(vectors))
        for j in range(i + 1, len(vectors))
    ]
    return {
        "min_pairwise": round(min(pairs), 4),
        "mean_pairwise": round(sum(pairs) / len(pairs), 4),
        "pairs": len(pairs),
        "threshold": settings.ENROLLMENT_MIN_SELF_SIMILARITY,
    }


def complete_enrollment(
    db: Session, user: User, enrollment_id: str
) -> dict:
    """Commit the collected samples as the live biometric profile."""
    enrollment = db.get(BiometricEnrollment, enrollment_id)
    if enrollment is None or enrollment.user_id != user.id:

        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Enrollment not found"
        )

    samples = (
        db.query(BiometricEnrollmentSample)
        .filter(
            BiometricEnrollmentSample.enrollment_id == enrollment.id,
            BiometricEnrollmentSample.accepted.is_(True),
        )
        .all()
    )
    if len(samples) < MIN_ACCEPTED_SAMPLES:

        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Only {len(samples)} usable sample(s) captured. "
                f"At least {MIN_ACCEPTED_SAMPLES} clear photos are needed."
            ),
        )

    engine = get_engine()
    vectors = [
        np.frombuffer(decrypt_bytes(s.embedding_blob), dtype=np.float64) for s in samples
    ]

    consistency = consistency_report(vectors, engine)

    # Refuse to build a template from samples that do not agree with each other.
    # Each sample passed the *per-image* quality gates, which say nothing about
    # whether the images are of the same person: four individually good photos of
    # two different faces satisfy every gate in the engine. Only a comparison
    # between the person's own samples catches that, and committing it would
    # create a template that matches neither identity well and, at the review
    # threshold, could match a stranger.
    if consistency["min_pairwise"] < settings.ENROLLMENT_MIN_SELF_SIMILARITY:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "The captured photos do not look like the same person "
                f"(closest pair {consistency['min_pairwise']:.2f}, "
                f"needs {settings.ENROLLMENT_MIN_SELF_SIMILARITY:.2f}). "
                "Please start again and capture all steps in one session, "
                "in the same place."
            ),
        )

    repo = ProfileRepository(db)
    profile = repo.biometric(user.id)
    if profile is None:
        profile = BiometricProfile(user_id=user.id)
        db.add(profile)
    profile.status = "enrolled"
    profile.enrolled_at = datetime.now(UTC)
    db.flush()

    # The version the matcher will look for. Taken from the live engine, not from
    # settings: the two differ on the real engine, and tagging a 128D SFace
    # descriptor with the simulation's string would make it invisible to
    # load_enrolled, so every enrollment would silently fail to match.
    algo_version = engine.algo_version

    # The template is the centroid of this person's samples, L2-normalised
    # because the matcher compares with cosine and an un-normalised mean is not a
    # unit vector. One template instead of N also means N-to-1 comparisons at
    # match time rather than N-to-N, and a single score instead of a max over
    # samples - which is what makes the consistency number above meaningful as a
    # description of the stored template rather than of a discarded input.
    centroid = normalized(np.mean(vectors, axis=0))

    # Re-enrollment replaces the previous templates outright, so a withdrawn
    # consent can never leave an older embedding behind.
    repo.replace_embeddings(
        profile, [encrypt_bytes(serialize_embedding(centroid))], algo_version
    )
    profile.num_samples = len(samples)
    steps_completed = sorted({s.step_key for s in samples})

    enrollment.status = "completed"
    enrollment.completed_at = datetime.now(UTC)

    # Retention. The raw per-sample embeddings existed only to build the
    # centroid; keeping them would leave N extra biometric vectors at rest for
    # the life of the row, from which the original photos' embeddings could be
    # recovered. So they go in the same transaction that commits the template:
    # either both survive or neither does. The enrollment row itself is kept -
    # it is the audit record of what was captured and when - but it retains
    # only per-sample quality and pose reports, never a vector.
    deleted = (
        db.query(BiometricEnrollmentSample)
        .filter(BiometricEnrollmentSample.enrollment_id == enrollment.id)
        .delete(synchronize_session=False)
    )
    db.commit()

    log_user_action(
        db,
        user.id,
        "biometric.enrolled",
        resource_id=profile.id,
        details={
            "samples": len(samples),
            "sample_vectors_purged": deleted,
            "algo": algo_version,
            "guided": True,
            "steps": steps_completed,
            # Recorded because it is the number that will explain a bad match
            # later, and it is not recoverable from the stored template.
            "intra_person_similarity": consistency["min_pairwise"],
        },
        commit=False,
    )
    db.commit()

    return {
        "status": "enrolled",
        "num_samples": len(samples),
        "algo_version": algo_version,
        "enrolled_at": profile.enrolled_at,
        "steps_completed": steps_completed,
        "consistency": consistency,
    }


def abort_enrollment(db: Session, user: User, enrollment_id: str) -> None:
    enrollment = db.get(BiometricEnrollment, enrollment_id)
    if enrollment is None or enrollment.user_id != user.id:
        return
    enrollment.status = "abandoned"
    db.commit()


def enrollment_state(enrollment: BiometricEnrollment) -> dict:
    """Serializable progress, including what the client should ask for next."""
    step_index = min(enrollment.current_step, len(POSE_STEPS) - 1)
    return {
        "enrollment_id": enrollment.id,
        "status": enrollment.status,
        "current_step": step_index,
        "total_steps": len(POSE_STEPS),
        "accepted_samples": enrollment.accepted_samples,
        "rejected_samples": enrollment.rejected_samples,
        "min_samples": MIN_ACCEPTED_SAMPLES,
        "steps": [
            {
                "index": i,
                "key": s["key"],
                "pose": s["pose"],
                "done": i < step_index
                or (i == step_index and enrollment.status == "completed"),
            }
            for i, s in enumerate(POSE_STEPS)
        ],
        "current_instruction": STEP_INSTRUCTIONS[STEP_KEYS[step_index]],
        "can_complete": enrollment.accepted_samples >= MIN_ACCEPTED_SAMPLES,
    }


def _record_report(enrollment: BiometricEnrollment, verdict: SampleVerdict) -> None:
    """Keep the last 20 sample verdicts for the progress panel."""
    reports = list(enrollment.sample_reports or [])
    reports.append(verdict.to_dict())
    enrollment.sample_reports = reports[-20:]


def _is_stale(enrollment: BiometricEnrollment) -> bool:
    created = enrollment.created_at
    if created is None:
        return False
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return datetime.now(UTC) - created > timedelta(minutes=ENROLLMENT_TTL_MINUTES)
