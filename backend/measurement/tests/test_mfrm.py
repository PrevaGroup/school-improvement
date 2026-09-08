"""MFRM, checked the only way an estimator can be: by recovering parameters it was not told.

Every other test in this file is a property. The first section is the one that matters — simulate
ratings from known person measures and known rater severities, hand the estimator nothing but the
ratings, and see whether it finds the numbers back. An estimator that passes property tests and
fails recovery is producing confident nonsense, and a severity of "+0.4 logits" is exactly the
kind of number nobody re-derives.
"""
from __future__ import annotations

import math
import random

import pytest

from measurement.mfrm import (Bias, NotConnected, Observation, bias, connected, fit,
                              paired_severity)


def simulate(persons: dict[str, float], raters: dict[str, float],
             thresholds: list[float], *, seed: int = 7) -> list[Observation]:
    """Draw ratings from the rating scale model with known parameters."""
    rng = random.Random(seed)
    cum, run = [0.0], 0.0
    for t in thresholds:
        run += t
        cum.append(run)

    obs = []
    for p, theta in persons.items():
        for r, sev in raters.items():
            lam = theta - sev
            terms = [k * lam - cum[k] for k in range(len(cum))]
            top = max(terms)
            ex = [math.exp(t - top) for t in terms]
            z = sum(ex)
            probs = [e / z for e in ex]
            u, acc, pick = rng.random(), 0.0, len(probs) - 1
            for k, pk in enumerate(probs):
                acc += pk
                if u <= acc:
                    pick = k
                    break
            obs.append(Observation(person=p, rater=r, category=pick))
    return obs


# ------------------------------------------------------------------ recovery

def test_the_paired_estimator_recovers_a_known_severity_difference():
    """The headline quantity, from the estimator appropriate to the design. A model half a logit
    harsher than the human pool must come back as about half a logit harsher — that number is what
    Phase 6 exists to produce, and it is the one nobody would recompute by hand."""
    rng = random.Random(11)
    persons = {f"p{i}": rng.gauss(0, 1.2) for i in range(600)}
    obs = simulate(persons, {"human": -0.25, "model": +0.25}, [-1.5, -0.7, 0.0, 0.7, 1.5])

    ps = paired_severity(obs)
    assert ps.converged
    assert ps.harsher == "model" and ps.milder == "human"
    # Two standard errors. Unbiased over repeated draws — mean +0.497 over eight seeds at this n —
    # so a single draw is checked against its own precision rather than a hand-picked tolerance.
    assert abs(ps.logits - 0.5) < 2 * ps.se, f"recovered {ps.logits:+.3f} +/- {ps.se:.3f}"


def test_the_paired_estimator_finds_no_gap_when_there_is_none():
    rng = random.Random(13)
    persons = {f"p{i}": rng.gauss(0, 1.2) for i in range(600)}
    obs = simulate(persons, {"human": 0.0, "model": 0.0}, [-1.5, -0.7, 0.0, 0.7, 1.5])
    ps = paired_severity(obs)
    assert abs(ps.logits) < 2 * ps.se


def test_joint_estimation_inflates_the_gap_when_each_paper_has_two_ratings():
    """A measured property of JMLE, recorded so nobody reads `fit().severity_gap` off a two-rater
    design and believes it. Simulated with a true gap of 0.5: JMLE returns ~0.86 with two raters,
    ~0.46 with four, ~0.46 with eight. The scale stretches because every paper measure is fitted
    to two observations and absorbs their noise.

    Two raters is exactly this project's design — one human pool, one model configuration — which
    is why `paired_severity` exists, and why this test records the inflation rather than a
    tolerance being widened until JMLE passed.
    """
    rng = random.Random(11)
    persons = {f"p{i}": rng.gauss(0, 1.2) for i in range(600)}
    thresholds = [-1.5, -0.7, 0.0, 0.7, 1.5]

    two = fit(simulate(persons, {"human": -0.25, "model": +0.25}, thresholds))
    four = fit(simulate(persons, {"human": -0.25, "model": +0.25, "x": 0.0, "y": 0.0},
                        thresholds))

    assert two.severity_gap("model", "human") > 0.75, "the documented inflation is gone"
    assert abs(four.severity_gap("model", "human") - 0.5) < 0.15, "four raters should recover"


def test_papers_both_raters_agreed_on_carry_no_information():
    """If both raters gave the same category the conditional distribution is symmetric and says
    nothing about which is harsher. Counted out of `n`, so the reported sample size is the number
    of papers that actually informed the estimate rather than the number that were scored."""
    rng = random.Random(29)
    persons = {f"p{i}": rng.gauss(0, 1.2) for i in range(300)}
    obs = simulate(persons, {"human": 0.0, "model": 0.4}, [-1.4, -0.5, 0.5, 1.4])
    ps = paired_severity(obs)
    assert 0 < ps.n < 300


def test_the_contrast_is_all_there_is_with_two_raters():
    """"The model is harsh" and "the humans are lenient" are the same statement when there is no
    external anchor. `paired_severity` reports a contrast and names which side; it does not
    pretend to an absolute."""
    rng = random.Random(37)
    persons = {f"p{i}": rng.gauss(0, 1.0) for i in range(400)}
    a = paired_severity(simulate(persons, {"human": 0.0, "model": 0.5}, [-1.2, 0.0, 1.2]))
    b = paired_severity(simulate(persons, {"human": -0.5, "model": 0.0}, [-1.2, 0.0, 1.2]))
    assert abs(a.logits - b.logits) < 2 * (a.se + b.se)
    assert a.harsher == b.harsher == "model"


def test_the_recovered_gap_does_not_depend_on_paper_quality():
    """The separation the whole model exists for. Shift every paper up a logit and the severity
    difference must not move — otherwise 'harsh' and 'faced easier papers' are confounded, which
    is precisely what raw agreement cannot tell apart."""
    rng = random.Random(31)
    base = {f"p{i}": rng.gauss(0, 1.0) for i in range(500)}
    thresholds = [-1.3, -0.4, 0.4, 1.3]
    truth = {"human": -0.3, "model": 0.3}

    low = fit(simulate(base, truth, thresholds, seed=5)).severity_gap("model", "human")
    high = fit(simulate({k: v + 1.0 for k, v in base.items()}, truth, thresholds,
                        seed=5)).severity_gap("model", "human")
    assert abs(low - high) < 0.2, f"gap moved with paper quality: {low:+.3f} vs {high:+.3f}"


def test_person_measures_track_the_truth():
    """Weakly — two ratings each is not much information, which is why `person_note` says so. The
    correlation should still be strong; if it is not, the persons facet is not being fitted."""
    rng = random.Random(41)
    persons = {f"p{i}": rng.gauss(0, 1.5) for i in range(400)}
    obs = simulate(persons, {"human": 0.0, "model": 0.0}, [-1.5, -0.5, 0.5, 1.5])
    f = fit(obs)

    pairs = [(persons[p], e.measure) for p, e in f.persons.items() if not e.extreme]
    mx = sum(a for a, _ in pairs) / len(pairs)
    my = sum(b for _, b in pairs) / len(pairs)
    cov = sum((a - mx) * (b - my) for a, b in pairs)
    sx = math.sqrt(sum((a - mx) ** 2 for a, _ in pairs))
    sy = math.sqrt(sum((b - my) ** 2 for _, b in pairs))
    assert cov / (sx * sy) > 0.7


# ------------------------------------------------------------------ fit statistics

def test_a_consistent_rater_fits_and_an_erratic_one_does_not():
    """The failure agreement statistics hide. A rater who agrees on average while disagreeing
    unpredictably is more dangerous than one who is simply harsh, and only fit separates them."""
    rng = random.Random(53)
    persons = {f"p{i}": rng.gauss(0, 1.2) for i in range(400)}
    obs = simulate(persons, {"human": 0.0, "steady": 0.0}, [-1.4, -0.5, 0.5, 1.4])

    # A third rater who ignores the paper entirely and rates at random.
    noise = random.Random(59)
    obs += [Observation(person=p, rater="erratic", category=noise.randint(0, 4))
            for p in persons]

    f = fit(obs)
    assert f.raters["steady"].outfit < 1.2
    # Measured at ~1.39 with three raters. Not higher because each paper measure is fitted to
    # three observations and partly absorbs the noise — the same mechanism that inflates the
    # severity gap above. Linacre reads >1.5 as unproductive and >2.0 as distorting; what matters
    # here is that the erratic rater separates clearly from the steady one.
    assert f.raters["erratic"].outfit > 1.3, f.raters["erratic"].outfit
    assert f.raters["erratic"].outfit > 1.15 * f.raters["steady"].outfit
    # And severity does NOT catch it: the erratic rater is unbiased on average. That is the
    # failure agreement statistics hide, and fit is the only thing here that sees it.
    assert abs(f.severity_gap("erratic", "steady")) < 0.4


def test_every_element_reports_a_standard_error():
    obs = simulate({f"p{i}": 0.0 for i in range(60)}, {"a": 0.0, "b": 0.3}, [-1.0, 0.0, 1.0])
    f = fit(obs)
    assert all(e.se > 0 for e in f.raters.values())
    # A rater with hundreds of observations is estimated far more precisely than a paper with two.
    assert max(e.se for e in f.raters.values()) < min(
        e.se for e in f.persons.values() if not e.extreme)


# ------------------------------------------------------------------ what it refuses

def test_a_disconnected_design_raises_rather_than_returning_numbers():
    """Two raters who never rate the same papers sit on two floating scales, and the difference
    between their severities is an artefact of which papers each saw. The numbers look entirely
    ordinary, which is why this raises instead of returning them."""
    obs = ([Observation(f"p{i}", "a", 2) for i in range(10)]
           + [Observation(f"q{i}", "b", 3) for i in range(10)])
    assert not connected(obs)
    with pytest.raises(NotConnected, match="artefact"):
        fit(obs)


def test_a_fully_crossed_design_is_connected():
    obs = [Observation(f"p{i}", r, 2) for i in range(5) for r in ("a", "b")]
    assert connected(obs)


def test_an_extreme_person_is_excluded_and_named():
    """A paper rated at the ceiling by everyone has an infinite measure in this model. Assigning
    it a large finite number would look like a measurement."""
    obs = ([Observation("top", r, 4) for r in ("a", "b")]
           + [Observation(f"p{i}", r, (i % 4) + 1) for i in range(80) for r in ("a", "b")])
    f = fit(obs, max_category=4)
    assert "top" in f.excluded
    assert f.persons["top"].extreme and math.isnan(f.persons["top"].measure)


def test_the_person_note_warns_about_precision():
    obs = simulate({f"p{i}": 0.0 for i in range(50)}, {"a": 0.0, "b": 0.0}, [-1.0, 0.0, 1.0])
    note = fit(obs).person_note
    assert "imprecise" in note and "standard errors" in note


# ------------------------------------------------------------------ bias, conditional on quality

def test_bias_finds_a_rater_who_is_harsher_on_one_group():
    """The fairness analysis. A rater who marks one group down at equal paper quality shows up
    here as a positive interaction, and nowhere else."""
    rng = random.Random(67)
    persons = {f"p{i}": rng.gauss(0, 1.0) for i in range(500)}
    groups = {p: ("ell" if i % 2 else "not") for i, p in enumerate(persons)}

    # A fair rater, and one who is 0.8 logits harsher on the `ell` group only.
    obs = simulate(persons, {"human": 0.0}, [-1.3, -0.4, 0.4, 1.3], seed=71)
    obs += simulate({p: v - (0.8 if groups[p] == "ell" else 0.0) for p, v in persons.items()},
                    {"model": 0.0}, [-1.3, -0.4, 0.4, 1.3], seed=73)

    f = fit(obs)
    found = {(b.rater, b.group): b for b in bias(obs, groups, f)}
    assert found[("model", "ell")].logits > 0.3
    assert found[("model", "ell")].t > 2
    assert found[("model", "ell")].direction == "harsher"

    # The human shows the MIRROR of it, at about the same size, and that is not a second finding.
    # With two raters each paper measure is fitted to both, so one rater's bias drags the estimate
    # down and the other then looks lenient against it. Only the CONTRAST is identifiable. The
    # first version of this test expected the human to sit at zero and was wrong about the model,
    # not about the code.
    assert found[("human", "ell")].logits < -0.3
    assert abs(found[("model", "ell")].logits + found[("human", "ell")].logits) < 0.25


def test_bias_is_conditional_on_paper_quality():
    """In PERSUADE, ELL papers concentrate at scores 1–3 and non-ELL at 3–5. An unconditional
    comparison would measure that population difference and report it as model bias. Here both
    raters behave identically and one group genuinely writes less well — the interaction must be
    ~zero for both."""
    rng = random.Random(83)
    persons = {}
    groups = {}
    for i in range(500):
        g = "ell" if i % 2 else "not"
        persons[f"p{i}"] = rng.gauss(-0.9 if g == "ell" else 0.6, 0.8)
        groups[f"p{i}"] = g

    obs = simulate(persons, {"human": 0.0, "model": 0.0}, [-1.3, -0.4, 0.4, 1.3], seed=89)
    f = fit(obs)
    for b in bias(obs, groups, f):
        assert abs(b.logits) < 0.3, f"{b.rater}/{b.group} = {b.logits:+.3f} from ability alone"


def test_an_unlabelled_paper_is_not_a_group():
    """5% of PERSUADE has no ELL status. Bucketing those together would invent a subgroup and
    then publish a fairness finding about it."""
    rng = random.Random(97)
    persons = {f"p{i}": rng.gauss(0, 1.0) for i in range(200)}
    groups = {p: "ell" for i, p in enumerate(persons) if i % 2}   # the rest unlabelled
    obs = simulate(persons, {"human": 0.0, "model": 0.0}, [-1.2, 0.0, 1.2])

    found = bias(obs, groups, fit(obs))
    assert {b.group for b in found} == {"ell"}
    assert all(b.n <= 100 for b in found)


def test_the_harsher_rater_is_named_correctly_in_both_directions():
    """A sign error here inverts a fairness finding while leaving the magnitude right, so nothing
    looks wrong. The first version of `paired_severity` had exactly that: it would have reported a
    harsh model as lenient, with a plausible number attached."""
    rng = random.Random(101)
    persons = {f"p{i}": rng.gauss(0, 1.2) for i in range(400)}
    thresholds = [-1.3, -0.4, 0.4, 1.3]

    model_harsh = paired_severity(
        simulate(persons, {"human": 0.0, "model": 0.6}, thresholds))
    human_harsh = paired_severity(
        simulate(persons, {"human": 0.6, "model": 0.0}, thresholds))

    assert model_harsh.harsher == "model" and model_harsh.milder == "human"
    assert human_harsh.harsher == "human" and human_harsh.milder == "model"
    assert model_harsh.logits > 0 and human_harsh.logits > 0
