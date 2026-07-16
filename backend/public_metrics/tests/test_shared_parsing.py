"""Characterization tests for public_metrics' parsing helpers (`_shared.py`).

Every fact row in the platform passes through these on its way into `fact_metric`:
~960k rows of CDE data are shaped by `_f`/`_i`/`field`, and every school's identity is
minted by `cds_from` + `nces_ids`. They had no tests. Like the peer matcher, they fail
silently — a mis-parsed value doesn't crash a load, it writes a wrong or missing number
that looks exactly like CDE suppression.

All pure functions; no database, no files. Values were read off the current
implementation, not derived from intent — where the behavior is surprising, the
docstring says so rather than the test pretending otherwise.
"""
import pytest

from public_metrics._shared import _b, _basename, _f, _i, _join, cds_from, field, nces_ids


# --------------------------------------------------------------------------- #
# _f — CDE cell -> float | None. None means "no value", which downstream treats
# as suppression/missing (value_status), NEVER as zero. So what maps to None here
# decides what the platform claims not to know.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("cell", ["", "*", "N/A", "NA", "--", None, "   "])
def test_f_maps_cde_suppression_markers_to_none(cell):
    """'*' is CDE's small-n privacy marker; the rest are its assorted no-data spellings."""
    assert _f(cell) is None


@pytest.mark.parametrize("cell, expected", [
    ("42.5", 42.5),
    (" 42.5 ", 42.5),        # CDE pads cells
    ("-3", -3.0),            # signed deltas exist (change columns)
    ("0", 0.0),              # zero is a VALUE, not missing — the data-honesty line
    ("97.30", 97.3),
])
def test_f_parses_numbers(cell, expected):
    assert _f(cell) == expected


def test_f_unparseable_text_is_none_not_an_error():
    """Any junk becomes None — same as suppression. Pinned deliberately: it means a
    formatting change upstream (e.g. CDE shipping '1,234' with thousands commas, or
    '12%') would not crash a load; it would silently null an entire column, which
    then reads as suppressed. If a load suddenly reports a spike in missing values,
    look HERE first."""
    assert _f("1,234") is None
    assert _f("12%") is None
    assert _f("abc") is None


def test_f_lowercase_na_is_none_by_accident_of_the_fallback():
    """'n/a' (lowercase) is NOT in the marker list — it returns None only because
    float('n/a') raises. Same result, different path; a refactor that tightens the
    except clause would change behavior for cells the marker list never covered."""
    assert _f("n/a") is None


# --------------------------------------------------------------------------- #
# _i / _b
# --------------------------------------------------------------------------- #
def test_i_truncates_rather_than_rounds():
    """int(42.7) == 42. Counts (n_size, enrollment) arrive as '123.0' sometimes;
    truncation is fine there, but don't reuse _i for anything where .7 matters."""
    assert _i("42.7") == 42
    assert _i("123.0") == 123
    assert _i("*") is None


def test_b_is_a_strict_allowlist():
    """Only y/yes/true/1 (any case) are True. Everything else — including None,
    'n', '0', and unrecognised junk — is False, never an error."""
    for yes in ("Y", "y", "YES", "yes", "True", "TRUE", "1"):
        assert _b(yes) is True
    for no in ("N", "n", "no", "false", "0", "", None, "2", "junk"):
        assert _b(no) is False


# --------------------------------------------------------------------------- #
# School identity — cds_from + nces_ids mint every school_id in fact_metric
# --------------------------------------------------------------------------- #
def test_cds_from_zero_pads_to_exactly_14_digits():
    """CDS = county(2) + district(5) + school(7). CDE files carry the parts
    unpadded in some vintages; identity depends on the padding being right."""
    assert cds_from("19", "64733", "1234567") == "19647331234567"
    assert cds_from("1", "2", "3") == "01000020000003"
    assert len(cds_from("1", "2", "3")) == 14


def test_nces_ids_uses_the_crosswalk_when_the_school_has_a_fed_id():
    """school_id = the 12-digit ncessch; district_id = its first 7 (the LEAID)."""
    xwalk = {"19647331234567": "062271003230"}
    school, district = nces_ids("19647331234567", xwalk)
    assert school == "062271003230"
    assert district == "0622710"


def test_nces_ids_falls_back_to_a_state_scoped_id_so_no_facts_are_lost():
    """No NCES id (mostly newly-opened charters) -> 'CA-<cds>'. Self-evidently not
    federal, can't collide with a real ncessch, upgraded by a later crosswalk
    refresh. NOTE the district fallback is 'CA-' + the CDS's first 7 chars — the
    county+district prefix of the STATE code, not a federal LEAID."""
    school, district = nces_ids("99999999999999", {})
    assert school == "CA-99999999999999"
    assert district == "CA-9999999"


# --------------------------------------------------------------------------- #
# field — CDE's inconsistent column names
# --------------------------------------------------------------------------- #
def test_field_returns_the_first_present_column():
    """CDE spells the same column differently per file ('Reporting Category' vs
    'ReportingCategory'); loaders pass every spelling they've met."""
    assert field({"ReportingCategory": "TA"}, "Reporting Category", "ReportingCategory") == "TA"
    assert field({"Reporting Category": "TA"}, "Reporting Category", "ReportingCategory") == "TA"
    assert field({}, "Reporting Category", "ReportingCategory") is None


def test_field_treats_empty_string_as_present():
    """The check is `is not None`, not truthiness: an empty cell in the first
    candidate column WINS over a populated later one. Pinned because 'fix' it to
    truthiness and a file that carries both spellings (one blank) would silently
    start reading the other column."""
    assert field({"A": "", "B": "x"}, "A", "B") == ""


# --------------------------------------------------------------------------- #
# Path helpers — one code path for local files and gs:// URIs
# --------------------------------------------------------------------------- #
def test_join_keeps_gs_uris_as_uris_and_local_paths_as_paths():
    """pathlib would mangle 'gs://' (collapses the //), so gs is string-joined.
    The branch condition is the URI scheme, nothing else."""
    assert _join("gs://bucket/raw/", "f.txt") == "gs://bucket/raw/f.txt"
    assert _join("gs://bucket/raw", "f.txt") == "gs://bucket/raw/f.txt"  # slash normalized
    local = _join("data/ca", "f.txt")
    assert local.endswith("f.txt") and "gs://" not in local


def test_basename_handles_uris_trailing_slashes_and_bare_names():
    assert _basename("gs://b/x/y.txt") == "y.txt"
    assert _basename("a/b/") == "b"
    assert _basename("plain.txt") == "plain.txt"
