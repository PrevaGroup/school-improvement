"""How close our scoring is to PERSUADE's human scores, and whether the gap is even across ELL.

    python -m measurement.corpus_agreement

One command, because the alternative is writing SQL at the moment the run finishes — which is the
moment to be reading numbers rather than composing joins.

## What is a real comparison here, and what is constructed

PERSUADE gives a human HOLISTIC score per paper, 1-6. That is a rater judging the same thing our
rater judged, and the agreement statistics on it mean what they normally mean.

It does NOT give a paper-level score for the argumentation elements. What it gives is an
effectiveness rating on each annotated SPAN — a paper with three claims has three claim ratings,
often disagreeing with each other. Folding those into one number per paper is a choice somebody
makes, not a judgment a human made. So every element comparison here is against a COMPARATOR WE
BUILT, is printed under that heading, and names the choice: `--elements-from` changes the numbers,
and that it can is the point.

## Why MFRM sits beside the kappas

They answer different questions and this run needs both. Agreement says how far apart the two
raters are. Severity says whether the distance is a constant offset — uniformly harsher, which can
be corrected for — or unpredictable disagreement, which cannot. Bias asks the fairness question
properly: given two papers the model measures as equal quality, does it score the ELL one lower?
An unconditional split by ELL would mostly measure the fact that ELL papers in this corpus sit
lower on the human scale, and would report that population difference as bias.

## Reads tables, imports nothing

`measurement` depends only on `core`. Trait labels and scales come from `registry_node`, our scores
from `score_event`, the human ratings from `corpus_score` and `corpus_discourse_span` — all
table-level contracts, which is how modules integrate here.
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict

from sqlalchemy import text

from ._db import engine
from .agreement import compare, render
from .mfrm import NotConnected, Observation, bias, fit, paired_severity

TENANT = "corpus"

# The node's `external_ref`, as `registry.persuade_rubrics` writes it, to the PERSUADE
# `discourse_type` that annotates the matching spans. Matched on external_ref rather than on the
# label, because a label is prose and somebody will reword it.
_SPAN_TYPE = {
    "persuade20-element:lead": "Lead",
    "persuade20-element:position": "Position",
    "persuade20-element:claim": "Claim",
    "persuade20-element:counterclaim": "Counterclaim",
    "persuade20-element:rebuttal": "Rebuttal",
    "persuade20-element:concluding_summary": "Concluding Statement",
    "persuade20-element:evidence-independent": "Evidence",
    "persuade20-element:evidence-text_dependent": "Evidence",
}

# The word the corpus stores, to the ordered category `registry.persuade_rubrics` scores on.
_EFFECTIVENESS = {"Ineffective": 1, "Adequate": 2, "Effective": 3}

# Our scores. Superseded events are excluded by the NOT EXISTS rather than by taking the newest:
# an escalation writes a replacement and points it at what it replaced, so the chain is the record
# of which score stands. Ordering by time would also pick the right row today, and would quietly
# pick the wrong one the first time two events share a timestamp.
_OURS = text("""
    SELECT e.node_id,
           n.criterion_label,
           n.external_ref,
           n.scale_categories,
           a.student_id AS paper_id,
           e.status,
           e.level,
           e.escalation_trigger,
           p.ell_status,
           p.task_type
      FROM score_event e
      JOIN artifact      a ON a.artifact_id = e.artifact_id
      JOIN registry_node n ON n.node_id     = e.node_id
      JOIN corpus_paper  p ON p.paper_id    = a.student_id
     WHERE e.tenant_id = :tenant
       AND e.scorer_type = 'ai'
       AND (:run_id IS NULL OR e.run_id = :run_id)
       AND NOT EXISTS (SELECT 1 FROM score_event s
                        WHERE s.supersedes_event_id = e.event_id)
""")

_HUMAN_HOLISTIC = text("""
    SELECT paper_id, value FROM corpus_score WHERE kind = 'holistic'
""")

_HUMAN_SPANS = text("""
    SELECT paper_id, discourse_type, effectiveness
      FROM corpus_discourse_span
     WHERE effectiveness IS NOT NULL
""")


# ------------------------------------------------------------------ the constructed comparator

def aggregate(values: list[int], how: str) -> int | None:
    """One element's span ratings within one paper, as one number.

    `best` is the default and the argument for it is the rubric's own: the element rubric asks how
    effectively the paper uses the element, and a paper that landed one effective claim has shown
    it can. `mean` reads the same spans as repeated attempts and averages them, which penalises a
    long paper for having more chances to be mediocre. Neither is right — a human rating the paper
    against the element rubric did neither — which is why the choice is named in the output rather
    than buried here.
    """
    if not values:
        return None
    if how == "best":
        return max(values)
    if how == "worst":
        return min(values)
    if how == "mean":
        return round(statistics.mean(values))
    if how == "modal":
        # Ties go to the lower category, which `statistics.mode` decides by first occurrence;
        # sorting makes that deterministic rather than dependent on span order in the file.
        return statistics.mode(sorted(values))
    raise ValueError(f"unknown aggregation {how!r}")


# ------------------------------------------------------------------ assembly

def _human_by_trait(conn, how: str) -> tuple[dict, dict]:
    """(holistic by paper, {span type: {paper: category}}).

    Read once and indexed in memory. It is a few hundred thousand span rows, and the alternative
    is a query per trait per paper.
    """
    holistic = {r.paper_id: int(r.value) for r in conn.execute(_HUMAN_HOLISTIC)}

    spans: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for r in conn.execute(_HUMAN_SPANS):
        cat = _EFFECTIVENESS.get((r.effectiveness or "").strip())
        if cat is not None:
            spans[r.discourse_type][r.paper_id].append(cat)

    elements = {t: {p: aggregate(v, how) for p, v in papers.items()}
                for t, papers in spans.items()}
    return holistic, elements


def collect(conn, *, run_id: str | None, how: str) -> dict:
    """Everything the report needs, keyed by node. One pass over our events."""
    ours = [r._mapping for r in conn.execute(_OURS, {"tenant": TENANT, "run_id": run_id})]
    holistic, elements = _human_by_trait(conn, how)

    traits: dict[str, dict] = {}
    for r in ours:
        t = traits.setdefault(r["node_id"], {
            "label": r["criterion_label"],
            "external_ref": r["external_ref"],
            "categories": [int(c) for c in (r["scale_categories"] or [])],
            "derived": r["external_ref"] in _SPAN_TYPE,
            "pairs": [], "ell": {}, "papers": set(),
            # Counted rather than dropped in silence: a trait where a third of the papers came
            # back abstained is not a trait with good agreement on the rest.
            "scored": 0, "abstained": 0, "no_human": 0, "escalated": 0,
        })
        t["papers"].add(r["paper_id"])
        if r["escalation_trigger"]:
            t["escalated"] += 1
        if r["status"] != "scored" or r["level"] is None:
            t["abstained"] += 1
            continue
        t["scored"] += 1

        span_type = _SPAN_TYPE.get(r["external_ref"])
        theirs = (elements.get(span_type, {}).get(r["paper_id"]) if span_type
                  else holistic.get(r["paper_id"]))
        if theirs is None:
            # A paper with no annotated span of this type, or no human holistic. Not a
            # disagreement — counting it as one manufactures error out of a silence.
            t["no_human"] += 1
            continue
        t["pairs"].append((theirs, int(r["level"]), r["paper_id"]))
        if r["ell_status"]:
            t["ell"][r["paper_id"]] = r["ell_status"]
    return traits


# ------------------------------------------------------------------ measurement

def measure(t: dict) -> dict:
    """Agreement, then severity and ELL bias, for one trait."""
    pairs = [(a, b) for a, b, _ in t["pairs"]]
    out: dict = {"agreement": compare(pairs, t["categories"] or None)}

    if len(pairs) < 2:
        return out | {"severity": None, "bias": [], "why": "too few paired papers"}

    lo = min(t["categories"]) if t["categories"] else 1
    obs = []
    for theirs, ours, paper in t["pairs"]:
        obs.append(Observation(person=paper, rater="human", category=theirs - lo))
        obs.append(Observation(person=paper, rater="model", category=ours - lo))

    try:
        # Two raters on the same papers: the conditional estimator, not the joint one. JMLE with
        # two ratings per paper inflates a true half-logit gap to +0.86 — a property of the
        # design, which is exactly this design.
        out["severity"] = paired_severity(obs)
    except (NotConnected, ValueError, ZeroDivisionError) as exc:
        out["severity"], out["why"] = None, str(exc)

    out["bias"] = []
    if t["ell"]:
        try:
            # Bias needs person measures, so it needs the joint fit — and reads the interaction,
            # not the measures themselves, which is what the joint fit is bad at.
            out["bias"] = [b for b in bias(obs, t["ell"], fit(obs)) if b.rater == "model"]
        except (NotConnected, ValueError, ZeroDivisionError):
            pass
    return out


# ------------------------------------------------------------------ output

_HEADINGS = (
    ("AGAINST HUMAN SCORES", False,
     "PERSUADE's own holistic rating. A human judged the same thing we did."),
    ("AGAINST A COMPARATOR WE BUILT", True,
     "PERSUADE rates each annotated SPAN, not the paper. These fold a paper's spans into one "
     "number by `{how}`. No human made this judgment, and another choice moves the numbers."),
)


def report(traits: dict, *, how: str) -> str:
    lines: list[str] = []
    for heading, derived, note in _HEADINGS:
        group = [(k, v) for k, v in traits.items() if v["derived"] is derived]
        if not group:
            continue
        lines += ["", "=" * 78, heading, note.format(how=how), "=" * 78]
        for _, t in sorted(group, key=lambda kv: kv[1]["label"]):
            m = measure(t)
            lines += ["", render(m["agreement"], label=t["label"])]
            covered = (f"  of {len(t['papers'])} papers: {t['scored']} scored, "
                       f"{t['abstained']} abstained, {t['no_human']} with no human rating")
            if t["escalated"]:
                covered += f", {t['escalated']} escalated"
            lines.append(covered)

            s = m.get("severity")
            if s:
                lines.append(
                    f"  severity: {s.harsher} is {abs(s.logits):.2f} logits harsher than "
                    f"{s.milder} (SE {s.se:.2f}, t {s.t:+.1f}, n {s.n})")
            elif m.get("why"):
                lines.append(f"  severity: not estimated — {m['why']}")
            for b in m["bias"]:
                lines.append(
                    f"  ELL bias: on `{b.group}` we are {abs(b.logits):.2f} logits "
                    f"{b.direction} than our own average (t {b.t:+.1f}, n {b.n}) — among papers "
                    f"the model measures as equal quality")
    if not lines:
        return ("No scored corpus papers found. Either the run has not written events yet, or "
                "--run-id names a run that does not exist.")
    return "\n".join(lines)


def as_json(traits: dict, how: str) -> dict:
    out = {}
    for node_id, t in traits.items():
        m = measure(t)
        a = m["agreement"]
        s = m.get("severity")
        out[node_id] = {
            "label": t["label"], "derived_comparator": t["derived"],
            "n": a.n, "exact": a.exact, "adjacent": a.adjacent, "qwk": a.qwk,
            "linear_kappa": a.linear_kappa, "mean_signed": a.mean_signed,
            "mean_absolute": a.mean_absolute, "compressed": a.compressed,
            "spread": a.spread, "matrix": a.matrix,
            "papers": len(t["papers"]), "scored": t["scored"],
            "abstained": t["abstained"], "no_human": t["no_human"],
            "escalated": t["escalated"],
            "severity": s and {"harsher": s.harsher, "milder": s.milder, "logits": s.logits,
                               "se": s.se, "t": s.t, "n": s.n},
            "ell_bias": [{"group": b.group, "logits": b.logits, "se": b.se, "t": b.t, "n": b.n}
                         for b in m["bias"]],
        }
    return {"elements_from": how, "traits": out}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run-id", default=None, help="default: every run in the corpus tenant")
    ap.add_argument("--elements-from", default="best",
                    choices=("best", "worst", "mean", "modal"),
                    help="how a paper's span ratings become one element score (default: best)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    with engine().connect() as conn:
        conn.execute(text("SELECT set_config('app.tenant', :t, true)"), {"t": TENANT})
        traits = collect(conn, run_id=a.run_id, how=a.elements_from)

    if a.json:
        print(json.dumps(as_json(traits, a.elements_from), indent=1, default=str))
    else:
        print(report(traits, how=a.elements_from))


if __name__ == "__main__":
    main()
