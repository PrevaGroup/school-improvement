"""The diagnostic reads stage-D bands that `scoring` writes, and may not import `scoring` to do it.

Same duplication and same hazard as `test_span_shape_agrees.py`, which exists because the drift
already happened once: `span_diagnostic` read `"text"` where `verify_all` writes `"span"`, every
span measured zero characters, and the result printed as a clean flat column — indistinguishable
from a genuine "the evidence stage is blind" finding.

The hazard here is the same shape and the stakes are higher, because this module's whole output
is a verdict about whether a column is flat. `bands_of` returning `{}` from a well-formed
evidence dict would read as "the model cannot see the top band" — the conclusion that costs a
re-scoring run and a rubric rewrite — when it in fact means the key was renamed.

`scoring.score.level_from` is the producer. It is called here for real, and its output is fed
through the consumer's parser.
"""
from __future__ import annotations

from measurement.band_diagnostic import bands_of, expected, facts_of, level_at
from scoring.score import level_from

CATS = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
# A paper the ladder puts at 3 under the shipped 0.5 threshold, carrying real probability at 5
# and 6 that the ladder discards — the case the whole diagnostic exists to detect.
PROBS = {2.0: 0.97, 3.0: 0.84, 4.0: 0.41, 5.0: 0.22, 6.0: 0.08}


def _evidence():
    """What `scoring.score` stores, built by the real producer."""
    decided = level_from(PROBS, CATS, 0.5)
    return {"bands": decided["probabilities"], "threshold": 0.5,
            "decided_at": decided["decided_at"], "decided_p": decided["decided_p"],
            "monotonicity_violations": decided["monotonicity_violations"]}


def test_the_parser_reads_every_band_the_producer_wrote():
    b = bands_of(_evidence())
    assert b == PROBS, "the key or the float conversion has drifted from what level_from stores"


def test_the_producer_writes_string_keys_and_the_parser_floats_them():
    """The contract that would silently halve the table if either side changed."""
    stored = _evidence()["bands"]
    assert all(isinstance(k, str) for k in stored), "level_from stores formatted string keys"
    assert set(bands_of(_evidence())) == set(CATS[1:])


def test_the_diagnostic_reproduces_the_shipped_decision():
    """At the threshold actually used, the re-implementation must agree with the pipeline."""
    assert level_at(bands_of(_evidence()), CATS, 0.5) == level_from(PROBS, CATS, 0.5)["level"]


def test_facts_carry_the_decision_the_producer_recorded():
    f = facts_of(_evidence())
    assert f["threshold"] == 0.5
    assert f["decided_at"] == 4.0, "the first rung under the threshold"
    assert f["violations"] == 0


def test_absent_bands_are_absent_rather_than_zero():
    """A `category` rater stores no bands. Reporting that as flat zeros would read as the
    verdict that costs the most to act on."""
    assert bands_of({"proposed": 3, "kept": []}) == {}
    assert bands_of(None) == {}


def test_the_ladder_discards_what_the_expectation_spends():
    """The premise of the third column, asserted against the real producer rather than asserted
    in prose: the same probabilities that the ladder resolves to 3 imply an expectation of 3.5."""
    b = bands_of(_evidence())
    assert level_from(PROBS, CATS, 0.5)["level"] == 3.0
    assert abs(expected(b, CATS) - (1 + 0.97 + 0.84 + 0.41 + 0.22 + 0.08)) < 1e-9
    assert expected(b, CATS) > 3.0
