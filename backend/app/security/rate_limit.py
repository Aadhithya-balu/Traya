"""Simple in-memory sliding-window rate limiter.

Per-IP only, per-IP *and* per-account for identification, since identification is
this product's enumeration vector.

Production deployments should back this with a distributed store (e.g. Redis);
the interface here is intentionally small and swap-able. That limitation is real
and is recorded in [SECURITY_MODEL.md](../../../docs/SECURITY_MODEL.md): with
multiple app workers each process holds its own window, so the effective limit
is `limit * workers`.
"""
import time
from collections import defaultdict, deque
from threading import Lock

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config.settings import settings


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def _cleanup(self) -> None:
        now = time.monotonic()
        stale = [
            k
            for k, q in self._hits.items()
            if not q or now - q[0] > settings.AUTH_WINDOW_SECONDS * 10
        ]
        for k in stale:
            self._hits.pop(k, None)

    def check(self, key: tuple[str, str], limit: int, window: int) -> bool:
        if not settings.RATE_LIMIT_ENABLED or settings.TESTING:
            return True
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            self._cleanup()
            return True

    def reset(self) -> None:
        """Drop every window. Test-only; a production reset would be a bypass."""
        with self._lock:
            self._hits.clear()


_limiter = RateLimiter()


def _bearer_user_id(request: Request) -> str | None:
    """The account id behind an `Authorization: Bearer` header, if any.

    Decoded, **not verified**. The signature check happens in the route
    dependency; this only needs a stable key, and re-verifying would mean
    decoding the token twice on every identification request. An attacker can
    present a forged sub and get a window keyed on a value they chose - which is
    no worse than the per-IP key they already have, and the route still rejects
    them. The point of this key is to hold a *legitimate* account to its own
    budget, not to authenticate.
    """
    header = request.headers.get("Authorization") or ""
    if not header.startswith("Bearer "):
        return None
    token = header[7:].strip()
    if not token:
        return None
    try:
        from app.security.tokens import decode_token

        return decode_token(token).get("sub")
    except Exception:
        return None


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Coarse rate limits per route family.

    Anonymous callers are limited by IP. A caller presenting a bearer token is
    **additionally** limited by account, because an IP key alone is defeated by
    address rotation while the account stays stable.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        client_ip = request.client.host if request.client else "unknown"
        route_key: str | None = None
        limit = settings.AUTH_LIMIT
        window = settings.AUTH_WINDOW_SECONDS

        if path.startswith("/api/emergency"):
            route_key = "emergency"
            limit = settings.PUBLIC_IDENTIFY_LIMIT
            window = settings.PUBLIC_IDENTIFY_WINDOW_SECONDS
        elif path.startswith("/api/auth"):
            route_key = "auth"

        if route_key:
            keys = [(client_ip, route_key, limit, window)]
            if route_key == "emergency":
                subject = _bearer_user_id(request)
                if subject:
                    keys.append((f"user:{subject}", "identify", settings.IDENTIFY_USER_LIMIT, settings.IDENTIFY_USER_WINDOW_SECONDS))

            blocked = next(
                (
                    budget
                    for budget in keys
                    if not _limiter.check((budget[0], budget[1]), budget[2], budget[3])
                ),
                None,
            )
            if blocked is None:
                return await call_next(request)

            self._audit(request, path, client_ip, blocked, window)
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Too many requests. Please wait a moment and try again.",
                    "retry_after": blocked[3],
                },
                headers={"Retry-After": str(blocked[3])},
            )

        return await call_next(request)

    @staticmethod
    def _audit(request, path, client_ip, budget, window) -> None:
        """A rate-limited request is evidence, so it is written down.

        Swallowed deliberately: failing to audit must not turn a 429 into a 500,
        and a missing audit row is a lesser problem than a crashed limiter.
        """
        from app.services.audit_service import write_audit

        try:
            db = request.app.state.db_factory()
            write_audit(
                db,
                actor_type="system",
                action="rate_limited",
                actor_id=hash(budget[0]) % 100000,
                details={
                    "path": path,
                    "limiter": budget[1],
                    "window": budget[3],
                },
                ip=client_ip,
            )
            db.close()
        except Exception:
            pass
