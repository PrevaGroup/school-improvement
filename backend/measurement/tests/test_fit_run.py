"""Fitting one assignment, and the two things that must not be mixed."""
from __future__ import annotations

import math

from measurement.fit_run import DISTORTING_OUTFIT, by_scale, observations
from measurement.mfrm import fit


def score(artifact, node, level, cats=(1, 2, 3)):
    return {"artifact_id": artifact, "node_id": node, "level": level,
            "scale_categories": list(cats), "scoring_configuration_id": "cfg-1"}


def test_scales_are_grouped_and_never_mixed():
    """The rating scale model estimates thresholds between adjacent categories, and thresholds
    belong to the scale. A 1-6 holistic trait fitted beside a 1-3 element estimates a scale nobody
    used."""
    groups = by_scale([score("p1", "elem", 2), score("p1", "holistic", 4, cats=(1, 2, 3, 4, 5, 6))])
    assert set(groups) == {(1, 2, 3), (1, 2, 3, 4, 5, 6)}
    assert len(groups[(1, 2, 3)]) == 1 and len(groups[(1, 2, 3, 4, 5, 6)]) == 1


def test_two_scales_of_the_same_length_are_still_two_scales():
    """Keyed by the categories, not by how many there are. A 1-3 scale and a 0-2 scale are both
    three categories and are not the same scale."""
    groups = by_scale([score("p1", "a", 2, cats=(1, 2, 3)), score("p1", "b", 1, cats=(0, 1, 2))])
    assert set(groups) == {(1, 2, 3), (0, 1, 2)}


def test_a_scale_with_one_category_is_dropped():
    """Nothing can be estimated from a scale with no alternatives."""
    assert by_scale([score("p1", "a", 1, cats=(1,))]) == {}


def test_the_paper_is_the_person_and_the_trait_is_the_rater():
    """The reverse of the corpus comparison, deliberately. There, several raters scored one paper
    and the question was about the raters. Here one rater scored several traits, and the question
    is whether a paper's answers agree with each other."""
    obs = observations([score("p1", "claim", 3), score("p1", "lead", 1)], (1, 2, 3))
    assert {o.person for o in obs} == {"p1"}
    assert {o.rater for o in obs} == {"claim", "lead"}


def test_categories_are_shifted_to_zero_for_the_estimator():
    """A 1-3 level arrives as 0-2. Feeding the raw level would give the model a category it has no
    threshold for, at the bottom of every scale that does not start at zero."""
    obs = observations([score("p1", "a", 1), score("p1", "b", 3)], (1, 2, 3))
    assert sorted(o.category for o in obs) == [0, 2]
    obs6 = observations([score("p2", "h", 4, cats=(1, 2, 3, 4, 5, 6))], (1, 2, 3, 4, 5, 6))
    assert obs6[0].category == 3


# ------------------------------------------------------------------ what the fit actually finds

def _class(consistent: int, odd_paper: bool) -> list:
    """A class where everyone scores the same on seven traits, optionally with one paper that
    scores high on six and low on one."""
    rows = []
    for i in range(consistent):
        for t in range(7):
            rows.append(score(f"p{i}", f"t{t}", 2 if i % 2 else 3))
    if odd_paper:
        for t in range(7):
            rows.append(score("odd", f"t{t}", 1 if t == 3 else 3))
    return rows


def test_a_paper_whose_scores_disagree_with_each_other_misfits():
    """The thing this exists to find. Six threes and a one is not a low score — it is one response
    the model did not expect, and no mean shows it."""
    rows = _class(10, odd_paper=True)
    f = fit(observations(rows, (1, 2, 3)), max_category=2)
    odd = f.persons["odd"]
    typical = [e.outfit for k, e in f.persons.items()
               if k != "odd" and not e.extreme and e.outfit == e.outfit]
    assert odd.outfit == odd.outfit, "the odd paper must have a computable outfit"
    if typical:
        assert odd.outfit > max(typical)


def test_a_paper_at_one_end_of_the_scale_throughout_is_extreme_not_misfitting():
    """Its measure is infinite in the model, so it is excluded from estimation and recorded. That
    is the difference between "not estimable" and "not present" — dropping it makes a whole class
    of papers quietly absent from every count."""
    rows = [score("top", f"t{t}", 3) for t in range(7)]
    rows += [score(f"p{i}", f"t{t}", 2) for i in range(6) for t in range(7)]
    f = fit(observations(rows, (1, 2, 3)), max_category=2)
    # `extreme` is a sentence, not a code — it has to be readable where it surfaces.
    assert f.persons["top"].extreme == "every rating at the top category"
    assert f.persons["top"].measure != f.persons["top"].measure   # nan: no measure exists
    assert f.persons["top"].n == 7


def test_the_threshold_is_a_reading_and_is_not_applied():
    """No flag is written. Deciding what counts as too much misfit is a reading, and readings
    belong to whoever is answerable for them — the module stores the number and says what the
    convention is."""
    import pathlib

    src = (pathlib.Path(__file__).parent.parent / "fit_run.py").read_text(encoding="utf8")
    assert DISTORTING_OUTFIT == 2.0
    assert "Stored, not acted on" in src
    # The table has no flag column, which is the part that matters — a stored verdict is a
    # reading somebody made, and it would outlive the reasoning that produced it.
    mig = (pathlib.Path(__file__).parent.parent / "migrations"
           / "0040_fit_statistics.py").read_text(encoding="utf8")
    for banned in ("flagged", "needs_review", "is_unexpected"):
        assert banned not in mig
