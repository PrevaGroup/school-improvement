"""The assembly around the statistics — which comparisons are real, and what is not counted.

`compare` and the MFRM estimators are tested against hand-worked cases elsewhere. What is tested
here is the part that decides WHAT gets compared, because that is where a number becomes a claim
about a rater it cannot support.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from measurement.corpus_agreement import _SPAN_TYPE, aggregate, measure, report

SIX = [1, 2, 3, 4, 5, 6]


def _trait(pairs, *, label="Holistic", derived=False, categories=SIX, ell=None, **counts):
    return {"label": label, "external_ref": "x", "categories": categories, "derived": derived,
            "pairs": [(a, b, f"p{i}") for i, (a, b) in enumerate(pairs)],
            "ell": ell or {}, "papers": {f"p{i}" for i in range(len(pairs))},
            "scored": counts.get("scored", len(pairs)), "abstained": counts.get("abstained", 0),
            "no_human": counts.get("no_human", 0), "escalated": counts.get("escalated", 0)}


# ------------------------------------------------------------------ the constructed comparator

def test_span_ratings_fold_by_the_named_rule():
    """A paper with three claims has three claim ratings, and the rubric asks one question about
    the paper. Every answer here is a choice somebody made."""
    v = [1, 3, 2, 2]
    assert aggregate(v, "best") == 3
    assert aggregate(v, "worst") == 1
    assert aggregate(v, "mean") == 2
    assert aggregate(v, "modal") == 2


def test_a_modal_tie_resolves_the_same_way_every_run():
    """`statistics.mode` breaks a tie by first occurrence, so unsorted input makes the comparator
    depend on the order spans happen to sit in the file — a number that moves between runs of the
    same query."""
    assert aggregate([3, 1, 3, 1], "modal") == aggregate([1, 3, 1, 3], "modal") == 1


def test_a_paper_with_no_span_of_that_type_has_no_comparator():
    """Not a zero and not a 1. A paper that never attempted a rebuttal has no human rebuttal
    rating, and scoring the silence would invent disagreement."""
    assert aggregate([], "best") is None


def test_every_element_trait_maps_to_a_span_type():
    """If a trait is missing from the map it silently falls through to the HOLISTIC comparator and
    gets scored against the wrong human number entirely — a 1-3 element against a 1-6 holistic,
    which would look like catastrophic disagreement rather than like a bug."""
    from registry.persuade_rubrics import evidence_trait, shared_element_traits

    refs = ([t["external_ref"] for t in shared_element_traits()]
            + [evidence_trait(f)["external_ref"] for f in ("independent", "text_dependent")])
    assert len(refs) == 8
    assert set(refs) <= set(_SPAN_TYPE)


def test_the_holistic_trait_is_not_in_the_span_map():
    """It is the one real comparison. Mapping it to a span type would replace PERSUADE's own human
    score with something we constructed, and the output would still say AGAINST HUMAN SCORES."""
    from registry.persuade_rubrics import holistic

    for form in ("independent", "text_dependent"):
        assert holistic(form)["traits"][0]["external_ref"] not in _SPAN_TYPE


# ------------------------------------------------------------------ what the report says it is

def test_a_derived_comparison_is_printed_under_its_own_heading():
    """The number is not wrong; the claim around it would be. A reader has to be told which of
    these a human actually produced."""
    out = report({"n1": _trait([(3, 3), (2, 2)], label="Holistic"),
                  "n2": _trait([(3, 3), (2, 2)], label="Claim", derived=True,
                               categories=[1, 2, 3])}, how="best")
    assert "AGAINST HUMAN SCORES" in out
    assert "AGAINST A COMPARATOR WE BUILT" in out
    assert out.index("AGAINST HUMAN SCORES") < out.index("AGAINST A COMPARATOR WE BUILT")


def test_the_aggregation_choice_appears_in_the_output():
    """Because it moves the numbers. A reader given a QWK and not told the rule cannot reproduce
    it and cannot argue with it."""
    out = report({"n": _trait([(3, 3), (2, 2)], label="Claim", derived=True,
                              categories=[1, 2, 3])}, how="worst")
    assert "`worst`" in out


def test_abstentions_are_reported_next_to_the_agreement():
    """A trait that agreed beautifully on the third of papers it was willing to score is not a
    trait with good agreement, and the kappa alone says it is."""
    out = report({"n": _trait([(3, 3)], abstained=40, no_human=5, escalated=7)}, how="best")
    assert "40 abstained" in out
    assert "5 with no human rating" in out
    assert "7 escalated" in out


def test_nothing_scored_says_so_rather_than_printing_an_empty_report():
    assert "No scored corpus papers" in report({}, how="best")


# ------------------------------------------------------------------ measurement, and its limits

def test_severity_and_bias_come_back_for_a_normal_trait():
    pairs = [(h, min(6, h + (i % 2))) for i, h in enumerate([1, 2, 3, 4, 5, 6] * 6)]
    ell = {f"p{i}": ("Yes" if i % 3 == 0 else "No") for i in range(len(pairs))}
    m = measure(_trait(pairs, ell=ell))
    assert m["severity"] is not None
    assert m["severity"].harsher in ("human", "model")
    assert all(b.rater == "model" for b in m["bias"])


def test_a_trait_with_one_paper_reports_why_rather_than_a_number():
    m = measure(_trait([(3, 3)]))
    assert m["severity"] is None and m["why"]


def test_the_scale_is_taken_from_the_node_not_the_data():
    """`categories` comes from `registry_node.scale_categories`, so a 1-3 element is measured on
    three categories even in a sample where nobody scored a 1."""
    m = measure(_trait([(2, 2), (3, 3), (2, 3)], categories=[1, 2, 3]))
    assert m["agreement"].categories == [1, 2, 3]
    assert set(m["agreement"].matrix) == {1, 2, 3}


# ------------------------------------------------------------------ the module boundary

def test_it_reads_tables_and_imports_no_other_module():
    """`measurement` depends only on `core`. The registry labels arrive through `registry_node`
    and the human ratings through the corpus tables — table-level contracts, which is how modules
    integrate here. Checked on the AST rather than by grepping the source, because a mention in a
    docstring is not an import and an import inside a function still is one."""
    src = pathlib.Path(__file__).parent.parent / "corpus_agreement.py"
    tree = ast.parse(src.read_text(encoding="utf8"))

    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])

    siblings = {"registry", "scoring", "corpus", "evals", "sip", "app"}
    assert not (imported & siblings), f"imports another module: {sorted(imported & siblings)}"


@pytest.mark.parametrize("table", ["registry_node", "corpus_paper", "corpus_score",
                                   "corpus_discourse_span", "score_event", "artifact"])
def test_the_tables_it_reads_are_named_in_one_place(table):
    """Every cross-module read is a query in this file, so `grep FROM` finds all of them. Reaching
    a table through an imported helper is how a dependency stops being visible."""
    src = (pathlib.Path(__file__).parent.parent / "corpus_agreement.py").read_text(encoding="utf8")
    assert table in src


def test_every_nullable_parameter_is_cast():
    """`:p IS NULL` with a NULL bind fails on Postgres — it cannot infer the parameter's type and
    raises `could not determine data type`. It shipped that way: the tests here run against a fake
    connection, so nothing exercised the SQL, and the default `--run-id` is None which is exactly
    the failing case.

    Grepping the SQL is a poor substitute for running it, and it is what can run without a
    database. The real check is that the command works, which is now the first thing done after a
    scoring run rather than the last."""
    src = (pathlib.Path(__file__).parent.parent / "corpus_agreement.py").read_text(encoding="utf8")
    for line in src.splitlines():
        if "IS NULL" in line and ":" in line and "--" not in line:
            assert "CAST(" in line, f"untyped nullable parameter: {line.strip()}"
