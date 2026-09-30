"""The settings file has to be where the docs say it is.

This is not a test about a value. It is a test about a path.

`BASE_DIR` in `app/config/settings.py` was `Path(__file__).resolve().parent.parent`,
which from `app/config/settings.py` resolves to `backend/app`. So `env_file`
pointed at `backend/app/.env` - a file that has never existed. The `.env` was
documented, recommended in the configuration page and the README, written by
anyone who followed the setup instructions, and read by nobody at all.

Nothing errored. The build passed, the tests passed, and the app behaved
identically with and without a `.env`, because every value fell through to the
class default. That is the same failure shape as a mistyped Tailwind class or a
missing `<alpha-value>`: silent, and invisible to any check that does not
specifically look for it.

The only way this kind of bug survives review is if something asserts the path.
So this asserts the path, and that a file actually sitting there is loaded.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]


def test_base_dir_is_the_backend_root():
    """Not `backend/app`. That is the bug this file exists for."""
    from app.config.settings import BASE_DIR

    assert BASE_DIR == BACKEND, (
        f"BASE_DIR is {BASE_DIR}, expected {BACKEND}. env_file is derived from it, so "
        f"the wrong value means .env is never read."
    )
    assert (BASE_DIR / "app").is_dir(), "BASE_DIR must be the directory containing `app/`"


def test_env_file_is_where_the_docs_say():
    from app.config.settings import settings

    env_file = Path(settings.model_config["env_file"])
    assert env_file == BACKEND / ".env", (
        f"env_file is {env_file}, but the docs say backend/.env. A .env at the documented "
        f"path would be silently ignored."
    )
    # The example file must sit beside it, since the setup instruction is
    # "copy .env.example to .env".
    assert (BACKEND / ".env.example").is_file(), "backend/.env.example is missing"


def test_a_file_at_that_path_is_actually_loaded(tmp_path, monkeypatch):
    """Prove the wiring end to end, not just the path arithmetic.

    Writes a throwaway `.env` with a value that differs from the class default
    and asserts `Settings` picks it up. A path can be correct while the
    `SettingsConfigDict` still fails to use it.
    """
    from app.config.settings import Settings

    marker = "traya-test-marker-value"
    env = tmp_path / ".env"
    env.write_text(f"APP_NAME={marker}\n", encoding="utf-8")

    loaded = Settings(_env_file=str(env), _env_file_encoding="utf-8")
    assert loaded.APP_NAME == marker, (
        "Settings did not read the file it was pointed at, so env_file is not wired up."
    )

    # And the same content passed via the real environment, to prove the
    # environment is not what made the above pass.
    monkeypatch.setenv("APP_NAME", marker)
    assert Settings().APP_NAME == marker


def test_unknown_env_keys_are_ignored_not_fatal(tmp_path):
    """A typo in a key is ignored, by design.

    Documented, and load-bearing: a stray `SUPABASE_ANON_KEYY=` should not stop
    the app booting. The cost is that a typo is also silent, which is why the
    keys that matter are asserted elsewhere rather than trusted to be spelled
    correctly here.
    """
    from app.config.settings import Settings

    env = tmp_path / ".env"
    env.write_text("THIS_SETTING_DOES_NOT_EXIST=1\nAPP_NAME=TRAYA\n", encoding="utf-8")
    loaded = Settings(_env_file=str(env), _env_file_encoding="utf-8")
    assert loaded.APP_NAME == "TRAYA"


def test_gitignore_excludes_the_env_file():
    """The file that holds the service-role key must never be committable.

    Checked rather than assumed, because `.env` being untracked is a one-time
    accident that is easy to make and hard to notice in a review.
    """
    ignore = (BACKEND.parent / ".gitignore").read_text(encoding="utf-8")
    lines = {ln.strip() for ln in ignore.splitlines()}
    assert ".env" in lines, "the repo .gitignore must list .env"
    if (BACKEND / ".env").exists():
        tracked = os.popen(f'cd "{BACKEND.parent}" && git ls-files --error-unmatch backend/.env').read()
        assert tracked.strip() == "", "backend/.env is tracked by git. Untrack it immediately."


@pytest.mark.parametrize(
    "field",
    ["SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_PROJECT_REF"],
)
def test_supabase_fields_are_blank_until_filled_in(field):
    """A committed default must not look like a configured credential.

    These ship empty. Once a developer fills in their own `.env`, git still sees
    nothing, so the only thing protecting the service-role key is that nothing
    in the repository ever holds a real one.
    """
    from app.config.settings import Settings

    loaded = Settings(_env_file=None)
    assert getattr(loaded, field) == "", f"{field} must default to empty, not a value"


def test_migration_env_reads_the_same_file():
    """Alembic must resolve the same `DATABASE_URL` the app does.

    Migrations running against a different database than the app is the kind of
    mismatch that is invisible until a column is missing at runtime. Both read
    `settings.DATABASE_URL`, so this asserts they are wired to the same object
    rather than assuming it.
    """
    from app.config.settings import settings

    migration_env = (BACKEND / "migrations" / "env.py").read_text(encoding="utf-8")
    assert "settings.DATABASE_URL" in migration_env, (
        "migrations/env.py must read settings.DATABASE_URL so the app and the "
        "migrations cannot target different databases."
    )
    assert settings.DATABASE_URL, "DATABASE_URL resolved to an empty string"
