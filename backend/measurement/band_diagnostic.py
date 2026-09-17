"""Why the model never awards a 6 — and whether the decision rule is what stops it.

    python -m measurement.band_diagnostic

`span_diagnostic` asked which STAGE loses the signal and answered stage D: verified evidence
rises monotonically with the human score, and in 9 of 10 traits predicts the human score better
than our own score does. Migration 0038 acted on that by changing the QUESTION — `cumulative`
asks one call per band instead of asking for a band, so there is no middle to retreat to.

It worked on ordering and not on spread. Across 171 independent papers `cumulative` moved r from
0.606 to 0.661 and SD from 0.78 to 0.81, against a human SD of 1.30 — and awarded, as `category`
did before it, ZERO 6s.

This module asks the question that separates the two remaining explanations, and they need
different fixes:

    THE DECISION RULE IS THE PROBLEM. P(>=6) is materially higher for the papers humans scored 6
    than for the rest — the model can see the top band — but never clears 0.5, so `level_from`
    discards it. Then fitting the threshold, or scoring the expectation instead of walking a
    ladder, awards 6s from data already in the database. No re-scoring.

    THE MODEL CANNOT SEE THE TOP BAND. P(>=6) is flat near zero for every paper, including the
    ones humans scored 6. Then no threshold recovers anything, because there is nothing to
    re-cut, and the work is exemplars in the stage-D prompt and the band-6 descriptor itself.

## The ladder still categorises

`cumulative` removed the single "name a band" call and kept a hard threshold per rung. A paper at
P(>=6) = 0.35 contributes nothing: `level_from` stops at the first rung under the threshold and
the magnitude is dropped. That is the same loss 0038 set out to remove, one step later — which is
the most likely reason changing the question moved r and not SD.

So the third column of the report is `E = 1 + sum P(>=k)`, the expected score implied by the same
probabilities. It spans 1..6 by construction and spends every band's magnitude rather than
testing it against a cliff.

## Why this costs nothing

`scoring.score` writes the whole stage-D result into `score_event.evidence`: `bands` (the
per-band probabilities), `threshold`, `decided_at`, `decided_p` and `monotonicity_violations`.
Every number here was persisted when the wave ran. No model is called.

## Only `cumulative` raters have bands

A `category` configuration names a band in one call and stores no probabilities, so it is
excluded rather than reported as empty — a rater with no bands is not a rater whose bands are
flat, and the two must not print the same way.
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict

from sqlalchemy import text

from ._db import engine
from .agreement import compare

TENANT = "corpus"

# One row per (paper, node) scored by a CUMULATIVE rater, with the human holistic beside it.
# Superseded events are excluded the same way `corpus_agreement` excludes them — by the absence
# of a successor, not by timestamp, because two events can share a timestamp.
_ROWS = text("""
    SELECT a.student_id      AS paper_id,
           n.criterion_label AS trait,
           n.external_ref,
           n.scale_categories,
           e.status,
           e.level           AS ours,
           e.evidence,
           c.config_key,
           c.level_method,
           p.task_type,
           h.value           AS human
      FROM score_event e
      JOIN artifact      a ON a.artifact_id = e.artifact_id
      JOIN registry_node n ON n.node_id     = e.node_id
      JOIN corpus_paper  p ON p.paper_id    = a.student_id
      JOIN corpus_score  h ON h.paper_id    = a.student_id AND h.kind = 'holistic'
      JOIN registry_scoring_configuration c
             ON c.config_id = e.scoring_configuration_id
     WHERE e.tenant_id    = :tenant
       AND e.scorer_type  = 'ai'
       AND c.level_method = 'cumulative'
       AND NOT EXISTS (SELECT 1 FROM score_event s
                        WHERE s.supersedes_event_id = e.event_id)
""")


# ------------------------------------------------------------------ parsing


def bands_of(evidence) -> dict:
    """The stage-D probabilities for one event, as {band: p}.

    Keys are written by `scoring.score` as strings through `_fmt`, so they arrive as "2".."6"
    and are floated here. An event with no `bands` returns {} — that is a `category` row that
    slipped the filter, or a stage D that never ran, and both must be counted as absent rather
    than as zeros. A zero is an answer; this is the absence of one.

    `measurement` may not import `scoring`, so this shape is a table-level contract. It is
    pinned by `tests/test_band_shape_agrees.py` against the real producer — the same protection
    `span_text` needed after reading the wrong key and printing a clean, false finding.
    """
    ev = evidence if isinstance(evidence, dict) else json.loads(evidence or "{}")
    raw = ev.get("bands") or {}
    out = {}
    for k, v in raw.items():
        try:
            out[float(k)] = float(v)
        except (TypeError, ValueError):
            continue
    return out


def facts_of(evidence) -> dict:
    """The rest of what stage D recorded about its own decision."""
    ev = evidence if isinstance(evidence, dict) else json.loads(evidence or "{}")
    return {"threshold": ev.get("threshold"),
            "decided_at": ev.get("decided_at"),
            "decided_p": ev.get("decided_p"),
            "violations": int(ev.get("monotonicity_violations") or 0)}


# ------------------------------------------------------------------ the two rules


def level_at(bands: dict, cats: list[float], threshold: float) -> float:
    """The ladder rule at an arbitrary threshold.

    Deliberately a re-implementation of `scoring.score.level_from`'s decision and not a call to
    it: `measurement` may not import `scoring`, and sweeping a threshold is a question about
    what WOULD have happened, which is this module's job rather than the pipeline's.

    The ladder is the point — the highest band whose whole ladder was climbed, so a confident
    stray answer at 6 under a failing 4 still promotes nothing.
    """
    level = cats[0]
    for c in cats[1:]:
        p = bands.get(c)
        if p is None or p < threshold:
            break
        level = c
    return level


def expected(bands: dict, cats: list[float]) -> float:
    """E[score] = 1 + sum P(>=k), the expectation implied by the same probabilities.

    The identity for a positive integer score: its expectation is the sum of its survival
    probabilities. It spans the full range by construction — all zeros gives the floor, all ones
    the ceiling — and, unlike the ladder, a band at 0.35 contributes 0.35 instead of nothing.

    Non-monotone probabilities do not break it. They make it a weighted average of contradictory
    answers rather than of coherent ones, which is why `violations` is reported beside it.
    """
    return cats[0] + sum(bands.get(c, 0.0) for c in cats[1:])


# ------------------------------------------------------------------ analysis


def _mean(xs) -> float:
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def separation(rows: list[dict]) -> dict:
    """Mean P(>=k) by human score — the table the whole question turns on.

    Read DOWN a column. Rising means the model discriminates at that band and the threshold is
    merely in the wrong place. Flat means it does not, and no threshold helps.
    """
    cats = rows[0]["cats"] if rows else []
    by_human: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        by_human[int(r["human"])].append(r)

    out = {}
    for h in sorted(by_human):
        rs = by_human[h]
        out[h] = {"papers": len(rs),
                  "bands": {c: _mean(r["bands"].get(c, 0.0) for r in rs) for c in cats[1:]},
                  "ours": _mean(r["ours"] for r in rs if r["ours"] is not None),
                  "expected": _mean(r["expected"] for r in rs)}
    return out


def top_band_signal(rows: list[dict]) -> dict:
    """Does P(>=top) tell the papers humans put at the top apart from the rest?

    A difference of means with its pooled spread, rather than a correlation: the question is not
    whether P(>=6) trends, it is whether the 25 papers a human called 6 are distinguishable at
    all. `d` is Cohen's d — a value near zero is the "cannot see the top band" verdict, and the
    threshold sweep below will then have nothing to find.
    """
    if not rows:
        return {}
    cats = rows[0]["cats"]
    top = cats[-1]
    hi = [r["bands"].get(top, 0.0) for r in rows if int(r["human"]) == int(top)]
    lo = [r["bands"].get(top, 0.0) for r in rows if int(r["human"]) < int(top)]
    if len(hi) < 2 or len(lo) < 2:
        return {"band": top, "n_top": len(hi), "verdict": "too few papers at the top band"}
    s_hi, s_lo = statistics.pstdev(hi), statistics.pstdev(lo)
    pooled = (((len(hi) - 1) * s_hi ** 2 + (len(lo) - 1) * s_lo ** 2)
              / max(1, len(hi) + len(lo) - 2)) ** 0.5
    gap = _mean(hi) - _mean(lo)
    if pooled:
        d = gap / pooled
    elif abs(gap) < 1e-9:
        # No variance and no gap: every paper carries the SAME top-band probability, whatever a
        # human thought of it. That is the flattest possible column and the strongest form of
        # "the model cannot see this band" — a finding, so it must report as 0.0 and reach the
        # verdict, not as nan and fall through to INCONCLUSIVE.
        #
        # Deliberately unlike `span_diagnostic._pearson`, which returns nan when a variable
        # never varies. There the constant is one side of a correlation and no question was
        # asked; here the constant IS the answer to the question asked.
        d = 0.0
    else:
        # No overlap at all: the groups are constant and different. Separation without bound.
        d = float("inf")
    return {"band": top, "n_top": len(hi), "n_rest": len(lo),
            "mean_top": _mean(hi), "mean_rest": _mean(lo),
            "max_seen": max(hi + lo), "d": d}


def sweep(rows: list[dict], steps: int = 19) -> list[dict]:
    """What every threshold from 0.05 to 0.95 would have produced.

    Reported with the resulting QWK *and* the count at the top band, because they are different
    questions and a threshold can improve one while leaving the other at zero. A rule that raises
    agreement and still never awards a 6 has not solved the problem in front of us.
    """
    if not rows:
        return []
    cats = rows[0]["cats"]
    out = []
    for i in range(1, steps + 1):
        t = i / (steps + 1)
        levels = [level_at(r["bands"], cats, t) for r in rows]
        pairs = [(int(r["human"]), int(l)) for r, l in zip(rows, levels)]
        a = compare(pairs, [int(c) for c in cats])
        out.append({"threshold": round(t, 3), "qwk": a.qwk, "exact": a.exact,
                    "mean": _mean(levels), "sd": statistics.pstdev(levels),
                    "at_top": sum(1 for l in levels if l == cats[-1]),
                    "dist": {int(c): sum(1 for l in levels if l == c) for c in cats}})
    return out


def expectation_rule(rows: list[dict]) -> dict:
    """The expected score, as a continuous measure and as a rounded band."""
    if not rows:
        return {}
    cats = rows[0]["cats"]
    e = [r["expected"] for r in rows]
    rounded = [min(cats[-1], max(cats[0], round(v))) for v in e]
    pairs = [(int(r["human"]), int(v)) for r, v in zip(rows, rounded)]
    a = compare(pairs, [int(c) for c in cats])
    human = [float(r["human"]) for r in rows]
    return {"continuous_mean": _mean(e), "continuous_sd": statistics.pstdev(e),
            "human_sd": statistics.pstdev(human),
            "qwk": a.qwk, "exact": a.exact, "mean_signed": a.mean_signed,
            "at_top": sum(1 for v in rounded if v == cats[-1]),
            "dist": {int(c): sum(1 for v in rounded if v == c) for c in cats}}


def analyse(rows: list[dict]) -> dict:
    best = max(sweep(rows), key=lambda s: s["qwk"], default=None)
    top = top_band_signal(rows)
    d = top.get("d")
    if d is None or d != d:
        verdict = "INCONCLUSIVE — not enough papers at the top band to ask the question."
    elif d >= 0.5 and best and best["at_top"] > 0:
        verdict = ("READS AS THE DECISION RULE. The model separates the top-band papers and the "
                   "threshold discards it. A fitted threshold awards them from stored data.")
    elif d >= 0.5:
        verdict = ("READS AS PARTIAL. The top band is separated but no threshold in the sweep "
                   "awards it — the probabilities are ordered and too flat to cross any cut. "
                   "The expectation rule is the one to look at.")
    else:
        verdict = ("READS AS THE MODEL. P(>=top) does not distinguish the papers humans put at "
                   "the top, so no threshold recovers them. Exemplars and the top-band "
                   "descriptor are the work, and they cost a scoring run.")
    return {"n": len(rows), "verdict": verdict, "top_band": top,
            "best_threshold": best, "expectation": expectation_rule(rows),
            "violations": sum(r["violations"] for r in rows)}


# ------------------------------------------------------------------ assembly


def collect(conn) -> dict:
    """Rows grouped by (rater, trait, task_type) — never pooled.

    Pooling two raters into one set of statistics is the error #138 fixed in `corpus_agreement`,
    and the two holistic nodes are separate nodes with different human distributions. Anything
    that merges them describes neither.
    """
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in conn.execute(_ROWS, {"tenant": TENANT}).mappings():
        b = bands_of(r["evidence"])
        if not b:
            continue
        cats = sorted(float(c) for c in (r["scale_categories"] or []))
        if len(cats) < 2:
            continue
        f = facts_of(r["evidence"])
        key = (f"{r['config_key']} ({r['level_method']})", r["trait"])
        groups[key].append({
            "paper": r["paper_id"], "human": float(r["human"]),
            "ours": None if r["ours"] is None else float(r["ours"]),
            "status": r["status"], "bands": b, "cats": cats,
            "expected": expected(b, cats), "violations": f["violations"],
            "threshold_used": f["threshold"],
        })
    return dict(groups)


def render(groups: dict) -> str:
    out: list[str] = []
    for (rater, trait), rows in sorted(groups.items()):
        scored = [r for r in rows if r["status"] == "scored" and r["human"] is not None]
        out += ["", "#" * 78, f"# {rater} — {trait}", "#" * 78, ""]
        if len(scored) < 5:
            out.append(f"  only {len(scored)} scored papers with a human rating — skipped")
            continue
        a = analyse(scored)
        cats = scored[0]["cats"]

        out += [f"  n={a['n']}   monotonicity violations: {a['violations']}", "", "  " + a["verdict"], ""]

        t = a["top_band"]
        if "mean_top" in t:
            out += [f"  P(>={int(t['band'])}) for the {t['n_top']} papers humans put there: "
                    f"{t['mean_top']:.3f}",
                    f"  P(>={int(t['band'])}) for the other {t['n_rest']}:"
                    f"{'':17s}{t['mean_rest']:.3f}",
                    f"  Cohen's d {t['d']:+.2f}   highest P(>={int(t['band'])}) seen anywhere: "
                    f"{t['max_seen']:.3f}", ""]

        out += ["  MEAN P(>=band) BY HUMAN SCORE", "  " + "-" * 74,
                "  human  papers " + "".join(f"  P>={int(c):<4d}" for c in cats[1:])
                + "    ours  E[score]"]
        for h, b in separation(scored).items():
            ours = "  --  " if b["ours"] != b["ours"] else f"{b['ours']:6.2f}"
            out.append(f"  {h:>5}  {b['papers']:>6} "
                       + "".join(f"  {b['bands'][c]:7.3f}" for c in cats[1:])
                       + f"  {ours}  {b['expected']:8.2f}")
        out += ["", "  Rising down a column is discrimination the threshold is throwing away.",
                "  Flat near zero in the last column is a band the model cannot see.", ""]

        out += ["  THRESHOLD SWEEP", "  " + "-" * 74,
                "  thresh     QWK   exact    mean     SD   at top   distribution"]
        for s in sweep(scored):
            dist = " ".join(f"{s['dist'].get(int(c), 0):>4}" for c in cats)
            mark = "  <-- best" if a["best_threshold"] and \
                s["threshold"] == a["best_threshold"]["threshold"] else ""
            out.append(f"  {s['threshold']:6.3f}  {s['qwk']:6.3f}  {s['exact']:5.1%}  "
                       f"{s['mean']:6.2f} {s['sd']:6.2f}   {s['at_top']:>6}   {dist}{mark}")

        e = a["expectation"]
        out += ["", "  EXPECTATION RULE  (E = 1 + sum P(>=k), no threshold at all)", "  " + "-" * 74,
                f"  continuous: mean {e['continuous_mean']:.2f}  SD {e['continuous_sd']:.2f}"
                f"   (human SD {e['human_sd']:.2f})",
                f"  rounded:    QWK {e['qwk']:.3f}   exact {e['exact']:.1%}   "
                f"signed {e['mean_signed']:+.2f}   at top: {e['at_top']}",
                "  distribution: " + " ".join(f"{int(c)}:{e['dist'].get(int(c), 0)}" for c in cats),
                ""]
    return "\n".join(out) if out else "no cumulative-rater rows with stored bands"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    with engine().connect() as conn:
        conn.execute(text("SELECT set_config('app.tenant', :t, true)"), {"t": TENANT})
        groups = collect(conn)

    if a.json:
        print(json.dumps({f"{r} | {t}": analyse([x for x in rows if x["status"] == "scored"])
                          for (r, t), rows in groups.items()}, indent=1, default=str))
    else:
        print(render(groups))


if __name__ == "__main__":
    main()
