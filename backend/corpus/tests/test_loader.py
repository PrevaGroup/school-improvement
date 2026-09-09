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


def test_this_system_holds_no_licensing_at_all():
    """Twice wrong before this. First `SPEC.licence = "CC BY 4.0"` — this project stating somebody
    else's terms from memory, with a test asserting it so CI defended the claim. Then a
    `licence_file` read from the distribution, which fixed the sourcing and kept the column.

    A better-sourced licence field is still this system holding a fact that belongs elsewhere.
    Terms are negotiated and they change without the data changing, so a copy here goes stale
    silently while looking authoritative — and it is read at exactly the moment somebody is
    deciding whether they may redistribute something.

    Licensing lives in the contracts system. This one records WHO published a corpus, which is
    provenance; what may be done with it is not ours to answer.
    """
    assert not hasattr(SPEC, "licence")
    assert not hasattr(SPEC, "licence_file")
    assert SPEC.url, "provenance stays: who published this is ours to record"


@pytest.mark.parametrize("module", ["corpus/_shared.py", "corpus/load_persuade.py",
                                     "corpus/models.py", "registry/persuade_rubrics.py",
                                     "registry/seed_persuade.py"])
def test_no_licence_is_named_anywhere_in_the_loaders(module):
    """Named licences specifically, not the word — the surviving mentions are comments explaining
    why there is no such field, and deleting those would invite the next author to add one back.

    This is the guard. The defect was not that somebody picked the wrong licence; it was that
    picking one here was possible at all.
    """
    src = (pathlib.Path(__file__).parent.parent.parent / module).read_text(encoding="utf8")
    for named in ("CC BY", "CC-BY", "Apache", "MIT License", "GPL", "creativecommons.org"):
        assert named not in src, f"{module} names a licence: {named}"


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
    """Counterclaims and rebuttals — the constructs the crosswalk found taught in three places and
    scored in none. Presence has ground truth here even though quality does not.

    The counts dropped when the span source moved from the 2021 file to the 2.0 TRAIN split:
    5,817 counterclaims against 9,534, because the split holds 15,594 of the corpus's 25,990
    essays. That is the trade — 60% coverage WITH human effectiveness ratings, against 100%
    coverage with none at all.
    """
    from collections import Counter

    from corpus._shared import rows
    seen = Counter()
    for row in rows(str(CORPUS_DIR / SPEC.spans_file)):
        s = _span(row)
        if s:
            seen[s["discourse_type"]] += 1
    assert seen["Counterclaim"] > 5_000
    assert seen["Rebuttal"] > 4_000
    assert "Unannotated" not in seen
    assert set(seen) <= set(DISCOURSE_TYPES)


@pytest.mark.skipif(not HAVE_CORPUS, reason="corpus files not present")
def test_the_real_span_file_actually_carries_effectiveness():
    """The reason for the whole change. Asserted against the real file, because a mapper that
    reads a column no file has is exactly the defect being fixed — and it would look identical to
    the one before it: every trait reporting `no pairs`."""
    from collections import Counter

    from corpus._shared import rows
    rated = Counter()
    for i, row in enumerate(rows(str(CORPUS_DIR / SPEC.spans_file))):
        if i >= 20_000:
            break
        s = _span(row)
        if s and s["effectiveness"]:
            rated[s["effectiveness"]] += 1
    assert set(rated) == {"Ineffective", "Adequate", "Effective"}
    assert sum(rated.values()) > 10_000


@pytest.mark.skipif(not HAVE_CORPUS, reason="corpus files not present")
def test_the_span_split_covers_less_than_the_paper_file():
    """Measured, and the reason the 2.0 file is NOT the papers file: it holds 15,594 essays where
    the corpus has 25,990. Using it for both passes would shrink the corpus by 40% and the loader
    would report loading exactly what it was given."""
    from corpus._shared import rows

    essays = {r["essay_id_comp"] for r in rows(str(CORPUS_DIR / SPEC.spans_file))}
    assert 15_000 < len(essays) < 17_000
    assert SPEC.papers_file != SPEC.spans_file


# ------------------------------------------------------------------ what was in the file all along

def _row(**over):
    """A minimal essay row, as the PERSUADE 2.0 header names its columns."""
    return {"essay_id_comp": "X", "full_text": "an essay", "task": "Independent", **over}


def test_the_assignment_is_mapped():
    """The task statement. `scoring.fit` short-circuits without one — deliberately, since no task
    statement means no gate — so every corpus paper skipped stage B while student work did not.
    The severity estimated on the anchor set described a rater running one stage fewer than
    production, and nothing downstream could have said so."""
    row = _row(assignment="Write an essay about driverless cars.")
    assert _paper(row)["assignment"] == "Write an essay about driverless cars."


def test_the_source_text_is_mapped():
    """The text-dependent evidence trait is defined as evidence "taken from the source text(s)".
    Nothing in the pipeline had seen a source text, so that trait asked whether a quotation came
    from a document the rater could not read — a validity problem, on 163 of 334 anchor papers."""
    row = _row(source_text="The article argues that autonomous vehicles are safer.")
    assert _paper(row)["source_text"] == "The article argues that autonomous vehicles are safer."


def test_an_independent_prompt_has_no_source_and_that_is_a_fact_not_a_gap():
    """NULL here means the prompt supplied no reading, which is what an independent prompt is.
    Defaulting it to an empty string would make "no source" and "a source we failed to load"
    indistinguishable."""
    assert _paper(_row(source_text=""))["source_text"] is None
    assert _paper(_row(assignment=""))["assignment"] is None


def test_both_columns_reach_the_upsert():
    """A mapped field that the INSERT does not name is silently dropped, and the loader would
    report the same counts either way."""
    from corpus._shared import _PAPER

    sql = str(_PAPER)
    for col in ("assignment", "source_text"):
        assert f":{col}" in sql, f"{col} is mapped but never bound"
        assert f"{col} = EXCLUDED.{col}" in sql, f"{col} would not backfill on a re-run"


# ------------------------------------------------------------------ the effectiveness rating

def test_the_effectiveness_rating_is_mapped():
    """NULL through every load before this one, because the 2021 segmentation file has no such
    column. That is why eight of the ten traits this system scores reported `no pairs` on 334
    papers scored twice — there was nothing human to compare them against."""
    span = _span(dict(_row(), discourse_type="Claim", discourse_start="1", discourse_end="9",
                      discourse_text="cars", discourse_effectiveness="Effective"))
    assert span["effectiveness"] == "Effective"


def test_the_corpus_word_is_kept_rather_than_a_number():
    """Ordering Ineffective < Adequate < Effective is a scoring decision, and it belongs where the
    scale is declared. A number in this column would be that decision made invisibly, in the one
    place nobody would look for it."""
    for word in ("Ineffective", "Adequate", "Effective"):
        got = _span(dict(_row(), discourse_type="Lead", discourse_start="1", discourse_end="2",
                         discourse_text="x", discourse_effectiveness=word))["effectiveness"]
        assert got == word


def test_a_span_with_no_rating_stays_null():
    """Not every element is rated. Blank must not become a category."""
    span = _span(dict(_row(), discourse_type="Lead", discourse_start="1", discourse_end="2",
                      discourse_text="x", discourse_effectiveness=""))
    assert span["effectiveness"] is None


def test_the_word_count_is_read_under_either_name():
    """The 2021 file said `word_count`; the 2.0 file says `essay_word_count`. A mapper that
    silently reads None from a renamed column is how this loader once counted 25,994 papers into
    25,990 rows."""
    assert _paper(_row(word_count="42"))["word_count"] == 42
    assert _paper(_row(essay_word_count="321"))["word_count"] == 321
    assert _paper(_row())["word_count"] is None


def test_the_spans_come_from_the_file_that_has_the_ratings():
    """And the papers do not. The 2.0 file is a train split covering 60% of the corpus; using it
    for papers as well would drop the other 40% silently."""
    assert "2.0_train" in SPEC.spans_file
    assert "human_scores" in SPEC.papers_file
