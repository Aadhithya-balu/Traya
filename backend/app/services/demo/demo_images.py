"""Synthetic face image generator for DEMO / SIMULATION mode.

Produces deterministic cartoon-style faces from a numeric seed so that the
enrollment pipeline and the public identification pipeline both work against
real image processing code (quality analysis, face localization, embedding,
matching) without shipping any real person's biometric data.

All output from this module is fictional demo data.
"""
from __future__ import annotations

import hashlib
import io
import math
import random

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

W, H = 320, 400


def _rng(seed: str | int) -> random.Random:
    if isinstance(seed, int):
        return random.Random(seed)
    digest = int(hashlib.sha256(str(seed).encode("utf-8")).hexdigest()[:12], 16)
    return random.Random(digest)


def _ellipse(draw: ImageDraw.ImageDraw, cx, cy, rx, ry, color, outline=None):
    draw.ellipse(
        [cx - rx, cy - ry, cx + rx, cy + ry],
        fill=color,
        outline=outline,
        width=2,
    )


def _draw_face(draw: ImageDraw.ImageDraw, irng: random.Random, cx: float, cy: float, scale: float = 1.0) -> None:
    skin_tone = irng.choice(
        [
            (238, 222, 205),  # light
            (224, 186, 158),  # medium-light
            (198, 148, 116),  # medium
            (172, 122, 88),   # tan
            (138, 96, 66),    # deep
        ]
    )
    skin = (skin_tone[0] + irng.randint(-8, 8), skin_tone[1] + irng.randint(-8, 8), skin_tone[2] + irng.randint(-8, 8))
    hair = irng.choice(
        [
            (25, 20, 28),    # black
            (55, 36, 30),    # dark brown
            (95, 60, 40),    # brown
            (160, 90, 50),   # light brown
            (205, 165, 95),  # blond
            (150, 60, 45),   # red
            (170, 170, 175), # gray
        ]
    )
    eye = (30, 30, 40)

    # identity-specific geometry (deterministic per identity seed)
    face_rx = 62 * scale * (0.85 + 0.30 * irng.random())
    face_ry = 78 * scale * (0.85 + 0.30 * irng.random())
    eye_gap = 20 * scale * (0.70 + 0.60 * irng.random())
    eye_r = 6 * scale * (0.80 + 0.50 * irng.random())
    brow_dy = 22 * scale * (0.85 + 0.35 * irng.random())
    mouth_w = 24 * scale * (0.75 + 0.55 * irng.random())
    nose_len = 14 * scale * (0.80 + 0.50 * irng.random())
    chin_shift = 0.85 + 0.35 * irng.random()
    hair_top_extra = 14 * scale * (0.5 + irng.random())

    # ears
    _ellipse(draw, cx - face_rx, cy, 8 * scale, 18 * scale, skin)
    _ellipse(draw, cx + face_rx, cy, 8 * scale, 18 * scale, skin)
    # face
    chin_y = cy + face_ry * chin_shift
    draw.polygon(
        [
            (cx - face_rx, chin_y),
            (cx, cy - face_ry - 14 * scale),
            (cx + face_rx, chin_y),
        ],
        fill=skin,
    )
    _ellipse(draw, cx, cy + 4 * scale, face_rx, face_ry, skin)
    # hair style
    hair_top = cy - face_ry - hair_top_extra
    hair_style = irng.choice(["cap", "top", "side", "none"])
    if hair_style == "cap":
        draw.polygon(
            [(cx - face_rx, cy - 20 * scale), (cx - face_rx - 8 * scale, hair_top), (cx + face_rx + 8 * scale, hair_top), (cx + face_rx, cy - 20 * scale)],
            fill=hair,
        )
        draw.arc(
            [cx - face_rx, hair_top - 34 * scale, cx + face_rx, hair_top + 34 * scale],
            start=180,
            end=360,
            fill=hair,
            width=int(16 * scale),
        )
    elif hair_style == "top":
        draw.polygon(
            [(cx - face_rx * 0.8, hair_top + 20 * scale), (cx, hair_top - 26 * scale), (cx + face_rx * 0.8, hair_top + 20 * scale)],
            fill=hair,
        )
    elif hair_style == "side":
        for side in (-1, 1):
            draw.arc(
                [cx + side * face_rx - 22 * scale, hair_top - 10 * scale, cx + side * face_rx + 14 * scale, hair_top + 46 * scale],
                start=90 if side == -1 else 270,
                end=270 if side == -1 else 450,
                fill=hair,
                width=int(10 * scale),
            )
    # brows
    brow_w = 12 * scale * (0.7 + 0.8 * irng.random())
    draw.line([(cx - eye_gap - 6 * scale, cy - brow_dy), (cx - brow_w, cy - brow_dy + 4 * scale)], fill=hair, width=4)
    draw.line([(cx + eye_gap + 6 * scale, cy - brow_dy), (cx + brow_w, cy - brow_dy + 4 * scale)], fill=hair, width=4)
    # eyes
    _ellipse(draw, cx - eye_gap, cy - 6 * scale, eye_r, eye_r * 1.3, (255, 255, 255))
    _ellipse(draw, cx + eye_gap, cy - 6 * scale, eye_r, eye_r * 1.3, (255, 255, 255))
    _ellipse(draw, cx - eye_gap, cy - 5 * scale, eye_r * 0.5, eye_r * 0.7, eye)
    _ellipse(draw, cx + eye_gap, cy - 5 * scale, eye_r * 0.5, eye_r * 0.7, eye)
    # glasses (identity-distinguishing, thick dark frames inside the face)
    if irng.random() < 0.35:
        shape = irng.choice(["round", "rect"])
        for side in (-1, 1):
            ex = cx + side * eye_gap
            if shape == "round":
                draw.ellipse([ex - eye_r - 6 * scale, cy - 8 * scale, ex + eye_r + 6 * scale, cy + 8 * scale], outline=(25, 25, 30), width=3)
            else:
                draw.rectangle([ex - eye_r - 7 * scale, cy - 10 * scale, ex + eye_r + 7 * scale, cy + 9 * scale], outline=(25, 25, 30), width=3)
        draw.line([(cx - eye_gap + eye_r + 6 * scale, cy - 4 * scale), (cx + eye_gap - eye_r - 6 * scale, cy - 4 * scale)], fill=(25, 25, 30), width=3)
    # nose
    draw.line([(cx, cy + 6 * scale), (cx - 4 * scale, cy + 6 * scale + nose_len), (cx + 6 * scale, cy + 5 * scale + nose_len)], fill=(160, 110, 90), width=2)
    # mouth: line or open
    mouth_y = cy + 44 * scale
    if irng.random() < 0.45:
        draw.ellipse([cx - mouth_w, mouth_y - 5 * scale, cx + mouth_w, mouth_y + 8 * scale], fill=(95, 35, 40))
    else:
        draw.line([(cx - mouth_w, mouth_y), (cx + mouth_w, mouth_y)], fill=(150, 60, 60), width=3)
    # beard (identity-distinguishing, dark region on the chin area)
    beard_style = irng.choice(["none", "none", "full", "goatee"])
    if beard_style == "full":
        beard = tuple(max(15, c - 35) for c in hair)
        draw.pieslice(
            [cx - face_rx * 0.92, cy + 10 * scale, cx + face_rx * 0.92, cy + face_ry * chin_shift * 1.4],
            start=0,
            end=180,
            fill=beard,
        )
    elif beard_style == "goatee":
        beard = tuple(max(15, c - 35) for c in hair)
        draw.ellipse([cx - 14 * scale, cy + 24 * scale, cx + 14 * scale, cy + 58 * scale], fill=beard)
    # moles / freckles (identity-distinguishing)
    for _ in range(irng.randint(0, 4)):
        mx = cx + irng.randint(-30, 30) * scale
        my = cy + irng.randint(-15, 45) * scale
        _ellipse(draw, mx, my, 2 * scale, 2 * scale, (120, 90, 80))
    # optional scar (trauma/feature)
    if irng.random() < 0.15:
        sx = cx + irng.randint(10, 30) * scale
        sy = cy + irng.randint(-20, 30) * scale
        draw.line([(sx, sy), (sx + 12 * scale, sy + 6 * scale)], fill=(140, 70, 70), width=3)


def render_face(
    seed: str | int,
    *,
    identity: str | int | None = None,
    faces: int = 1,
    noise: float = 0.0,
    blur: bool = False,
    dark: bool = False,
    bright: bool = False,
    occluded: float = 0.0,
    small_face: bool = False,
) -> Image.Image:
    """Render a synthetic face image with optional degradations.

    Geometry and coloring are derived from `identity` (or `seed`), so that
    enrollment and capture images of the same identity share appearance while
    per-capture `seed` randomness varies lighting/noise only.
    """
    rng = _rng(seed)
    irng = _rng(identity if identity is not None else seed)
    img = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)

    bg = tuple(irng.randint(130, 175) for _ in range(3))
    bg = (max(90, bg[0]), max(90, bg[0] + 25), max(120, bg[0] + 55))  # blue-gray, non-skin
    draw.rectangle([0, 0, W, H], fill=bg)
    # background furniture blobs so "no face" images still have content
    for _ in range(rng.randint(0, 4)):
        bx, by = rng.randint(0, W), rng.randint(0, H)
        br = rng.randint(10, 30)
        _ellipse(draw, bx, by, br, br, tuple(max(0, c - 25) for c in bg))

    if faces == 0:
        img = img.filter(ImageFilter.GaussianBlur(2))
    elif faces == 1:
        if small_face:
            scale = 0.45
            _draw_face(draw, irng, W / 2, H / 2 + 40, scale)
        else:
            _draw_face(draw, irng, W / 2, H / 2 - 20, 1.0)
    elif faces == 2:
        _draw_face(draw, irng, W * 0.30, H / 2 - 20, 0.75)
        _draw_face(draw, irng, W * 0.70, H / 2 - 20, 0.75)

    # degradations
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(radius=8))
    if dark:
        img = Image.eval(img, lambda p: max(0, int(p * 0.35)))
    if bright:
        img = Image.eval(img, lambda p: min(255, int(p * 1.5)))
    if noise:
        nrng = np.random.default_rng(rng.randrange(10**9))
        arr = np.asarray(img, dtype=np.int16)
        arr += nrng.integers(-int(60 * noise), int(60 * noise) + 1, size=arr.shape)
        arr = np.clip(arr, 0, 255).astype(np.uint8)
        img = Image.fromarray(arr)
    if occluded > 0:
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        band_y = int(H * (0.50 + 0.15 * occluded))
        od.rectangle([0, band_y, W, band_y + int(60 * occluded) + 5], fill=(60, 60, 60, 210))
        img = img.convert("RGBA")
        img = Image.alpha_composite(img, overlay).convert("RGB")

    return img


def render_enrollment(seed: str | int, samples: int = 3) -> list[Image.Image]:
    """A few slightly different renders of the same identity."""
    images = []
    variants = [
        {"noise": 0.03},
        {"noise": 0.07},
        {"noise": 0.05},
        {"noise": 0.02},
    ]
    for i in range(samples):
        images.append(
            render_face(
                f"{seed}-sample-{i}",
                identity=seed,
                **variants[i % len(variants)],
            )
        )
    return images


def to_base64(image: Image.Image, fmt: str = "JPEG") -> str:
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format=fmt, quality=90)
    import base64

    return base64.b64encode(buf.getvalue()).decode("ascii")


def to_bytes(image: Image.Image, fmt: str = "JPEG") -> bytes:
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format=fmt, quality=90)
    return buf.getvalue()
