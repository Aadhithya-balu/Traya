"""The real biometric engine: YuNet detection, landmark alignment, SFace 128D.

Every test here needs the model files, so the whole module skips when they are
absent. That is deliberate and is *not* a way of making a failure disappear:
``fetch_required`` fails the run when the models are missing and the suite is
running on the machine where they are expected, and skips only where they never
were. ``BIOMETRIC_ENGINE=yunet`` is set at import so these tests can never
silently fall through to the simulation and pass for the wrong reason - the
failure that matters most in this project is a real-engine test that quietly
tested a fake engine.

The numbers asserted are measured on the three photographs in
``tests/fixtures/faces`` and are recorded in ``docs/MODEL_EVALUATION.md``. They
are not an accuracy claim: three photographs of two people cannot support a
false-match rate, and no threshold in this project is derived from them. What
they do establish is that the engine separates two identities, that it produces
a real 128-dimensional descriptor, and that alignment does the job it exists for.
"""
from __future__ import annotations

import os
import pathlib

import pytest
from PIL import Image

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "faces"

from app.config.settings import settings  # noqa: E402
from app.services.identification import providers  # noqa: E402
from app.services.identification.engine import (  # noqa: E402
    BiometricEngine,
    PoseEstimate,
    direction_against,
    estimate_pose,
    get_provider,
)

# The photographs are committed, but the 38 MB of model weights are not: they are
# fetched by scripts/fetch_biometric_models.py. So this module skips where the
# weights are absent, and says why.
pytestmark = pytest.mark.skipif(
    not (FIXTURES / "same-person-a.png").exists() or not providers.models_present(),
    reason="real engine needs tests/fixtures/faces and models from "
    "scripts/fetch_biometric_models.py",
)

# Measured, not assumed. See docs/MODEL_EVALUATION.md.
SAME_IDENTITY = 0.8977
CROSS_IDENTITY_MAX = 0.2792


@pytest.fixture(scope="module")
def provider():
    """Resolve the real provider, then put the simulation back.

    Two things have to be undone, and both are load-bearing.

    `settings` is a pydantic object built at import time, so it is mutated
    directly here - assigning `os.environ["BIOMETRIC_ENGINE"]` after that point
    does nothing at all, which is the trap this fixture is built around. And
    `get_provider` caches for the life of the process, so without `reset_provider`
    the real engine would still be installed for every module that runs after
    this one, alphabetically `test_registration` and `test_visual_design` -
    which would be the tests to fail, nowhere near the cause.
    """
    if not providers.models_present():
        pytest.skip("model files absent")
    previous = settings.BIOMETRIC_ENGINE
    settings.BIOMETRIC_ENGINE = "yunet"
    providers.reset_provider()
    try:
        yield get_provider(reload=True)
    finally:
        settings.BIOMETRIC_ENGINE = previous
        providers.reset_provider()


def load(name: str) -> Image.Image:
    return Image.open(FIXTURES / name).convert("RGB")


def describe(provider, name: str):
    """Detect and embed one fixture. Asserts a face was found."""
    image = load(name)
    faces = provider.detect(image)
    assert faces, f"{name}: YuNet found no face in a real photograph"
    box = faces[0]
    return provider.embed(image, box), box, image


# --------------------------------------------------------------------------
# The engine is real, and says so
# --------------------------------------------------------------------------
def test_engine_resolves_to_the_real_provider(provider):
    assert provider.is_simulation is False
    assert provider.mode == "yunet"
    assert provider.name == "sface"
    assert BiometricEngine().is_simulation is False


def test_embedding_is_128_dimensional_and_not_padded(provider):
    vector, _, _ = describe(provider, "same-person-a.png")
    assert vector.shape == (128,)
    # The pre-Phase-5 engine was twelve real numbers and 308 zeros. Every
    # coordinate being non-zero is what distinguishes a real descriptor from the
    # padded one it replaced, and it is the specific thing a reader of the old
    # code would be checking for.
    assert int((vector != 0).sum()) == 128
    assert provider.dimension == 128


def test_embedding_is_l2_normalised(provider):
    import numpy as np

    vector, _, _ = describe(provider, "same-person-a.png")
    assert float(np.linalg.norm(vector)) == pytest.approx(1.0, abs=1e-9)


def test_model_provenance_is_pinned(provider):
    """Version strings are what make a stored template comparable or not."""
    assert provider.version == "sface-128d-v1"
    assert provider.preprocessing_version == "aligned112-rgb-v1"
    assert BiometricEngine().algo_version == provider.version


# --------------------------------------------------------------------------
# Real detection
# --------------------------------------------------------------------------
def test_detects_a_real_face_with_a_real_box(provider):
    _, box, image = describe(provider, "same-person-a.png")
    assert box.source == "yunet"
    assert box.score > 0.8, f"detector confidence was only {box.score}"
    assert box.w > 0 and box.h > 0
    # Inside the frame, and not the whole frame.
    assert 0 <= box.x < image.width and 0 <= box.y < image.height
    assert box.area < image.width * image.height


def test_detection_returns_five_landmarks(provider):
    _, box, _ = describe(provider, "same-person-a.png")
    assert box.has_landmarks
    assert len(box.landmarks) == 5
    # Eyes are the top two and share a row; that ordering is what the alignment
    # step relies on.
    (right_eye, left_eye) = box.landmarks[0], box.landmarks[1]
    assert abs(right_eye[1] - left_eye[1]) < box.h * 0.35


def test_landmarks_lie_inside_the_face_box(provider):
    _, box, _ = describe(provider, "same-person-a.png")
    for x, y in box.landmarks:
        assert box.x <= x <= box.x + box.w, "landmark outside the detected face"
        assert box.y <= y <= box.y + box.h, "landmark outside the detected face"


def test_detector_reports_no_face_on_a_blank_image(provider):
    blank = Image.new("RGB", (320, 240), (250, 250, 250))
    assert provider.detect(blank) == []


# --------------------------------------------------------------------------
# Alignment
# --------------------------------------------------------------------------
def test_alignment_corrects_roll(provider):
    """The point of alignment: roll must stop mattering.

    Measured on the fixture, with the face region upscaled so detection is not
    the limiting factor:

        roll    aligned    unaligned box crop
          0      1.0000          0.3791
         10      0.9529          0.4732
         20      0.9192          0.3581

    The aligned column holds above 0.91 out to 20 degrees while the unaligned one
    never rises above 0.48. Without this the descriptor would be a function of
    how the phone was held.
    """
    image = load("same-person-a.png")
    box = provider.detect(image)[0]
    margin = 60
    face = image.crop(
        (
            max(0, box.x - margin),
            max(0, box.y - margin),
            min(image.width, box.x + box.w + margin),
            min(image.height, box.y + box.h + margin),
        )
    ).resize((480, 480), Image.BICUBIC)
    reference = provider.embed(face, provider.detect(face)[0])

    for angle in (0, 10, 20):
        rolled = (
            face.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=(240, 240, 240))
            if angle
            else face
        )
        rolled_box = provider.detect(rolled)
        assert rolled_box, f"no face detected at {angle} degrees of roll"
        aligned_similarity = provider.similarity(reference, provider.embed(rolled, rolled_box[0]))
        naive_similarity = provider.similarity(
            reference, provider.embed(provider._box_crop(rolled, rolled_box[0]), None)
        )
        assert aligned_similarity > 0.90, (
            f"aligned similarity fell to {aligned_similarity:.4f} at {angle} degrees"
        )
        assert aligned_similarity > naive_similarity + 0.30, (
            f"alignment did not earn its place at {angle} degrees: "
            f"aligned {aligned_similarity:.4f} vs unaligned {naive_similarity:.4f}"
        )


def test_alignment_reports_the_roll_it_removed(provider):
    image = load("same-person-a.png")
    box = provider.detect(image)[0]
    aligned = provider.align(image, box)
    assert aligned.image.size == (112, 112)
    rolled = image.rotate(20, resample=Image.BICUBIC, expand=True, fillcolor=(240, 240, 240))
    rolled_box = provider.detect(rolled)[0]
    assert provider.align(rolled, rolled_box).roll_degrees is not None


# --------------------------------------------------------------------------
# Similarity separates identities
# --------------------------------------------------------------------------
def test_same_identity_beats_cross_identity(provider):
    a, _, _ = describe(provider, "same-person-a.png")
    b, _, _ = describe(provider, "same-person-b.png")
    other, _, _ = describe(provider, "other-person.png")

    same = provider.similarity(a, b)
    cross_ab = provider.similarity(a, other)
    cross_bo = provider.similarity(b, other)

    assert same == pytest.approx(SAME_IDENTITY, abs=0.02)
    assert max(cross_ab, cross_bo) == pytest.approx(CROSS_IDENTITY_MAX, abs=0.02)
    assert same > max(cross_ab, cross_bo) + 0.5, (
        f"same-identity {same:.4f} is not clearly above cross-identity "
        f"{max(cross_ab, cross_bo):.4f}"
    )


def test_similarity_is_symmetric_and_bounded(provider):
    a, _, _ = describe(provider, "same-person-a.png")
    other, _, _ = describe(provider, "other-person.png")
    assert provider.similarity(a, other) == pytest.approx(provider.similarity(other, a))
    assert 0.0 <= provider.similarity(a, other) <= 1.0


def test_similarity_refuses_vectors_from_a_different_engine(provider):
    """128-dimensional against 320-dimensional is an error, not a low score."""
    import numpy as np

    real = describe(provider, "same-person-a.png")[0]
    simulated = np.zeros(settings.EMBEDDING_DIM)
    with pytest.raises(ValueError, match="different engine build"):
        provider.similarity(real, simulated)


# --------------------------------------------------------------------------
# Pose from landmarks
# --------------------------------------------------------------------------
def test_pose_comes_from_landmarks_and_keeps_the_asymmetry_reader_available(provider):
    _, box, image = describe(provider, "same-person-a.png")
    pose = estimate_pose(image, box)
    assert pose.source == "landmarks"
    assert pose.confident is True
    assert pose.roll_degrees is not None
    # Without landmarks the same engine falls back to the brightness heuristic.
    bare = box.__class__(x=box.x, y=box.y, w=box.w, h=box.h)
    assert estimate_pose(image, bare).source == "asymmetry"


def test_landmark_yaw_is_not_absolute_and_says_unknown_without_a_baseline(provider):
    """The bias that forced this rule, recorded as a test.

    Three frontal faces from three different people measured +0.43, +0.45 and
    +0.53 on the raw yaw proxy - all of them "left" if read absolutely, and all
    of them far over the turned threshold of 0.03. So a landmark reading with no
    baseline must return unknown rather than a direction, and must become
    interpretable once the same person's own frontal reading is supplied.
    """
    _, box, image = describe(provider, "same-person-a.png")
    pose = estimate_pose(image, box)

    # The bias is real and large, which is the whole reason for the rule.
    assert abs(pose.offset_x) > 0.3, (
        f"expected the per-identity yaw bias to exceed 0.3, measured {pose.offset_x}"
    )
    assert pose.direction == "unknown", (
        "a landmark reading with no baseline must not claim a direction"
    )

    # With this person's own frontal reading as the baseline, the same capture is
    # read as level, because it *is* their frontal capture.
    baseline = PoseEstimate(
        offset_x=pose.offset_x, offset_y=pose.offset_y, confident=True, source="landmarks"
    )
    # With a baseline equal to the current reading, the horizontal delta is
    # zero, so it should return front.
    assert direction_against(pose, baseline) == "front"

    # And a capture genuinely turned relative to that baseline is detected.
    turned = PoseEstimate(
        offset_x=pose.offset_x + 0.25, offset_y=pose.offset_y, confident=True, source="landmarks"
    )
    assert direction_against(turned, baseline) == "left"


def test_roll_is_absolute_and_needs_no_baseline(provider):
    """Roll is a measurement of a line, so it stands on its own."""
    _, box, image = describe(provider, "same-person-a.png")
    pose = estimate_pose(image, box)
    assert abs(pose.roll_degrees) < 15.0, f"fixture should be near level, got {pose.roll_degrees}"
    assert pose.roll_degrees is not None
    # And it is not merely the asymmetry reader wearing a different name.
    assert pose.source == "landmarks"
