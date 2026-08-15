"""Unit tests for the biometric engine (simulation mode): embeddings, quality,
face detection and discrimination."""
from __future__ import annotations

from app.services.demo.demo_images import render_face, to_bytes
from app.services.identification.engine import analyze_quality, detect_faces, extract_embedding, get_engine

SAME_IDENTITY = "aarav-kumar-demo"
OTHER_IDENTITY = "priya-sharma-demo"
UNKNOWN_IDENTITY = "enroll-demo-charlie-99"


def embed(identity: str, **kwargs):
    engine = get_engine()
    raw = to_bytes(render_face("unit-" + identity + "-sample", identity=identity, **kwargs))
    det = engine.process(raw)
    assert det.faces, f"expected a face for {identity} ({kwargs})"
    return engine.embed(raw, det.faces[0]), det


def test_engine_runs_in_simulation_or_opencv_mode():
    engine = get_engine()
    assert engine.mode in ("simulation", "opencv")


def test_embedding_dimensionality():
    vec, _ = embed(SAME_IDENTITY)
    assert vec.shape[0] == 320


def test_same_identity_high_similarity():
    a, _ = embed(SAME_IDENTITY, noise=0.03)
    b, _ = embed(SAME_IDENTITY, noise=0.07)
    score = get_engine().similarity(a, b)
    assert score >= 0.9


def test_cross_identity_lower_similarity():
    a, _ = embed(SAME_IDENTITY)
    b, _ = embed(OTHER_IDENTITY)
    same, _ = embed(SAME_IDENTITY, noise=0.05)
    cross = get_engine().similarity(a, b)
    assert cross < get_engine().similarity(a, same)
    assert cross < 0.85


def test_unknown_person_below_threshold():
    a, _ = embed(SAME_IDENTITY)
    u, _ = embed(UNKNOWN_IDENTITY)
    score = get_engine().similarity(a, u)
    assert score < 0.62


def test_quality_accepts_clean_image():
    _, det = embed(SAME_IDENTITY)
    assert det.quality.usable_for_matching is True
    assert det.quality.image_quality_score >= 0.5


def test_quality_rejects_blurred_image():
    raw = to_bytes(render_face("unit-blur", identity=SAME_IDENTITY, blur=True))
    engine = get_engine()
    det = engine.process(raw)
    assert det.quality.usable_for_matching is False
    assert any("blurry" in r.lower() for r in det.quality.reasons)


def test_quality_rejects_combined_degradation():
    raw = to_bytes(render_face("unit-comb", identity=SAME_IDENTITY, dark=True, occluded=0.5))
    det = get_engine().process(raw)
    assert det.quality.usable_for_matching is False
    assert det.quality.reasons


def test_detect_multiple_faces():
    image = render_face("unit-multi", identity=SAME_IDENTITY, faces=2)
    boxes, source = detect_faces(image)
    assert len(boxes) == 2
    assert source in ("simulation", "opencv-haar")


def test_detect_no_face():
    image = render_face("unit-none", identity=SAME_IDENTITY, faces=0)
    boxes, _ = detect_faces(image)
    assert len(boxes) == 0


def test_quality_analyze_multi_face():
    image = render_face("unit-multi2", identity=SAME_IDENTITY, faces=2)
    boxes, _ = detect_faces(image)
    report = analyze_quality(image, boxes)
    assert report.usable_for_matching is False
    assert any("Multiple" in r for r in report.reasons)


def test_embedding_stable_across_degradation():
    """Same identity under mild noise -> small distance."""
    a, _ = embed(SAME_IDENTITY, noise=0.10)
    b, _ = embed(SAME_IDENTITY, noise=0.20)
    score = get_engine().similarity(a, b)
    assert score >= 0.9
