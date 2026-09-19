"""Student work is reached only through a session bound to the caller's classes.

Migration 0041 puts row-level security on the writing tables; `get_db_classes` is the dependency
that binds the two settings those policies read. Neither is worth anything without the other — a
policy nobody binds sees nothing, and a binding on a route that still opens `get_db_public` binds
nothing — so these tests hold both ends: every student-work route uses the bound session, the
session binds what the policies read and keeps binding it after a commit, and every table a writing
module creates is covered by the migration.

The policies themselves are exercised against a real Postgres by `sql/30_writing_rls_smoketest.sql`,
which CI cannot run: it needs a database, and this suite deliberately has none.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sqlite3

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from app import db as app_db
from app import security, traces
from app.config import settings

_BACKEND = pathlib.Path(__file__).resolve().parents[1]


def _load_migration():
    path = _BACKEND / "migrations" / "versions" / "0041_writing_rls.py"
    spec = importlib.util.spec_from_file_location("m0041", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ------------------------------------------------------------------ every route is bound

def _student_work_routers():
    from app.review_view import router as review_view
    from delivery.view import router as delivery_view
    from intake.review import router as intake_review
    from scoring.review import router as scoring_review
    return {"review_view": review_view, "scoring.review": scoring_review,
            "intake.review": intake_review, "delivery.view": delivery_view}


def _calls(dependant) -> set:
    found = {dependant.call}
    for sub in dependant.dependencies:
        found |= _calls(sub)
    return found


@pytest.mark.parametrize("name", list(_student_work_routers()))
def test_every_student_work_route_opens_a_class_bound_session(name):
    routes = [r for r in _student_work_routers()[name].routes if isinstance(r, APIRoute)]
    assert routes, f"{name} has no routes — the test would pass by checking nothing"
    for route in routes:
        calls = _calls(route.dependant)
        assert app_db.get_db_classes in calls, f"{name} {route.path} is not bound to classes"
        assert app_db.get_db_public not in calls, f"{name} {route.path} still opens get_db_public"


# ------------------------------------------------------------------ the identity it binds

def test_the_hash_names_a_person_the_way_traces_and_staff_rows_do(monkeypatch):
    monkeypatch.setattr(settings, "trace_salt", "salt-for-test")
    assert security.principal_hash({"sub": "uid-1"}) == traces._principal_hash("uid-1")


def test_no_subject_is_refused_rather_than_hashed_as_empty(monkeypatch):
    monkeypatch.setattr(settings, "trace_salt", "salt-for-test")
    with pytest.raises(HTTPException) as exc:
        security.principal_hash({"email": "someone@example.org"})
    assert exc.value.status_code == 401


def test_no_salt_fails_closed(monkeypatch):
    monkeypatch.setattr(settings, "trace_salt", None)

    def _no_secret(*_a, **_k):
        raise RuntimeError("secret manager unreachable")
    monkeypatch.setattr(type(settings), "_secret", _no_secret)
    with pytest.raises(HTTPException) as exc:
        security.principal_hash({"sub": "uid-1"})
    assert exc.value.status_code == 503


# ------------------------------------------------------------------ the session, on a real engine

@pytest.fixture
def bound_engine(monkeypatch):
    """SQLite standing in for Postgres: `set_config` is recorded, the staff table is real.

    The point is the SQLAlchemy side — when the binding happens and whether it survives a commit —
    which a mock of the session could not show.
    """
    monkeypatch.setattr(settings, "trace_salt", "salt-for-test")
    calls: list[tuple[str, str]] = []

    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _register(dbapi_conn, _record):
        def set_config(key, value, _local):
            calls.append((key, value))
            return value
        dbapi_conn.create_function("set_config", 3, set_config)

    with engine.begin() as conn:
        conn.execute(text("""CREATE TABLE roster_section_staff (
            tenant_id TEXT, principal_hash TEXT, active_from DATE, active_to DATE)"""))

    monkeypatch.setattr(app_db, "_writing_sessions", sessionmaker(bind=engine, future=True))
    # SIP's factory must never be the one student work opens; make it fail loudly if it is.
    monkeypatch.setattr(app_db, "SessionLocal", lambda: pytest.fail("opened a SIP session"))
    return engine, calls


def _staff(engine, *tenants, active_to=None):
    with engine.begin() as conn:
        for t in tenants:
            conn.execute(text("INSERT INTO roster_section_staff VALUES (:t, 'h', NULL, :to)"),
                         {"t": t, "to": active_to})


def _open(principal=None):
    gen = app_db.get_db_classes(principal or {"sub": "uid-1"})
    return gen, next(gen)


def test_no_class_is_a_refusal_not_an_empty_page(bound_engine):
    with pytest.raises(HTTPException) as exc:
        _open()
    assert exc.value.status_code == 403
    assert "not on the staff of any class" in exc.value.detail


def test_an_ended_assignment_is_no_class(bound_engine):
    engine, _ = bound_engine
    _staff(engine, "district_a", active_to="2000-01-01")
    with pytest.raises(HTTPException) as exc:
        _open()
    assert exc.value.status_code == 403


def test_classes_in_two_districts_are_refused_rather_than_merged(bound_engine):
    engine, _ = bound_engine
    _staff(engine, "district_a", "district_b")
    with pytest.raises(HTTPException) as exc:
        _open()
    assert exc.value.status_code == 409


def test_one_district_is_bound_with_the_callers_hash(bound_engine):
    engine, calls = bound_engine
    _staff(engine, "district_a")
    gen, session = _open()
    assert session.info["tenant"] == "district_a"
    expected_hash = security.principal_hash({"sub": "uid-1"})
    assert ("app.principal_hash", expected_hash) in calls
    assert ("app.tenant", "district_a") in calls
    gen.close()


def test_the_binding_survives_a_commit(bound_engine):
    """The review handlers commit mid-request. SET LOCAL ends with the transaction, so a binding
    made once would be gone for every read after the first commit."""
    engine, calls = bound_engine
    _staff(engine, "district_a")
    gen, session = _open()
    session.commit()
    calls.clear()
    session.execute(text("SELECT 1"))
    assert ("app.tenant", "district_a") in calls, "the second transaction ran unbound"
    assert any(k == "app.principal_hash" for k, _ in calls)
    gen.close()


# ------------------------------------------------------------------ the migration covers the tables

_WRITING_MODULES = ("scoring", "intake", "delivery", "measurement", "roster")


def _writing_tables_with_a_tenant() -> set[str]:
    from app.models import Base
    for module in _WRITING_MODULES:
        importlib.import_module(f"{module}.models")
    return {t.name for t in Base.metadata.tables.values()
            if "tenant_id" in t.columns
            and any(t.name.startswith(p) for p in (
                "artifact", "score_event", "intake_", "roster_", "estimation_frame",
                "measurement_"))}


def test_every_tenanted_writing_table_is_covered_by_the_migration():
    m = _load_migration()
    covered = set(m.POLICIES) | set(m.DENY_ALL)
    missing = _writing_tables_with_a_tenant() - covered
    assert not missing, (f"writing tables with no row-level security: {sorted(missing)} — add "
                         "each to POLICIES or DENY_ALL in a migration, or it is readable by every "
                         "signed-in user")


def test_the_api_role_can_delete_no_student_work():
    m = _load_migration()
    for table, (_predicate, commands) in m.POLICIES.items():
        assert "DELETE" not in commands, f"{table} grants DELETE to the API"


def test_every_student_table_checks_the_district_as_well_as_the_class():
    m = _load_migration()
    for table, (predicate, _commands) in m.POLICIES.items():
        if table == "roster_section_staff":
            continue  # keyed on the person, across districts: it is how the district is found
        assert "app.tenant" in predicate, f"{table} does not check the district"
        assert ("roster_visible_sections" in predicate or " IN (SELECT " in predicate), \
            f"{table} does not check the class"


def test_the_sqlite_stand_in_has_the_function_it_needs():
    # Guards the fixture: create_function exists on the stdlib driver this test relies on.
    assert hasattr(sqlite3.connect(":memory:"), "create_function")
