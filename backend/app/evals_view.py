"""Read-only admin view over the eval trace store — the in-app half of the eval loop.

Serves what the `evals` module ingests: `serving` reads the `trace` table with SQL (the
sanctioned cross-module seam — never an import), shapes it for the dashboard, and gates
every route on `require_admin`. There is no write path here; the loop's writes live in the
`evals` module (ingest, and later the runner/miner).

Degrades gracefully: before the eval tables migration + `evals.ingest_traces` have run the
`trace` table is missing/empty, so the endpoints return `available: false` / empty lists
rather than 500 — the dashboard then shows an honest "no traces yet" state.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .db import get_db_public
from .security import require_admin

log = logging.getLogger(__name__)
router = APIRouter(prefix="/evals", tags=["evals"])

SUMMARY_WINDOW = 500  # recent traces the summary aggregates over — plenty at prototype volume


def _f(totals: dict | None, key: str) -> float:
    try:
        return float((totals or {}).get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


def summarize_traces(rows: list[dict]) -> dict:
    """Aggregate trace rows into the dashboard summary (pure — no DB, unit-tested).

    Rows are dicts with at least: status, source, latency_ms, model, totals (JSONB dict with
    token kinds + cost_usd_est). Everything tolerates missing/None so a half-populated store
    never throws."""
    n = len(rows)
    by_status: dict[str, int] = {}
    by_model: dict[str, int] = {}
    by_source: dict[str, int] = {}
    cost = 0.0
    tokens = 0
    latencies: list[int] = []
    for r in rows:
        by_status[r.get("status") or "unknown"] = by_status.get(r.get("status") or "unknown", 0) + 1
        if r.get("model"):
            by_model[r["model"]] = by_model.get(r["model"], 0) + 1
        by_source[r.get("source") or "prod"] = by_source.get(r.get("source") or "prod", 0) + 1
        t = r.get("totals")
        cost += _f(t, "cost_usd_est")
        tokens += int(_f(t, "input_tokens") + _f(t, "output_tokens"))
        if r.get("latency_ms") is not None:
            latencies.append(int(r["latency_ms"]))
    latencies.sort()
    p50 = latencies[len(latencies) // 2] if latencies else None
    return {
        "traces": n,
        "ok_rate": round(100 * by_status.get("ok", 0) / n, 1) if n else None,
        "by_status": by_status,
        "by_source": by_source,
        "by_model": by_model,
        "cost_usd": round(cost, 4),
        "tokens": tokens,
        "latency_p50_ms": p50,
        "latency_max_ms": latencies[-1] if latencies else None,
    }


def _recent_rows(db: Session, limit: int, *, source: str = "prod") -> list[dict]:
    """Recent traces, newest first. Filtered to `source` ('prod' by default) so the Traces tab
    shows real use, not the eval runner's own turns; `source='all'` drops the filter. Raises
    SQLAlchemyError if the table isn't there yet."""
    where, params = "", {"n": limit}
    if source and source != "all":
        where, params["source"] = "WHERE source = :source ", source
    rows = db.execute(
        text("SELECT trace_id, ts, status, source, latency_ms, model, question, totals, versions "
             f"FROM trace {where}ORDER BY ts DESC LIMIT :n"),
        params,
    ).mappings().all()
    return [dict(r) for r in rows]


@router.get("/summary")
def evals_summary(source: str = "prod", _: dict = Depends(require_admin),
                  db: Session = Depends(get_db_public)) -> dict:
    """Headline metrics over the most recent traces. `available: false` when the store is
    empty/not yet migrated — the UI shows a 'no traces ingested yet' state, never an error."""
    try:
        rows = _recent_rows(db, SUMMARY_WINDOW, source=source)
    except SQLAlchemyError:
        log.info("evals summary: trace store not available yet")
        return {"available": False, "window": SUMMARY_WINDOW}
    return {"available": True, "window": SUMMARY_WINDOW, **summarize_traces(rows)}


@router.get("/traces")
def evals_traces(
    limit: int = 50,
    source: str = "prod",
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db_public),
) -> dict:
    """The recent-traces feed. Identity is never returned — the store is pseudonymous
    (principal is a salted hash) and even that stays server-side."""
    limit = max(1, min(limit, 200))
    try:
        rows = _recent_rows(db, limit, source=source)
    except SQLAlchemyError:
        return {"available": False, "traces": []}
    out = []
    for r in rows:
        t = r.get("totals") or {}
        out.append({
            "trace_id": r["trace_id"],
            "ts": r["ts"].isoformat() if r.get("ts") else None,
            "question": r.get("question"),
            "status": r.get("status"),
            "latency_ms": r.get("latency_ms"),
            "model": r.get("model"),
            "cost_usd_est": t.get("cost_usd_est"),
            "iterations": t.get("iterations"),
            "git_sha": (r.get("versions") or {}).get("git_sha"),
        })
    return {"available": True, "traces": out}


# --- eval cases / runs / results (the loop's later stages; all read via SQL, admin-gated) --- #
# Pure row shapers, unit-tested. `expected`/`aggregates`/`scores`/`ui` arrive as JSONB dicts.


def shape_case(r: dict) -> dict:
    expected = r.get("expected") or {}
    return {
        "eval_case_id": r["eval_case_id"],
        "question": r.get("question"),
        "level": (r.get("ui") or {}).get("level"),
        "status": r.get("status"),
        "source": r.get("source"),
        "tags": r.get("tags") or [],
        "graders": expected.get("graders") or [],
        "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
    }


def shape_run(r: dict) -> dict:
    agg = r.get("aggregates") or {}
    return {
        "eval_run_id": r["eval_run_id"],
        "ts": r["ts"].isoformat() if r.get("ts") else None,
        "set_name": r.get("set_name"),
        "target": r.get("target"),
        "model": r.get("model"),
        "pass_rate": agg.get("pass_rate"),
        "n": agg.get("n"),
        "passed": agg.get("passed"),
        "failed": agg.get("failed"),
        "error": agg.get("error"),
        "cost_usd": r.get("cost_usd"),
        "baseline_run_id": r.get("baseline_run_id"),
    }


def shape_result(r: dict) -> dict:
    return {
        "eval_case_id": r["eval_case_id"],
        "question": r.get("question"),
        "verdict": r.get("verdict"),
        "scores": r.get("scores") or {},
        "judge_rationale": r.get("judge_rationale"),
        "trace_id": r.get("trace_id"),
    }


@router.get("/cases")
def evals_cases(limit: int = 200, _: dict = Depends(require_admin),
                db: Session = Depends(get_db_public)) -> dict:
    """Curated + mined eval cases. `available: false` until the loop's tables/data exist."""
    limit = max(1, min(limit, 500))
    try:
        rows = db.execute(
            text("SELECT eval_case_id, question, ui, expected, source, status, tags, created_at "
                 "FROM eval_case ORDER BY created_at DESC LIMIT :n"), {"n": limit},
        ).mappings().all()
    except SQLAlchemyError:
        return {"available": False, "cases": []}
    cases = [shape_case(dict(r)) for r in rows]
    by_status: dict[str, int] = {}
    for c in cases:
        by_status[c["status"]] = by_status.get(c["status"], 0) + 1
    return {"available": True, "cases": cases, "by_status": by_status}


@router.get("/runs")
def evals_runs(limit: int = 50, _: dict = Depends(require_admin),
               db: Session = Depends(get_db_public)) -> dict:
    """Scored eval runs, newest first — each an execution of the set against a target."""
    limit = max(1, min(limit, 200))
    try:
        rows = db.execute(
            text("SELECT eval_run_id, ts, set_name, target, model, aggregates, cost_usd, "
                 "baseline_run_id FROM eval_run ORDER BY ts DESC LIMIT :n"), {"n": limit},
        ).mappings().all()
    except SQLAlchemyError:
        return {"available": False, "runs": []}
    return {"available": True, "runs": [shape_run(dict(r)) for r in rows]}


@router.get("/runs/{run_id}/results")
def evals_run_results(run_id: str, _: dict = Depends(require_admin),
                      db: Session = Depends(get_db_public)) -> dict:
    """Per-case results for one run (failures first), joined to the case question."""
    try:
        rows = db.execute(
            text("SELECT r.eval_case_id, c.question, r.verdict, r.scores, r.judge_rationale, "
                 "r.trace_id FROM eval_result r LEFT JOIN eval_case c "
                 "ON c.eval_case_id = r.eval_case_id WHERE r.eval_run_id = :run "
                 "ORDER BY (r.verdict = 'pass'), r.eval_case_id"), {"run": run_id},
        ).mappings().all()
    except SQLAlchemyError:
        return {"available": False, "results": []}
    return {"available": True, "results": [shape_result(dict(r)) for r in rows]}
