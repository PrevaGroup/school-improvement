"""The words the loader stores must be the words the scoring side can read.

`corpus` writes `corpus_discourse_span.effectiveness` as the corpus's own word.
`measurement.corpus_agreement` turns that word into an ordered category. They are in different
modules, which may not import each other, so the vocabulary is agreed by convention — and a
convention without a check is drift with a delay on it.

The failure would be silent in the worst way: an unrecognised word is skipped, the trait reports
`no pairs`, and `no pairs` is exactly what it reported for months while the column was NULL. The
symptom of a broken mapping is indistinguishable from the symptom of missing data.
"""
from __future__ import annotations

from corpus.models import DISCOURSE_TYPES
from measurement.corpus_agreement import _EFFECTIVENESS, _SPAN_TYPE

PERSUADE_WORDS = ("Ineffective", "Adequate", "Effective")


def test_every_rating_the_corpus_ships_can_be_read():
    for word in PERSUADE_WORDS:
        assert word in _EFFECTIVENESS, f"{word!r} would be silently skipped"


def test_the_scale_is_ordered_the_way_the_rubric_orders_it():
    """Higher is better, and the rating scale model needs the direction to be right — an inverted
    scale produces a rater that looks systematically backwards rather than obviously broken."""
    assert _EFFECTIVENESS["Ineffective"] < _EFFECTIVENESS["Adequate"] < _EFFECTIVENESS["Effective"]


def test_every_span_type_the_report_expects_is_a_type_the_corpus_defines():
    """The report maps a trait to a PERSUADE `discourse_type`. A type that the corpus never writes
    matches nothing, and the trait reports `no pairs` — which reads as missing data."""
    unknown = set(_SPAN_TYPE.values()) - set(DISCOURSE_TYPES)
    assert not unknown, f"the report expects discourse types the corpus does not define: {unknown}"
