"""The five stop conditions, and the rule that makes them gates rather than a report.

"Five results would mean the system should stop releasing scores to students while they are true.
None is a reason to abandon the approach; each needs a threshold agreed in advance and a grader
that enforces it, because a result without a prior commitment gets explained rather than acted
on."

The pre-commitment half is the part that is easy to build and easy to quietly not build, so it
comes first here.
"""
from __future__ import annotations

from evals.stop_conditions import (CONDITIONS, HOLDS, INSUFFICIENT, PROPOSED, TRIGGERED,
                                   UNCOMMITTED, Threshold, abstention_subgroup,
                                   cohort_invariance, evaluate, matched_pairs,
                                   severity_uniformity, teacher_acceptance)

AGREED = Threshold(0.0, agreed_by="Tim Kinkead", agreed_on="2026-09-07",
                   rationale="test fixture")


# ------------------------------------------------------------------ pre-commitment

def test_an_uncommitted_threshold_cannot_stop_a_release():
    """The whole design. A number nobody agreed to in advance is a number somebody will explain
    after the fact, which is the failure this module exists to prevent."""
    proposed_only = Threshold(0.0)
    f = matched_pairs([{"pair_id": "p1", "node_id": "n1", "clean": 3, "errored": 2}],
                      proposed_only)
    assert f.verdict == UNCOMMITTED
    assert not f.stops_release


def test_an_uncommitted_threshold_still_reports_the_number():
    """Measure, THEN decide who may act on it. Suppressing the measurement too would withhold
    exactly the number a person needs in order to agree a threshold."""
    f = matched_pairs([{"pair_id": "p1", "node_id": "n1", "clean": 3, "errored": 2}],
                      Threshold(0.0))
    assert f.observed == 1.0
    assert "would exceed" in f.detail


def test_a_committed_threshold_gates():
    f = matched_pairs([{"pair_id": "p1", "node_id": "n1", "clean": 3, "errored": 2}], AGREED)
    assert f.verdict == TRIGGERED and f.stops_release


def test_a_threshold_needs_both_a_name_and_a_date():
    """Either alone is not a commitment: a number with a name and no date cannot be shown to
    predate the result, and a date with no name has nobody behind it."""
    assert not Threshold(0.0, agreed_by="Tim").committed
    assert not Threshold(0.0, agreed_on="2026-09-07").committed
    assert Threshold(0.0, agreed_by="Tim", agreed_on="2026-09-07").committed


def test_every_proposed_threshold_ships_uncommitted():
    """Defaults here are proposals with a place to sign, not settings. If any of these ever ships
    pre-agreed, the module has started choosing thresholds on somebody's behalf."""
    for name, t in PROPOSED.items():
        assert not t.committed, f"{name} ships already agreed to"
        assert t.rationale, f"{name} proposes a number with no argument for it"


def test_every_condition_has_a_proposed_threshold():
    assert set(PROPOSED) == set(CONDITIONS)


# ------------------------------------------------------------------ not tested is not passed

def test_no_data_is_insufficient_rather_than_holding():
    """"We did not test this" and "this held" are the two answers a report like this is most often
    read as interchangeable."""
    for f in (cohort_invariance([], AGREED), matched_pairs([], AGREED),
              severity_uniformity([], AGREED), teacher_acceptance([], AGREED)):
        assert f.verdict == INSUFFICIENT
        assert not f.stops_release
        assert "not a pass" in f.detail


def test_the_summary_separates_held_from_untested():
    data = {"matched_pairs": [{"pair_id": "p", "node_id": "n", "clean": 3, "errored": 3}]}
    out = evaluate(data, {"matched_pairs": AGREED})
    assert out["held"] == ["matched_pairs"]
    assert set(out["not_run"]) == set(CONDITIONS) - {"matched_pairs"}
    assert not out["stop_release"]


def test_a_single_triggered_condition_stops_the_release():
    data = {"matched_pairs": [{"pair_id": "p", "node_id": "n", "clean": 3, "errored": 1}]}
    out = evaluate(data, {"matched_pairs": AGREED})
    assert out["stop_release"] and out["triggered"] == ["matched_pairs"]


# ------------------------------------------------------------------ 1. cohort invariance

def test_a_paper_that_scores_the_same_in_two_cohorts_holds():
    arms = [{"artifact_key": "a1", "node_id": "n1", "cohort": "A", "level": 3},
            {"artifact_key": "a1", "node_id": "n1", "cohort": "B", "level": 3}]
    assert cohort_invariance(arms, AGREED).verdict == HOLDS


def test_a_paper_that_moves_with_its_cohort_triggers():
    """Nothing shows the scorer another student's work, so movement means an isolation guarantee
    is leaking through a path none of the architectural precautions can see."""
    arms = [{"artifact_key": "a1", "node_id": "n1", "cohort": "A", "level": 3},
            {"artifact_key": "a1", "node_id": "n1", "cohort": "B", "level": 2}]
    f = cohort_invariance(arms, AGREED)
    assert f.verdict == TRIGGERED and f.observed == 1


def test_one_cohort_only_is_not_a_pass():
    arms = [{"artifact_key": "a1", "node_id": "n1", "cohort": "A", "level": 3}]
    f = cohort_invariance(arms, AGREED)
    assert f.verdict == INSUFFICIENT
    assert "not a pass" in f.detail


# ------------------------------------------------------------------ 2. matched pairs

def test_conventions_errors_must_move_nothing():
    pairs = [{"pair_id": f"p{i}", "node_id": "n1", "clean": 3, "errored": 3} for i in range(5)]
    assert matched_pairs(pairs, AGREED).verdict == HOLDS


def test_a_mean_of_zero_point_two_still_triggers_against_a_zero_threshold():
    """The expected delta is exactly zero, not small. A mean that looks tolerable can hide a few
    large movements behind many zeros, so the breakdown names the pairs that moved."""
    pairs = ([{"pair_id": f"p{i}", "node_id": "n1", "clean": 3, "errored": 3} for i in range(4)]
             + [{"pair_id": "p9", "node_id": "n1", "clean": 3, "errored": 2}])
    f = matched_pairs(pairs, AGREED)
    assert f.verdict == TRIGGERED
    assert "p9/n1" in f.breakdown


def test_the_direction_of_the_conventions_effect_is_reported():
    """A scorer marking errored prose DOWN is penalising conventions — the expected failure. One
    marking it UP is stranger and worse, and the two should not read the same in a report."""
    down = matched_pairs([{"pair_id": "p", "node_id": "n", "clean": 3, "errored": 2}], AGREED)
    up = matched_pairs([{"pair_id": "p", "node_id": "n", "clean": 2, "errored": 3}], AGREED)
    assert "direction down" in down.detail
    assert "direction up" in up.detail


# ------------------------------------------------------------------ 3. severity uniformity

def test_a_uniform_offset_is_survivable():
    """Every criterion shifted the same way still supports comparisons within a class. It is the
    SPREAD that disqualifies the trait profile, not the offset."""
    obs = [{"node_id": "n1", "model": 3, "human": 2},
           {"node_id": "n2", "model": 4, "human": 3}]
    f = severity_uniformity(obs, Threshold(0.5, agreed_by="T", agreed_on="2026-09-07"))
    assert f.verdict == HOLDS and f.observed == 0


def test_severity_that_differs_by_criterion_triggers():
    obs = [{"node_id": "n1", "model": 3, "human": 2},
           {"node_id": "n2", "model": 2, "human": 4}]
    f = severity_uniformity(obs, Threshold(0.5, agreed_by="T", agreed_on="2026-09-07"))
    assert f.verdict == TRIGGERED
    assert f.observed == 3
    assert set(f.breakdown) == {"n1", "n2"}


def test_severity_cannot_be_estimated_without_human_scores():
    """No anchor set, no severity. A number computed from the model alone would be a measurement
    of nothing wearing the name of a fairness check."""
    obs = [{"node_id": "n1", "model": 3, "human": None},
           {"node_id": "n2", "model": 2, "human": None}]
    assert severity_uniformity(obs, AGREED).verdict == INSUFFICIENT


# ------------------------------------------------------------------ 4. subgroup abstention

def _obs(group, n, abstain):
    return [{"subgroup": group, "abstained": i < abstain} for i in range(n)]


def test_an_even_abstention_rate_holds():
    obs = _obs("A", 40, 4) + _obs("B", 40, 4)
    f = abstention_subgroup(obs, Threshold(0.10, agreed_by="T", agreed_on="2026-09-07"))
    assert f.verdict == HOLDS


def test_one_subgroup_abstaining_far_more_triggers():
    obs = _obs("A", 40, 2) + _obs("B", 40, 20)
    f = abstention_subgroup(obs, Threshold(0.10, agreed_by="T", agreed_on="2026-09-07"))
    assert f.verdict == TRIGGERED
    assert f.breakdown["rates"]["B"] > f.breakdown["rates"]["A"]


def test_a_subgroup_too_small_to_measure_is_named_not_dropped():
    """A subgroup too small to measure is exactly the one most likely to be underserved. A report
    that omitted it would read as evidence of fairness."""
    obs = _obs("A", 40, 2) + _obs("B", 40, 2) + _obs("C", 3, 3)
    f = abstention_subgroup(obs, Threshold(0.10, agreed_by="T", agreed_on="2026-09-07"))
    assert f.breakdown["too_small_to_measure"] == {"C": 3}


def test_it_has_no_knob_that_makes_it_easier_to_pass():
    """The plan: "a fairness finding, and not one to be managed by lowering the threshold". The
    only parameter suppresses noise from tiny groups; it cannot move the line."""
    import inspect

    sig = inspect.signature(abstention_subgroup)
    assert set(sig.parameters) == {"observations", "t", "min_per_subgroup"}
    tight = abstention_subgroup(_obs("A", 40, 2) + _obs("B", 40, 20),
                                Threshold(0.10, agreed_by="T", agreed_on="2026-09-07"),
                                min_per_subgroup=1)
    loose = abstention_subgroup(_obs("A", 40, 2) + _obs("B", 40, 20),
                                Threshold(0.10, agreed_by="T", agreed_on="2026-09-07"),
                                min_per_subgroup=40)
    assert tight.observed == loose.observed


# ------------------------------------------------------------------ 5. teacher acceptance

def review(node, **kw):
    r = {"artifact_id": kw.pop("artifact_id", f"a-{node}"), "node_id": node,
         "overridden": False, "feedback_edited": True, "probe": False, "probe_caught": False}
    r.update(kw)
    return r


def test_review_that_varies_by_criterion_and_edits_drafts_holds():
    reviews = ([review("n1", artifact_id=f"a{i}", overridden=i % 2 == 0) for i in range(10)]
               + [review("n2", artifact_id=f"b{i}") for i in range(10)])
    f = teacher_acceptance(reviews, Threshold(0.90, agreed_by="T", agreed_on="2026-09-07"))
    assert f.verdict == HOLDS


def test_feedback_released_verbatim_at_scale_triggers():
    """A drafting model nobody edits is a drafting model nobody is checking."""
    reviews = [review("n1", artifact_id=f"a{i}", feedback_edited=False, overridden=i % 2 == 0)
               for i in range(20)]
    f = teacher_acceptance(reviews, Threshold(0.90, agreed_by="T", agreed_on="2026-09-07"))
    assert f.verdict == TRIGGERED
    assert f.breakdown["feedback_released_verbatim"] == 1.0


def test_a_missed_seeded_probe_triggers():
    """The most direct evidence available: a deliberately wrong score that got released."""
    reviews = ([review("n1", artifact_id=f"a{i}", overridden=i % 2 == 0) for i in range(10)]
               + [review("n2", artifact_id=f"p{i}", probe=True, probe_caught=False)
                  for i in range(10)])
    f = teacher_acceptance(reviews, Threshold(0.90, agreed_by="T", agreed_on="2026-09-07"))
    assert f.verdict == TRIGGERED
    assert f.breakdown["seeded_probe_miss_rate"] == 1.0


def test_absent_probes_are_named_rather_than_scored_around():
    """No probes means the strongest of the three signals was never collected, and a score
    computed from the other two would look like evidence."""
    reviews = [review("n1", artifact_id=f"a{i}", overridden=i % 2 == 0) for i in range(10)]
    f = teacher_acceptance(reviews, Threshold(0.90, agreed_by="T", agreed_on="2026-09-07"))
    assert "strongest signal is missing" in f.breakdown["seeded_probes"]


def test_the_breakdown_is_never_a_single_number():
    """A lone "acceptance score" with nothing under it is exactly the uninformative summary this
    condition exists to detect."""
    reviews = [review("n1", artifact_id=f"a{i}") for i in range(5)]
    f = teacher_acceptance(reviews, Threshold(0.90, agreed_by="T", agreed_on="2026-09-07"))
    assert "override_rate_by_criterion" in f.breakdown
    assert len(f.breakdown) >= 3


# ------------------------------------------------------------------ the findings are recorded

def test_the_threshold_is_copied_onto_the_row_not_referenced():
    """A finding records the number that was in force when it was measured. Referencing the
    current threshold instead would let somebody relax a line in January and have December's runs
    retroactively pass — the pre-commitment failure arriving through a foreign key."""
    from evals.record_stop_conditions import rows_for

    data = {"matched_pairs": [{"pair_id": "p", "node_id": "n", "clean": 3, "errored": 1}]}
    rows = rows_for("run-1", data, {"matched_pairs": AGREED})
    row = next(r for r in rows if r["condition"] == "matched_pairs")
    assert row["threshold_value"] == AGREED.value
    assert row["agreed_by"] == "Tim Kinkead" and row["agreed_on"] == "2026-09-07"
    assert row["verdict"] == TRIGGERED


def test_an_uncommitted_finding_records_with_no_signatory():
    """It still gets a row — the history of a condition nobody has agreed a threshold for is
    exactly what somebody needs in order to agree one."""
    from evals.record_stop_conditions import rows_for

    data = {"matched_pairs": [{"pair_id": "p", "node_id": "n", "clean": 3, "errored": 1}]}
    row = rows_for("run-1", data)[0]
    assert row["verdict"] == UNCOMMITTED
    assert row["agreed_by"] is None and row["agreed_on"] is None
    assert row["observed"] == 2.0   # |1 - 3|


def test_the_database_refuses_a_stop_nobody_agreed_to():
    """The pre-commitment rule in the schema, not only in Python: this module is one way to write
    that table and a script is another. Same argument as the release-authority trigger."""
    import importlib.util
    import pathlib

    spec = importlib.util.spec_from_file_location(
        "m30", pathlib.Path(__file__).resolve().parents[1]
        / "migrations" / "0030_stop_conditions.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    issued: list[str] = []
    created: list = []

    class FakeOp:
        @staticmethod
        def add_column(*a, **k): pass

        @staticmethod
        def execute(sql): issued.append(str(sql))

        @staticmethod
        def create_index(*a, **k): pass

        @staticmethod
        def create_table(name, *cols, **k): created.append((name, cols))

    m.op = FakeOp
    m.upgrade()

    checks = [str(c.sqltext) for _, cols in created for c in cols
              if hasattr(c, "sqltext")]
    # The vocabulary CHECK also contains the word, so match the constraint that CONSTRAINS it.
    stop_check = [c for c in checks if "verdict <> 'triggered'" in c]
    assert stop_check, f"no CHECK constrains a triggered verdict; saw {checks}"
    assert "agreed_by" in stop_check[0] and "agreed_on" in stop_check[0]


def test_a_finding_with_no_number_carries_no_number():
    """`insufficient` means there was nothing to measure. A row with a verdict of insufficient and
    an observed value would be a number invented by the recorder."""
    from evals.record_stop_conditions import rows_for

    row = rows_for("run-1", {"matched_pairs": []}, {"matched_pairs": AGREED})[0]
    assert row["verdict"] == INSUFFICIENT and row["observed"] is None
