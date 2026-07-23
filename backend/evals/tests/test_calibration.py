"""Calibration report tests — pure. Pin the LC-aligned metric vocabulary and the deliberate
distinction between strict verdict match (exact_match) and looser score agreement."""
from __future__ import annotations

from evals.calibration import METRICS, calibration_report, to_pair


def test_empty_sample_reports_none_not_a_crash():
    r = calibration_report([])
    assert r == {"n": 0, "exact_match": None, "expert_agreement_rate": None,
                 "reasoning_quality": None}


def test_perfect_agreement():
    pairs = [{"judge_verdict": "pass", "judge_score": 0.9, "human_verdict": "pass",
              "human_score": 0.88, "human_reasoning_quality": 1.0},
             {"judge_verdict": "fail", "judge_score": 0.2, "human_verdict": "fail",
              "human_score": 0.25, "human_reasoning_quality": 0.8}]
    r = calibration_report(pairs)
    assert r["n"] == 2
    assert r["exact_match"] == 1.0 and r["expert_agreement_rate"] == 1.0
    assert r["reasoning_quality"] == 0.9


def test_exact_match_and_agreement_are_distinct():
    # verdicts match, but the scores are far apart → exact_match counts it, agreement doesn't.
    pairs = [{"judge_verdict": "pass", "judge_score": 0.95, "human_verdict": "pass",
              "human_score": 0.62}]
    r = calibration_report(pairs, score_tol=0.1)
    assert r["exact_match"] == 1.0 and r["expert_agreement_rate"] == 0.0


def test_agreement_falls_back_to_verdict_when_scores_absent():
    pairs = [{"judge_verdict": "pass", "human_verdict": "pass"},
             {"judge_verdict": "pass", "human_verdict": "fail"}]
    r = calibration_report(pairs)
    assert r["exact_match"] == 0.5 and r["expert_agreement_rate"] == 0.5


def test_reasoning_quality_is_none_when_never_rated():
    pairs = [{"judge_verdict": "pass", "judge_score": 0.9, "human_verdict": "pass",
              "human_score": 0.9}]
    assert calibration_report(pairs)["reasoning_quality"] is None


def test_to_pair_builds_from_a_judge_result():
    jr = {"name": "usefulness_judge", "verdict": "pass", "score": 0.8}
    p = to_pair(jr, human_verdict="fail", human_score=0.4, human_reasoning_quality=0.5)
    assert p == {"judge_verdict": "pass", "judge_score": 0.8, "human_verdict": "fail",
                 "human_score": 0.4, "human_reasoning_quality": 0.5}
    assert calibration_report([p])["exact_match"] == 0.0


def test_metrics_vocabulary_is_lc_aligned():
    assert METRICS == ("exact_match", "expert_agreement_rate", "reasoning_quality")
