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

import json
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
        text("SELECT trace_id, session_id, ts, status, source, latency_ms, model, question, "
             f"totals, versions FROM trace {where}ORDER BY ts DESC LIMIT :n"),
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
            "session_id": r.get("session_id"),
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
    shaped = [shape_result(dict(r)) for r in rows]
    return {"available": True, "results": shaped, "grader_stats": grader_stats(shaped)}


# --- one trace's full turn: envelope + the GCS event stream (question → tools → answer) ----- #
# The trace table holds only the envelope; the events (with full tool outputs) live in the GCS
# object. This is the only place serving reads that object — the graders do the same from evals.


def _shape_event(e: dict) -> dict:
    """Trim one raw event to what the detail view renders (drops span ids, content digests)."""
    t = e.get("type")
    if t == "turn_start":
        return {"type": t, "question": e.get("question"), "prior_messages": e.get("prior_messages"),
                "system_prompt": e.get("system_prompt")}
    if t == "model_call":
        return {"type": t, "iteration": e.get("iteration"), "stop": e.get("stop"),
                "usage": e.get("usage") or {}, "latency_ms": e.get("latency_ms")}
    if t == "tool_call":
        return {"type": t, "name": e.get("name"), "input": e.get("input"),
                "output": e.get("output"), "error": e.get("error"), "latency_ms": e.get("latency_ms")}
    if t == "turn_end":
        return {"type": t, "reply": e.get("reply"), "tools_used": e.get("tools_used") or []}
    return {"type": t}


def shape_trace_detail(row: dict, events: list[dict]) -> dict:
    """Envelope row + parsed event lines → the detail payload (pure)."""
    return {
        "trace_id": row["trace_id"],
        "session_id": row.get("session_id"),
        "ts": row["ts"].isoformat() if row.get("ts") else None,
        "status": row.get("status"),
        "source": row.get("source"),
        "model": row.get("model"),
        "level": (row.get("ui") or {}).get("level"),
        "question": row.get("question"),
        "totals": row.get("totals") or {},
        "versions": row.get("versions") or {},
        "gcs_uri": row.get("gcs_uri"),
        "events": [_shape_event(e) for e in events],
    }


def _fetch_events(gcs_uri: str | None) -> list[dict]:
    """Read the JSONL object from GCS and return its event lines (line 0 is the envelope). Returns
    [] if the object is gone (90-day lifecycle) or unreadable — the detail degrades to the
    envelope header rather than erroring."""
    if not gcs_uri:
        return []
    try:
        import fsspec
        with fsspec.open(gcs_uri, "r") as f:
            lines = [json.loads(x) for x in f.read().strip().splitlines()]
        return lines[1:]
    except Exception:
        log.info("trace detail: could not read %s", gcs_uri)
        return []


@router.get("/traces/{trace_id}")
def evals_trace_detail(trace_id: str, _: dict = Depends(require_admin),
                       db: Session = Depends(get_db_public)) -> dict:
    """One trace's full turn: envelope + the event stream (question → tool calls with outputs →
    answer). `available: false` if the trace is unknown or the store isn't there yet."""
    try:
        row = db.execute(
            text("SELECT trace_id, session_id, ts, status, source, model, question, ui, "
                 "versions, totals, gcs_uri FROM trace WHERE trace_id = :id"), {"id": trace_id},
        ).mappings().first()
    except SQLAlchemyError:
        return {"available": False}
    if not row:
        return {"available": False}
    return {"available": True,
            "trace": shape_trace_detail(dict(row), _fetch_events(row.get("gcs_uri")))}


# --- grader reference + per-run grader stats ------------------------------------------------ #
# GRADER_CATALOG is serving's copy of the grader registry — serving may NOT import the evals
# module (the boundary), so it can't read evals.graders.GRADERS at runtime. Instead
# tests/test_grader_catalog.py imports BOTH (tests are boundary-exempt) and fails if they drift,
# so this reference stays honest to the code.

TIER_LABEL = {"T1": "honesty", "T2": "usefulness", "T3": "trajectory"}
GRADER_CATALOG = [
    {"name": "numeric_provenance", "tier": "T1",
     "summary": "Every number in the reply must appear in some tool output — the invented-figure guard."},
    {"name": "plan_status_compliance", "tier": "T1",
     "summary": "If a plan is not on file, the reply must not claim the school has no plan (defamation guard)."},
    {"name": "suppressed_value_handling", "tier": "T1",
     "summary": "A privacy-suppressed value must never be reported as 0 or none — suppressed is UNKNOWN."},
    {"name": "resolution_correctness", "tier": "T1",
     "summary": "The turn must have operated on the expected school — catches wrong-school answers."},
    {"name": "expected_tools", "tier": "T3",
     "summary": "The tool(s) a correct answer needs were actually used."},
    {"name": "no_redundant_tool_calls", "tier": "T3",
     "summary": "No identical tool call was made twice."},
    {"name": "efficiency", "tier": "T3",
     "summary": "Iterations, cost, and latency stayed within the case's budget."},
    {"name": "usefulness_judge", "tier": "T2",
     "summary": "A stronger (Opus) judge scores whether the answer is grounded, direct, and actionable."},
]


def grader_stats(results: list[dict]) -> list[dict]:
    """Per-grader ran/failed tallies across a run's results (pure) — the fix backlog, ranked."""
    stats: dict[str, dict] = {}
    for r in results:
        for name, s in (r.get("scores") or {}).items():
            st = stats.setdefault(name, {"grader": name, "tier": s.get("tier"), "ran": 0, "failed": 0})
            st["ran"] += 1
            if s.get("verdict") == "fail":
                st["failed"] += 1
    return sorted(stats.values(), key=lambda s: (-s["failed"], s["grader"]))


@router.get("/graders")
def evals_graders(_: dict = Depends(require_admin)) -> dict:
    """The grader reference: what each grader checks and its tier. A test ties this to the evals
    GRADERS registry so it can't silently drift from the code."""
    return {"graders": GRADER_CATALOG, "tiers": TIER_LABEL}
