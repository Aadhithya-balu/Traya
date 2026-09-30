"""Alembic environment for TRAYA.

Reads DATABASE_URL from the application settings (app.config.settings) so that
``DATABASE_URL``/``.env`` remain the single source of truth for the connection
string across the app, tests and migrations.
"""
from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config.settings import settings
from app.database.session import Base
from app.models import all_models  # noqa: F401  (register all tables on metadata)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# `set_main_option` writes into a ConfigParser, where `%` starts an
# interpolation. A percent-encoded password (`@` -> `%40`, which any Supabase
# password containing a reserved character will produce) therefore raises
# "invalid interpolation syntax" before a single query is sent.
#
# Doubling the percent is the documented ConfigParser escape and Alembic
# un-escapes it when the value is read back, so the engine receives the real
# URL. Verified end to end against Supabase: a password containing `@` connects
# only with this line present.
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL.replace("%", "%%"))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL to stdout)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (connect directly to the engine)."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
