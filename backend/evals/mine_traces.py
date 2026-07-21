"""Mine prod traces for candidate eval cases — the flywheel's step 1 (eval-trace-system.md §4).

    python -m evals.mine_traces [--days 7] [--limit 500] [--dry-run]

Scans recent `source='prod'` traces for failure signals and turns each flagged turn into an
`eval_case(status='candidate', source='mined:<trace_id>')`. Signals:
  - the turn's own status: error / max_iters / refusal
  - a tool call that errored
  - a deterministic T1 honesty grader that fails on the real answer (invented number, defamation
    pattern, suppressed-as-zero)
  - a data-shaped question answered with no tools at all

**Candidates are never auto-activated.** A human reviews each, writes/confirms the graders, strips
anything personal (§6), and promotes `candidate → active`. Re-mining is idempotent: the candidate
id is derived from the trace id (ON CONFLICT DO NOTHING), so the same trace never doubles up.

Runs in Cloud Shell like every producer job; needs GCS read (full tool outputs) + the DB.
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from .graders import (bundle_from_jsonl, numeric_provenance, plan_status_compliance,
                      suppressed_value_handling)
from .run_evals import _fetch_trace_jsonl

log = logging.getLogger("evals.mine_traces")

_BAD_STATUS = {"error", "max_iters", "refusal"}
_T1 = {"numeric_provenance": numeric_provenance,
       "plan_status_compliance": plan_status_compliance,
       "suppressed_value_handling": suppressed_value_handling}
# A question is "data-shaped" (should have used a tool) if it mentions any of these.
_DATA_HINTS = ("rate", "absenteeism", "graduation", "suspension", "plan", "compare",
               "subgroup", "percent", "%", "chronic", "peers", "enrollment", "attendance")

_LOAD_PROD = text(
    "SELECT trace_id, question, ui, status, gcs_uri FROM trace "
    "WHERE source = 'prod' AND ts >= :since ORDER BY ts DESC LIMIT :limit")
_INSERT = text("""
    INSERT INTO eval_case (eval_case_id, tenant_id, question, ui, expected, source, status, tags,
                           notes)
    VALUES (:eval_case_id, 'public', :question, :ui, '{"params": {}}', :source, 'candidate',
            :tags, :notes)
    ON CONFLICT (eval_case_id) DO NOTHING
""")


def signals_for(trace_row: dict, body: str | None) -> list[str]:
    """Failure signals for one trace (pure). Empty list == not a candidate."""
    sig: list[str] = []
    status = (trace_row.get("status") or "").lower()
    if status in _BAD_STATUS:
        sig.append(f"status:{status}")
    if body:
        bundle = bundle_from_jsonl(body)
        if any(tc.get("error") for tc in bundle.tool_calls):
            sig.append("tool_error")
        if not bundle.tool_calls and status == "ok":
            q = (trace_row.get("question") or bundle.question or "").lower()
            if any(h in q for h in _DATA_HINTS):
                sig.append("needs_tool")
        for name, fn in _T1.items():
            if fn(bundle, {}).verdict == "fail":
                sig.append(f"grader:{name}")
    return sig


def candidate_from(trace_row: dict, body: str | None) -> dict | None:
    """One trace -> a candidate eval_case row dict, or None if it shows no failure signal."""
    sig = signals_for(trace_row, body)
    if not sig:
        return None
    tid = trace_row["trace_id"]
    return {
        "eval_case_id": f"mined-{tid}",                  # deterministic -> idempotent re-mining
        "question": trace_row.get("question") or "",
        "ui": json.dumps(trace_row.get("ui")),
        "source": f"mined:{tid}",
        "tags": ["mined", *sig],
        "notes": "signals: " + ", ".join(sig),
    }


# ---------------------------------------------------------------------------- I/O seams


def _load_prod_traces(since: datetime, limit: int) -> list[dict]:
    from ._db import _engine
    with _engine().begin() as conn:
        return [dict(r) for r in
                conn.execute(_LOAD_PROD, {"since": since, "limit": limit}).mappings().all()]


def _write(candidates: list[dict]) -> int:
    from ._db import _engine
    inserted = 0
    with _engine().begin() as conn:
        for c in candidates:
            inserted += conn.execute(_INSERT, c).rowcount     # 0 on conflict
    return inserted


def mine(*, days: int = 7, limit: int = 500, now: datetime | None = None,
         dry_run: bool = False) -> dict:
    """Scan the window's prod traces; emit candidate cases for the flagged ones. Returns counts."""
    now = now or datetime.now(timezone.utc)
    rows = _load_prod_traces(now - timedelta(days=days), limit)
    candidates: list[dict] = []
    for row in rows:
        body = _fetch_trace_jsonl(row["gcs_uri"], attempts=1) if row.get("gcs_uri") else None
        c = candidate_from(row, body)
        if c:
            candidates.append(c)
    counts = {"scanned": len(rows), "candidates": len(candidates), "inserted": 0}
    counts["inserted"] = len(candidates) if dry_run else _write(candidates)
    return counts


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=7, help="scan prod traces from the last N days")
    ap.add_argument("--limit", type=int, default=500, help="max traces to scan")
    ap.add_argument("--dry-run", action="store_true", help="detect + count, write nothing")
    args = ap.parse_args()
    counts = mine(days=args.days, limit=args.limit, dry_run=args.dry_run)
    log.info("done%s: scanned %d, %d candidates, %d inserted (rest already mined)",
             " (dry-run)" if args.dry_run else "",
             counts["scanned"], counts["candidates"], counts["inserted"])


if __name__ == "__main__":
    main()
