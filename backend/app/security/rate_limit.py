"""Simple in-memory sliding-window rate limiter (per client IP).

Production deployments should back this with a distributed store (e.g. Redis);
the interface here is intentionally small and swap-able.
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


_limiter = RateLimiter()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Applies coarse rate limits per route family for public/anonymous use."""

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
            if not _limiter.check((client_ip, route_key), limit, window):
                from app.services.audit_service import write_audit

                try:
                    db = request.app.state.db_factory()
                    write_audit(
                        db,
                        actor_type="system",
                        action="rate_limited",
                        actor_id=hash(client_ip) % 100000,
                        details={"path": path},
                        ip=client_ip,
                    )
                    db.close()
                except Exception:
                    pass
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": "Too many requests. Please wait a moment and try again.",
                        "retry_after": window,
                    },
                    headers={"Retry-After": str(window)},
                )

        return await call_next(request)
