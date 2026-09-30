"""Contrast is a build-time fact, so it is asserted at build time.

Every value here is the one that shipped in index.css. If someone edits a
colour by eye and this test fails, the edit is wrong - not the test.

Why a per-token test is not enough: `text-warn` on `--c-raised` measured 5.20:1
and passed, while `text-warn` on a `bg-warn/15` badge - the same colour, over a
background tinted 15% toward it - measured 4.26:1 and failed. The tint pulls
the background toward the text, so the worst case is never a plain ramp colour.
That is why TINTED below enumerates the pairs the codebase actually renders.
"""

import json
import re
from pathlib import Path

import pytest

CSS_PATH = Path(__file__).resolve().parents[2] / "frontend" / "src" / "index.css"

# WCAG 2.1 AA for body text. Large text (18.66px bold / 24px) gets 3.0, but
# every use of these tokens is small text: badges are text-xs, .eyebrow is
# text-xs, placeholders are text-base. So 4.5 everywhere.
MIN_NORMAL = 4.5

LIGHT = {
    "canvas": (246, 246, 245),
    "surface": (255, 255, 255),
    "raised": (240, 240, 239),
    "text": (23, 23, 26),
    "muted": (92, 92, 99),
    "faint": (106, 106, 112),
    "accent": (23, 23, 26),
    "accent-fg": (255, 255, 255),
    "danger": (180, 35, 31),
    "danger-fg": (255, 255, 255),
    "warn": (130, 85, 0),
    "warn-fg": (255, 255, 255),
    "ok": (31, 107, 58),
    "ok-fg": (255, 255, 255),
}

DARK = {
    "canvas": (10, 10, 11),
    "surface": (19, 19, 20),
    "raised": (28, 28, 30),
    "text": (242, 242, 240),
    "muted": (161, 161, 166),
    "faint": (134, 134, 140),
    "accent": (242, 242, 240),
    "accent-fg": (10, 10, 11),
    "danger": (234, 110, 113),
    "danger-fg": (26, 10, 10),
    "warn": (240, 180, 41),
    "warn-fg": (26, 18, 0),
    "ok": (65, 170, 95),
    "ok-fg": (6, 24, 12),
}

# Colours that appear as foreground text.
FONTS = ("text", "muted", "faint", "danger", "warn", "ok")

# The three backgrounds content actually sits on. `raised` is the lightest, so
# it is the worst case for a dark foreground in light mode.
PLAIN_BASES = ("canvas", "surface", "raised")

# (tint colour, alpha) pairs that appear as a background behind that colour's
# own text. Both /10 and /15 are used: /15 in badges, /10 in alert blocks.
TINTS = ((0.10, 0.15))

# The solid button pairs: --c-*-fg on --c-*.
SOLID = (("accent", "accent-fg"), ("danger", "danger-fg"), ("ok", "ok-fg"), ("warn", "warn-fg"))


def _channel(value: int) -> float:
    c = value / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = (_channel(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def tint_over(fg: tuple[int, int, int], bg: tuple[int, int, int], alpha: float):
    return tuple(round(fg[i] * alpha + bg[i] * (1 - alpha)) for i in range(3))


def _hex(rgb) -> str:
    return "#%02x%02x%02x" % rgb


def _css_text() -> str:
    return CSS_PATH.read_text(encoding="utf-8")


def _assert_shipped_values_match_this_file() -> None:
    """The dicts above must equal what index.css actually declares.

    Without this, someone can fix the CSS, leave the dict stale, and the suite
    keeps passing on numbers that no longer describe the product - which is the
    exact failure mode this file exists to prevent.
    """
    css = _css_text()
    blocks = {
        "light": css.split(":root", 1)[1].split(".dark", 1)[0],
        "dark": css.split(".dark", 1)[1],
    }
    for theme_name, block in blocks.items():
        declared = {
            name: hexval
            for name, hexval in re.findall(r"--c-([a-z-]+):\s*(#[0-9a-fA-F]{6})\s*;", block)
        }
        expected = (LIGHT if theme_name == "light" else DARK)
        # -fg tokens are also asserted via SOLID; check the whole ramp is present.
        for name, rgb in expected.items():
            assert name in declared, f"{theme_name}: --c-{name} is missing from index.css"
            assert declared[name] == _hex(rgb).lower(), (
                f"{theme_name}: --c-{name} is {declared[name]} in index.css but this test "
                f"believes it is {_hex(rgb)}. Update the dict above to the shipped value."
            )


@pytest.fixture(scope="module", autouse=True)
def _shipped_values_are_current():
    _assert_shipped_values_match_this_file()


@pytest.mark.parametrize("theme_name", ["light", "dark"])
@pytest.mark.parametrize("token", FONTS)
def test_text_colour_clears_aa_on_every_plain_background(theme_name, token):
    ramp = LIGHT if theme_name == "light" else DARK
    worst = min(contrast(ramp[token], ramp[base]) for base in PLAIN_BASES)
    assert worst >= MIN_NORMAL, (
        f"{theme_name} text-{token} ({_hex(ramp[token])}) is only {worst:.2f}:1 on a plain "
        f"ramp background. Needs {MIN_NORMAL}:1."
    )


@pytest.mark.parametrize("theme_name", ["light", "dark"])
@pytest.mark.parametrize("token", ["ok", "warn", "danger"])
@pytest.mark.parametrize("alpha", TINTS)
def test_text_colour_clears_aa_on_its_own_tint(theme_name, token, alpha):
    """The failure that motivated this file.

    A tint at alpha over a background darkens the background toward the text,
    so `text-X` on `bg-X/{alpha}` is always worse than `text-X` on a plain
    surface. Checking only plain backgrounds is how #8a5a00 shipped at 4.26:1.
    """
    ramp = LIGHT if theme_name == "light" else DARK
    fg = ramp[token]
    worst, worst_base = 99.0, None
    for base in PLAIN_BASES:
        bg = tint_over(fg, ramp[base], alpha)
        ratio = contrast(fg, bg)
        if ratio < worst:
            worst, worst_base = ratio, base
    assert worst >= MIN_NORMAL, (
        f"{theme_name} text-{token} ({_hex(fg)}) is only {worst:.2f}:1 on bg-{token}/{alpha:g} "
        f"over {worst_base} ({_hex(tint_over(fg, ramp[worst_base], alpha))}). Needs "
        f"{MIN_NORMAL}:1. Darken or lighten the token, or lower the tint alpha."
    )


@pytest.mark.parametrize("theme_name", ["light", "dark"])
@pytest.mark.parametrize("bg,fg", SOLID)
def test_solid_button_label_clears_aa(theme_name, bg, fg):
    ramp = LIGHT if theme_name == "light" else DARK
    ratio = contrast(ramp[fg], ramp[bg])
    assert ratio >= MIN_NORMAL, (
        f"{theme_name} button bg-{bg} with text-{fg} is {ratio:.2f}:1. Needs {MIN_NORMAL}:1."
    )


@pytest.mark.parametrize("theme_name", ["light", "dark"])
@pytest.mark.parametrize("alpha", [0.90])
def test_label_on_a_heavy_tint_uses_the_ramp_fg_token(theme_name, alpha):
    """`bg-danger/90` is the camera-error bar, so its label must clear AA too.

    It used `text-text`, which is 3.18:1 on that tint in light mode. The ramp
    already carries the answer in `--c-accent-fg` - the token that means "on this
    colour" - and the codebase was not using it. Asserted here so the pairing
    stays put, since `accent-fg` differs per theme (white in light, near-black in
    dark) and a hardcoded colour would pass in one and fail in the other.
    """
    ramp = LIGHT if theme_name == "light" else DARK
    worst, worst_base = 99.0, None
    for base in PLAIN_BASES:
        bg = tint_over(ramp["danger"], ramp[base], alpha)
        ratio = contrast(ramp["accent-fg"], bg)
        if ratio < worst:
            worst, worst_base = ratio, base
    assert worst >= MIN_NORMAL, (
        f"{theme_name} text-accent-fg is only {worst:.2f}:1 on bg-danger/{alpha:g} over "
        f"{worst_base}. Needs {MIN_NORMAL}:1."
    )


@pytest.mark.parametrize("theme_name", ["light", "dark"])
def test_muted_on_raised_badge_clears_aa(theme_name):
    """`TONE_CLASS.neutral` is `bg-raised text-muted`, the default for an
    unrecognised status - so a status the backend invents renders at whatever
    contrast this is."""
    ramp = LIGHT if theme_name == "light" else DARK
    ratio = contrast(ramp["muted"], ramp["raised"])
    assert ratio >= MIN_NORMAL, f"{theme_name} text-muted on bg-raised is {ratio:.2f}:1."


@pytest.mark.parametrize("theme_name", ["light", "dark"])
def test_every_colour_is_declared_in_both_forms(theme_name):
    """A colour added in one form only is the Phase 1 defect again.

    The hex form feeds hand-written CSS; the `-rgb` form feeds Tailwind's
    opacity modifier. Dropping either one is silent - the build still passes.
    """
    css = _css_text()
    block = css.split(":root", 1)[1].split(".dark", 1)[0] if theme_name == "light" else css.split(".dark", 1)[1]
    names = re.findall(r"--c-([a-z-]+):\s*#[0-9a-fA-F]{6}\s*;", block)
    channels = set(re.findall(r"--c-([a-z-]+)-rgb:\s*[0-9]+ [0-9]+ [0-9]+;", block))
    missing = sorted(set(names) - channels)
    assert not missing, f"{theme_name}: no --c-*-rgb channel form for {missing}"
    orphans = sorted(channels - set(names))
    assert not orphans, f"{theme_name}: --c-*-rgb with no hex form for {orphans}"


def test_channel_form_agrees_with_the_hex_form(theme_name="both"):
    """A channel triplet that disagrees with its hex is an invisible bug.

    Both forms feed different rules, so a hand edit to one leaves the UI two
    different colours depending on which class is applied.
    """
    css = _css_text()
    blocks = {
        "light": css.split(":root", 1)[1].split(".dark", 1)[0],
        "dark": css.split(".dark", 1)[1],
    }
    for theme_name, block in blocks.items():
        hexes = dict(
            re.findall(r"--c-([a-z-]+):\s*(#[0-9a-fA-F]{6})\s*;", block)
        )
        tris = dict(
            (name, tuple(int(v) for v in triplet.split()))
            for name, triplet in re.findall(
                r"--c-([a-z-]+)-rgb:\s*([0-9]+ [0-9]+ [0-9]+)\s*;", block
            )
        )
        for name, hexval in hexes.items():
            r, g, b = (int(hexval[i : i + 2], 16) for i in (1, 3, 5))
            assert tris[name] == (r, g, b), (
                f"{theme_name} --c-{name}: hex {hexval} is (r={r},g={g},b={b}) but the channel "
                f"form says {tris[name]}. Tailwind and hand-written CSS are rendering "
                f"different colours."
            )


def test_reduced_motion_covers_every_animation():
    """`prefers-reduced-motion` was honoured for the sheet entry only.

    `animate-fade-in` and `animate-pulse` are used on the result screen and the
    recording indicator, which is exactly where motion is unwelcome.
    """
    css = _css_text()
    block = css.split("prefers-reduced-motion", 1)
    assert len(block) == 2, "no prefers-reduced-motion block in index.css"
    reduced = block[1]
    for prop in ("animation-duration", "animation-iteration-count", "transition-duration"):
        assert prop in reduced, f"prefers-reduced-motion does not neutralise {prop}"


def test_no_backdrop_blur_without_a_solid_background():
    """`backdrop-blur` only makes sense over something translucent.

    It was paired with `bg-canvas/90` and `bg-surface/95`, which meant the bars
    were see-through. Both are now opaque and the blur is gone; if someone
    reintroduces a translucent bar, this fails and points at why it looked wrong.
    """
    source = (
        Path(__file__).resolve().parents[2] / "frontend" / "src" / "components" / "Layout.tsx"
    ).read_text(encoding="utf-8")
    # Strip comments: this file documents why the blur was removed, and a test
    # that trips on its own explanation is a test that gets deleted.
    layout = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    layout = re.sub(r"//[^\n]*", "", layout)
    assert "backdrop-blur" not in layout, (
        "Layout.tsx uses backdrop-blur. If the bar is translucent again, content scrolls "
        "visibly under it - which is the Phase 2 defect. Prefer a solid background."
    )
    # The two fixed bars must be solid, not tinted.
    for bar in ("bg-canvas", "bg-surface"):
        assert f"{bar}/" not in layout, f"Layout.tsx uses a translucent {bar}/NN bar."


def test_no_utility_name_appears_only_in_a_comment():
    """Tailwind's content scanner does not strip comments.

    A class named in a comment is a class the scanner sees, so the rule is
    emitted into the stylesheet. `backdrop-blur` was documented in a comment
    explaining its removal, and the build still shipped a `.backdrop-blur` rule.
    Nothing rendered through it - no element carries the class - but a shipped
    rule for a class nothing uses is exactly the "unused component class" trap
    that `.tap` fell into, one level down.
    """
    root = Path(__file__).resolve().parents[2] / "frontend" / "src"
    offenders: dict[str, list[str]] = {}
    # A utility shape: an optional dash-prefixed modifier then a known prefix.
    utility = re.compile(
        r"(?<![\w-])((?:-)?(?:bg|text|border|ring|shadow|fill|stroke|from|to|via|"
        r"divide|outline|decoration|accent|caret|placeholder)-[a-z]+(?:/[0-9]+)?)"
    )
    for path in sorted(root.rglob("*.tsx")):
        raw = path.read_text(encoding="utf-8")
        code = re.sub(r"/\*.*?\*/", "", raw, flags=re.DOTALL)
        code = re.sub(r"//[^\n]*", "", code)
        commented_only = set(utility.findall(raw)) - set(utility.findall(code))
        # A class may be named in a comment *and* in a docstring-ish block; only
        # flag it when it appears in a comment and nowhere in the live code.
        if commented_only:
            offenders[path.relative_to(root).as_posix()] = sorted(commented_only)
    assert not offenders, (
        "utility class names that appear only in a comment - Tailwind will emit "
        "rules for them:\n" + json.dumps(offenders, indent=2)
    )