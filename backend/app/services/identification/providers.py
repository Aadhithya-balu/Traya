"""Face detection, alignment and embedding providers.

The engine in :mod:`app.services.identification.engine` owns the *interface* that
the rest of the platform depends on. This module owns the *implementations*
behind it, so that swapping the arithmetic never reaches a caller.

Two implementations exist and both are selectable at runtime:

``YuNet128Provider``
    Real. YuNet detects faces and returns five landmarks per face; the
    landmarks drive a similarity transform that removes roll and scale before
    SFace sees the crop; SFace produces a 128-dimensional descriptor, L2
    normalised. Executed by OpenCV's own dnn module, so this needs no deep
    learning runtime beyond the ``cv2`` already installed.

``SimulationProvider``
    The pre-Phase-5 behaviour, kept intact and clearly labelled. Twelve
    interpretable brightness measurements zero-padded to ``EMBEDDING_DIM``.
    It is what makes the demo honest, the tests fast and the whole platform
    testable without the weights present, so it is not scheduled for deletion.

Neither provider is a "better" or "worse" implementation of the same idea: they
produce vectors in different spaces with different dimensions, which is why
:func:`app.repositories.recognition.RecognitionRepository.enrolled_profiles`
filters on algo version. Comparing a 128-dimensional real descriptor against a
320-dimensional simulated one is meaningless, and the filter is what stops the
matcher from trying.

Model provenance and licences: ``scripts/fetch_biometric_models.py`` writes a
NOTICE.txt beside the weights it fetches.
"""
from __future__ import annotations

import base64
import io
import logging
import math
import pathlib
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import numpy as np
from PIL import Image, ImageFilter, ImageOps

from app.config.settings import settings

logger = logging.getLogger("traya.biometric")

try:
    import cv2  # type: ignore

    _HAS_CV2 = True
except Exception:  # pragma: no cover - environment dependent
    cv2 = None  # type: ignore
    _HAS_CV2 = False


# --------------------------------------------------------------------------
# Shared value types
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
    score: float = 0.0
    #: Right eye, left eye, nose, right mouth corner, left mouth corner, each
    #: (x, y) in full-image pixels. Empty for the simulation provider, which has
    #: no landmarks and does not pretend to.
    landmarks: list[tuple[float, float]] = field(default_factory=list)

    @property
    def area(self) -> int:
        return max(1, self.w * self.h)

    @property
    def has_landmarks(self) -> bool:
        return len(self.landmarks) == 5


@dataclass
class AlignedFace:
    """A crop normalised to the pose and scale the recognizer expects."""

    image: Image.Image
    #: Mean absolute difference against the unaligned crop. Measured, not
    #: assumed, so a test can assert that alignment did something.
    correction: float = 0.0
    roll_degrees: float = 0.0


# --------------------------------------------------------------------------
# Image helpers, shared by both providers
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


def variance_of_laplacian(gray: np.ndarray) -> float:
    lap_x = np.diff(gray, axis=1)
    lap_y = np.diff(gray, axis=0)
    lap = lap_x[:-1, :] + lap_y[:, :-1]
    return float(lap.var()) if lap.size else 0.0


# --------------------------------------------------------------------------
# Provider interface
# --------------------------------------------------------------------------
@runtime_checkable
class FaceEmbeddingProvider(Protocol):
    """The contract both providers satisfy and the engine depends on.

    Declared as a Protocol rather than an ABC so a provider cannot be
    accidentally half-implemented by inheritance: the engine takes any object
    that structurally satisfies this.
    """

    name: str
    version: str
    dimension: int
    preprocessing_version: str
    is_simulation: bool
    mode: str

    def detect(self, image: Image.Image) -> list[FaceBox]: ...

    def align(self, image: Image.Image, box: FaceBox) -> AlignedFace: ...

    def embed(self, image: Image.Image, box: FaceBox | None = None) -> np.ndarray: ...

    def similarity(self, a: np.ndarray, b: np.ndarray) -> float: ...


# --------------------------------------------------------------------------
# The real provider
# --------------------------------------------------------------------------
class YuNet128Provider:
    """YuNet detection + landmarks, similarity-transform alignment, SFace 128D.

    Three stages, each doing one job:

    1. **Detect.** YuNet returns a box, a confidence and five landmarks per
       face. The landmarks are the reason this provider exists: without them
       there is nothing to align against and roll leaks into the descriptor.
    2. **Align.** The five points are mapped onto a canonical 112x112 layout
       with a partial affine fit, so head roll and distance are removed. A
       rotated photo of the same person then produces a far more similar
       descriptor than the unaligned crop would.
    3. **Embed.** SFace is MobileFaceNet trained with the SFace loss. It expects
       an aligned crop and returns 128 float32 values, which are L2 normalised
       here so that similarity is a plain dot product.
    """

    name = "sface"
    version = "sface-128d-v1"
    dimension = 128
    preprocessing_version = "aligned112-rgb-v1"
    is_simulation = False
    mode = "yunet"

    #: Canonical landmark layout for a 112x112 crop. Taken from the ArcFace
    #: reference alignment; SFace inherits that preprocessing, so using its
    #: layout is what makes its output comparable with its own training.
    _TEMPLATE = np.array(
        [
            [38.2946, 51.6963],   # right eye
            [73.5318, 51.5014],   # left eye
            [56.0252, 71.7366],   # nose tip
            [41.5493, 92.3655],   # right mouth corner
            [70.7299, 92.2041],   # left mouth corner
        ],
        dtype=np.float32,
    )
    _CROP_SIZE = 112

    def __init__(self) -> None:
        if not _HAS_CV2:
            raise RuntimeError("OpenCV is not importable; the real engine cannot run")
        for attribute in ("FaceDetectorYN", "FaceRecognizerSF", "estimateAffinePartial2D"):
            if not hasattr(cv2, attribute):
                raise RuntimeError(
                    f"OpenCV {cv2.__version__} has no {attribute}; the real engine needs OpenCV 5"
                )
        root = pathlib.Path(settings.FACE_MODELS_DIR)
        detector_path = root / settings.FACE_DETECTOR_MODEL
        recognizer_path = root / settings.FACE_RECOGNIZER_MODEL
        missing = [p for p in (detector_path, recognizer_path) if not p.exists()]
        if missing:
            names = ", ".join(p.name for p in missing)
            raise RuntimeError(
                f"model file(s) not found in {root}: {names}. "
                "Run scripts/fetch_biometric_models.py."
            )
        self._detector = cv2.FaceDetectorYN.create(
            str(detector_path),
            "",
            (320, 320),
            float(settings.FACE_DETECTOR_SCORE_THRESHOLD),
            float(settings.FACE_DETECTOR_NMS_THRESHOLD),
            int(settings.FACE_DETECTOR_TOP_K),
        )
        self._recognizer = cv2.FaceRecognizerSF.create(str(recognizer_path), "")
        logger.info("real engine ready: YuNet + SFace 128D from %s", root)

    # -- stage 1 ---------------------------------------------------------
    def detect(self, image: Image.Image) -> list[FaceBox]:
        bgr = self._to_bgr(image)
        height, width = bgr.shape[:2]
        # YuNet needs the input size set per image, and it refuses a zero
        # dimension, which a failed decode can produce.
        if height < 2 or width < 2:
            return []
        self._detector.setInputSize((width, height))
        try:
            _, faces = self._detector.detect(bgr)
        except Exception as exc:  # pragma: no cover - model/runtime dependent
            logger.warning("YuNet detection failed (%s); reporting no face.", exc)
            return []
        if faces is None or len(faces) == 0:
            return []

        boxes: list[FaceBox] = []
        for row in faces:
            x, y, w, h = (float(v) for v in row[:4])
            landmarks = [(float(row[4 + 2 * i]), float(row[5 + 2 * i])) for i in range(5)]
            area = max(1.0, w * h)
            frame_area = max(1.0, width * height)
            boxes.append(
                FaceBox(
                    x=int(round(x)),
                    y=int(round(y)),
                    w=int(round(w)),
                    h=int(round(h)),
                    # The simulation provider derived these from skin
                    # segmentation. A real detector does not produce them, so
                    # they are derived from geometry instead and the quality
                    # report's meaning changes accordingly - see
                    # analyze_quality's density handling.
                    skin_ratio=area / frame_area,
                    density=None,
                    source="yunet",
                    score=float(row[-1]),
                    landmarks=landmarks,
                )
            )
        boxes.sort(key=lambda b: b.score, reverse=True)
        return boxes

    # -- stage 2 ---------------------------------------------------------
    def align(self, image: Image.Image, box: FaceBox) -> AlignedFace:
        """Remove roll and scale using the five landmarks.

        The transform is fitted against the canonical layout, which is what
        makes a 20-degree head tilt produce nearly the same descriptor as a
        level one. Falls back to a plain box crop when the landmarks are
        unusable, and says so through ``correction`` so a caller can tell an
        aligned face from a merely cropped one.
        """
        bgr = self._to_bgr(image)
        if not box.has_landmarks:
            return AlignedFace(image=self._box_crop(image, box), correction=0.0)

        source = np.array(box.landmarks, dtype=np.float32)
        try:
            matrix, _ = cv2.estimateAffinePartial2D(
                source, self._TEMPLATE, method=cv2.LMEDS
            )
        except Exception:  # pragma: no cover - degenerate landmark sets
            matrix = None
        if matrix is None or not np.isfinite(matrix).all():
            return AlignedFace(image=self._box_crop(image, box), correction=0.0)

        size = (self._CROP_SIZE, self._CROP_SIZE)
        warped = cv2.warpAffine(
            bgr,
            matrix,
            size,
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REPLICATE,
        )
        aligned = Image.fromarray(cv2.cvtColor(warped, cv2.COLOR_BGR2RGB))

        # Measure what the transform did rather than asserting it did something.
        naive = self._box_crop(image, box).resize(aligned.size, Image.BILINEAR)
        correction = float(
            np.asarray(ImageOps.grayscale(aligned), dtype=np.float32).mean()
        ) - float(np.asarray(ImageOps.grayscale(naive), dtype=np.float32).mean())
        return AlignedFace(
            image=aligned,
            correction=correction,
            roll_degrees=self._roll_degrees(box.landmarks),
        )

    def _box_crop(self, image: Image.Image, box: FaceBox) -> Image.Image:
        x = max(0, min(box.x, image.width - 1))
        y = max(0, min(box.y, image.height - 1))
        w = min(image.width - x, max(1, box.w))
        h = min(image.height - y, max(1, box.h))
        crop = image.crop((x, y, x + w, y + h))
        return crop.resize((self._CROP_SIZE, self._CROP_SIZE), Image.BILINEAR)

    @staticmethod
    def _roll_degrees(landmarks: list[tuple[float, float]]) -> float:
        right_eye, left_eye = landmarks[0], landmarks[1]
        return float(math.degrees(math.atan2(left_eye[1] - right_eye[1], left_eye[0] - right_eye[0])))

    # -- stage 3 ---------------------------------------------------------
    def embed(self, image: Image.Image, box: FaceBox | None = None) -> np.ndarray:
        if box is not None:
            image = self.align(image, box).image
        bgr = self._to_bgr(image)
        try:
            feature = self._recognizer.feature(bgr)
        except Exception as exc:  # pragma: no cover - model/runtime dependent
            logger.warning("SFace embedding failed (%s); returning zeros.", exc)
            return np.zeros(self.dimension, dtype=np.float64)
        vector = np.asarray(feature, dtype=np.float64).reshape(-1)
        norm = float(np.linalg.norm(vector))
        if norm < 1e-8:
            return np.zeros(self.dimension, dtype=np.float64)
        return vector / norm

    def similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """Cosine similarity of two L2-normalised descriptors, in [0, 1].

        Cosine, not Euclidean distance: on unit vectors the two are monotonically
        related, but cosine is what the descriptors were trained for and it
        cannot be gamed by a longer vector. Negative similarities clamp to 0
        rather than going negative, because a negative score is not a
        meaningful "probability of being the same person" and the threshold
        layer above is written in [0, 1].
        """
        va, vb = self._unit(a), self._unit(b)
        if va.size != vb.size:
            raise ValueError(
                f"cannot compare a {va.size}-dimensional vector with a {vb.size}-dimensional one; "
                "the stored templates were produced by a different engine build"
            )
        return float(max(0.0, min(1.0, float(np.dot(va, vb)))))

    @staticmethod
    def _unit(vector: np.ndarray) -> np.ndarray:
        v = np.asarray(vector, dtype=np.float64).reshape(-1)
        norm = float(np.linalg.norm(v))
        return v / norm if norm > 1e-12 else v

    @staticmethod
    def _to_bgr(image: Image.Image) -> np.ndarray:
        rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


# --------------------------------------------------------------------------
# The simulation provider: unchanged behaviour, honestly labelled
# --------------------------------------------------------------------------
class SimulationProvider:
    """The pre-Phase-5 engine, preserved as-is.

    Every claim this platform makes about accuracy rests on the *absence* of
    this class being noticed, so it stays labelled `is_simulation = True` and
    keeps its own dimension. It is what the demo runs, what the test suite
    exercises, and what a deployment with no model files falls back to.
    """

    name = "pseudo-features"
    version = settings.BIOMETRIC_ALGO_VERSION
    dimension = settings.EMBEDDING_DIM
    preprocessing_version = "crop16-luma-v1"
    is_simulation = True
    mode = "simulation"

    def detect(self, image: Image.Image) -> list[FaceBox]:
        _, components = skin_mask(image)
        if not components:
            return []
        img_area = image.width * image.height
        faces: list[FaceBox] = []
        for x0, y0, x1, y1, area in components:
            w, h = x1 - x0, y1 - y0
            density = area / max(1, w * h)
            borders_touched = sum([x0 <= 0, y0 <= 0, x1 >= image.width - 1, y1 >= image.height - 1])
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
        return [f for f in faces if f.area / img_area >= 0.015]

    def align(self, image: Image.Image, box: FaceBox) -> AlignedFace:
        """No landmarks means no alignment. Said plainly rather than faked."""
        return AlignedFace(image=self._crop(image, box), correction=0.0)

    def _crop(self, image: Image.Image, box: FaceBox) -> Image.Image:
        x = max(0, min(box.x, image.width - 1))
        y = max(0, min(box.y, image.height - 1))
        w = min(image.width - x, max(1, box.w))
        h = min(image.height - y, max(1, box.h))
        return image.crop((x, y, x + w, y + h))

    def embed(self, image: Image.Image, box: FaceBox | None = None) -> np.ndarray:
        """Twelve interpretable measurements of the face crop, zero-padded.

        DEMO/SIMULATION. Skin tone, skin variation, hair darkness, three eye
        bands, brow, mouth, beard, symmetry, aspect and mean luminance. Not a
        biometric: it measures how bright parts of the picture are, so two
        similar-looking people collide and one person under two lights does not.
        """
        crop = image
        aspect = 1.0
        if box is not None:
            w = max(1, box.w)
            h = max(1, box.h)
            if w > 4 and h > 4:
                crop = self._crop(image, box)
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
        scales = np.array(
            [0.30, 0.12, 0.30, 0.18, 0.18, 0.18, 0.20, 0.20, 0.28, 0.25, 0.20, 0.20],
            dtype=np.float64,
        )
        features = raw / scales
        if features.size < self.dimension:
            features = np.pad(features, (0, self.dimension - features.size))
        return features

    def similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """Unchanged from the pre-Phase-5 engine: similarity from L2 distance.

        The real provider uses cosine. This one cannot, because these vectors
        are not L2 normalised and were never trained to be compared that way -
        the scoring scale is different, which is exactly why the thresholds are
        not portable between the two providers.
        """
        d = float(np.linalg.norm(np.asarray(a, dtype=np.float64) - np.asarray(b, dtype=np.float64)))
        return max(0.0, min(1.0, 1.0 - d / 3.0))


# --------------------------------------------------------------------------
# Resolution
# --------------------------------------------------------------------------
def models_present() -> bool:
    root = pathlib.Path(settings.FACE_MODELS_DIR)
    return (root / settings.FACE_DETECTOR_MODEL).exists() and (
        root / settings.FACE_RECOGNIZER_MODEL
    ).exists()


_provider: FaceEmbeddingProvider | None = None


def get_provider(reload: bool = False) -> FaceEmbeddingProvider:
    """Resolve the configured provider, once per process.

    Resolution is logged, not silent. A deployment that believes it is running
    a real recognizer and is not is the single worst failure this project has,
    so the choice is always stated at startup and carried in every result as
    ``engine_mode``.
    """
    global _provider
    if _provider is not None and not reload:
        return _provider

    requested = settings.BIOMETRIC_ENGINE.strip().lower()
    if requested == "opencv":
        # The value that used to promise a real detector and silently deliver
        # the simulation, because OpenCV 5 removed the cascade API it gated on.
        logger.warning(
            "BIOMETRIC_ENGINE=opencv never produced real detection (OpenCV 5 removed "
            "CascadeClassifier); treating it as 'yunet'."
        )
        requested = "yunet"

    if requested == "simulation":
        _provider = SimulationProvider()
        logger.info("biometric engine: simulation (configured explicitly)")
        return _provider

    if requested in ("auto", "yunet"):
        if not models_present():
            if requested == "yunet":
                raise RuntimeError(
                    "BIOMETRIC_ENGINE=yunet was requested but the model files are absent. "
                    "Run scripts/fetch_biometric_models.py, or set BIOMETRIC_ENGINE=simulation "
                    "to use the demo engine on purpose."
                )
            logger.warning(
                "biometric engine: SIMULATION, because no model files are in %s. "
                "This is not a recognizer. Run scripts/fetch_biometric_models.py for the "
                "real engine.",
                settings.FACE_MODELS_DIR,
            )
            _provider = SimulationProvider()
            return _provider
        try:
            _provider = YuNet128Provider()
        except Exception as exc:
            if requested == "yunet":
                raise
            logger.warning(
                "biometric engine: SIMULATION, because the real engine failed to load (%s). "
                "This is not a recognizer.",
                exc,
            )
            _provider = SimulationProvider()
            return _provider
        logger.info("biometric engine: real (YuNet + SFace 128D), algo %s", _provider.version)
        return _provider

    raise ValueError(
        f"unknown BIOMETRIC_ENGINE={settings.BIOMETRIC_ENGINE!r}; "
        "expected auto, yunet or simulation"
    )


def reset_provider() -> None:
    """Drop the cached provider. Tests use this after changing settings."""
    global _provider
    _provider = None
