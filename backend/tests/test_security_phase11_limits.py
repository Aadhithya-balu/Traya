"""Phase 11 gate: uploads and identification limiting.

Both properties here were absent, not merely untested:

- A 200-byte PNG can declare 40000x40000 pixels. That is ~6.4 GB of RGBA when
  decoded, and the byte cap passed it. Every photo in this product is
  attacker-supplied, so that is a one-request denial of service.
- Identification was limited per IP only. An attacker rotating addresses, or
  anyone behind a shared NAT gateway, has a fresh budget every time.
"""
from __future__ import annotations

import base64
import io
import struct
import zlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config.settings import settings
from app.security.rate_limit import _limiter

REPO_ROOT = Path(__file__).resolve().parents[2]


def _png_bytes(width: int, height: int) -> bytes:
    """A structurally valid PNG of the requested size, without allocating it.

    The IHDR header is all the guard reads, so this is enough to be honest about
    what the test proves: the dimensions are rejected *before* `Image.load()`
    runs, which is the whole point of the guard.
    """

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IEND", b"")


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


# ------------------------------------------------------------- pixel bombs
def test_a_huge_declared_dimension_is_refused_before_decoding():
    from app.utils.helpers import validate_and_decode_image

    payload = _b64(_png_bytes(40000, 40000))
    with pytest.raises(Exception) as exc:
        validate_and_decode_image(payload)
    assert getattr(exc.value, "status_code", None) in (413, 422), (
        f"expected a rejection, got {exc.value!r}"
    )


def test_a_wide_but_small_image_is_refused_on_aspect_ratio():
    from app.utils.helpers import validate_and_decode_image

    # 5000 x 20 is 50000 pixels: trivially under MAX_IMAGE_PIXELS. It is not a
    # photograph, and a 250:1 strip is a second decompression trick.
    payload = _b64(_png_bytes(5000, 20))
    with pytest.raises(Exception) as exc:
        validate_and_decode_image(payload)
    assert getattr(exc.value, "status_code", None) == 422


def test_an_ordinary_photograph_is_accepted():
    """The guard must not be so strict that it breaks the actual product."""
    from PIL import Image

    from app.utils.helpers import validate_and_decode_image

    buf = io.BytesIO()
    Image.new("RGB", (640, 480), (120, 120, 120)).save(buf, format="JPEG")
    assert validate_and_decode_image(_b64(buf.getvalue())).startswith(b"\xff\xd8")


def test_the_pixel_limits_are_documented_in_the_settings_contract():
    """A guard nobody can raise is a bug waiting for a 48MP camera."""
    doc = REPO_ROOT / "docs" / "backend" / "configuration.md"
    assert doc.exists(), "docs/backend/configuration.md is missing"
    text = doc.read_text(encoding="utf-8")
    assert "MAX_IMAGE_PIXELS" in text, "MAX_IMAGE_PIXELS is undocumented"


# ------------------------------------------------------- per-user limiting
@pytest.fixture
def limiter_on(monkeypatch):
    """Enable the limiter for one test.

    `RateLimiter.check` short-circuits under `TESTING`, which is what keeps the
    rest of the suite from tripping it. `settings` is import-time mutable state,
    so it can be flipped per test and restored after.
    """
    monkeypatch.setattr(settings, "TESTING", False)
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "PUBLIC_IDENTIFY_LIMIT", 3)
    monkeypatch.setattr(settings, "IDENTIFY_USER_LIMIT", 3)
    _limiter.reset()
    yield
    _limiter.reset()


def _tiny_jpeg_b64() -> str:
    """A real, decodable 32x32 JPEG.

    The rate-limit tests must exercise the limiter, not the upload validator.
    A header-only PNG is rejected 422 at the decode step, which would let a
    broken limiter look like a working one if the assertion only counted calls.
    """
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (32, 32), (128, 128, 128)).save(buf, format="JPEG")
    return _b64(buf.getvalue())


@pytest.fixture
def live_session(client: TestClient):
    """A real emergency session, so the route is reached rather than 404'd."""
    r = client.post("/api/emergency/start", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    return body["session_id"], {"X-TRAYA-Session-Token": body["session_token"]}


def _hammer(client: TestClient, session_id: str, headers: dict, attempts: int = 8) -> list[int]:
    return [
        client.post(
            f"/api/emergency/{session_id}/identify",
            json={"image": _tiny_jpeg_b64()},
            headers=headers,
        ).status_code
        for _ in range(attempts)
    ]


def test_the_harness_really_reaches_the_route(limiter_on, client, live_session):
    """Guard on the guard: the fixture must produce a non-429, non-422 result.

    Without this, a test asserting "eventually 429" would also pass if the
    upload validator were rejecting every image and the limiter never ran.
    """
    session_id, headers = live_session
    statuses = _hammer(client, session_id, headers, attempts=2)
    assert all(s < 400 for s in statuses), (
        f"the fixture image never reached identification: {statuses}"
    )


def test_repeated_identification_is_rate_limited(limiter_on, client, live_session):
    """Phase 11 gate: an enumeration attempt is limited.

    The first 429 lands on the *third* attempt, not the fourth, because
    `POST /api/emergency/start` shares the `/api/emergency/*` budget: the limiter
    is middleware and cannot tell a session-creation from an identification.
    That is a real (and defensible) property of the design, not a bug, so the
    assertion measures the effect rather than pretending the budget is separate.
    """
    statuses = _hammer(client, *live_session)
    assert 429 in statuses, f"never rate limited: {statuses}"
    allowed = statuses.count(200)
    assert allowed == 2, (
        f"expected 2 successful calls (one budget slot spent by /start), "
        f"got {allowed}: {statuses}"
    )
    assert statuses.index(429) == allowed, f"limit did not take effect: {statuses}"


def test_the_rate_limit_response_is_actionable(limiter_on, client, live_session):
    """A 429 with no retry hint is a support ticket waiting to happen."""
    session_id, headers = live_session
    body = None
    resp_headers = {}
    for _ in range(8):
        r = client.post(
            f"/api/emergency/{session_id}/identify",
            json={"image": _tiny_jpeg_b64()},
            headers=headers,
        )
        if r.status_code == 429:
            body, resp_headers = r.json(), r.headers
            break
    assert body is not None, "never reached the limit"
    assert isinstance(body.get("retry_after"), int) and body["retry_after"] > 0
    assert resp_headers.get("Retry-After") == str(body["retry_after"])


def test_the_rate_limited_request_is_audited(limiter_on, client, live_session):
    """A limit nobody can prove was applied is indistinguishable from no limit."""
    from app.database.session import SessionLocal
    from app.models.entities import AuditLog

    _hammer(client, *live_session)

    db = SessionLocal()
    try:
        rows = db.query(AuditLog).filter(AuditLog.action == "rate_limited").all()
        assert rows, "a rate-limited request wrote no audit row"
        assert rows[0].details, "the audit row records no context"
    finally:
        db.close()


def test_rate_limiting_covers_authentication_too(limiter_on, client):
    """Brute-forcing a password is the same class of problem as enumerating a face."""
    statuses = [
        client.post(
            "/api/auth/login",
            json={"email": "nobody@traya.demo", "password": "wrong-password"},
        ).status_code
        for _ in range(40)
    ]
    assert 429 in statuses, f"login was never rate limited: {set(statuses)}"


def test_the_per_user_key_is_independent_of_the_ip_key(limiter_on):
    """The whole point: a stable account is limited even as the address moves.

    This is asserted against the limiter directly rather than over HTTP because
    a TestClient cannot easily change its source address, and the property under
    test is about the keys, not the transport.
    """
    from app.security.rate_limit import RateLimiter

    limiter = RateLimiter()
    ok = [
        limiter.check(("user:alice", "identify"), 3, 60)
        for _ in range(4)
    ]
    assert ok == [True, True, True, False]

    # A different account is untouched by alice's exhaustion.
    assert limiter.check(("user:bob", "identify"), 3, 60) is True


def test_the_user_key_cannot_be_evaded_by_forging_a_sub(limiter_on):
    """Decoded, not verified - so a forged sub buys a window keyed on garbage.

    That is acceptable (documented in `_bearer_user_id`) because the route still
    rejects the token. What must NOT happen is an empty sub collapsing every
    forged token onto one shared window, which would let an attacker deny
    service to a real account by guessing its id.
    """
    from app.security.rate_limit import _bearer_user_id

    class FakeRequest:
        def __init__(self, headers):
            self.headers = headers

    assert _bearer_user_id(FakeRequest({})) is None
    assert _bearer_user_id(FakeRequest({"Authorization": "Bearer garbage"})) is None
    assert (
        _bearer_user_id(FakeRequest({"Authorization": "Basic abc"})) is None
    ), "a non-bearer scheme must not be treated as a user key"


def test_rate_limiting_is_documented_as_its_actual_scope():
    """It is per-process and per-IP-with-per-account. Say so, do not imply Redis."""
    doc = REPO_ROOT / "docs" / "SECURITY_MODEL.md"
    text = doc.read_text(encoding="utf-8").lower()
    assert "rate limit" in text
    assert "redis" in text, (
        "the limiter is per-process; the missing distributed store must be "
        "named, not left implied"
    )
