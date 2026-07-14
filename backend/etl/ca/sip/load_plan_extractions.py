"""Load extracted plan JSONs into the public plan_extraction (JSONB) table.

The serving source for the plan-content marts: it keeps the FULL extraction (provenance
quotes, funding text, proposed metric links) that the normalized plan_* tables drop.
Public tier — no tenant, no RLS (SPSAs are public documents).

Run in Cloud Shell (DB via the loaders' engine + ADC), from backend/:
    python -m etl.ca.sip.load_plan_extractions \
      --in-prefix gs://school-improvement-501916-raw/raw/ca/districts/0622500/sip/extracted \
      [--limit N] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Optional

sys.path.append(str(pathlib.Path(__file__).resolve().parents[3]))  # -> backend/

import fsspec
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.reference import PlanExtraction

from .._shared import _engine


def list_json(prefix: str) -> list[tuple[str, str]]:
    fs, _ = fsspec.core.url_to_fs(prefix)
    scheme = prefix.split("://", 1)[0] if "://" in prefix else None
    out = []
    for p in fs.glob(prefix.rstrip("/") + "/*.json"):
        src = p if ("://" in p or scheme is None) else f"{scheme}://{p}"
        out.append((p.rsplit("/", 1)[-1], src))
    return sorted(out)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Load extracted plan JSONs into public plan_extraction (JSONB).")
    ap.add_argument("--in-prefix", required=True, help="gs:// prefix (or local dir) of the extracted *.json")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    files = list_json(args.in_prefix)
    if args.limit:
        files = files[: args.limit]
    print(f"[extractions] {len(files)} JSONs under {args.in_prefix}", file=sys.stderr)

    rows, errors = [], []
    for fname, src in files:
        try:
            with fsspec.open(src, "r", encoding="utf-8") as fh:
                doc = json.load(fh)
            rows.append(dict(
                plan_id=doc["plan_id"],
                school_id=doc.get("school_id"),
                plan_year=doc.get("plan_year"),
                plan_type=doc.get("plan_type"),
                extracted_at=(doc.get("source") or {}).get("extracted_at"),
                document=doc,
            ))
        except Exception as e:
            errors.append((fname, str(e)))
            print(f"[extractions] ERROR {fname}: {e}", file=sys.stderr)

    print(f"[extractions] parsed {len(rows)} ok, {len(errors)} errors", file=sys.stderr)
    if args.dry_run or not rows:
        for r in rows:
            print(f"  would upsert {r['plan_id']} (school {r['school_id']})", file=sys.stderr)
        return 1 if errors else 0

    with _engine().begin() as conn:
        stmt = pg_insert(PlanExtraction).values(rows)
        conn.execute(stmt.on_conflict_do_update(
            index_elements=["plan_id"],
            set_={c: stmt.excluded[c] for c in ("school_id", "plan_year", "plan_type", "extracted_at", "document")},
        ))
    print(f"[extractions] upserted {len(rows)} plan_extraction rows")
    for f, e in errors:
        print(f"  error {f}: {e}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
