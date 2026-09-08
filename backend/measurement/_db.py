"""measurement's database engine.

A near-copy of `scoring/_db.py`, which is a near-copy of `evals/_db.py`, and deliberately so —
hoisting an engine factory into `core` was considered and rejected there. A module opening its own
connection is honest about being a separate job; a shared factory is coupling in the costume of
reuse.
"""
from __future__ import annotations

from sqlalchemy import create_engine

from app.config import settings


def engine():
    return create_engine(settings.migration_database_url, future=True)
