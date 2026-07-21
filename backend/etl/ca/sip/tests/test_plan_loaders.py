"""Characterization tests for the SIP plan-JSON loaders (etl/ca/sip).

Locks in the behavior around the concurrent read path that replaced the serial,
one-GCS-GET-per-file loop in `load_plan_extractions` and `batch_load`:

  * row / plan shape and the nested `source.extracted_at` pull;
  * `list_json` returns (name, src) pairs sorted by name;
  * per-file resilience — one malformed JSON is reported, not fatal, and the rest
    of the batch still parses (this is the property the ThreadPoolExecutor loop
    must preserve).

Everything runs against fsspec's LocalFileSystem — no network, no DB.

Deliberately no `importorskip` guard: the loaders' deps are declared in
requirements-dev.txt, and a missing one is a broken environment, not a reason to
report green. Skipping on a bare box is how this file spent its life silently
contributing zero coverage.
"""
import json
import pathlib

import pytest

import fsspec

from etl.ca.sip import batch_load
from etl.ca.sip import load_plan_extractions as lpe

EXAMPLE = pathlib.Path(__file__).resolve().parent.parent / "example_extract.json"


@pytest.fixture
def plans_dir(tmp_path):
    """3 well-formed plan_extraction JSONs + 1 malformed, in a temp dir."""
    good = {
        "plan_1.json": {"plan_id": "p1", "school_id": "0600001", "plan_year": "2024-25",
                        "plan_type": "SPSA", "source": {"extracted_at": "2026-01-01"}},
        "plan_2.json": {"plan_id": "p2", "school_id": "0600002", "plan_year": "2024-25",
                        "plan_type": "SPSA", "source": {"extracted_at": "2026-01-02"}},
        "plan_3.json": {"plan_id": "p3", "school_id": "0600003", "plan_year": "2024-25",
                        "plan_type": "SPSA", "source": {"extracted_at": "2026-01-03"}},
    }
    for name, doc in good.items():
        (tmp_path / name).write_text(json.dumps(doc), encoding="utf-8")
    (tmp_path / "plan_bad.json").write_text("{ not valid json ", encoding="utf-8")
    return tmp_path


# --------------------------------------------------------------------------- #
# load_plan_extractions — the public-mart JSONB loader
# --------------------------------------------------------------------------- #
def test_fetch_row_shape(plans_dir):
    fs = fsspec.filesystem("file")
    row = lpe._fetch_row(fs, str(plans_dir / "plan_1.json"))
    assert set(row) == {"plan_id", "school_id", "plan_year", "plan_type", "extracted_at", "document"}
    assert row["plan_id"] == "p1"
    assert row["extracted_at"] == "2026-01-01"        # pulled from nested source.extracted_at
    assert row["document"]["school_id"] == "0600001"  # full doc retained as the JSONB payload


def test_fetch_row_raises_on_bad_json(plans_dir):
    fs = fsspec.filesystem("file")
    with pytest.raises(json.JSONDecodeError):
        lpe._fetch_row(fs, str(plans_dir / "plan_bad.json"))


def test_list_json_sorted(plans_dir):
    _, files = lpe.list_json(str(plans_dir))
    names = [n for n, _ in files]
    assert names == sorted(names)
    assert set(names) == {"plan_1.json", "plan_2.json", "plan_3.json", "plan_bad.json"}


def test_dedup_by_plan_id_collapses_last_wins():
    # Two files resolving to the same deterministic plan_id must collapse to one row (last
    # wins) — otherwise the single-statement ON CONFLICT upsert would touch a row twice and
    # Postgres aborts the whole window.
    rows = [
        {"plan_id": "p1", "school_id": "a", "document": {"v": 1}},
        {"plan_id": "p2", "school_id": "b", "document": {"v": 1}},
        {"plan_id": "p1", "school_id": "a", "document": {"v": 2}},  # dup plan_id, newer
    ]
    out = lpe.dedup_by_plan_id(rows)
    assert [r["plan_id"] for r in out] == ["p1", "p2"]      # first-seen order preserved
    assert next(r for r in out if r["plan_id"] == "p1")["document"] == {"v": 2}  # last wins


def test_dedup_by_plan_id_noop_when_unique():
    rows = [{"plan_id": "p1"}, {"plan_id": "p2"}, {"plan_id": "p3"}]
    assert lpe.dedup_by_plan_id(rows) == rows


def test_main_dry_run_is_resilient(plans_dir, capsys):
    # 3 good + 1 malformed. The concurrent read loop must parse the 3, report the 1
    # error, and exit non-zero — regardless of completion order.
    rc = lpe.main(["--in-prefix", str(plans_dir), "--workers", "4", "--dry-run"])
    err = capsys.readouterr().err
    assert "parsed 3 ok, 1 errors" in err
    assert rc == 1  # errors present -> non-zero exit


# --------------------------------------------------------------------------- #
# batch_load — the tenant-scoped augment loader (read phase is what parallelized)
# --------------------------------------------------------------------------- #
def test_read_plan_validates_example():
    plan = batch_load.read_plan(str(EXAMPLE))
    assert plan.plan_id == "062271012345:spsa:2024-25"
    assert plan.review_status in batch_load.ReviewStatus  # gating field the loader reads


def test_read_plan_raises_on_bad_json(plans_dir):
    with pytest.raises(Exception):  # invalid JSON or schema-validation failure
        batch_load.read_plan(str(plans_dir / "plan_bad.json"))
