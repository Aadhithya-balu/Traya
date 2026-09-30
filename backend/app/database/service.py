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
                logger.warning("Primary database unavailable: %s", exc)
                if not settings.DATABASE_ALLOW_FALLBACK:
                    raise
                self._status = self._activate(
                    fallback,
                    BACKEND_SQLITE,
                    primary_configured=True,
                    degraded=True,
                    reason="primary_unavailable",
                    detail=type(exc).__name__,
                )
                logger.warning(
                    "Falling back to SQLite demo storage. TRAYA will run, but "
                    "this deployment is not using the primary database."
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
        exception, because /api/health must stay answerable.
        """
        st = self.status
        checks: dict[str, bool] = {}
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
                checks["connect"] = True
                from sqlalchemy import inspect

                checks["schema"] = bool(inspect(self.engine).get_table_names())
                st.tables = len(inspect(self.engine).get_table_names())
        except Exception as exc:
            checks["connect"] = False
            logger.warning("Database health check failed: %s", exc)
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
