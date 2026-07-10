"""Alembic environment. Runs as the migrator role (MIGRATION_DATABASE_URL)."""
from __future__ import annotations

import os
import pathlib
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make the app package importable (env.py runs from backend/migrations/).
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from app.models import Base  # noqa: E402  (import after sys.path tweak)

target_metadata = Base.metadata
config = context.config

# Prefer the migrator URL; fall back to the app URL only if not set.
url = os.environ.get("MIGRATION_DATABASE_URL") or os.environ.get("DATABASE_URL")
if url:
    config.set_main_option("sqlalchemy.url", url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
