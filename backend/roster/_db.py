"""roster's database engine.

A near-copy of `scoring/_db.py`, which is a near-copy of `sip/_db.py`, and deliberately so: hoisting
an engine factory into `core` was considered and rejected there. A module opening its own
connection is honest about the fact that it is a separate job; a shared factory is coupling wearing
the costume of reuse.

Runs as the migrator role, which owns the objects. The app role must never have this.
"""
from __future__ import annotations

from sqlalchemy import create_engine

from app.config import settings


def engine():
    return create_engine(settings.migration_database_url, future=True)
