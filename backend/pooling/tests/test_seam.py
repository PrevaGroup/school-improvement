"""The district threshold — the properties that make the wall a property of the data.

Two of these tests reach outside the module on purpose. `pooling` is the single place cross-tenant
code is permitted, and a property with zero exceptions is only cheap to maintain if something
notices the first one. That is what `test_no_other_module_iterates_tenants` is for.
"""
from __future__ import annotations

import ast
import importlib.util
import re
import pathlib

import pytest

from pooling.models import (CONSENT_SCOPES, FORBIDDEN_KEYS, AggregateRun, AggregationConsent)

BACKEND = pathlib.Path(__file__).resolve().parent.parent.parent
MIGRATION = BACKEND / "pooling" / "migrations" / "0011_pooling_seam.py"
SQL = MIGRATION.read_text(encoding="utf8")

TENANT_NEUTRAL = (AggregationConsent, AggregateRun)


# --------------------------------------------------------------------------- #
# The wall is a property of the data
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("model", TENANT_NEUTRAL)
def test_no_table_here_carries_an_identifier(model):
    """A screen that wanted to drill from a pooled figure to a class, a teacher or a paper could
    not be built, because the column does not exist. An interface-level rule is one someone can be
    persuaded to relax in a sprint planning meeting; a missing column is not."""
    cols = {c.name for c in model.__table__.columns}
    leaked = sorted(cols & set(FORBIDDEN_KEYS))
    assert not leaked, (
        f"{model.__tablename__} carries identifier(s) {leaked}. Pooled data crosses an "
        f"organisation boundary — nothing that resolves to a person or a class may cross with it.")


@pytest.mark.parametrize("model", TENANT_NEUTRAL)
def test_tables_here_are_tenant_neutral(model):
    """Not an omission. These belong to no district, which is why the PM principal — deliberately
    unmapped to any tenant — can read them while every district-scoped table returns zero rows."""
    cols = {c.name for c in model.__table__.columns}
    assert "tenant_id" not in cols
    assert "visibility" not in cols


def test_district_tenant_id_on_consent_is_a_plain_column():
    """The consent row names the district it is about. It is the gate on the crossing, read by the
    producer as its own principal, so scoping it to the tenant being read would be circular."""
    cols = {c.name for c in AggregationConsent.__table__.columns}
    assert "district_tenant_id" in cols
    assert not any(fk for c in AggregationConsent.__table__.columns for fk in c.foreign_keys), (
        "a foreign key into the tenant registry would make this row tenant-scoped, and the gate "
        "cannot live inside the thing it gates")


# --------------------------------------------------------------------------- #
# Consent
# --------------------------------------------------------------------------- #
def test_consent_scopes_are_separable():
    """A district agreeing that module evidence may reach the publisher has not thereby agreed that
    its teachers' acceptance behaviour may. Conflating them is how the override stream — the
    calibration asset the measurement design depends on — gets poisoned by teachers who reasonably
    conclude they are being monitored."""
    assert set(CONSENT_SCOPES) == {"module_evidence", "teacher_instrumentation"}


def test_consent_is_dated_and_revocable():
    """A figure computed under an earlier participation set is a different figure."""
    cols = {c.name for c in AggregationConsent.__table__.columns}
    assert {"effective_from", "effective_to", "revoked_at"} <= cols


def test_consent_points_at_the_real_agreement():
    """The system holds the flag, not the agreement. A signed contract is not a fact any table
    holds, so the row says where the real one lives."""
    assert "instrument_ref" in {c.name for c in AggregationConsent.__table__.columns}


# --------------------------------------------------------------------------- #
# The run audit
# --------------------------------------------------------------------------- #
def test_run_records_a_district_count_not_a_list():
    """The count is what a reader needs to judge whether a figure is thin. A list is what would let
    a determined reader difference two runs into an identity."""
    cols = {c.name for c in AggregateRun.__table__.columns}
    assert "district_count" in cols
    assert not {c for c in cols if "district_ids" in c or "districts" in c}


def test_run_stamps_what_would_be_needed_to_explain_the_number_later():
    """'Why does this number exist and who agreed to it' has to be answerable from the row."""
    cols = {c.name for c in AggregateRun.__table__.columns}
    assert {"consent_snapshot", "suppression_params", "definition_version",
            "frame_version", "configuration_version"} <= cols


def test_run_counts_what_it_suppressed():
    """Suppressed cells are counted in the denominator and not displayed. A run that cannot say how
    much it withheld cannot be read honestly."""
    assert "cells_suppressed" in {c.name for c in AggregateRun.__table__.columns}


# --------------------------------------------------------------------------- #
# Timing, and the exception this module is
# --------------------------------------------------------------------------- #
def test_the_aggregate_tables_are_not_created_yet():
    """Their grain follows from the PM console data contract and from suppression parameters that
    depend on the legal basis — both open. A table created early is a shape frozen before the
    question that determines it has an answer."""
    created = re.findall(r'create_table\(\s*"([^"]+)"', SQL)
    assert not [n for n in created if n.startswith("agg_")], (
        f"an aggregate table was created before its grain was settled: {created}")
    # The docstring naming them is correct and should stay — it says why they are absent.
    assert "agg_task_difficulty" in SQL, "the migration should explain what it deliberately omits"


def test_no_other_module_iterates_tenants():
    """`pooling` is the single place cross-tenant code is permitted. A property with zero exceptions
    is only cheap to maintain if something notices the first one — this is that something.

    Looks for the shape of a tenant loop: iterating something tenant-ish while setting the tenant.
    Deliberately crude. It is a smoke alarm, not a proof, and the boundary test next door is what
    actually keeps modules apart.
    """
    suspicious: list[str] = []
    for path in BACKEND.rglob("*.py"):
        rel = path.relative_to(BACKEND)
        top = rel.parts[0]
        if top in {"pooling", "migrations", "tests", "scripts"} or "test" in path.name:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.For, ast.AsyncFor)):
                continue
            body = ast.dump(node)
            if "SET LOCAL app.tenant" in body or "set_local_tenant" in body:
                suspicious.append(f"{rel}:{node.lineno}")
    assert not suspicious, (
        f"cross-tenant iteration outside `pooling`: {suspicious}. One job crosses the district "
        f"threshold; if a second needs to, that is a design question to raise, not a loop to write.")


def test_migration_follows_the_measurement_revision():
    spec = importlib.util.spec_from_file_location("pooling_0011", MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert (mod.revision, mod.down_revision) == ("0011", "0010")
