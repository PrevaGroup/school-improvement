"""Load the seed golden set into `eval_case`.

    python -m evals.load_seed_cases [--dry-run]

Turns `seed_cases.SEED_CASES` (curated DATA) into `eval_case` rows: `status='active'`,
`source='seed'`, a stable hash id per case so re-running is idempotent (ON CONFLICT DO NOTHING —
edits to an existing seed case's grader config are applied by the human, not silently by re-load;
to reshape a case, bump its question or clear the row). Runs in Cloud Shell like every producer
job, connecting as the migrator role via `_db._engine`.
"""
from __future__ import annotations

import argparse
import json
import logging

from sqlalchemy import text

from .seed_cases import SEED_CASES, case_id

log = logging.getLogger("evals.load_seed_cases")

_INSERT = text("""
    INSERT INTO eval_case (eval_case_id, tenant_id, question, ui, expected, source, status, tags,
                           notes)
    VALUES (:eval_case_id, 'public', :question, :ui, :expected, 'seed', 'active', :tags, :notes)
    ON CONFLICT (eval_case_id) DO NOTHING
""")


def _row(case: dict) -> dict:
    """One seed case -> one eval_case row dict (JSONB fields as JSON strings; tags as a PG array)."""
    expected: dict = {"params": case.get("params", {})}
    if case.get("graders"):
        expected["graders"] = case["graders"]
    return {
        "eval_case_id": case_id(case),
        "question": case["question"],
        "ui": json.dumps({"level": case.get("level", "High"),
                          **({"selected_school": case["school_id"]} if case.get("school_id") else {})}),
        "expected": json.dumps(expected),
        "tags": case.get("tags") or [],
        "notes": case.get("notes"),
    }


def load(*, dry_run: bool = False) -> dict:
    """Upsert every seed case. Returns counts."""
    rows = [_row(c) for c in SEED_CASES]
    counts = {"cases": len(rows), "inserted": 0}
    if dry_run:
        counts["inserted"] = len(rows)
        return counts
    from ._db import _engine
    with _engine().begin() as conn:
        for row in rows:
            counts["inserted"] += conn.execute(_INSERT, row).rowcount     # 0 on conflict
    return counts


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="build rows + count, write nothing")
    args = ap.parse_args()
    counts = load(dry_run=args.dry_run)
    log.info("done%s: %d seed cases, %d inserted (rest already present)",
             " (dry-run)" if args.dry_run else "", counts["cases"], counts["inserted"])


if __name__ == "__main__":
    main()
