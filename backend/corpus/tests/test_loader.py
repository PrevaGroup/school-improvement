"""The corpus loader's decisions — the ones that would be expensive to notice later.

Runs against the real files when they are present and skips otherwise, so CI stays green without a
900MB checkout while a developer with the corpus gets the real assertions.
"""
from __future__ import annotations

import os
import pathlib

import pytest

from corpus._shared import (VALIDATION_SHARE, blank_to_none, partition_for, text_hash)
from corpus.load_persuade import SPEC, _paper, _scores, _span
from corpus.models import DISCOURSE_TYPES, PARTITIONS

CORPUS_DIR = pathlib.Path(os.environ.get("CORPUS_DIR", "N:/studentworkfeedback/corpus"))
HAVE_CORPUS = (CORPUS_DIR / SPEC.papers_file).exists()
needs_corpus = pytest.mark.skipif(not HAVE_CORPUS, reason="corpus files not present")


# --------------------------------------------------------------------------- #
# The partition — reproducibility of the holdout
# --------------------------------------------------------------------------- #
def test_partition_is_deterministic():
    """The same corpus must produce the same holdout on a different machine, or 'held out from
    calibration' is a claim nobody can check."""
    a = [partition_for("persuade20", f"E{i}") for i in range(500)]
    b = [partition_for("persuade20", f"E{i}") for i in range(500)]
    assert a == b


def test_partition_does_not_depend_on_load_order():
    ids = [f"E{i}" for i in range(500)]
    forward = {i: partition_for("s", i) for i in ids}
    backward = {i: partition_for("s", i) for i in reversed(ids)}
    assert forward == backward


def test_partition_share_is_close_to_target():
    n = 5000
    v = sum(partition_for("s", f"E{i}") == "validation" for i in range(n))
    assert abs(v / n - VALIDATION_SHARE) < 0.02


def test_partition_differs_across_sources():
    """Two corpora must not hold out the same essay positions — otherwise a paper appearing in both
    lands in the same half twice and the holdout is smaller than it looks.

    The bar is independence, not disagreement. Two independent 80/20 splits agree by chance at
    p^2 + (1-p)^2 = 0.68, so anything near 0.5 would mean they were anti-correlated and anything
    near 1.0 would mean the source id is not reaching the hash.
    """
    n = 2000
    same = sum(partition_for("a", f"E{i}") == partition_for("b", f"E{i}") for i in range(n))
    expected = VALIDATION_SHARE ** 2 + (1 - VALIDATION_SHARE) ** 2
    assert abs(same / n - expected) < 0.04, (
        f"agreement {same / n:.3f} against {expected:.3f} expected under independence")


def test_only_declared_partitions_are_produced():
    assert {partition_for("s", f"E{i}") for i in range(200)} <= set(PARTITIONS)


# --------------------------------------------------------------------------- #
# Conforming
# --------------------------------------------------------------------------- #
def test_blank_demographic_stays_null():
    """Absence of a label is not a label. Letting blank become a value would quietly create an
    'unknown' subgroup in every fairness table, and it would be the largest one."""
    assert blank_to_none("") is None
    assert blank_to_none("   ") is None
    assert blank_to_none(None) is None
    assert blank_to_none(" Yes ") == "Yes"


def test_paper_mapper_rejects_an_empty_essay():
    assert _paper({"essay_id_comp": "X", "full_text": "   "}) is None


def test_paper_mapper_keeps_every_demographic_column():
    row = {"essay_id_comp": "X", "full_text": "an essay", "word_count": "42",
           "prompt_name": "Phones", "task": "Independent", "grade_level": "10",
           "gender": "F", "ell_status": "Yes", "race_ethnicity": "Black/African American",
           "economically_disadvantaged": "", "student_disability_status": "No"}
    p = _paper(row)
    assert p["ell_status"] == "Yes"
    assert p["economically_disadvantaged"] is None
    assert p["disability_status"] == "No"
    assert p["word_count"] == 42


def test_score_mapper_records_no_rater():
    """The corpus ships none. Inventing a synthetic rater would hide that severity is not estimable
    from it — the single most consequential thing the files told us."""
    s = _scores({"holistic_essay_score": "4"}, "p1")
    assert len(s) == 1
    assert s[0]["rater_id"] is None
    assert (s[0]["scale_min"], s[0]["scale_max"]) == (1, 6)


def test_unannotated_spans_are_dropped():
    """`Unannotated` is the corpus saying 'no element here', not an element called Unannotated."""
    assert _span({"essay_id_comp": "X", "discourse_type": "Unannotated"}) is None
    kept = _span({"essay_id_comp": "X", "discourse_type": "Counterclaim",
                  "discourse_start": "10.0", "discourse_end": "42.0",
                  "discourse_text": "Some say"})
    assert kept["discourse_type"] == "Counterclaim"
    assert (kept["start_char"], kept["end_char"]) == (10, 42)
    assert kept["effectiveness"] is None


def test_text_hash_ignores_whitespace_and_case():
    assert text_hash("The  Court\nsaid") == text_hash("the court said")


# --------------------------------------------------------------------------- #
# Non-independence, recorded
# --------------------------------------------------------------------------- #
def test_spec_records_the_asap_overlap():
    """A later reader must not repeat the mistake of treating them as independent sources."""
    assert SPEC.overlaps_source_id == "asap2"
    assert "circular" in SPEC.overlap_note


def test_spec_records_a_licence():
    assert SPEC.licence == "CC BY 4.0"


# --------------------------------------------------------------------------- #
# Against the real files
# --------------------------------------------------------------------------- #
@needs_corpus
def test_real_corpus_conforms():
    from corpus._shared import rows
    n, ell, blank_ell = 0, 0, 0
    for row in rows(str(CORPUS_DIR / SPEC.papers_file)):
        p = _paper(row)
        if p is None:
            continue
        n += 1
        if p["ell_status"] == "Yes":
            ell += 1
        if p["ell_status"] is None:
            blank_ell += 1
    assert n > 25_000, f"expected the full corpus, conformed {n}"
    assert ell > 2_000, "the ELL subgroup is what makes the fairness work possible"
    assert blank_ell > 0, "unlabelled rows must survive as NULL rather than become a subgroup"


@needs_corpus
def test_real_spans_include_the_taught_but_unscored_constructs():
    """9,534 counterclaims and 7,217 rebuttals — the constructs the crosswalk found taught in three
    places and scored in none. Presence has ground truth here even though quality does not."""
    from collections import Counter

    from corpus._shared import rows
    seen = Counter()
    for row in rows(str(CORPUS_DIR / SPEC.spans_file)):
        s = _span(row)
        if s:
            seen[s["discourse_type"]] += 1
    assert seen["Counterclaim"] > 9_000
    assert seen["Rebuttal"] > 7_000
    assert "Unannotated" not in seen
    assert set(seen) <= set(DISCOURSE_TYPES)
