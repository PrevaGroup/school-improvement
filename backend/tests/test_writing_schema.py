"""The writing product lives in its own schema, reached through its own database user.

Migration 0042 moved every writing table into schema `writing`, gave `writing_app` exactly the
commands 0041's policies allow, and took every grant away from `sip_app`. These hold the parts a
later change could quietly undo: a new writing model created in `public`, a table the migration
forgot, a later migration that creates a table without saying where, and a student-work session
opened on SIP's credentials.

What each role can actually see is proved against Postgres by `sql/30_writing_rls_smoketest.sql`.
"""
from __future__ import annotations

import importlib
import importlib.util
import pathlib
import re

from app.config import settings
from app.models import Base
from app.models.base import WRITING_SCHEMA

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
WRITING_MODULES = ("scoring", "intake", "delivery", "measurement", "roster", "registry", "corpus",
                   "pooling")

# Created by migrations with no model (measurement's fit tables). Still writing's, still moved.
MIGRATION_ONLY = {"measurement_fit_run", "measurement_fit_element"}


def _migration(name: str):
    path = _BACKEND / "migrations" / "versions" / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _writing_model_tables():
    tables = []
    for module in WRITING_MODULES:
        models = importlib.import_module(f"writing.{module}.models")
        for obj in vars(models).values():
            table = getattr(obj, "__table__", None)
            if table is not None and obj.__module__ == models.__name__:
                tables.append(table)
    return tables


def test_every_writing_model_is_declared_in_the_writing_schema():
    stray = sorted(t.name for t in _writing_model_tables() if t.schema != WRITING_SCHEMA)
    assert not stray, (f"{stray} would be created in `public`, where SIP's role has grants by "
                       "default. Add {'schema': WRITING_SCHEMA} to __table_args__.")


def test_no_sip_model_is_in_the_writing_schema():
    writing = {t.fullname for t in _writing_model_tables()}
    wrong = sorted(t.fullname for t in Base.metadata.tables.values()
                   if t.schema == WRITING_SCHEMA and t.fullname not in writing)
    assert not wrong, f"{wrong} are in schema `writing` but no writing module owns them"


def test_the_migration_moved_every_writing_table():
    moved = set(_migration("0042_writing_schema.py").TABLES)
    models = {t.name for t in _writing_model_tables()}
    assert models - moved == set(), f"never moved to `writing`: {sorted(models - moved)}"
    assert moved - models == MIGRATION_ONLY, sorted(moved - models)


def test_the_policies_and_the_grants_name_the_same_tables():
    m41 = _migration("0041_writing_rls.py")
    m42 = _migration("0042_writing_schema.py")
    moved = set(m42.TABLES)
    assert set(m41.POLICIES) <= moved and set(m41.DENY_ALL) <= moved
    assert set(m42.APP_READS).isdisjoint(m41.DENY_ALL)


def test_writing_migrations_after_the_move_say_which_schema():
    """After 0042 the migrator's search_path is `public, writing`, so a bare create_table lands in
    `public` — beside SIP, readable by SIP's default grants."""
    offenders = []
    for module in WRITING_MODULES:
        for path in (_BACKEND / "writing" / module / "migrations").glob("*.py"):
            m = re.match(r"(\d{4})_", path.name)
            if not m or int(m.group(1)) <= 42:
                continue
            for call in re.findall(r"op\.create_table\((.*?)\n\s*\)", path.read_text("utf-8"),
                                   re.S):
                if "schema=" not in call:
                    offenders.append(path.name)
    assert not offenders, f"create_table without schema= in {sorted(set(offenders))}"


def test_student_work_and_sip_connect_as_different_roles():
    assert settings.writing_db_user != settings.app_db_user
    assert settings.writing_db_password_secret != settings.app_db_password_secret
