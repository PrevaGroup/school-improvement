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


def _build_engine():
    """Cloud Run uses the Cloud SQL Python Connector (no Auth Proxy sidecar) when
    INSTANCE_CONNECTION_NAME is set; local/dev falls back to the Auth-Proxy URL.
    Tenant binding below is identical either way — only how we open the socket differs.
    """
    if settings.instance_connection_name:
        from google.cloud.sql.connector import Connector, IPTypes

        connector = Connector()

        def _getconn():
            return connector.connect(
                settings.instance_connection_name,
                "pg8000",
                user=settings.app_db_user,
                password=settings.app_db_password_value,
                db=settings.db_name,
                ip_type=IPTypes.PRIVATE if settings.db_ip_type == "private" else IPTypes.PUBLIC,
            )

        return create_engine("postgresql+pg8000://", creator=_getconn, pool_pre_ping=True, future=True)

    return create_engine(settings.database_url, pool_pre_ping=True, future=True)


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


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
