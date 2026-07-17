"""Batch-ingest chat traces: GCS JSONL objects -> `trace` envelope rows.

    python -m evals.ingest_traces [--days 3] [--date 2026-07-16] [--dry-run]

The store half of the eval trace system's hybrid storage (eval-trace-system.md §1, §8.1):
`serving` emits one JSONL object per turn to gs://<bucket>/traces/v1/dt=YYYY-MM-DD/; this job
reads each object's first line (the envelope), pulls the verbatim question from the
`turn_start` event (kept indefinitely, §8.3), and upserts into `trace`.

Idempotent on trace_id (INSERT .. ON CONFLICT DO NOTHING), so re-running a window is safe and
cheap — which is the whole sync story: no watermark, no ledger, just re-scan the last N day
partitions (default 3) each run. Emission is fire-and-forget with no retries, so an object can
land late within its dt= partition; the overlap window absorbs that.

A malformed object is SKIPPED AND LOGGED, never fatal: one corrupt trace must not stall the
pipeline (same posture as emission — traces are best-effort evidence, not ledger data).

Runs in Cloud Shell / a Cloud Run job like every producer's batch work — never locally.
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import date, timedelta

from sqlalchemy import text

log = logging.getLogger("evals.ingest_traces")

_INSERT = text("""
    INSERT INTO trace (trace_id, session_id, ts, latency_ms, status, tenant_id,
                       principal_hash, source, question, ui, provider, model,
                       versions, totals, gcs_uri)
    VALUES (:trace_id, :session_id, :ts, :latency_ms, :status, :tenant_id,
            :principal_hash, :source, :question, :ui, :provider, :model,
            :versions, :totals, :gcs_uri)
    ON CONFLICT (trace_id) DO NOTHING
""")


def parse_trace(body: str, gcs_uri: str) -> dict:
    """One GCS object -> one `trace` row dict. Pure — the unit under test.

    Line 1 is the envelope (written by TraceRecorder.envelope(), the same shape this table
    stores); the question is lifted from the `turn_start` event. Raises on malformed input —
    the caller decides that means skip-and-log, not crash.
    """
    lines = [json.loads(x) for x in body.strip().splitlines()]
    env = lines[0]
    if "trace_id" not in env or "type" in env:
        raise ValueError("first line is not a trace envelope")
    question = next((e.get("question") for e in lines[1:] if e.get("type") == "turn_start"),
                    None)
    return {
        "trace_id": env["trace_id"],
        "session_id": env.get("session_id"),
        "ts": env["ts"],
        "latency_ms": env.get("latency_ms"),
        "status": env["status"],
        "tenant_id": env.get("tenant_id") or "public",
        "principal_hash": env.get("principal_hash"),
        "source": env.get("source") or "prod",
        "question": question,
        # JSONB params go over the wire as JSON strings; postgres casts on insert.
        "ui": json.dumps(env.get("ui")),
        "provider": env.get("gen_ai.provider.name"),
        "model": env.get("gen_ai.request.model"),
        "versions": json.dumps(env.get("versions")),
        "totals": json.dumps(env.get("totals")),
        "gcs_uri": env.get("gcs_uri") or gcs_uri,
    }


def _partitions(bucket: str, days: int, one_date: str | None) -> list[str]:
    if one_date:
        return [f"gs://{bucket}/traces/v1/dt={one_date}/*.jsonl"]
    today = date.today()
    return [f"gs://{bucket}/traces/v1/dt={(today - timedelta(days=n)).isoformat()}/*.jsonl"
            for n in range(days)]


def ingest(bucket: str, *, days: int = 3, one_date: str | None = None,
           dry_run: bool = False) -> dict:
    """Scan the window's partitions; upsert every parseable object. Returns counts."""
    import fsspec

    fs = fsspec.filesystem("gs")
    counts = {"objects": 0, "inserted": 0, "skipped_malformed": 0}
    rows: list[dict] = []
    for pattern in _partitions(bucket, days, one_date):
        for path in fs.glob(pattern):
            counts["objects"] += 1
            uri = f"gs://{path}" if not str(path).startswith("gs://") else str(path)
            try:
                with fs.open(path, "r") as f:
                    rows.append(parse_trace(f.read(), uri))
            except Exception:
                counts["skipped_malformed"] += 1
                log.warning("malformed trace object skipped: %s", uri, exc_info=True)

    if dry_run:
        counts["inserted"] = len(rows)  # what WOULD be attempted (conflicts unknowable offline)
        return counts

    from ._db import _engine

    with _engine().begin() as conn:
        for row in rows:
            counts["inserted"] += conn.execute(_INSERT, row).rowcount  # 0 on conflict
    return counts


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    from app.config import settings

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bucket", default=settings.traces_bucket,
                    help="GCS bucket holding traces/v1/ (default: TRACES_BUCKET)")
    ap.add_argument("--days", type=int, default=3,
                    help="re-scan the last N day partitions (default 3; idempotent)")
    ap.add_argument("--date", default=None, help="ingest exactly one dt=YYYY-MM-DD partition")
    ap.add_argument("--dry-run", action="store_true", help="parse + count, write nothing")
    args = ap.parse_args()
    if not args.bucket:
        raise SystemExit("no bucket: pass --bucket or set TRACES_BUCKET")

    counts = ingest(args.bucket, days=args.days, one_date=args.date, dry_run=args.dry_run)
    log.info("done%s: %d objects, %d inserted, %d malformed",
             " (dry-run)" if args.dry_run else "",
             counts["objects"], counts["inserted"], counts["skipped_malformed"])


if __name__ == "__main__":
    main()
