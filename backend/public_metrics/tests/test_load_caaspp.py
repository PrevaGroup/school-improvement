"""Tests for the CAASPP loader (`load_ca_caaspp.py`) — pure, no database.

The row filter (`iter_caaspp_facts`) decides which of ~3M rows/year become facts; a
wrong filter doesn't crash, it silently loads the wrong universe (per-grade rows,
district rollups, complement groups). These pin the decisions. The zip test runs the
real `load_caaspp_zip` end-to-end in dry mode against an in-memory zip, so member
selection, the entities lookup, and caret parsing are exercised together.
"""
import io
import zipfile

import pytest

from app.vocab import METRIC_IDS, STUDENT_GROUP_IDS
from public_metrics._shared import CAASPP_GROUP
from public_metrics.load_ca_caaspp import (
    ALL_GRADES, N_COL, SPECS, TEST_METRIC, VALUE_COL,
    _norm_id, iter_caaspp_facts, load_caaspp_zip, pick_member,
)


# --------------------------------------------------------------------------- #
# The adapter must land inside the conformed vocabulary — an id that isn't in
# core's vocab writes rows that join to nothing (the exact failure vocab.py warns
# about). These two tests are the tripwire for vocab/adapter drift.
# --------------------------------------------------------------------------- #
def test_every_caaspp_group_maps_into_the_conformed_vocab():
    assert set(CAASPP_GROUP.values()) <= set(STUDENT_GROUP_IDS)


def test_both_test_ids_map_to_seeded_metric_ids():
    assert set(TEST_METRIC.values()) <= set(METRIC_IDS)
    assert TEST_METRIC == {"1": "ela_met_standard_pct", "2": "math_met_standard_pct"}


def test_caaspp_group_keys_are_canonical_ints():
    """Keys are 'str(int(...))' — '074' would never match because _norm_id strips
    zero-padding before lookup."""
    assert all(k == str(int(k)) for k in CAASPP_GROUP)


@pytest.mark.parametrize("raw, expected", [
    ("001", "1"), (" 74 ", "74"), ("240", "240"),
    ("", None), ("*", None), ("TA", None), (None, None),
])
def test_norm_id_strips_ets_zero_padding(raw, expected):
    assert _norm_id(raw) == expected


# --------------------------------------------------------------------------- #
# iter_caaspp_facts — the row filter
# --------------------------------------------------------------------------- #
def _row(**over):
    """A qualifying Grade-13 school ELA row; tests override one axis at a time."""
    r = {
        "County Code": "19", "District Code": "64733", "School Code": "1234567",
        "Test Year": "2025", "Student Group ID": "001", "Test Type": "B",
        "Grade": "13", "Test ID": "1",
        VALUE_COL: "47.5", N_COL: "312",
    }
    r.update(over)
    return r


def _run(rows, xwalk=None, names=None):
    counters = dict(fact=0, grade=0, roll=0, agg=0, skip=0)
    out = list(iter_caaspp_facts(rows, "p2024-25", xwalk or {}, names or {}, counters, "src.zip!m.txt"))
    return out, counters


def test_qualifying_row_becomes_one_fact():
    out, counters = _run([_row()])
    (stub, fact), = out  # exactly one (stub, fact) pair

    assert counters == dict(fact=1, grade=0, roll=0, agg=0, skip=0)
    assert fact["metric_id"] == "ela_met_standard_pct"
    assert fact["student_group_id"] == "all"
    assert fact["value"] == 47.5 and fact["value_status"] == "reported"
    assert fact["n_size"] == 312
    assert fact["period_id"] == "p2024-25"
    assert stub["state_school_id"] == "19647331234567"


def test_test_id_2_is_math_and_zero_padding_is_tolerated():
    out, _ = _run([_row(**{"Test ID": "02"})])
    assert out[0][1]["metric_id"] == "math_met_standard_pct"


def test_per_grade_rows_are_skipped_only_all_grades_loads():
    out, counters = _run([_row(Grade="03"), _row(Grade="8"), _row(Grade="11"), _row(Grade="13")])
    assert len(out) == 1 and counters["grade"] == 3
    assert ALL_GRADES == "13"


def test_unmapped_group_and_unknown_test_are_skipped_not_loaded():
    """092 = parent education (different axis), 053 = 'Not homeless' (complement),
    Test ID 4 = CAST science — none belong in these metrics."""
    out, counters = _run([
        _row(**{"Student Group ID": "092"}),
        _row(**{"Student Group ID": "053"}),
        _row(**{"Test ID": "4"}),
    ])
    assert out == [] and counters["skip"] == 3


def test_rollup_rows_and_nps_bucket_are_excluded():
    out, counters = _run([
        _row(**{"School Code": "0000000"}),   # district/county/state rollup
        _row(**{"School Code": "0000001"}),   # NPS placement bucket
    ])
    assert out == [] and counters["roll"] == 1 and counters["agg"] == 1


def test_suppressed_star_is_none_with_status_not_zero():
    """The data-honesty line: '*' (ETS small-n marker) must never load as 0.0."""
    out, _ = _run([_row(**{VALUE_COL: "*"})])
    fact = out[0][1]
    assert fact["value"] is None and fact["value_status"] == "suppressed"


def test_blank_value_is_not_collected():
    out, _ = _run([_row(**{VALUE_COL: ""})])
    fact = out[0][1]
    assert fact["value"] is None and fact["value_status"] == "not_collected"


def test_nces_crosswalk_and_ca_fallback():
    xwalk = {"19647331234567": "062271003230"}
    out, _ = _run([_row()], xwalk=xwalk)
    assert out[0][1]["school_id"] == "062271003230"
    out, _ = _run([_row()])                       # no crosswalk entry
    assert out[0][1]["school_id"] == "CA-19647331234567"


def test_entity_names_flow_into_the_school_stub():
    names = {"19647331234567": ("Los Angeles", "Long Beach Unified", "Roosevelt Elementary")}
    out, _ = _run([_row()], names=names)
    stub = out[0][0]
    assert stub["school_name"] == "Roosevelt Elementary"
    assert stub["district_name"] == "Long Beach Unified"


# --------------------------------------------------------------------------- #
# pick_member + the zip end-to-end (dry run — parses, counts, writes nothing)
# --------------------------------------------------------------------------- #
class _Info:
    def __init__(self, filename, file_size):
        self.filename, self.file_size = filename, file_size


def test_pick_member_takes_the_largest_non_entities_txt():
    infos = [_Info("sb_ca2025entities_csv_v1.txt", 5_000_000),
             _Info("sb_ca2025_all_csv_v1.txt", 990_000_000),
             _Info("readme.pdf", 100)]
    assert pick_member(infos) == "sb_ca2025_all_csv_v1.txt"


def test_pick_member_raises_when_no_data_member():
    with pytest.raises(FileNotFoundError):
        pick_member([_Info("sb_ca2025entities_csv_v1.txt", 5)])


def _caret(*rows):
    cols = list(rows[0].keys())
    lines = ["^".join(cols)] + ["^".join(str(r[c]) for c in cols) for r in rows]
    return "\r\n".join(lines).encode("latin-1")


def test_load_caaspp_zip_dry_run_end_to_end(tmp_path):
    data = _caret(
        _row(),                                    # ELA all-students -> fact
        _row(**{"Test ID": "2", VALUE_COL: "33.1"}),  # Math -> fact
        _row(Grade="03"),                          # per-grade -> skipped
        _row(**{"School Code": "0000000"}),        # rollup -> deferred
    )
    entities = _caret({
        "County Code": "19", "District Code": "64733", "School Code": "1234567",
        "Test Year": "2025", "Type ID": "07",
        "County Name": "Los Angeles", "District Name": "LBUSD", "School Name": "Roosevelt",
    })
    zpath = tmp_path / "caaspp_smarterbalanced_all_2024-25.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("sb_ca2025_all_csv_v1.txt", data)
        zf.writestr("sb_ca2025entities_csv_v1.txt", entities)
    counters = load_caaspp_zip(None, str(zpath), "p2024-25", {}, dry=True)
    assert counters == dict(fact=2, grade=1, roll=1, agg=0, skip=0)


def test_specs_cover_both_years():
    assert [s["period_id"] for s in SPECS] == ["p2023-24", "p2024-25"]
    assert all(s["file"].startswith("academics/") for s in SPECS)
