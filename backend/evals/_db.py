"""evals' database engine.

Deliberately a near-copy of sip's `_db.py` (which is itself a near-copy of public_metrics'
`_engine`) rather than a shared helper — see sip/_db.py's docstring for why hoisting this
into `core` was rejected. A module opening its own connection is more honest; sharing an
engine factory is coupling, not reuse.

Runs as the migrator role (owns the objects), which is what batch ingest needs and the app
must never have. Like every producer job, this runs in Cloud Shell / a Cloud Run job —
never locally (backend/README.md).
"""
from __future__ import annotations

from sqlalchemy import create_engine

from app.config import settings


def _engine():
    return create_engine(settings.migration_database_url)
