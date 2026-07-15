"""sip's database engine.

Deliberately a near-copy of public_metrics' `_engine` (`etl/ca/_shared.py`) rather than a shared
helper. It isn't shared logic — it's one call against `core`'s `settings.migration_database_url`,
which both modules already depend on. Importing public_metrics' copy is what made sip depend on
a module it has nothing to do with (the last cross-module import in the repo, 2026-07-15).

The alternative — hoisting it into `core` — was rejected: the obvious home, `app/db.py`, builds
the app's engine at *import* time as `sip_app`, so importing it from an ETL script would demand
the app password and drag FastAPI in behind it. A module opening its own connection is also
simply more honest; sharing an engine factory is coupling, not reuse.

Runs as the migrator role (owns the objects), which is what ETL needs and the app must never have.
"""
from __future__ import annotations

from sqlalchemy import create_engine

from app.config import settings


def _engine():
    return create_engine(settings.migration_database_url)
