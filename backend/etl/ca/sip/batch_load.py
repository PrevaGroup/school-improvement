"""Bulk-load extracted plan JSONs into the augment tables — counterpart to batch_extract.

Reads gs://.../extracted/*.json (the ExtractedPlan staging artifacts), validates each
against schema.ExtractedPlan, and upserts plan / plan_goal / plan_action **under a
tenant** via app.plan_loader.load_plan. The augment `plan_*` tables are private + RLS,
so every row is stamped with --tenant and written inside `SET LOCAL app.tenant`.

Review gate: by default only `review_status='approved'` plans load. `--force` loads
`draft` plans as-is (MVP — get the augment layer populated; review later in the DB).

Idempotent: deterministic ids + ON CONFLICT, so re-running (e.g. as more plans finish
extracting) upserts in place. It globs whatever JSONs exist now, so you can load the
first few and re-run after the full batch completes.

Run in Cloud Shell (DB via the loaders' engine + ADC), from backend/:
    python -m etl.ca.sip.batch_load \
      --tenant lbusd --display-name "Long Beach Unified" \
      --in-prefix gs://school-improvement-501916-raw/raw/ca/districts/0622500/sip/extracted \
      --force [--limit N] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Optional

sys.path.append(str(pathlib.Path(__file__).resolve().parents[3]))  # -> backend/

import fsspec
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import sessionmaker

from app.models.reference import DimTenant
from app.plan_loader import load_plan

from .._shared import _engine
from .schema import ExtractedPlan, ReviewStatus


def list_json(prefix: str) -> list[tuple[str, str]]:
    fs, _ = fsspec.core.url_to_fs(prefix)
    scheme = prefix.split("://", 1)[0] if "://" in prefix else None
    out = []
    for p in fs.glob(prefix.rstrip("/") + "/*.json"):
        src = p if ("://" in p or scheme is None) else f"{scheme}://{p}"
        out.append((p.rsplit("/", 1)[-1], src))
    return sorted(out)


def read_plan(src: str) -> ExtractedPlan:
    with fsspec.open(src, "r", encoding="utf-8") as fh:
        return ExtractedPlan.model_validate(json.load(fh))


def ensure_tenant(engine, tenant_id: str, display_name: Optional[str]) -> None:
    """Upsert the dim_tenant row so plan_*.tenant_id FK is satisfied (public table)."""
    with engine.begin() as c:
        c.execute(
            pg_insert(DimTenant)
            .values(
                tenant_id=tenant_id,
                tenant_type="district",
                display_name=display_name or tenant_id,
                jurisdiction="CA",
            )
            .on_conflict_do_nothing()
        )


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Bulk-load extracted plan JSONs into plan_* under a tenant.")
    ap.add_argument("--tenant", required=True, help="tenant_id to load under (e.g. lbusd)")
    ap.add_argument("--in-prefix", required=True, help="gs:// prefix (or local dir) of the extracted *.json")
    ap.add_argument("--display-name", default=None, help="dim_tenant.display_name if the tenant is new")
    ap.add_argument("--force", action="store_true", help="load review_status='draft' plans as-is (MVP)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true", help="parse + report only, no writes")
    args = ap.parse_args(argv)

    eng = _engine()
    files = list_json(args.in_prefix)
    if args.limit:
        files = files[: args.limit]
    print(f"[load] {len(files)} JSONs under {args.in_prefix} -> tenant {args.tenant}", file=sys.stderr)

    if not args.dry_run:
        ensure_tenant(eng, args.tenant, args.display_name)
    SessionLocal = sessionmaker(bind=eng)

    loaded = skipped = 0
    errors: list[tuple[str, str]] = []
    for fname, src in files:
        try:
            plan = read_plan(src)
        except Exception as e:  # invalid / unreadable JSON
            errors.append((fname, f"parse: {e}"))
            print(f"[load] ERROR  {fname}: parse {e}", file=sys.stderr)
            continue

        if plan.review_status != ReviewStatus.approved and not args.force:
            skipped += 1
            print(f"[load] SKIP   {fname}: review_status={plan.review_status.value} (pass --force)", file=sys.stderr)
            continue

        if args.dry_run:
            loaded += 1
            print(f"[load] would load {fname}: {plan.plan_id} ({len(plan.goals)} goals)", file=sys.stderr)
            continue

        try:
            with SessionLocal() as s, s.begin():
                s.execute(text("SELECT set_config('app.tenant', :t, true)"), {"t": args.tenant})
                counts = load_plan(s, args.tenant, plan)
            loaded += 1
            print(f"[load] {fname}: {plan.plan_id}  goals={counts['goals']} actions={counts['actions']}", file=sys.stderr)
        except Exception as e:
            errors.append((fname, str(e)))
            print(f"[load] ERROR  {fname}: {e}", file=sys.stderr)

    print(f"\n[load] done: {loaded} loaded, {skipped} skipped (unapproved), {len(errors)} errors")
    for f, e in errors:
        print(f"  error {f}: {e}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
