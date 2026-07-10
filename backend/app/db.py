"""Engine + the tenant-bound session that makes RLS enforce the right rows.

The app connects as `sip_app` (non-owner, NOBYPASSRLS). Every request runs inside a
transaction where we `SET LOCAL app.tenant = <tenant>`; the RLS policies read that
GUC. `SET LOCAL` is transaction-scoped, so it resets on commit/rollback and can't
leak across pooled connections.

The tenant value MUST come from the verified request identity (app/security.py),
never from client-supplied data — that is the whole trust boundary (§10.3).
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from fastapi import Depends
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from .config import settings
from .security import get_current_tenant

engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)

# NOTE (Cloud SQL): to skip the Auth Proxy and use the Python Connector / IAM DB
# auth, build the engine with a `creator=` that returns a connector connection
# instead of a URL. The tenant-binding logic below is identical.


@contextmanager
def tenant_session(tenant_id: str) -> Iterator[Session]:
    session = SessionLocal()
    try:
        # set_config(key, value, is_local=true) == SET LOCAL, and it's parameterized
        # (no string interpolation of the tenant into SQL).
        session.execute(text("SELECT set_config('app.tenant', :t, true)"), {"t": tenant_id})
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db(tenant_id: str = Depends(get_current_tenant)) -> Iterator[Session]:
    """FastAPI dependency: a session already scoped to the caller's tenant."""
    with tenant_session(tenant_id) as session:
        yield session
