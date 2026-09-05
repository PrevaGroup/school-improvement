"""registry's database engine.

An honest near-copy of `scoring/_db.py`, which is a near-copy of `evals/_db.py`. Hoisting an
engine factory into `core` was considered and rejected when `sip` needed one: a module opening its
own connection is honest about being a separate job, and a shared factory is coupling wearing the
costume of reuse.
"""
from __future__ import annotations

from sqlalchemy import create_engine

from app.config import settings


def engine():
    return create_engine(settings.migration_database_url, future=True)
