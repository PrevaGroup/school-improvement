"""Choosing the anchor papers, and the four ways a sample stops being replayable.

The anchor set is what model severity is estimated against and what a new scoring configuration is
replayed on before promotion. Both are claims about a FIXED set, so the draw has to be
reproducible from the corpus alone — `ORDER BY random() LIMIT 300` makes "we replayed the anchor
set" a claim nobody can check.
"""
from __future__ import annotations

from corpus.anchor import ELL, SCORES, Draw, rank_key, report, select


def paper(pid, ell="No", score="3", partition="calibration"):
    return {"paper_id": pid, "ell_status": ell, "score": score, "partition": partition}


def corpus(**counts):
    """counts keyed 'ell:score' -> n, e.g. corpus(**{"Yes:1": 50, "No:1": 200})."""
    out = []
    for key, n in counts.items():
        ell, score = key.split(":")
        out += [paper(f"{ell}-{score}-{i}", ell=ell, score=score) for i in range(n)]
    return out


# ------------------------------------------------------------------ reproducible

def test_the_same_corpus_draws_the_same_set_twice():
    """The property the whole file exists for. A set that cannot be redrawn cannot be replayed,
    and replay is the promotion gate for a new scoring configuration."""
    papers = corpus(**{"No:3": 500, "Yes:3": 100})
    assert select(papers, 20).paper_ids == select(papers, 20).paper_ids


def test_the_draw_does_not_depend_on_row_order():
    """Row order is an artefact of how the CSV was written, and it changes when a corpus is
    re-issued or a load is resumed."""
    papers = corpus(**{"No:2": 200, "Yes:2": 80})
    forward = select(papers, 15).paper_ids
    backward = select(list(reversed(papers)), 15).paper_ids
    assert sorted(forward) == sorted(backward)


def test_the_ordering_is_a_hash_not_a_position():
    a, b = rank_key("paper-a"), rank_key("paper-b")
    assert a != b
    assert rank_key("paper-a") == a


# ------------------------------------------------------------------ waves nest

def test_wave_one_is_a_subset_of_wave_two():
    """Scoring 300 now and 300 later must produce ONE sample of 600, not two of 300. If the first
    wave were re-drawn, its scores would be unusable and the money spent on them wasted."""
    papers = corpus(**{"No:3": 300, "Yes:3": 300})
    d = select(papers, 60, waves=(20, 60))
    assert set(d.wave(1)) < set(d.wave(2))
    assert len(d.wave(1)) == 40      # 20 per cell, two cells
    assert len(d.wave(2)) == 120


def test_extending_a_wave_does_not_move_a_paper_between_waves():
    papers = corpus(**{"No:3": 300, "Yes:3": 300})
    small = select(papers, 60, waves=(20, 40))
    big = select(papers, 60, waves=(20, 60))
    assert small.wave(1) == big.wave(1)


def test_every_drawn_paper_has_a_wave():
    d = select(corpus(**{"No:3": 50}), 10, waves=(4,))
    assert set(d.waves) == set(d.paper_ids)


# ------------------------------------------------------------------ the cell that cannot be filled

def test_a_cell_with_too_few_papers_takes_what_exists_and_says_so():
    """Four ELL papers in the whole corpus scored 6. No sample size fixes that, and a DIF claim at
    the top of the scale is UNAVAILABLE rather than underpowered — a distinction a reader cannot
    recover from a confidence interval."""
    papers = corpus(**{"Yes:6": 4, "No:6": 800})
    d = select(papers, 60)
    short = {(c.ell, c.score): c for c in d.shortfalls}
    assert ("Yes", "6") in short
    assert short[("Yes", "6")].available == 4
    assert short[("Yes", "6")].taken == 4
    assert ("No", "6") not in short


def test_the_report_names_the_unfillable_cells():
    d = select(corpus(**{"Yes:6": 4, "No:6": 800}), 60)
    text = report(d)
    assert "UNAVAILABLE" in text
    assert "ELL=Yes score=6" in text
    assert "the corpus has 4" in text


def test_a_short_cell_does_not_borrow_from_another():
    """Topping up score 6 from score 5 would silently change what the stratum means, and the
    resulting severity estimate would describe a different population than its label."""
    d = select(corpus(**{"Yes:5": 70, "Yes:6": 4}), 60)
    taken = {(c.ell, c.score): c.taken for c in d.cells}
    assert taken[("Yes", "6")] == 4
    assert taken[("Yes", "5")] == 60


# ------------------------------------------------------------------ what is not eligible

def test_validation_papers_are_never_drawn():
    """Estimating severity on papers and then validating a claim on the same papers is circular.
    The partition exists so the holdout survives a decision made in a hurry."""
    papers = ([paper(f"v{i}", partition="validation") for i in range(100)]
              + [paper(f"c{i}") for i in range(100)])
    assert all(p.startswith("c") for p in select(papers, 50).paper_ids)


def test_a_paper_with_no_ell_label_is_excluded_not_bucketed():
    """5% of the corpus has a blank ELL status. Absence of a label is not a label — the same rule
    the loader applies when it keeps a blank demographic NULL. Bucketing them as "unknown" would
    invent a subgroup and then report fairness about it."""
    papers = corpus(**{"No:3": 50}) + [paper(f"blank{i}", ell="") for i in range(50)]
    assert all(not p.startswith("blank") for p in select(papers, 100).paper_ids)


def test_a_paper_with_no_human_score_is_excluded():
    papers = corpus(**{"No:3": 50}) + [paper(f"noscore{i}", score="") for i in range(50)]
    assert all(not p.startswith("noscore") for p in select(papers, 100).paper_ids)


# ------------------------------------------------------------------ the strata

def test_the_draw_is_balanced_across_ell_status():
    """8.6% ELL in the corpus. A simple random draw of 600 gives ~52 ELL papers, which is
    underpowered for the one analysis the corpus exists to make possible."""
    papers = corpus(**{"No:3": 7000, "Yes:3": 800})
    d = select(papers, 100)
    ell = sum(1 for p in d.paper_ids if p.startswith("Yes"))
    assert ell == 100 and len(d.paper_ids) == 200


def test_the_top_of_the_scale_can_ask_for_less_than_the_middle():
    """Per-score targets, because the thin end of the scale cannot fill a middle-sized cell and
    asking it to produces a shortfall report on every run for no reason."""
    papers = corpus(**{"No:3": 500, "No:6": 500})
    d = select(papers, {"3": 60, "6": 10})
    taken = {c.score: c.taken for c in d.cells if c.ell == "No"}
    assert taken["3"] == 60 and taken["6"] == 10


def test_every_stratum_appears_in_the_report_even_at_zero():
    """A cell with nothing in it is a fact about the corpus. Omitting it makes the report look
    like full coverage of a scale it never touched."""
    d = select(corpus(**{"No:3": 10}), 5)
    assert len(d.cells) == len(ELL) * len(SCORES)
    assert any(c.available == 0 for c in d.cells)
