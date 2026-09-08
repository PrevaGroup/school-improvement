"""Where does the compression come from — the evidence stage, or the level stage?

    python -m measurement.span_diagnostic

The first anchor wave came back compressed on both PERSUADE forms: our scores sit in a narrow band
around 2.4-2.8 while the humans' means differ by 1.7 between the two forms. Something is refusing
to use the ends of the scale. There are two candidates and they need different fixes.

    STAGE D IS THE PROBLEM. The evidence differs sharply between a paper humans scored 6 and one
    they scored 2, and the level assignment flattens it anyway. Then per-descriptor probability
    scoring — asking whether each band's descriptor is met, rather than asking for one band —
    targets exactly the step that is failing.

    STAGE C IS THE PROBLEM. Span proposal returns much the same evidence whatever the paper is
    like, so stage D sees no difference and quite reasonably scores everything a 3. Then
    redesigning the level decision is a day spent on the wrong stage: the information was already
    gone before it got there.

## The 2x2 that separates them

Two correlations, over the papers scored in the anchor wave:

    evidence volume  vs  HUMAN score   — does the evidence stage carry any signal at all?
    evidence volume  vs  OUR score     — does the level stage use whatever signal is there?

A weak first correlation with a strong second one is stage C: the level follows the evidence
faithfully, and the evidence is blind. A strong first with a weak second is stage D: the signal
arrives and is discarded.

## Why this costs nothing

Every verified span is already in `score_event.evidence` — `proposed`, `kept`, and `dropped` were
written when the wave ran. No model is called here. I first estimated this experiment at about $8
having forgotten the spans are persisted.

## Volume is a proxy, and a crude one

"How much verified evidence" is not "how good is the writing". A short brilliant essay can carry
few spans. It is used because it is the one dimension available without another model call, and
because the failure it is looking for is gross: if stage C were blind, volume would be flat across
the whole human range, and it would take a much subtler measure to hide a real difference.

The per-trait breakdown is there for the same reason — a signal that exists on `claim` and not on
`lead` is worth seeing before concluding anything about the stage as a whole.
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict

from sqlalchemy import text

from ._db import engine

TENANT = "corpus"

# One row per (paper, trait) scored in the corpus tenant, with the human holistic beside it.
# `evidence` carries the stage-C result: what was proposed, what survived verification.
_ROWS = text("""
    SELECT a.student_id                AS paper_id,
           n.criterion_label           AS trait,
           n.external_ref,
           e.status,
           e.level                     AS ours,
           e.evidence,
           h.value                     AS human
      FROM score_event e
      JOIN artifact      a ON a.artifact_id = e.artifact_id
      JOIN registry_node n ON n.node_id     = e.node_id
      JOIN corpus_score  h ON h.paper_id    = a.student_id AND h.kind = 'holistic'
     WHERE e.tenant_id = :tenant
       AND e.scorer_type = 'ai'
       AND NOT EXISTS (SELECT 1 FROM score_event s
                        WHERE s.supersedes_event_id = e.event_id)
""")


def volume(evidence) -> dict:
    """What stage C actually produced for one criterion on one paper.

    `kept` is the list that survived substring verification, so it is what stage D saw and the
    only one that can explain a level. `proposed` is counted beside it because a high proposal
    count with a low keep rate is a different failure — a model inventing quotations — and it
    would otherwise look identical to a model finding nothing.
    """
    ev = evidence if isinstance(evidence, dict) else json.loads(evidence or "{}")
    kept = ev.get("kept") or []
    return {"proposed": int(ev.get("proposed") or 0),
            "kept": len(kept),
            "chars": sum(len(span_text(k)) for k in kept)}


# `scoring.verify.verify_all` writes {"span": <the text>, **verdict}. The first version of this
# file read "text" and got zero characters from every span on every paper — which printed as a
# clean flat column and a nan correlation, i.e. exactly what "stage C is blind" looks like. A
# parse failure that is indistinguishable from a finding is the worst kind.
#
# `tests/test_span_shape_agrees.py` pins this against the real producer; `measurement` may not
# import `scoring`, so the shape cannot simply be shared.
_TEXT_KEYS = ("span", "text", "quote")


def span_text(k) -> str:
    """The text of one kept span, whatever key it arrived under."""
    if isinstance(k, str):
        return k
    if isinstance(k, dict):
        for key in _TEXT_KEYS:
            v = k.get(key)
            if isinstance(v, str):
                return v
    return ""


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 3:
        return float("nan")
    mx, my = sum(xs) / n, sum(ys) / n
    sx = statistics.pstdev(xs)
    sy = statistics.pstdev(ys)
    if not sx or not sy:
        # One of them never varies. Not zero correlation — no question was asked.
        return float("nan")
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / n
    return cov / (sx * sy)


def collect(conn) -> list[dict]:
    out = []
    for r in conn.execute(_ROWS, {"tenant": TENANT}).mappings():
        v = volume(r["evidence"])
        out.append({"paper": r["paper_id"], "trait": r["trait"], "status": r["status"],
                    "ours": None if r["ours"] is None else float(r["ours"]),
                    "human": float(r["human"]), **v})
    return out


def analyse(rows: list[dict]) -> dict:
    """The two correlations, overall and per trait."""
    def corr(rs, key):
        pairs = [(r[key], r["chars"]) for r in rs if r[key] is not None]
        return _pearson([p[0] for p in pairs], [p[1] for p in pairs]), len(pairs)

    by_trait = defaultdict(list)
    for r in rows:
        by_trait[r["trait"]].append(r)

    return {
        "overall": {"human_vs_evidence": corr(rows, "human"),
                    "ours_vs_evidence": corr(rows, "ours")},
        "by_trait": {t: {"human_vs_evidence": corr(rs, "human"),
                         "ours_vs_evidence": corr(rs, "ours"),
                         "n": len(rs)}
                     for t, rs in sorted(by_trait.items())},
    }


def bands(rows: list[dict]) -> list[tuple[int, dict]]:
    """Evidence volume by HUMAN score band. The flat-or-not picture, which is the whole question
    and is easier to disbelieve from a table than from a correlation."""
    by_h = defaultdict(list)
    for r in rows:
        by_h[int(r["human"])].append(r)
    out = []
    for h in sorted(by_h):
        rs = by_h[h]
        out.append((h, {
            "papers": len({r["paper"] for r in rs}),
            "kept": round(statistics.mean([r["kept"] for r in rs]), 2),
            "chars": round(statistics.mean([r["chars"] for r in rs]), 1),
            "proposed": round(statistics.mean([r["proposed"] for r in rs]), 2),
            "abstained": sum(1 for r in rs if r["status"] != "scored"),
            "ours": round(statistics.mean([r["ours"] for r in rs if r["ours"] is not None]), 2)
                    if any(r["ours"] is not None for r in rs) else None,
        }))
    return out


def render(rows: list[dict]) -> str:
    if not rows:
        return ("No scored corpus papers with a human holistic score. Nothing to diagnose — run "
                "the anchor wave first.")
    # Kept spans with no characters in them is not a finding, it is a parse failure — and it
    # renders as a flat column and a nan correlation, which is what a real "stage C is blind"
    # result looks like. Say so instead of publishing it.
    kept_total = sum(r["kept"] for r in rows)
    if kept_total and not sum(r["chars"] for r in rows):
        return (f"{kept_total:,} verified spans carry zero characters between them, which is "
                f"impossible. `span_text` is not finding the text on this evidence shape — see "
                f"tests/test_span_shape_agrees.py. Not reporting a diagnosis from it.")

    a = analyse(rows)
    (hc, hn), (oc, on) = a["overall"]["human_vs_evidence"], a["overall"]["ours_vs_evidence"]

    out = ["EVIDENCE VOLUME AGAINST BOTH RATERS", "=" * 78,
           f"  human score vs verified-evidence characters:  r = {hc:+.3f}  (n={hn})",
           f"  our score   vs verified-evidence characters:  r = {oc:+.3f}  (n={on})",
           ""]

    # The reading, stated rather than left to the reader — it is the decision this exists to make.
    if hc == hc and oc == oc:                       # both non-nan
        if abs(hc) < 0.15 and abs(oc) >= 0.3:
            out.append("  READS AS STAGE C. The level follows the evidence, and the evidence "
                       "barely tracks writing quality — so the signal is lost before stage D "
                       "sees it, and redesigning the level decision would not recover it.")
        elif abs(hc) >= 0.3 and abs(oc) < 0.15:
            out.append("  READS AS STAGE D. The evidence tracks writing quality and the level "
                       "does not follow it — the signal arrives and is discarded.")
        else:
            out.append("  READS AS NEITHER CLEANLY. Both correlations are middling, which means "
                       "evidence volume is too crude a proxy to separate the stages here. The "
                       "per-band table below is the thing to look at.")
    out.append("")

    out += ["EVIDENCE BY HUMAN SCORE BAND", "=" * 78,
            "  human   papers   kept spans   chars   proposed   abstained   our mean"]
    for h, b in bands(rows):
        ours = "  --  " if b["ours"] is None else f"{b['ours']:6.2f}"
        out.append(f"  {h:>5}   {b['papers']:>6}   {b['kept']:>10}   {b['chars']:>5}   "
                   f"{b['proposed']:>8}   {b['abstained']:>9}   {ours}")
    out += ["", "  Flat `chars` down this column is stage C being blind. Rising `chars` with a "
                "flat", "  `our mean` is stage D discarding what it was given.", ""]

    out += ["PER TRAIT", "=" * 78,
            "  trait                                    human_r    ours_r      n"]
    for t, d in a["by_trait"].items():
        (h_r, _), (o_r, _) = d["human_vs_evidence"], d["ours_vs_evidence"]
        out.append(f"  {t[:38]:<38}  {h_r:+7.3f}   {o_r:+7.3f}  {d['n']:>5}")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    with engine().connect() as conn:
        conn.execute(text("SELECT set_config('app.tenant', :t, true)"), {"t": TENANT})
        rows = collect(conn)

    if a.json:
        print(json.dumps({"analysis": analyse(rows), "bands": bands(rows)},
                         indent=1, default=str))
    else:
        print(render(rows))


if __name__ == "__main__":
    main()
