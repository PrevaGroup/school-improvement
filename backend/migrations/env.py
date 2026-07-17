"""Alembic environment. Connects as the migrator role and builds the schema.

The connection comes from app.config.settings (which reads .env via pydantic — no
shell sourcing), assembled with URL.create so special characters in the password
are handled correctly.
"""
from __future__ import annotations

import pathlib
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

# Make the app package importable (env.py runs from backend/migrations/).
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.models import Base      # noqa: E402

# Module-owned tables live with their module, not in core (docs/MODULES.md). A model only
# reaches Base.metadata if something imports it, and autogenerate reads a table it cannot
# see as DROP TABLE — so every module that owns tables MUST be imported here. env.py is
# migration tooling, not core, which is why it (like app/main.py) may know every module.
# Add a line here when a module starts owning tables; never "fix" a missing table by
# re-exporting it from app.models — that would make core depend on a module.
# Guarded by backend/tests/test_schema_inventory.py.
import etl.ca.sip.models  # noqa: E402,F401  — plan_extraction, plan, plan_goal, plan_action
import likeschools.models  # noqa: E402,F401  — feat_match_vector, mart_school_peer, model_partition_stats
import evals.models  # noqa: E402,F401  — trace, eval_case, eval_run, eval_result, feedback

target_metadata = Base.metadata
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def run_migrations_offline() -> None:
    context.configure(
        url=settings.migration_database_url.render_as_string(hide_password=False),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(settings.migration_database_url, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
