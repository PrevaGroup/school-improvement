"""Run the eval set against the deployed agent and score every answer.

    python -m evals.run_evals [--set pr-gate|full] [--target live] [--target-url URL]
                              [--max-cases N] [--no-judge] [--dry-run]

The loop's scoring pass (eval-trace-system.md §3–4). For each active `eval_case` it drives
`/api/chat` **as an HTTP client** against a deployed revision — never importing serving — signed
in as the eval principal (so answers are metered by that principal's cap and stamped
`source="eval"`). It reads each answer's own trace back from GCS (full tool outputs), runs the
graders (`graders.run_graders`), and writes one `eval_run` + one `eval_result` per case, with a
pass-rate delta against the previous run of the same target/set.

The T2 judge is a direct Opus call (grading infra, not the system under test); `--max-cases`
bounds it, and answer generation stays inside the chat spend cap. Runs in Cloud Shell / a Cloud
Run job like every producer job.

Env the runner reads (set in Cloud Shell, never committed): EVAL_PRINCIPAL_EMAIL,
EVAL_PRINCIPAL_PASSWORD, IDENTITY_PLATFORM_API_KEY, EVAL_TARGET_URL (or --target-url).
"""
from __future__ import annotations

import argparse
import json
import logging
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import text

from ._ids import uuid7
from .graders import bundle_from_jsonl, run_graders

log = logging.getLogger("evals.run_evals")

_LOAD_ACTIVE = text(
    "SELECT eval_case_id, question, ui, expected, tags FROM eval_case WHERE status = 'active'")
_BASELINE = text(
    "SELECT eval_run_id, aggregates FROM eval_run WHERE target = :target AND set_name = :set "
    "ORDER BY ts DESC LIMIT 1")
_INSERT_RUN = text("""
    INSERT INTO eval_run (eval_run_id, tenant_id, ts, set_name, target, provider, model,
                          versions, baseline_run_id, aggregates, cost_usd)
    VALUES (:eval_run_id, 'public', :ts, :set_name, :target, :provider, :model,
            :versions, :baseline_run_id, :aggregates, :cost_usd)
""")
_INSERT_RESULT = text("""
    INSERT INTO eval_result (eval_run_id, eval_case_id, tenant_id, verdict, scores,
                             judge_rationale, trace_id)
    VALUES (:eval_run_id, :eval_case_id, 'public', :verdict, :scores, :judge_rationale, :trace_id)
""")


# ---------------------------------------------------------------- pure assembly (unit-tested)


def _aggregate(results: list[dict]) -> dict:
    """Pass rates overall, per tag, and fail counts per grader tier — the run's headline."""
    n = len(results)
    verdicts = Counter(r["verdict"] for r in results)
    tag_n, tag_pass = Counter(), Counter()
    tier_fail = Counter()
    for r in results:
        for t in r.get("tags") or []:
            tag_n[t] += 1
            tag_pass[t] += r["verdict"] == "pass"
        for s in (r.get("scores") or {}).values():
            if s.get("verdict") == "fail":
                tier_fail[s.get("tier")] += 1
    return {
        "n": n,
        "passed": verdicts.get("pass", 0),
        "failed": verdicts.get("fail", 0),
        "error": verdicts.get("error", 0),
        "pass_rate": round(verdicts.get("pass", 0) / n, 3) if n else None,
        "by_tag": {t: {"n": tag_n[t], "passed": tag_pass[t]} for t in sorted(tag_n)},
        "fails_by_tier": dict(tier_fail),
    }


def assemble(cases: list[dict], *, answers: dict, traces: dict, judge, run_id: str,
             set_name: str, target: str, baseline_run_id: str | None, now: datetime) -> dict:
    """Pure core: turn cases + their answers/traces into the run summary + result rows.

    `answers`: {eval_case_id: (reply, trace_id)}. `traces`: {trace_id: jsonl body}. A case with
    no answer or no trace is an `error` result (the turn never produced gradeable evidence)."""
    results: list[dict] = []
    versions = provider = model = None
    cost = 0.0
    for case in cases:
        cid = case["eval_case_id"]
        tags = case.get("tags") or []
        reply, trace_id = answers.get(cid, (None, None))
        body = traces.get(trace_id) if trace_id else None
        if not body:
            results.append({"eval_case_id": cid, "trace_id": trace_id, "verdict": "error",
                            "scores": {}, "judge_rationale": "no answer/trace", "tags": tags})
            continue
        bundle = bundle_from_jsonl(body)
        graded = run_graders(bundle, case.get("expected") or {}, judge=judge)
        if versions is None:
            versions = bundle.envelope.get("versions")
            provider = bundle.envelope.get("gen_ai.provider.name")
            model = bundle.envelope.get("gen_ai.request.model")
        cost += float((bundle.totals or {}).get("cost_usd_est") or 0.0)
        results.append({"eval_case_id": cid, "trace_id": trace_id, "verdict": graded["verdict"],
                        "scores": graded["scores"], "judge_rationale": graded["judge_rationale"],
                        "tags": tags})
    aggregates = _aggregate(results)
    return {
        "run_row": {
            "eval_run_id": run_id, "ts": now, "set_name": set_name, "target": target,
            "provider": provider, "model": model, "versions": versions,
            "baseline_run_id": baseline_run_id, "aggregates": aggregates,
            "cost_usd": round(cost, 4),
        },
        "results": results,
    }


# ---------------------------------------------------------------------------- I/O seams


def _load_active_cases() -> list[dict]:
    from ._db import _engine
    with _engine().begin() as conn:
        return [dict(r) for r in conn.execute(_LOAD_ACTIVE).mappings().all()]


def _baseline(target: str, set_name: str) -> dict | None:
    from ._db import _engine
    with _engine().begin() as conn:
        row = conn.execute(_BASELINE, {"target": target, "set": set_name}).mappings().first()
    return dict(row) if row else None


def _answer(case: dict, *, base_url: str, token: str, timeout: float = 120.0):
    """POST one case's question to /api/chat as the eval principal → (reply, trace_id)."""
    import httpx

    ui = case.get("ui") or {}
    payload = {"messages": [{"role": "user", "content": case["question"]}],
               "level": ui.get("level", "High"),
               "session_id": f"eval-{case['eval_case_id']}"}
    if ui.get("selected_school"):
        payload["school_id"] = ui["selected_school"]
    try:
        resp = httpx.post(f"{base_url.rstrip('/')}/api/chat", json=payload,
                          headers={"Authorization": f"Bearer {token}"}, timeout=timeout)
        resp.raise_for_status()
        body = resp.json()
        return body.get("reply"), body.get("trace_id")
    except Exception as e:
        log.warning("answer failed for %s: %s", case["eval_case_id"], e)
        return None, None


def _fetch_trace_jsonl(gcs_uri: str, *, attempts: int = 8, delay: float = 2.0) -> str | None:
    """Read an eval turn's trace object from GCS, retrying: the emitter flushes it in a
    background task AFTER the HTTP response, so it can land a beat late."""
    import time

    import fsspec
    for i in range(attempts):
        try:
            with fsspec.open(gcs_uri, "r") as f:
                return f.read()
        except Exception:
            if i < attempts - 1:
                time.sleep(delay)
    log.warning("trace object never appeared: %s", gcs_uri)
    return None


def _make_judge(model: str, api_key: str):
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)

    def judge(prompt: str) -> str:
        resp = client.messages.create(model=model, max_tokens=400,
                                       messages=[{"role": "user", "content": prompt}])
        return "".join(b.text for b in resp.content if b.type == "text")
    return judge


def _write(run_row: dict, results: list[dict]) -> None:
    from ._db import _engine

    def _j(v):
        return json.dumps(v, default=str)
    with _engine().begin() as conn:
        conn.execute(_INSERT_RUN, {**run_row, "versions": _j(run_row["versions"]),
                                   "aggregates": _j(run_row["aggregates"])})
        for r in results:
            conn.execute(_INSERT_RESULT, {
                "eval_run_id": run_row["eval_run_id"], "eval_case_id": r["eval_case_id"],
                "verdict": r["verdict"], "scores": _j(r["scores"]),
                "judge_rationale": r["judge_rationale"], "trace_id": r["trace_id"]})


# ---------------------------------------------------------------------------- orchestration


def run(*, set_name: str, target: str, base_url: str, token: str, bucket: str, judge,
        now: datetime, max_cases: int | None = None, dry_run: bool = False) -> dict:
    """Drive the set end-to-end. Returns the run summary (with a baseline pass-rate delta)."""
    cases = _load_active_cases()
    if max_cases:
        cases = cases[:max_cases]
    baseline = _baseline(target, set_name)
    log.info("running %d cases against %s (%s)", len(cases), target, base_url)

    answers, traces = {}, {}
    for case in cases:
        reply, trace_id = _answer(case, base_url=base_url, token=token)
        answers[case["eval_case_id"]] = (reply, trace_id)
        if trace_id:
            uri = f"gs://{bucket}/traces/v1/dt={now.date().isoformat()}/{trace_id}.jsonl"
            body = _fetch_trace_jsonl(uri)
            if body:
                traces[trace_id] = body

    out = assemble(cases, answers=answers, traces=traces, judge=judge, run_id=uuid7(),
                   set_name=set_name, target=target,
                   baseline_run_id=(baseline or {}).get("eval_run_id"), now=now)
    out["baseline"] = baseline
    if not dry_run:
        _write(out["run_row"], out["results"])
    return out


def _report(out: dict) -> None:
    agg = out["run_row"]["aggregates"]
    base = (out.get("baseline") or {}).get("aggregates") or {}
    rate, brate = agg["pass_rate"], base.get("pass_rate")
    delta = f" (Δ {rate - brate:+.3f} vs baseline)" if rate is not None and brate is not None else ""
    log.info("run %s: %d cases — %d pass / %d fail / %d error — pass_rate %s%s — $%.4f",
             out["run_row"]["eval_run_id"], agg["n"], agg["passed"], agg["failed"], agg["error"],
             rate, delta, out["run_row"]["cost_usd"])
    for r in out["results"]:
        if r["verdict"] != "pass":
            fails = [n for n, s in (r["scores"] or {}).items() if s.get("verdict") == "fail"]
            log.info("  %s %s %s", r["verdict"].upper(), r["eval_case_id"], fails or "")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    import os

    from app.config import settings
    from .auth import eval_token_from_env

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--set", dest="set_name", default="pr-gate", choices=["pr-gate", "full"],
                    help="pr-gate = the fast set run as a PR check; full = all active cases")
    ap.add_argument("--target", default="live", help="label stored on the run (default: live)")
    ap.add_argument("--target-url", default=os.environ.get("EVAL_TARGET_URL", ""),
                    help="deployed base URL, e.g. https://sip.prevagroup.com (or EVAL_TARGET_URL)")
    ap.add_argument("--bucket", default=settings.traces_bucket, help="traces bucket (TRACES_BUCKET)")
    ap.add_argument("--judge-model", default="claude-opus-4-8")
    ap.add_argument("--max-cases", type=int, default=None, help="cap cases run (judge-spend guard)")
    ap.add_argument("--no-judge", action="store_true", help="skip the paid T2 usefulness judge")
    ap.add_argument("--dry-run", action="store_true", help="score but write no rows")
    args = ap.parse_args()
    if not args.target_url:
        raise SystemExit("no target url: pass --target-url or set EVAL_TARGET_URL")
    if not args.bucket:
        raise SystemExit("no bucket: pass --bucket or set TRACES_BUCKET")

    token = eval_token_from_env()
    judge = None if args.no_judge else _make_judge(args.judge_model, settings.anthropic_api_key_value)
    out = run(set_name=args.set_name, target=args.target, base_url=args.target_url, token=token,
              bucket=args.bucket, judge=judge, now=datetime.now(timezone.utc),
              max_cases=args.max_cases, dry_run=args.dry_run)
    _report(out)


if __name__ == "__main__":
    main()
