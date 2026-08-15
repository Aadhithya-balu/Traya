"""Biometric engine for TRAYA.

Two operating modes (selected by `settings.BIOMETRIC_ENGINE`):

* ``simulation``  – deterministic, dependency-light pipeline. Face location is
  approximated from skin-tone segmentation and embeddings are stable
  ``numpy`` vectors derived from the normalized face crop. Clearly labelled
  DEMO/SIMULATION. Used when heavy ML dependencies are not installed.
* ``opencv``      – uses OpenCV's Haar cascade for real face detection when
  ``cv2`` is importable; embeddings still use the deterministic vectorizer.
* ``auto``        – uses OpenCV when available, otherwise simulation.

The engine is intentionally isolated behind a small interface
(``detect`` / ``embed`` / ``compare`` / ``analyze``) so a production model
(InsightFace, face_recognition, DeepFace, ...) can be swapped in without
touching the rest of the platform. **Embeddings never leave the backend.**
"""
from __future__ import annotations

import base64
import io
import logging
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from PIL import Image, ImageFilter, ImageOps

from app.config.settings import settings

logger = logging.getLogger("traya.biometric")

# --------------------------------------------------------------------------
# OpenCV availability
# --------------------------------------------------------------------------
try:
    import cv2  # type: ignore

    _HAS_CV2 = bool(hasattr(cv2, "CascadeClassifier"))
    if not _HAS_CV2:
        logger.info("OpenCV 5+ installed without the classic cascade API; using simulation face localization.")
    else:
        logger.info("OpenCV available: using Haar-cascade face detection.")
except Exception:  # pragma: no cover - environment dependent
    cv2 = None  # type: ignore
    _HAS_CV2 = False
    logger.info("OpenCV not available: using simulation face localization.")


# --------------------------------------------------------------------------
# Data structures
# --------------------------------------------------------------------------
@dataclass
class FaceBox:
    x: int
    y: int
    w: int
    h: int
    skin_ratio: float = 0.0
    density: float | None = None
    source: str = "simulation"

    @property
    def area(self) -> int:
        return max(1, self.w * self.h)


@dataclass
class QualityReport:
    image_quality_score: float
    face_visibility_score: float
    occlusion_score: float
    blur_score: float
    lighting_score: float
    usable_for_matching: bool
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "image_quality_score": round(self.image_quality_score, 3),
            "face_visibility_score": round(self.face_visibility_score, 3),
            "occlusion_score": round(self.occlusion_score, 3),
            "blur_score": round(self.blur_score, 3),
            "lighting_score": round(self.lighting_score, 3),
            "usable_for_matching": self.usable_for_matching,
            "reasons": self.reasons,
        }


@dataclass
class DetectionResult:
    faces: list[FaceBox]
    quality: QualityReport
    source: str


# --------------------------------------------------------------------------
# Image helpers
# --------------------------------------------------------------------------
def decode_image(data: str | bytes) -> Image.Image:
    """Decode base64 or raw bytes into a PIL RGB image, validating magic bytes."""
    raw = data if isinstance(data, bytes) else base64.b64decode(data)
    if len(raw) < 16:
        raise ValueError("Image data too small")
    magic = raw[:16]
    if not (magic.startswith(b"\xff\xd8") or magic.startswith(b"\x89PNG") or magic.startswith(b"RIFF")):
        raise ValueError("Unsupported image format (JPEG/PNG/WebP only)")
    image = Image.open(io.BytesIO(raw))
    image.load()
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    return image


def to_gray_np(image: Image.Image) -> np.ndarray:
    gray = ImageOps.grayscale(image)
    return np.asarray(gray, dtype=np.float32)


def skin_mask(image: Image.Image, downscale: int = 4) -> tuple[np.ndarray, list[tuple[int, int, int, int, int]]]:
    """Approximate skin-tone mask in HSV. Returns (mask_full, component_boxes)
    where each component box is (x0, y0, x1, y1, area) in full-res pixels."""
    small = image.convert("RGB").resize(
        (max(8, image.width // downscale), max(8, image.height // downscale))
    )
    arr = np.asarray(small, dtype=np.uint8)
    hsv = np.zeros(arr.shape[:2], dtype=np.float32)
    sat = np.zeros(arr.shape[:2], dtype=np.float32)
    # vectorized HSV conversion (Hue, Saturation only are enough for skin filter)
    r, g, b = arr[..., 0].astype(np.float32), arr[..., 1].astype(np.float32), arr[..., 2].astype(np.float32)
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    diff = mx - mn + 1e-6
    with np.errstate(divide="ignore", invalid="ignore"):
        h = np.where(
            mx == r, (60 * ((g - b) / diff)) % 360,
            np.where(mx == g, 60 * ((b - r) / diff) + 120, 60 * ((r - g) / diff) + 240),
        )
    sat = np.where(mx == 0, 0, diff / (mx + 1e-6)) * 255
    val = mx

    mask = (
        (h >= 0) & (h <= 60) & (sat > 18) & (sat < 225) & (val > 25)
    ).astype(np.uint8) * 255

    # binary connected components to count blobs
    labels, count = _label(mask > 0)
    boxes: list[tuple[int, int, int, int, int]] = []
    scale = downscale
    for lab in range(1, count + 1):
        ys, xs = np.where(labels == lab)
        if len(ys) < 40:
            continue
        area = len(ys)
        boxes.append((xs.min() * scale, ys.min() * scale, xs.max() * scale, ys.max() * scale, area * scale * scale))

    mask_full = np.asarray(
        Image.fromarray(mask).resize((image.width, image.height), Image.NEAREST),
        dtype=np.uint8,
    )
    return mask_full, boxes


def _label(mask: np.ndarray) -> tuple[np.ndarray, int]:
    """4-connected component labeling (breadth-first)."""
    h, w = mask.shape
    labels = np.zeros((h, w), dtype=np.int32)
    count = 0
    for y in range(h):
        for x in range(w):
            if mask[y, x] and labels[y, x] == 0:
                count += 1
                queue = [(y, x)]
                labels[y, x] = count
                while queue:
                    cy, cx = queue.pop()
                    for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                        ny, nx = cy + dy, cx + dx
                        if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and labels[ny, nx] == 0:
                            labels[ny, nx] = count
                            queue.append((ny, nx))
    return labels, count


def _variance_of_laplacian(gray: np.ndarray) -> float:
    lap_x = np.diff(gray, axis=1)
    lap_y = np.diff(gray, axis=0)
    lap = lap_x[:-1, :] + lap_y[:, :-1]
    return float(lap.var()) if lap.size else 0.0


# --------------------------------------------------------------------------
# Quality analysis
# --------------------------------------------------------------------------
def analyze_quality(image: Image.Image, face_boxes: list[FaceBox]) -> QualityReport:
    gray = to_gray_np(image)
    reasons: list[str] = []

    blur_var = _variance_of_laplacian(gray)
    blur_score = min(1.0, max(0.0, math.log1p(blur_var) / math.log(500)))

    mean = float(gray.mean())
    std = float(gray.std())
    lighting_score = 1.0 - min(1.0, abs(mean - 127) / 127)
    contrast_score = min(1.0, std / 60)

    image_quality_score = 0.40 * blur_score + 0.35 * lighting_score + 0.25 * contrast_score

    # face-based scores (uses skin density inside the detected box)
    face_visibility = 0.0
    occlusion = 1.0
    img_area = image.width * image.height
    if face_boxes:
        best = max(face_boxes, key=lambda f: f.area)
        size_score = min(1.0, (best.area / img_area) * 12)
        density = best.density
        if density is None:
            density = min(1.0, (best.skin_ratio * img_area) / best.area)
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
    if occlusion > 0.75:
        reasons.append("Face is significantly obstructed")
    if face_boxes and face_boxes[0].area / (image.width * image.height) < 0.02:
        reasons.append("Face is too small in the frame")

    return QualityReport(
        image_quality_score=round(image_quality_score, 3),
        face_visibility_score=round(face_visibility, 3),
        occlusion_score=round(occlusion, 3),
        blur_score=round(blur_score, 3),
        lighting_score=round(lighting_score, 3),
        usable_for_matching=usable,
        reasons=reasons,
    )


# --------------------------------------------------------------------------
# Detection
# --------------------------------------------------------------------------
def detect_faces(image: Image.Image) -> tuple[list[FaceBox], str]:
    """Return face boxes. Uses OpenCV Haar cascade when available."""
    if _HAS_CV2 and settings.BIOMETRIC_ENGINE in ("auto", "opencv"):
        try:
            cascade = cv2.CascadeClassifier(
                cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            )
            if not cascade.empty():
                arr = np.asarray(ImageOps.grayscale(image), dtype=np.uint8)
                rects = cascade.detectMultiScale(arr, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))
                boxes = [
                    FaceBox(x=int(x), y=int(y), w=int(w), h=int(h), skin_ratio=0.5, source="opencv")
                    for (x, y, w, h) in rects
                ]
                if boxes:
                    return boxes, "opencv-haar"
        except Exception as exc:  # pragma: no cover
            logger.warning("OpenCV cascade failed (%s); falling back.", exc)

    return _simulate_detect(image)


def _simulate_detect(image: Image.Image) -> tuple[list[FaceBox], str]:
    mask, components = skin_mask(image)
    if not components:
        return [], "simulation"
    img_area = image.width * image.height
    faces: list[FaceBox] = []
    for x0, y0, x1, y1, area in components:
        w, h = x1 - x0, y1 - y0
        density = area / max(1, w * h)
        # Background walls are typically large regions touching frame borders
        borders_touched = sum(
            [x0 <= 0, y0 <= 0, x1 >= image.width - 1, y1 >= image.height - 1]
        )
        if area / img_area > 0.55 or borders_touched >= 3:
            continue
        faces.append(
            FaceBox(
                x=int(x0),
                y=int(y0),
                w=int(w),
                h=int(h),
                skin_ratio=area / img_area,
                density=min(1.0, density),
                source="simulation",
            )
        )
    # drop tiny spurious blobs
    faces = [f for f in faces if f.area / img_area >= 0.015]
    return faces, "simulation"


# --------------------------------------------------------------------------
# Embedding
# --------------------------------------------------------------------------
def extract_embedding(image: Image.Image, box: FaceBox | None = None) -> np.ndarray:
    """Deterministic feature-vector embedding of a normalized face crop.

    DEMO/SIMULATION embedding: a small set of interpretable facial features
    (skin tone, hair darkness, eye/brow/mouth/beard presence, symmetry and
    face aspect) extracted from a 16x16 luminance grid. Identity differences
    are directly measured, so the vector is stable for the same identity and
    distinct across identities. Documented as NOT a production biometric.
    """
    crop = image
    aspect = 1.0
    if box is not None:
        x = max(0, box.x)
        y = max(0, box.y)
        w = min(image.width - x, box.w)
        h = min(image.height - y, box.h)
        if w > 4 and h > 4:
            crop = image.crop((x, y, x + w, y + h))
        aspect = min(2.0, max(0.5, w / max(1, h)))

    lum_src = ImageOps.grayscale(crop).filter(ImageFilter.MedianFilter(size=3)).resize((16, 16))
    lum = np.asarray(lum_src, dtype=np.float32) / 255.0

    skin_mean = float(np.median(lum[5:11, 2:14]))
    skin_std = float(lum[5:11, 2:14].std())
    hair_dark = 1.0 - float(lum[0:3, :].mean())
    eye_band = lum[4:10, 1:15]
    eye_left = 1.0 - float(eye_band[:, 0:5].mean())
    eye_mid = 1.0 - float(eye_band[:, 5:9].mean())
    eye_right = 1.0 - float(eye_band[:, 9:14].mean())
    brow = 1.0 - float(lum[2:4, 3:13].mean())
    mouth = 1.0 - float(lum[10:13, 4:12].mean())
    beard = 1.0 - float(lum[12:16, 3:13].mean())
    left_mean = float(lum[:, 0:6].mean())
    right_mean = float(lum[:, 10:16].mean())
    symmetry = 1.0 - min(1.0, abs(left_mean - right_mean) * 3)

    raw = np.array(
        [
            skin_mean, skin_std, hair_dark,
            eye_left, eye_mid, eye_right,
            brow, mouth, beard,
            symmetry, aspect, float(lum.mean()),
        ],
        dtype=np.float64,
    )

    # per-feature scales -> unit variance approximations
    scales = np.array(
        [0.30, 0.12, 0.30, 0.18, 0.18, 0.18, 0.20, 0.20, 0.28, 0.25, 0.20, 0.20],
        dtype=np.float64,
    )
    features = raw / scales
    if features.size < settings.EMBEDDING_DIM:
        features = np.pad(features, (0, settings.EMBEDDING_DIM - features.size))
    return features


def compare(embedding_a: np.ndarray, embedding_b: np.ndarray) -> float:
    """Similarity in [0, 1] from the L2 distance of feature embeddings.

    A distance of ~3.0 maps to ~0.0 similarity; identical vectors map to 1.0.
    """
    d = float(np.linalg.norm(embedding_a - embedding_b))
    return max(0.0, min(1.0, 1.0 - d / 3.0))


def get_template() -> np.ndarray:
    return np.zeros(settings.EMBEDDING_DIM)


def mean_center(vector: np.ndarray, template: np.ndarray | None = None) -> np.ndarray:
    return vector


def compare_centered(a: np.ndarray, b: np.ndarray) -> float:
    return compare(a, b)


# --------------------------------------------------------------------------
# Facade
# --------------------------------------------------------------------------
class BiometricEngine:
    """Single entry point used by the identification pipeline."""

    mode: str

    def __init__(self) -> None:
        if settings.BIOMETRIC_ENGINE == "simulation":
            self.mode = "simulation"
        elif _HAS_CV2:
            self.mode = "opencv"
        else:
            self.mode = "simulation"

    @property
    def is_simulation(self) -> bool:
        return self.mode == "simulation"

    def process(self, image_bytes: bytes | str) -> DetectionResult:
        image = decode_image(image_bytes)
        faces, source = detect_faces(image)
        quality = analyze_quality(image, faces)
        if not faces:
            quality.usable_for_matching = False
        return DetectionResult(faces=faces, quality=quality, source=source)

    def embed(self, image_bytes: bytes | str, box: FaceBox | None = None) -> np.ndarray:
        image = decode_image(image_bytes)
        return extract_embedding(image, box)

    def similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        return compare_centered(a, b)


_engine: BiometricEngine | None = None


def get_engine() -> BiometricEngine:
    global _engine
    if _engine is None:
        _engine = BiometricEngine()
    return _engine
