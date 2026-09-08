"""Write what a stop-condition run found, so a gate has a history.

Until this existed, `evaluate()` returned five verdicts and nothing kept them — which makes the
most important question about a gate unanswerable. "Has this ever held?" and "when did it start
failing?" cannot be told apart from "nobody has run it since June" by a result with no history,
and a green screen is read as the first of those every time.

## The threshold is copied onto the row

Not referenced. A finding records the number that was in force when the measurement was taken, so
relaxing a line in January cannot make December's runs retroactively pass. That is the same
failure the pre-commitment rule exists to prevent, arriving through the back door of a foreign
key.

## Recording is not gating

This module writes rows. Whether a triggered condition actually stops anything is the caller's
decision, and the database enforces only that a stop names who agreed to it — the CHECK in 0030.
Keeping those apart means a run can record honestly in an environment where nothing is being
released, which is where most of these will run for months.
"""
from __future__ import annotations

import logging

from sqlalchemy import text

from ._db import _engine
from ._ids import uuid7
from .stop_conditions import TRIGGERED, evaluate

log = logging.getLogger("evals.stop_conditions")

_INSERT = text("""
    INSERT INTO eval_stop_condition
        (finding_id, eval_run_id, condition, verdict, observed,
         threshold_value, agreed_by, agreed_on, n, detail, breakdown, tenant_id)
    VALUES (:finding_id, :eval_run_id, :condition, :verdict, :observed,
            :threshold_value, :agreed_by, :agreed_on, :n, :detail,
            CAST(:breakdown AS jsonb), :tenant_id)
""")

# The question the history index exists for: what does each condition say most recently, and when
# did it last change its mind?
_LATEST = text("""
    SELECT DISTINCT ON (condition)
           condition, verdict, observed, threshold_value, agreed_by, agreed_on,
           n, detail, breakdown, created_at, eval_run_id
      FROM eval_stop_condition
     WHERE tenant_id = :tenant
     ORDER BY condition, created_at DESC
""")


def rows_for(run_id: str, data: dict, thresholds=None, *, tenant: str = "public") -> list[dict]:
    """Findings -> rows. Pure, so what gets written can be asserted without a database."""
    import json

    out = []
    for f in evaluate(data, thresholds)["findings"]:
        t = f["threshold"]
        out.append({
            "finding_id": uuid7(),
            "eval_run_id": run_id,
            "condition": f["name"],
            "verdict": f["verdict"],
            "observed": f["observed"],
            # Copied, not referenced — see the module docstring.
            "threshold_value": t["value"],
            "agreed_by": t["agreed_by"] or None,
            "agreed_on": t["agreed_on"] or None,
            "n": f["n"],
            "detail": f["detail"],
            "breakdown": json.dumps(f["breakdown"]),
            "tenant_id": tenant,
        })
    return out


def record(run_id: str, data: dict, thresholds=None, *, tenant: str = "public") -> dict:
    """Evaluate and write. Returns the summary the caller reports."""
    summary = evaluate(data, thresholds)
    rows = rows_for(run_id, data, thresholds, tenant=tenant)

    eng = _engine()
    with eng.begin() as conn:
        conn.execute(text("SELECT set_config('app.tenant', :t, true)"), {"t": tenant})
        for r in rows:
            conn.execute(_INSERT, r)

    for f in summary["findings"]:
        if f["verdict"] == TRIGGERED:
            log.error("STOP CONDITION %s: %s", f["name"], f["detail"])
    if summary["uncommitted"]:
        # Not a warning about the code — a warning about the process. These are measured and
        # cannot stop anything because nobody has agreed what they would mean.
        log.warning("%d condition(s) measured with no agreed threshold, so they cannot gate: %s",
                    len(summary["uncommitted"]), ", ".join(summary["uncommitted"]))
    if summary["not_run"]:
        log.warning("%d condition(s) had no data and were not tested: %s",
                    len(summary["not_run"]), ", ".join(summary["not_run"]))
    return summary | {"recorded": len(rows)}
