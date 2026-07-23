"""Judge calibration against a human-labeled sample (eval-interoperability.md P6).

The T2 usefulness judge is an LLM; it is trustworthy only insofar as it agrees with human
experts. This turns a labeled sample into an agreement report, in the **vocabulary Learning
Commons uses** for its evaluators — so our calibration numbers are comparable to the field's,
and rubric drift is visible run-over-run (the design's §4 calibration step):

- **exact_match** — fraction where the judge's discrete verdict equals the human's (strict
  categorical match; LC's "overall accuracy / exact match").
- **expert_agreement_rate** — fraction where the judge's *score* is within `score_tol` of the
  human's (a looser numeric agreement, deliberately distinct from strict verdict match). With no
  numeric human score, it falls back to verdict equality for that pair.
- **reasoning_quality** — mean human rating (0..1) of the judge's rationale, where provided
  (`None` if no rationale was rated).

Pure and unit-tested. A periodic calibration step (or `run_evals`) supplies the pairs: a human
labels a sample of eval turns, and this reports agreement to attach to a run.
"""
from __future__ import annotations

from typing import Iterable

# The metric names, aligned to Learning Commons' evaluator reporting. Kept as a tuple so a caller
# (a report writer, a dashboard) can iterate them without hard-coding strings.
METRICS = ("exact_match", "expert_agreement_rate", "reasoning_quality")


def to_pair(judge_result: dict, *, human_verdict: str, human_score: float | None = None,
            human_reasoning_quality: float | None = None) -> dict:
    """Build one calibration pair from a judge `GraderResult.to_dict()` + a human label."""
    return {
        "judge_verdict": judge_result.get("verdict"),
        "judge_score": judge_result.get("score"),
        "human_verdict": human_verdict,
        "human_score": human_score,
        "human_reasoning_quality": human_reasoning_quality,
    }


def calibration_report(pairs: Iterable[dict], *, score_tol: float = 0.1) -> dict:
    """Judge-vs-human agreement over a labeled sample, in LC's metric vocabulary.

    Each pair: `{judge_verdict, judge_score, human_verdict, human_score,
    human_reasoning_quality?}`. Empty input yields `None`s (and `n=0`), never a divide-by-zero —
    an un-calibrated judge reports honestly rather than 100%."""
    pairs = list(pairs)
    n = len(pairs)
    if not n:
        return {"n": 0, "exact_match": None, "expert_agreement_rate": None,
                "reasoning_quality": None}
    exact = agree = 0
    rq: list[float] = []
    for p in pairs:
        jv, hv = p.get("judge_verdict"), p.get("human_verdict")
        verdicts_match = jv is not None and hv is not None and jv == hv
        if verdicts_match:
            exact += 1
        js, hs = p.get("judge_score"), p.get("human_score")
        if js is not None and hs is not None:
            if abs(float(js) - float(hs)) <= score_tol:
                agree += 1
        elif verdicts_match:                              # no numeric scores → verdict agreement
            agree += 1
        hq = p.get("human_reasoning_quality")
        if hq is not None:
            rq.append(float(hq))
    return {
        "n": n,
        "exact_match": round(exact / n, 3),
        "expert_agreement_rate": round(agree / n, 3),
        "reasoning_quality": round(sum(rq) / len(rq), 3) if rq else None,
    }
