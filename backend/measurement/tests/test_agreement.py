"""Agreement statistics, checked against hand-worked cases and the failure kappa cannot show.

MFRM answers why two raters differ. These answer how much, in numbers comparable to published work
on this corpus — a severity of +0.4 logits means nothing to somebody who has only read kappas.
"""
from __future__ import annotations

import math

from measurement.agreement import compare, render

SIX = [1, 2, 3, 4, 5, 6]


def test_perfect_agreement_is_one():
    a = compare([(1, 1), (3, 3), (6, 6), (4, 4)], SIX)
    assert a.exact == 1.0 and a.adjacent == 1.0
    assert a.qwk == 1.0
    assert a.mean_signed == 0 and a.mean_absolute == 0


def test_quadratic_weighting_punishes_a_far_miss_more_than_a_near_one():
    """On an ordered scale, calling a 6 a 5 is not the mistake that calling it a 1 is — and
    unweighted kappa treats them identically."""
    near = compare([(6, 5), (1, 2), (3, 3), (4, 4)], SIX)
    far = compare([(6, 1), (1, 6), (3, 3), (4, 4)], SIX)
    assert near.qwk > far.qwk


def test_exact_and_adjacent_are_reported_separately():
    """Kappa hides its shape. "Agreed outright half the time and was within one nine times in ten"
    is what a person can picture, and it distinguishes a rater that is usually right from one that
    is never far wrong."""
    a = compare([(3, 3), (3, 4), (3, 4), (3, 5)], SIX)
    assert a.exact == 0.25
    assert a.adjacent == 0.75


def test_the_signed_mean_says_which_way():
    """Positive means WE score higher. Deliberately the opposite sign from severity, where
    positive means harsher — and named in the output rather than left to be inferred."""
    higher = compare([(2, 3), (3, 4), (4, 5)], SIX)
    lower = compare([(3, 2), (4, 3), (5, 4)], SIX)
    assert higher.mean_signed == 1.0
    assert lower.mean_signed == -1.0
    assert "positive = we score higher" in render(higher, label="x")


# ------------------------------------------------------------------ the failure kappa hides

def test_compression_is_detected_and_named():
    """A rater that never uses the ends of the scale has compressed it, and kappa can look
    respectable while that happens. It is the specific failure predicted for this model, and the
    first three real papers hinted at it: a human 1 came back 2 and a human 5 came back 3."""
    a = compare([(1, 3), (2, 3), (3, 3), (4, 4), (5, 4), (6, 4)], SIX)
    assert a.compressed
    assert a.spread["ours_sd"] < a.spread["theirs_sd"]
    assert "COMPRESSED" in render(a, label="holistic")


def test_a_rater_using_the_whole_scale_is_not_flagged():
    a = compare([(1, 1), (2, 2), (3, 3), (4, 4), (5, 5), (6, 6)], SIX)
    assert not a.compressed


def test_kappa_does_not_move_when_the_category_list_does():
    """Pinned because the intuition is wrong, and mine was — I first justified supplying the
    categories by claiming an unused top of the scale inflates kappa. It does not. Weights come
    from the score values, a common factor on them cancels between the observed and expected sums,
    and an unused category has a zero marginal on both sides.

    So the same disagreements earn the same number whether or not the sample reached the ends of
    the scale, and whether or not it has a hole in it. That is the property worth having on a
    per-trait split, where holes are routine."""
    # isclose, not ==: the invariance is exact in arithmetic, and the two paths divide by different
    # presentational normalisers on the way, which costs the last bit of a float.
    pairs = [(1, 1), (3, 5), (5, 3), (1, 1)]      # nobody used 2, 4 or 6
    assert math.isclose(compare(pairs, SIX).qwk, compare(pairs).qwk)

    off_the_end = [(2, 2), (3, 4), (4, 3), (5, 5)]  # nobody used 1 or 6
    assert math.isclose(compare(off_the_end, SIX).qwk, compare(off_the_end).qwk)


def test_the_categories_are_supplied_for_the_matrix():
    """Which is the actual reason. A matrix drawn only over the values a rater used always looks
    like full coverage of the scale, and the unused rows are precisely where compression shows."""
    pairs = [(1, 1), (3, 5), (5, 3), (1, 1)]
    assert set(compare(pairs, SIX).matrix) == set(SIX)
    assert set(compare(pairs).matrix) == {1, 3, 5}


def test_a_wider_miss_costs_more_even_across_a_hole_in_the_sample():
    """The failure that value-weighting avoids. With position weights and nobody scoring a 4, a
    3-versus-5 disagreement would count as adjacent — the same as 3-versus-2 — and a gap in the
    sample would flatter the rater."""
    near = compare([(3, 2), (1, 1), (5, 5)], SIX)
    across_the_hole = compare([(3, 5), (1, 1), (5, 5)], SIX)
    assert across_the_hole.qwk < near.qwk


# ------------------------------------------------------------------ what it refuses to claim

def test_no_pairs_is_not_zero_agreement():
    a = compare([], SIX)
    assert a.n == 0 and math.isnan(a.qwk)
    assert "no pairs" in render(a, label="x")


def test_one_category_used_by_both_is_undefined_not_perfect():
    """Both raters said 3 every time. There is perfect agreement and no information in it —
    reporting 1.0 would be a claim about a rater that the data cannot support."""
    a = compare([(3, 3), (3, 3), (3, 3)], [3])
    assert math.isnan(a.qwk)


def test_a_missing_score_is_dropped_rather_than_treated_as_zero():
    """An abstention is not a category. Scoring it as one would put a rater's refusal to judge on
    the scale as if it were a judgment."""
    a = compare([(3, 3), (4, None), (None, 2), (5, 5)], SIX)
    assert a.n == 2


# ------------------------------------------------------------------ the matrix

def test_the_matrix_shows_every_cell_including_the_empty_ones():
    """Compression is invisible in a kappa and obvious in a matrix — but only if the unused rows
    are printed. A matrix that omits them looks like full coverage."""
    a = compare([(1, 3), (2, 3), (3, 3)], SIX)
    assert set(a.matrix) == set(SIX)
    assert all(set(row) == set(SIX) for row in a.matrix.values())
    assert a.matrix[1][3] == 1
    assert a.matrix[6][6] == 0
    out = render(a, label="x")
    assert "human 6:" in out
