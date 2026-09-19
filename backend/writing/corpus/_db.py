"""corpus' database engine.

A near-copy of `evals/_db.py` rather than a shared helper, for the reason sip's `_db.py` records:
a module opening its own connection is more honest than sharing an engine factory, which is
coupling rather than reuse.

Runs as the MIGRATOR role. A corpus load creates rows the API may only ever read — public
reference content, no tenancy — and the app role holds no INSERT on any of these tables.
"""
from __future__ import annotations

from sqlalchemy import create_engine

from app.config import settings


def _engine():
    return create_engine(settings.migration_database_url)
