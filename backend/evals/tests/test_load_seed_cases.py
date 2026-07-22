"""Seed-loader tests — row shaping + idempotent insert, no real DB."""
from __future__ import annotations

import json

import pytest

from evals import load_seed_cases
from evals.graders import GRADERS
from evals.load_seed_cases import _row, load
from evals.seed_cases import SEED_CASES, case_id

# Known grader names: the deterministic registry + the judge (dispatched separately in run_graders).
KNOWN_GRADERS = set(GRADERS) | {"usefulness_judge"}


def test_every_seed_case_lists_only_real_graders():
    """run_graders silently SKIPS an unknown grader name, so a typo (or a tool name pasted in by
    mistake) quietly under-grades a case. Pin every seed case's graders to the real registry so
    that can't recur — this test would have caught the query_school_plan/compare_to_peers slip."""
    for c in SEED_CASES:
        for g in c.get("graders") or []:
            assert g in KNOWN_GRADERS, (
                f"case {c['question'][:48]!r} lists unknown grader {g!r} — did you mean a grader "
                f"from {sorted(KNOWN_GRADERS)}? (a tool goes in params['tools'] with expected_tools)")


def test_case_id_is_stable_and_prefixed():
    c = {"level": "High", "question": "q?"}
    assert case_id(c) == case_id(dict(c)) and case_id(c).startswith("seed-")


def test_row_shapes_jsonb_and_carries_grader_config():
    row = _row(SEED_CASES[0])
    assert row["eval_case_id"].startswith("seed-")
    expected = json.loads(row["expected"])
    assert "params" in expected
    assert json.loads(row["ui"])["level"] in {"High", "Middle", "Primary"}
    assert isinstance(row["tags"], list)


def test_dry_run_counts_every_case_and_writes_nothing():
    counts = load(dry_run=True)
    assert counts["cases"] == len(SEED_CASES) == counts["inserted"]


class _FakeConn:
    def __init__(self, log):
        self._log = log

    def execute(self, sql, row):
        self._log.append(row)
        return type("R", (), {"rowcount": 1})()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_load_inserts_one_row_per_seed_case(monkeypatch):
    executed: list = []

    class _Eng:
        def begin(self):
            return _FakeConn(executed)

    import evals._db as db
    monkeypatch.setattr(db, "_engine", lambda: _Eng())
    counts = load()
    assert counts["inserted"] == len(SEED_CASES)
    assert len(executed) == len(SEED_CASES)
    assert {r["eval_case_id"] for r in executed} == {case_id(c) for c in SEED_CASES}  # unique ids
