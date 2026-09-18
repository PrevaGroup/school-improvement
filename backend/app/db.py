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

from fastapi import Depends, HTTPException, status
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from .config import settings
from .security import get_current_principal, get_current_tenant, principal_hash


def _build_engine(user: str | None = None, password=None, url=None):
    """Cloud Run uses the Cloud SQL Python Connector (no Auth Proxy sidecar) when
    INSTANCE_CONNECTION_NAME is set; local/dev falls back to the Auth-Proxy URL.
    Tenant binding below is identical either way — only how we open the socket differs.

    Defaults to SIP's role. The writing product passes its own (see `_writing_engine`).
    """
    user = user or settings.app_db_user
    password = password or (lambda: settings.app_db_password_value)
    url = url or (lambda: settings.database_url)
    if settings.instance_connection_name:
        from google.cloud.sql.connector import Connector, IPTypes

        connector = Connector()

        def _getconn():
            return connector.connect(
                settings.instance_connection_name,
                "pg8000",
                user=user,
                password=password(),
                db=settings.db_name,
                ip_type=IPTypes.PRIVATE if settings.db_ip_type == "private" else IPTypes.PUBLIC,
            )

        return create_engine("postgresql+pg8000://", creator=_getconn, pool_pre_ping=True, future=True)

    return create_engine(url(), pool_pre_ping=True, future=True)


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


def get_db_public() -> Iterator[Session]:
    """FastAPI dependency for PUBLIC endpoints — no tenant binding, no auth.

    Reads only public rows: RLS `p_read` admits `visibility='public'` without a tenant
    GUC, and non-RLS reference tables (dim_school, plan_extraction) are always readable.
    Never use for private data.
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# --------------------------------------------------------------------------- #
# Student work: scoped to the caller's CLASSES, not just their district.
#
# SIP's private data is tenant-scoped: `app.tenant` is enough. Student work needs a second key,
# because a leak between two teachers in one district deserves the same defence as a leak between
# districts — so the policies on the writing tables (migration 0041) also read
# `app.principal_hash`, and resolve it to sections through `roster_visible_sections()`.
#
# The tenant is not taken from the identity-to-district mapping SIP uses. It is read from the
# caller's own active staff rows, so the classes a person teaches are the only route to a
# district's student work: a district administrator with a SIP mapping and no class sees none.
# --------------------------------------------------------------------------- #

# `roster_section_staff`'s policy admits only the caller's own rows, so this reads nothing else.
_STAFF_TENANTS = text("""
    SELECT DISTINCT tenant_id
      FROM roster_section_staff
     WHERE (active_from IS NULL OR active_from <= current_date)
       AND (active_to   IS NULL OR active_to   >= current_date)
""")


# Student work connects as `writing_app`, not `sip_app` (migration 0042): the two products share a
# database server and nothing else. Built on first use rather than at import, so a process that
# never serves a student-work route never resolves the writing credential — and so importing this
# module does not reach for a second secret, which is the smell `conftest.py` already works around
# for the first one.
_writing_sessions: sessionmaker | None = None


def _writing_session_factory() -> sessionmaker:
    global _writing_sessions
    if _writing_sessions is None:
        engine_ = _build_engine(settings.writing_db_user,
                                lambda: settings.writing_db_password_value,
                                lambda: settings.writing_database_url)
        _writing_sessions = sessionmaker(bind=engine_, autoflush=False, expire_on_commit=False,
                                         class_=Session)
    return _writing_sessions


def _bind(connection, principal_hash_value: str, tenant_id: str | None) -> None:
    connection.execute(text("SELECT set_config('app.principal_hash', :h, true)"),
                       {"h": principal_hash_value})
    connection.execute(text("SELECT set_config('app.tenant', :t, true)"),
                       {"t": tenant_id or ""})


def get_db_classes(principal: dict = Depends(get_current_principal)) -> Iterator[Session]:
    """FastAPI dependency for student work: a session that sees only the caller's classes.

    403 when the caller teaches no class — "you have no classes" and "your class is empty" are
    different answers, and a console that rendered the first as the second would be the defect
    this codebase keeps finding: a thing reporting success while not doing the job. 409 when the
    caller's classes span two districts, which nothing here can yet display honestly.

    The binding is re-applied at the start of EVERY transaction, not once. `SET LOCAL` ends with
    the transaction, and the review handlers commit partway through a request; a binding made
    once would silently fall away after the first commit and every later read would see nothing.
    Fail-closed, but wrong, and exactly the kind of wrong nobody notices.

    The session's district is in `session.info["tenant"]` for queries that name it.
    """
    hashed = principal_hash(principal)
    session = _writing_session_factory()()
    state: dict[str, str | None] = {"tenant": None}

    @event.listens_for(session, "after_begin")
    def _rebind(_session, _transaction, connection):  # noqa: ANN001 — SQLAlchemy's signature
        _bind(connection, hashed, state["tenant"])

    try:
        tenants = [r[0] for r in session.execute(_STAFF_TENANTS)]
        if not tenants:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "You are not on the staff of any class, so there is no student work to show. "
                "Ask an administrator to add you to your class.")
        if len(tenants) > 1:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Your classes are in more than one district, which this version cannot show "
                "together yet.")
        state["tenant"] = tenants[0]
        session.info["tenant"] = tenants[0]
        _bind(session.connection(), hashed, tenants[0])
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
