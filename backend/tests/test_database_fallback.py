"""The SQLite fallback must fail loudly, not degrade silently.

Phase 3 gate item: *"With `DATABASE_URL` pointing at Supabase and the network
down, the app **fails to start** instead of silently using SQLite."*

This is one of the three irreversible actions called out in `AGENTS.md`, so it
is tested by mechanism rather than by inspection. The previous default was
`DATABASE_ALLOW_FALLBACK=True`, which meant the guarantee existed only if
somebody remembered to set it to false in production - and an unreachable
Supabase project produced a running application writing emergency data to a
local file, with nothing but a `logger.warning` to indicate it.

A real TCP connection is never attempted. A malformed or unroutable
`postgresql://` URL fails in SQLAlchemy's own URL parsing or at `SELECT 1`,
which is the same code path a network outage takes, so the tests are fast,
offline and deterministic.
"""
from __future__ import annotations

import pytest

from app.config.settings import settings
from app.database.service import (
    BACKEND_POSTGRES,
    BACKEND_SQLITE,
    DatabaseService,
)

# Parses as a valid URL, then fails to connect. Reserved TEST-NET-1 address
# (RFC 5737), so nothing can accidentally be listening there.
UNREACHABLE = "postgresql+psycopg://postgres:secret@192.0.2.1:5432/postgres"


@pytest.fixture()
def svc():
    """A fresh service, so one test's resolved status cannot leak into the next."""
    return DatabaseService()


def _patch(monkeypatch, **values):
    for key, value in values.items():
        monkeypatch.setattr(settings, key, value)


def test_fallback_is_off_by_default():
    """The default is the safe one.

    Asserted against the class default, not the live singleton, because the
    singleton has `DEMO_MODE=True` from conftest and that is not what is under
    test here.
    """
    from app.config.settings import Settings

    assert Settings(_env_file=None).DATABASE_ALLOW_FALLBACK is False, (
        "DATABASE_ALLOW_FALLBACK must default to false. Opting in to data loss "
        "should require writing the setting down, not omitting it."
    )


def test_unreachable_primary_fails_when_fallback_is_off(monkeypatch, svc):
    """The gate item. No fallback, so the exception propagates."""
    _patch(
        monkeypatch,
        DATABASE_URL=UNREACHABLE,
        DATABASE_ALLOW_FALLBACK=False,
        DEMO_MODE=True,
        DATABASE_PROBE_TIMEOUT_SECONDS=1,
    )
    with pytest.raises(Exception):
        svc.initialize()


def test_unreachable_primary_refuses_fallback_in_production_mode(monkeypatch, svc):
    """`DEMO_MODE=false` outranks a permissive `DATABASE_ALLOW_FALLBACK`.

    The flag alone is not enough to authorise data loss. Someone who turns on
    both must be told no.
    """
    _patch(
        monkeypatch,
        DATABASE_URL=UNREACHABLE,
        DATABASE_ALLOW_FALLBACK=True,
        DEMO_MODE=False,
        DATABASE_PROBE_TIMEOUT_SECONDS=1,
    )
    with pytest.raises(Exception):
        svc.initialize()


def test_fallback_still_works_when_explicitly_opted_in(monkeypatch, svc, tmp_path):
    """The opt-in path must remain functional, or the setting is a dead branch.

    Runs against a real SQLite file rather than asserting on the permission
    helper, so it proves the degraded status is built correctly and carries the
    fields an operator needs.
    """
    db = tmp_path / "fallback.db"
    _patch(
        monkeypatch,
        DATABASE_URL=UNREACHABLE,
        DATABASE_FALLBACK_URL=f"sqlite:///{db.as_posix()}",
        DATABASE_ALLOW_FALLBACK=True,
        DEMO_MODE=True,
        DATABASE_PROBE_TIMEOUT_SECONDS=1,
    )
    status = svc.initialize()
    assert status.backend == BACKEND_SQLITE
    assert status.degraded is True
    assert status.reason == "primary_unavailable"
    assert status.primary_configured is True
    svc.dispose()


def test_fallback_permitted_matrix(monkeypatch):
    """The permission rule, stated once, as a table.

    Both conditions must hold. A test that only checked the
    `ALLOW_FALLBACK=False` row would pass against an implementation that
    ignored `DEMO_MODE` entirely.
    """
    cases = [
        (False, True, False, "flag off, demo on"),
        (False, False, False, "flag off, demo off"),
        (True, False, False, "flag on, production"),
        (True, True, True, "flag on, demo"),
    ]
    for allow, demo, expected, label in cases:
        _patch(monkeypatch, DATABASE_ALLOW_FALLBACK=allow, DEMO_MODE=demo)
        svc = DatabaseService()
        assert svc._fallback_permitted() is expected, label


def test_sqlite_primary_never_consults_the_fallback(monkeypatch, tmp_path):
    """Zero-config must keep working with the fallback off.

    This is the regression the change could plausibly have caused: SQLite as
    the primary is the demo path, and it must not be treated as a failed probe.
    """
    db = tmp_path / "primary.db"
    _patch(
        monkeypatch,
        DATABASE_URL=f"sqlite:///{db.as_posix()}",
        DATABASE_ALLOW_FALLBACK=False,
        DEMO_MODE=True,
    )
    status = DatabaseService().initialize()
    assert status.backend == BACKEND_SQLITE
    assert status.degraded is False
    assert status.primary_configured is False


def test_dispose_clears_status_so_a_reconfigure_is_possible(monkeypatch, tmp_path):
    """`initialize` caches. A deploy that fixes its config needs a way to retry.

    Without `dispose` clearing `_status`, a service that failed once would keep
    the failure forever, and the rollback path in `AGENTS.md` §9 would depend on
    restarting the process rather than on fixing the environment.
    """
    good = tmp_path / "good.db"
    _patch(
        monkeypatch,
        DATABASE_URL=f"sqlite:///{good.as_posix()}",
        DATABASE_ALLOW_FALLBACK=False,
        DEMO_MODE=True,
    )
    svc = DatabaseService()
    svc.initialize()
    svc.dispose()
    assert svc._status is None
    assert svc.initialize().backend == BACKEND_SQLITE
    svc.dispose()


def test_health_never_raises_when_the_database_is_gone(monkeypatch):
    """ADR 0003 clause 5: `/api/health` reports, it does not 500.

    Monitoring has to be able to tell "the app is down" from "the database is
    unreachable". If health raises, those look identical from outside.

    Uses a SQLite path inside a directory that does not exist, which fails on
    connect without needing a network.
    """
    _patch(
        monkeypatch,
        DATABASE_URL="sqlite:////nonexistent-dir-traya-xyz/x.db",
        DATABASE_ALLOW_FALLBACK=False,
        DEMO_MODE=True,
    )
    status = DatabaseService().health()
    assert status.checks["connect"] is False
    assert isinstance(status.as_dict(), dict)
    assert status.as_dict()["checks"]["connect"] is False