"""Biometric engine for TRAYA.

This module is the *interface* the platform depends on. The arithmetic behind it
lives in :mod:`app.services.identification.providers`, and the engine's job is
to route to whichever provider is configured without any caller being able to
tell or to care.

Two providers exist:

* **real** - YuNet detects faces and returns five landmarks, a similarity
  transform removes roll and scale, and SFace produces a 128-dimensional
  L2-normalised descriptor. Selected by ``BIOMETRIC_ENGINE=auto`` when the model
  files are present, or by ``yunet`` unconditionally.
* **simulation** - the pre-Phase-5 behaviour, kept and clearly labelled. Twelve
  brightness measurements zero-padded to ``EMBEDDING_DIM``. Selected by
  ``simulation``, and chosen automatically - with a warning - when the model
  files are absent.

``is_simulation`` exists so no caller can quietly present a simulation result as
a biometric. Every API result carries ``engine_mode`` and ``demo_mode``, and the
UI renders a disclosure banner. **Embeddings never leave the backend.**

The public names here - ``decode_image``, ``detect_faces``, ``extract_embedding``,
``estimate_pose``, ``compare``, ``analyze_quality``, ``FaceBox``,
``QualityReport``, ``DetectionResult``, ``PoseEstimate``, ``BiometricEngine``,
``get_engine`` - are unchanged from before Phase 5 and are re-exported from
:mod:`app.services.identification.providers` where they now live.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from PIL import Image, ImageOps

from app.config.settings import settings
from app.services.identification.providers import (
    AlignedFace,
    FaceBox,
    FaceEmbeddingProvider,
    SimulationProvider,
    YuNet128Provider,
    decode_image,
    get_provider,
    models_present,
    reset_provider,
    skin_mask,
    to_gray_np,
    variance_of_laplacian,
)

logger = logging.getLogger("traya.biometric")

__all__ = [
    "AlignedFace",
    "BiometricEngine",
    "DetectionResult",
    "FaceBox",
    "PoseEstimate",
    "QualityReport",
    "analyze_quality",
    "compare",
    "decode_image",
    "detect_faces",
    "extract_embedding",
    "get_engine",
    "get_provider",
    "estimate_pose",
    "pose_step_key",
    "models_present",
]


# --------------------------------------------------------------------------
# Quality analysis
# --------------------------------------------------------------------------
@dataclass
class QualityReport:
    image_quality_score: float
    face_visibility_score: float
    occlusion_score: float
    blur_score: float
    lighting_score: float
    usable_for_matching: bool
    reasons: list[str] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "image_quality_score": round(self.image_quality_score, 3),
            "face_visibility_score": round(self.face_visibility_score, 3),
            "occlusion_score": round(self.occlusion_score, 3),
            "blur_score": round(self.blur_score, 3),
            "lighting_score": round(self.lighting_score, 3),
            "usable_for_matching": self.usable_for_matching,
            "reasons": self.reasons,
            "reason_codes": self.reason_codes,
        }


@dataclass
class DetectionResult:
    faces: list[FaceBox]
    quality: QualityReport
    source: str


def analyze_quality(image: Image.Image, face_boxes: list[FaceBox]) -> QualityReport:
    """Score a capture. Provider-independent, and deliberately unchanged.

    The sub-scores are image measurements - blur, lighting, contrast, face size,
    obstruction - so they mean the same thing whichever detector found the face.
    What *did* change in Phase 5 is where ``density`` comes from: the simulation
    detector measured skin coverage inside the box, and a real detector does not
    produce that measurement. When a real box carries no density, face
    visibility is computed from the face's share of the frame alone and occlusion
    is reported as unknown-but-assumed-clear rather than invented from skin
    pixels that were never measured. Guessing an occlusion score from a crop of
    someone's face is not a quality assessment.
    """
    gray = to_gray_np(image)
    reasons: list[str] = []

    blur_var = variance_of_laplacian(gray)
    blur_score = min(1.0, max(0.0, math.log1p(blur_var) / math.log(500)))

    mean = float(gray.mean())
    std = float(gray.std())
    lighting_score = 1.0 - min(1.0, abs(mean - 127) / 127)
    contrast_score = min(1.0, std / 60)

    image_quality_score = 0.40 * blur_score + 0.35 * lighting_score + 0.25 * contrast_score

    face_visibility = 0.0
    occlusion = 1.0
    measured_density = False
    img_area = image.width * image.height
    if face_boxes:
        best = max(face_boxes, key=lambda f: f.area)
        size_score = min(1.0, (best.area / img_area) * 12)
        density = best.density
        if density is None:
            density = min(1.0, (best.skin_ratio * img_area) / best.area)
        else:
            measured_density = True
        if measured_density:
            face_visibility = min(1.0, 0.55 * min(1.0, density * 1.15) + 0.45 * size_score)
            occlusion = min(1.0, max(0.0, 1.0 - density * 0.85))

    usable = (
        image_quality_score >= 0.5
        and face_visibility >= 0.45
        and occlusion <= 0.75
        and len(face_boxes) == 1
    )

    if blur_var < 30:
        reasons.append("Image is too blurry")
    if abs(mean - 127) > 80:
        reasons.append("Lighting is too dark or too bright")
    if not face_boxes:
        reasons.append("No face detected")
    elif len(face_boxes) > 1:
        reasons.append("Multiple faces detected")
    if occlusion > 0.75 and measured_density:
        reasons.append("Face is significantly obstructed")
    if face_boxes and face_boxes[0].area / (image.width * image.height) < 0.02:
        reasons.append("Face is too small in the frame")

    # Stable machine-readable codes, kept in step with the sub-scores above.
    # Consumers (guided enrollment, the emergency quality panel) map these to
    # localized guidance instead of re-deriving thresholds of their own, so a
    # capture is never accepted in one place and rejected in another.
    reason_codes: list[str] = []
    if not face_boxes:
        reason_codes.append("no_face")
    elif len(face_boxes) > 1:
        reason_codes.append("multiple_faces")
    if blur_score < 0.35:
        reason_codes.append("blurry")
    if lighting_score < 0.45:
        reason_codes.append("too_dark")
    if face_boxes and face_boxes[0].area / img_area < 0.02:
        reason_codes.append("face_too_small")
    if occlusion > 0.75 and measured_density:
        reason_codes.append("occluded")
    if not reason_codes and not usable:
        reason_codes.append("low_quality")

    return QualityReport(
        image_quality_score=round(image_quality_score, 3),
        face_visibility_score=round(face_visibility, 3),
        occlusion_score=round(occlusion, 3),
        blur_score=round(blur_score, 3),
        lighting_score=round(lighting_score, 3),
        usable_for_matching=usable,
        reasons=reasons,
        reason_codes=reason_codes,
    )


# --------------------------------------------------------------------------
# Detection
# --------------------------------------------------------------------------
def detect_faces(image: Image.Image) -> tuple[list[FaceBox], str]:
    """Return face boxes and the source that produced them.

    ``source`` is now the meaningful answer to "how was this face found": either
    ``yunet`` for the real detector or ``simulation``. The old ``opencv-haar``
    value is gone because that path could not run - OpenCV 5 removed the cascade
    API it required - so returning it would have been a false provenance claim.
    """
    provider = get_provider()
    return provider.detect(image), provider.mode


# --------------------------------------------------------------------------
# Embedding
# --------------------------------------------------------------------------
def extract_embedding(image: Image.Image, box: FaceBox | None = None) -> np.ndarray:
    """Embed a face crop. Delegates to the active provider.

    Real provider: the box is used to align against the five landmarks before
    SFace sees the crop, and the result is 128-dimensional. Simulation provider:
    the historical twelve-feature vector.
    """
    return get_provider().embed(image, box)


# --------------------------------------------------------------------------
# Pose estimation
# --------------------------------------------------------------------------
@dataclass
class PoseEstimate:
    """Coarse head-orientation reading for guided enrollment.

    Two sources, one shape, and the two are **not** equally meaningful.

    **With landmarks (real engine).** YuNet's five points give a geometric
    reading. ``roll_degrees`` is absolute and reliable - the eye line's angle is
    a direct measurement of a physical line. ``offset_y`` behaves as an absolute
    reading and measured near zero on three real frontal photographs.
    ``offset_x`` is a yaw proxy that is **not** absolute: a real nose tip is not
    exactly centred between that person's own eyes, and the offset is a property
    of the face rather than of the head's angle. Judged on its own it reported
    every one of three frontal faces as "left", so it must be read against a
    baseline from the same person. :func:`direction_against` enforces that and
    returns ``unknown`` rather than a guess.

    **Without landmarks (simulation engine).** Normalised brightness asymmetry
    between the halves of the crop. Documented in ADR 0001; it measures how
    lopsided the dark regions are, not where the head is pointing, and it says
    so. Its left/right reading is signed by the crop, so it does not need a
    baseline for horizontal.

    ``confident`` is False when the reading cannot be trusted. Callers must treat
    a low-confidence reading as "unknown" and must not use it to reject an
    otherwise good capture.
    """

    offset_x: float
    offset_y: float
    confident: bool
    reason: str = ""
    #: Present only for the real engine. Roll is the measured eye-line angle;
    #: source is "landmarks" or "asymmetry" so a consumer can tell a geometric
    #: reading from a brightness heuristic.
    roll_degrees: float | None = None
    source: str = "asymmetry"

    @property
    def direction(self) -> str:
        """Coarse bucket: front, left, right, up, down, or unknown.

        Returns ``unknown`` rather than ``front`` when the reading is not
        trustworthy, so an unmeasurable pose is never mistaken for a frontal
        one.
        """
        if not self.confident:
            return "unknown"
        return direction_against(self, baseline=None)

    @property
    def is_frontal(self) -> bool:
        return self.confident and self.direction == "front"


# Normalised asymmetry above which a head counts as turned. Chosen in the gap
# between the frontal band (<= 0.016) and the clearly-turned band (>= 0.050)
# so the threshold does not depend on a particular face or capture seed.
TURNED_OFFSET = 0.03
# Beyond this, one side holds nearly all the energy and the split is no longer
# describing a head.
MAX_MEASURABLE_ASYMMETRY = 0.6


def direction_against(pose: PoseEstimate, baseline: "PoseEstimate | None") -> str:
    """Bucket a reading into front/left/right/up/down.

    Horizontal needs no baseline for the *asymmetry* reader, whose left/right
    asymmetry is a relative measure of the crop that happens to be signed. For
    the *landmark* reader it does need one, for a measured reason: the nose tip
    of a real face sits a little off the midpoint of its own eyes, and by an
    amount that varies per person. Measured on three real photographs the raw
    yaw proxy came out at +0.43, +0.45 and +0.53 - a per-identity offset three
    times larger than the turned threshold. Reported absolutely, that would call
    every face "left", including frontal ones, and Phase 6's guided wizard would
    ask a person to turn their head when they were already facing the camera.

    So a landmark reading with no baseline returns ``unknown``. ``unknown`` is
    the honest answer: the measurement happened, and it is not interpretable
    without knowing where this particular person's centre is. The vertical axis
    behaves the same way for both readers, as it always has.
    """
    if not pose.confident:
        return "front"
    usable_baseline = baseline is not None and baseline.confident

    if pose.source == "landmarks":
        if not usable_baseline:
            return "unknown"
        # Both axes are read as a *delta* from this person's own baseline,
        # because both carry a per-identity offset. Comparing the raw offset_x
        # against the threshold here would reintroduce exactly the bias the
        # unknown-above rule exists to suppress.
        turn = pose.offset_x - baseline.offset_x
        if abs(turn) >= TURNED_OFFSET:
            return "left" if turn > 0 else "right"
        pitch = pose.offset_y - baseline.offset_y
        if abs(pitch) >= TURNED_OFFSET * 1.5:
            return "down" if pitch > 0 else "up"
        return "front"

    if abs(pose.offset_x) >= TURNED_OFFSET:
        return "left" if pose.offset_x > 0 else "right"
    if usable_baseline:
        pitch = pose.offset_y - baseline.offset_y
        if abs(pitch) >= TURNED_OFFSET * 1.5:
            return "down" if pitch > 0 else "up"
    return "front"


def _asymmetry(values: np.ndarray) -> float:
    """Signed energy imbalance of an array split down its first axis."""
    half = values.shape[0] // 2
    low = float(values[:half].sum())
    high = float(values[half:].sum())
    total = low + high
    if total < 1e-6:
        return 0.0
    return (low - high) / total


def estimate_pose(image: Image.Image, box: FaceBox | None = None) -> PoseEstimate:
    """Read head orientation. Landmarks when available, asymmetry otherwise."""
    if box is not None and box.has_landmarks:
        reading = _pose_from_landmarks(box)
        if reading is not None:
            return reading
    return _pose_from_asymmetry(image, box)


def _pose_from_landmarks(box: FaceBox) -> PoseEstimate | None:
    """Geometric pose from YuNet's five points.

    Three readings, and they are not equally trustworthy, so they are not
    reported as if they were:

    ``roll_degrees``
        The angle of the eye line. **Absolute and reliable.** It is a direct
        measurement of a physical line and needs no reference, which is why it
        is the reading that matters for capture guidance.

    ``offset_y``
        How far the nose tip sits from midway between the eye line and the mouth
        line, in eye separations. Near zero on a level head, and it measured
        between -0.004 and +0.016 on three real frontal photographs, so it
        behaves as an absolute reading and needs no baseline.

    ``offset_x``
        How far the nose tip sits to one side of the eye midpoint, in eye
        separations. A yaw proxy, and **not absolute**: a real nose tip is not
        exactly centred between that person's own eyes, and the offset is a
        property of the face rather than the head's angle. Callers must judge it
        against a baseline, which is what :func:`direction_against` enforces.
    """
    landmarks = box.landmarks
    if len(landmarks) != 5:
        return None
    right_eye, left_eye, nose, right_mouth, left_mouth = landmarks

    eye_separation = float(np.hypot(left_eye[0] - right_eye[0], left_eye[1] - right_eye[1]))
    if eye_separation < 6.0:
        # Too small to divide by. A confident reading here would be a rounding
        # artefact, so it is reported as unmeasurable instead.
        return PoseEstimate(0.0, 0.0, False, "landmarks_too_small", source="landmarks")

    eye_mid_x = (left_eye[0] + right_eye[0]) / 2.0
    eye_mid_y = (left_eye[1] + right_eye[1]) / 2.0
    mouth_mid_y = (right_mouth[1] + left_mouth[1]) / 2.0

    offset_x = 2.0 * (nose[0] - eye_mid_x) / eye_separation
    offset_y = (nose[1] - (eye_mid_y + mouth_mid_y) / 2.0) / eye_separation

    roll = math.degrees(
        math.atan2(left_eye[1] - right_eye[1], left_eye[0] - right_eye[0])
    )
    confident = (
        abs(offset_x) < MAX_MEASURABLE_ASYMMETRY
        and abs(offset_y) < MAX_MEASURABLE_ASYMMETRY
        and abs(roll) < 60.0
    )
    return PoseEstimate(
        offset_x=round(float(offset_x), 4),
        offset_y=round(float(offset_y), 4),
        confident=confident,
        reason="" if confident else "outside_measurable_range",
        roll_degrees=round(float(roll), 2),
        source="landmarks",
    )


def _pose_from_asymmetry(image: Image.Image, box: FaceBox | None = None) -> PoseEstimate:
    """Read orientation from how lopsided the dark regions of the crop are.

    HONEST LIMITATION, unchanged from before Phase 5: this is not a
    landmark-based solver. It measures the darkness energy of one half of the
    crop against the other, per axis. It is a heuristic, and a real engine should
    not reach it at all - the path exists for the simulation provider, which has
    no landmarks.
    """
    crop = image
    if box is not None:
        x, y = max(0, box.x), max(0, box.y)
        w, h = min(image.width - x, box.w), min(image.height - y, box.h)
        if w > 4 and h > 4:
            crop = image.crop((x, y, x + w, y + h))

    if crop.width < 24 or crop.height < 24:
        return PoseEstimate(0.0, 0.0, False, "face_too_small")

    lum = np.asarray(ImageOps.grayscale(crop).resize((24, 24)), dtype=np.float32) / 255.0
    if float(lum.std()) < 0.04:
        # A flat crop carries no structure to measure; lighting, not pose.
        return PoseEstimate(0.0, 0.0, False, "low_contrast")

    darkness = np.clip(1.0 - lum, 0.0, None)
    if float(darkness.sum()) < 1e-3:
        return PoseEstimate(0.0, 0.0, False, "no_structure")

    # columns -> left/right, rows -> top/bottom
    offset_x = _asymmetry(darkness.sum(axis=0))
    offset_y = _asymmetry(darkness.sum(axis=1))

    confident = (
        abs(offset_x) < MAX_MEASURABLE_ASYMMETRY
        and abs(offset_y) < MAX_MEASURABLE_ASYMMETRY
    )
    reason = "" if confident else "one_side_dominated"
    return PoseEstimate(
        offset_x=offset_x, offset_y=offset_y, confident=confident, reason=reason
    )


def pose_step_key(pose: PoseEstimate) -> str:
    """Bucket a reading into the enrollment step it most resembles."""
    return pose.direction


# --------------------------------------------------------------------------
# Comparison
# --------------------------------------------------------------------------
def compare(embedding_a: np.ndarray, embedding_b: np.ndarray) -> float:
    """Similarity in [0, 1], delegated to the active provider.

    The two providers score differently on purpose. The real one uses cosine
    similarity on L2-normalised descriptors, which is what SFace was trained
    for. The simulation one keeps the distance-based scale it always had, because
    its vectors are neither normalised nor trained and rescaling them would
    invalidate the thresholds and the measured impostor scores.
    """
    return get_provider().similarity(embedding_a, embedding_b)


def get_template() -> np.ndarray:
    """A zero vector in the active provider's dimension."""
    return np.zeros(get_provider().dimension)


# --------------------------------------------------------------------------
# Facade
# --------------------------------------------------------------------------
class BiometricEngine:
    """Single entry point used by the identification pipeline."""

    #: Identifies the scoring implementation, independently of how it was
    #: reached. A stored embedding is only comparable against an embedding
    #: produced by the same version, so the matcher filters on this: a 128D real
    #: descriptor must never be compared against a 320D simulated one.
    @property
    def algo_version(self) -> str:
        return get_provider().version

    @property
    def mode(self) -> str:
        return get_provider().mode

    @property
    def dimension(self) -> int:
        return get_provider().dimension

    @property
    def is_simulation(self) -> bool:
        return get_provider().is_simulation

    def process(self, image_bytes: bytes | str) -> DetectionResult:
        image = decode_image(image_bytes)
        provider = get_provider()
        faces = provider.detect(image)
        quality = analyze_quality(image, faces)
        if not faces:
            quality.usable_for_matching = False
        return DetectionResult(faces=faces, quality=quality, source=provider.mode)

    def embed(self, image_bytes: bytes | str, box: FaceBox | None = None) -> np.ndarray:
        image = decode_image(image_bytes)
        return get_provider().embed(image, box)

    def pose(self, image_bytes: bytes | str, box: FaceBox | None = None) -> PoseEstimate:
        image = decode_image(image_bytes)
        return estimate_pose(image, box)

    def similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        return compare(a, b)


_engine: BiometricEngine | None = None


def get_engine() -> BiometricEngine:
    global _engine
    if _engine is None:
        _engine = BiometricEngine()
    return _engine
