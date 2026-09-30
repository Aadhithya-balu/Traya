"""Database service: one place that decides which backend TRAYA talks to.

The application never constructs a SQLAlchemy engine directly. It asks this
service, which resolves the backend once at startup:

    Supabase / PostgreSQL   (primary, production)
            |
            |  probe fails or pool unreachable
            v
    SQLite                  (demo / development fallback)

The active choice is exposed through :attr:`DatabaseService.status` so the
health endpoint and the UI can show a plain-language connection indicator
("Connected" / "Demo Offline Mode") instead of leaking a driver error.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.config.settings import settings

logger = logging.getLogger("traya.db")

BACKEND_SUPABASE = "supabase"
BACKEND_POSTGRES = "postgres"
BACKEND_SQLITE = "sqlite"


@dataclass
class DatabaseStatus:
    """What the rest of the app (and the UI) needs to know about storage."""

    backend: str
    dialect: str
    masked_url: str
    primary_configured: bool
    degraded: bool = False
    reason: str | None = None
    detail: str | None = None
    tables: int = 0
    checks: dict[str, bool] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "dialect": self.dialect,
            "url": self.masked_url,
            "primary_configured": self.primary_configured,
            "degraded": self.degraded,
            "reason": self.reason,
            "detail": self.detail,
            "tables": self.tables,
            "checks": self.checks,
        }


class DatabaseService:
    """Resolves and owns the active engine, with a SQLite safety net."""

    def __init__(self) -> None:
        self._engine: Engine | None = None
        self._lock = threading.RLock()
        self._status: DatabaseStatus | None = None

    # ---------------------------------------------------------------- build
    def _build_engine(self, url: str) -> Engine:
        kwargs: dict[str, Any] = {"future": True, "pool_pre_ping": True}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
        else:
            # Fail fast instead of hanging a cold boot behind an unreachable
            # Supabase project. psycopg honours connect_timeout in seconds.
            kwargs["connect_args"] = {
                "connect_timeout": max(1, int(settings.DATABASE_PROBE_TIMEOUT_SECONDS))
            }
        return create_engine(url, **kwargs)

    def _probe(self, engine: Engine) -> None:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))

    # ------------------------------------------------------------- resolve
    def _fallback_permitted(self) -> bool:
        """Whether a failed primary may degrade to SQLite.

        Two independent conditions, because either one alone is a way to lose
        an incident without noticing:

        - ``DATABASE_ALLOW_FALLBACK`` must be true. It defaults to false, so
          pointing ``DATABASE_URL`` at Supabase and having the network fail is
          a startup error rather than a quiet downgrade.
        - ``DEMO_MODE`` must be true. Demo mode is explicitly the SQLite
          fallback's world; in production the answer is no regardless of the
          flag, so a stray env var cannot re-enable data loss.

        Neither check matters when the primary is already SQLite, which is the
        zero-config path: :meth:`initialize` returns before the fallback is
        ever consulted.
        """
        if not settings.DATABASE_ALLOW_FALLBACK:
            return False
        if not settings.DEMO_MODE:
            logger.error(
                "DATABASE_ALLOW_FALLBACK is true but DEMO_MODE is false. Refusing "
                "to fall back: production runs must not degrade to a local SQLite "
                "file."
            )
            return False
        return True

    def initialize(self) -> DatabaseStatus:
        """Pick the backend. Idempotent; safe to call on every boot."""
        with self._lock:
            if self._status is not None:
                return self._status

            primary = settings.DATABASE_URL
            fallback = settings.effective_fallback_url

            if settings.is_sqlite:
                self._status = self._activate(
                    primary, BACKEND_SQLITE, primary_configured=False
                )
                return self._status

            try:
                self._activate(
                    primary,
                    BACKEND_SUPABASE if settings.uses_supabase else BACKEND_POSTGRES,
                    primary_configured=True,
                    probe=True,
                )
                logger.info("Database backend: %s", self._status.backend)
                return self._status
            except Exception as exc:
                logger.error("Primary database unavailable: %s", exc)
                if not self._fallback_permitted():
                    raise
                self._status = self._activate(
                    fallback,
                    BACKEND_SQLITE,
                    primary_configured=True,
                    degraded=True,
                    reason="primary_unavailable",
                    detail=type(exc).__name__,
                )
                logger.error(
                    "FALLING BACK TO SQLITE. Identifications, embeddings and audit "
                    "rows from this point are written to a local file that is not "
                    "shared with responders, not covered by row-level security, and "
                    "not backed up. This is a degraded emergency mode, not a normal "
                    "state. Set DATABASE_ALLOW_FALLBACK=false to make an unreachable "
                    "primary a startup failure instead."
                )
                return self._status

    def _activate(
        self,
        url: str,
        backend: str,
        *,
        primary_configured: bool,
        probe: bool = False,
        degraded: bool = False,
        reason: str | None = None,
        detail: str | None = None,
    ) -> DatabaseStatus:
        engine = self._build_engine(url)
        if probe:
            self._probe(engine)
        elif backend == BACKEND_SQLITE:
            self._probe(engine)
        self._engine = engine
        self._status = DatabaseStatus(
            backend=backend,
            dialect=engine.dialect.name,
            masked_url=_mask(url),
            primary_configured=primary_configured,
            degraded=degraded,
            reason=reason,
            detail=detail,
        )
        return self._status

    # -------------------------------------------------------------- access
    @property
    def engine(self) -> Engine:
        if self._engine is None:
            self.initialize()
        assert self._engine is not None
        return self._engine

    @property
    def status(self) -> DatabaseStatus:
        return self.initialize()

    def sessionmaker(self) -> sessionmaker:
        return sessionmaker(
            bind=self.engine, autoflush=False, autocommit=False, expire_on_commit=False
        )

    def health(self) -> DatabaseStatus:
        """Re-probe the active engine and refresh the cached status.

        Never raises: an unreachable database is reported as a status, not an
        exception, because `/api/health` must stay answerable. Resolving the
        backend is inside the guard too, not just the probe. It used to sit
        outside, so with `DATABASE_ALLOW_FALLBACK=false` and a dead primary the
        resolution raised here and the endpoint 500'd — precisely the situation
        it exists to report. Now it returns `connect: false`, which is the
        difference between a monitor that pages you and one that fires once and
        goes quiet.
        """
        try:
            st = self.status
            checks: dict[str, bool] = {}
            try:
                with self.engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                    checks["connect"] = True
                    from sqlalchemy import inspect

                    names = inspect(self.engine).get_table_names()
                    checks["schema"] = bool(names)
                    st.tables = len(names)
            except Exception as exc:
                checks["connect"] = False
                logger.warning("Database health check failed: %s", exc)
        except Exception as exc:
            logger.warning("Database resolution failed: %s", exc)
            return DatabaseStatus(
                backend="none",
                dialect="none",
                masked_url=_mask(settings.DATABASE_URL),
                primary_configured=not settings.is_sqlite,
                degraded=False,
                reason="unresolved",
                detail=type(exc).__name__,
                checks={"connect": False},
            )
        st.checks = checks
        return st

    def create_all(self) -> None:
        from app.models import all_models  # noqa: F401  (registers the models)
        from app.database.session import Base

        Base.metadata.create_all(bind=self.engine)

    def dispose(self) -> None:
        with self._lock:
            if self._engine is not None:
                self._engine.dispose()
            self._engine = None
            self._status = None


def _mask(url: str) -> str:
    if "@" not in url or "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    credentials, host = rest.split("@", 1)
    return f"{scheme}://{credentials.split(':', 1)[0]}:***@{host}"


db_service = DatabaseService()
