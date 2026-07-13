"""Batch-extract a district's SPSA PDFs from GCS, using the tools already at hand.

Instead of scraping each PDF for a CDS code it often doesn't print, this resolves
school identity from the **datastore** (`dim_school`, the conformed CDS<->NCES<->name
crosswalk) keyed off the GCS path, and feeds each school's identity + known metric
baselines (`fact_metric`) to the extractor through the `--context` channel. So every
plan gets a correct, school-specific `plan_id` and the model is grounded in what we
already know about the school.

Pipeline per PDF:
    gs://…/districts/<LEAID>/sip/<School>.pdf
      → match <School> to a dim_school row (exact-normalized; ambiguous/miss = reported)
      → context = identity + fact_metric baselines (+ optional district structure notes)
      → extract_sip.extract(..., school_id_nces=<NCES>, context=…)
      → gs://…/sip/extracted/<School>.json

--district-id is matched against dim_school.district_id = the 7-digit NCES LEAID
(Long Beach = 0622500). The GCS raw path is named districts/0622710/ (a different id) —
that's just where the files live, not the DB key.

Run in Cloud Shell (DB access via the loaders' engine + ADC), from backend/:
    python -m etl.ca.sip.batch_extract \
      --district-id 0622500 \
      --pdf-prefix gs://school-improvement-501916-raw/raw/ca/districts/0622710/sip \
      --out-prefix gs://school-improvement-501916-raw/raw/ca/districts/0622710/sip/extracted \
      --plan-year 2025-26 \
      --context-file etl/ca/sip/contexts/lbusd_spsa.txt \
      [--limit N] [--dry-run]

`--dry-run` resolves + reports the filename→school matches without any API calls — run
it first to confirm the roster match before spending tokens on all 77.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys
from pathlib import Path
from typing import Optional

sys.path.append(str(pathlib.Path(__file__).resolve().parents[3]))  # -> backend/

import fsspec
from sqlalchemy import bindparam, text

from .._shared import _engine
from .extract_sip import extract

PUBLIC = "public"


# --------------------------------------------------------------------------- #
# Datastore reads (public reference: dim_school + public fact_metric)
# --------------------------------------------------------------------------- #
def _norm(s: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def load_schools(conn, district_id: str) -> list[dict]:
    # dim_school keys on federal NCES after 0002_nces_rekey: school_id = 12-digit
    # ncessch, district_id = 7-digit LEAID; the CA CDS rides as state_school_id.
    # NOTE: Long Beach's NCES LEAID is 0622500 (the crosswalk value). The GCS raw path
    # districts/0622710/ uses a different id (LAUSD) — that's just storage, not the DB key.
    rows = conn.execute(
        text(
            "SELECT school_id, state_school_id, school_name, district_name, school_level "
            "FROM dim_school WHERE district_id = :d"
        ),
        {"d": district_id},
    ).mappings().all()
    return [dict(r) for r in rows]


def load_baselines(conn, school_ids: set[str]) -> dict[str, dict[str, tuple[float, str]]]:
    """{school_id: {metric_id: (value, school_year)}} — All-students, latest year each."""
    if not school_ids:
        return {}
    stmt = text(
        "SELECT f.school_id, f.metric_id, p.school_year, f.value "
        "FROM fact_metric f JOIN dim_period p ON f.period_id = p.period_id "
        "WHERE f.student_group_id = 'all' AND f.value IS NOT NULL AND f.school_id IN :ids"
    ).bindparams(bindparam("ids", expanding=True))
    out: dict[str, dict[str, tuple[float, str]]] = {}
    for r in conn.execute(stmt, {"ids": list(school_ids)}).mappings():
        d = out.setdefault(r["school_id"], {})
        cur = d.get(r["metric_id"])
        year = r["school_year"] or ""
        if cur is None or year > cur[1]:
            d[r["metric_id"]] = (float(r["value"]), year)
    return out


# --------------------------------------------------------------------------- #
# Filename -> school (conservative: unique match only; never guess an identity)
# --------------------------------------------------------------------------- #
def resolve(name: str, by_norm: dict[str, list[dict]]) -> Optional[dict]:
    n = _norm(name)
    if not n:
        return None
    exact = by_norm.get(n)
    if exact and len({s["school_id"] for s in exact}) == 1:
        return exact[0]
    cands = {
        s["school_id"]: s
        for key, lst in by_norm.items()
        for s in lst
        if key.startswith(n) or n.startswith(key) or n in key
    }
    return next(iter(cands.values())) if len(cands) == 1 else None


def build_context(school: dict, baselines: dict[str, tuple[float, str]], district_context: Optional[str]) -> str:
    parts = [
        f'This plan is for {school["school_name"]} — NCES {school["school_id"]}, '
        f'CDS {school.get("state_school_id")}'
        + (f', {school["district_name"]}' if school.get("district_name") else "")
        + ". Use this school identity."
    ]
    if baselines:
        b = "; ".join(f"{m} {v} ({y})" for m, (v, y) in sorted(baselines.items()))
        parts.append(
            "Known conformed metric baselines for this school (All students, latest year): "
            f"{b}. When a plan target names one of these metrics, map to that metric_id and "
            "treat the value here as the baseline."
        )
    if district_context:
        parts.append(district_context.strip())
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# GCS listing / output
# --------------------------------------------------------------------------- #
def list_pdfs(prefix: str) -> list[tuple[str, str]]:
    """Return [(basename, full_uri)] for *.pdf directly under the prefix."""
    fs, _ = fsspec.core.url_to_fs(prefix)
    scheme = prefix.split("://", 1)[0] if "://" in prefix else None
    out = []
    for p in fs.glob(prefix.rstrip("/") + "/*.pdf"):
        src = p if ("://" in p or scheme is None) else f"{scheme}://{p}"
        out.append((p.rsplit("/", 1)[-1], src))
    return sorted(out)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Batch-extract a district's SPSA PDFs, resolving identity from dim_school.")
    ap.add_argument("--district-id", required=True, help="dim_school.district_id = 7-digit NCES LEAID (Long Beach = 0622500)")
    ap.add_argument("--pdf-prefix", required=True, help="gs:// prefix (or local dir) holding the source PDFs")
    ap.add_argument("--out-prefix", required=True, help="gs:// prefix (or local dir) to write <school>.json")
    ap.add_argument("--plan-year", default=None, help="school-year hint, e.g. 2025-26")
    ap.add_argument("--context-file", type=Path, default=None, help="district structure/format notes injected into every prompt")
    ap.add_argument("--alias", action="append", default=[], metavar="STEM=SCHOOL_ID",
                    help="pin a filename stem to a school_id when the name won't match (repeatable), e.g. --alias CAMS=062250...")
    ap.add_argument("--max-tokens", type=int, default=32000)
    ap.add_argument("--limit", type=int, default=None, help="process at most N PDFs (for a trial run)")
    ap.add_argument("--dry-run", action="store_true", help="resolve + report matches only; no API calls")
    args = ap.parse_args(argv)

    district_context = args.context_file.read_text(encoding="utf-8") if args.context_file else None

    eng = _engine()
    with eng.connect() as conn:
        conn.execute(text("SELECT set_config('app.tenant', :t, false)"), {"t": PUBLIC})
        schools = load_schools(conn, args.district_id)
        baselines = load_baselines(conn, {s["school_id"] for s in schools})
    print(f"[batch] datastore: {len(schools)} schools in district {args.district_id}, "
          f"{sum(len(v) for v in baselines.values())} metric baselines", file=sys.stderr)

    by_norm: dict[str, list[dict]] = {}
    for s in schools:
        by_norm.setdefault(_norm(s["school_name"]), []).append(s)
    by_id = {s["school_id"]: s for s in schools}

    aliases: dict[str, str] = {}
    for a in args.alias:
        if "=" not in a:
            print(f"[batch] bad --alias (need STEM=SCHOOL_ID): {a}", file=sys.stderr)
            return 2
        stem, sid = a.split("=", 1)
        aliases[_norm(stem)] = sid.strip()

    pdfs = list_pdfs(args.pdf_prefix)
    if args.limit:
        pdfs = pdfs[: args.limit]
    print(f"[batch] {len(pdfs)} PDFs under {args.pdf_prefix}", file=sys.stderr)

    matched: list[tuple[str, str]] = []
    unmatched: list[str] = []
    errors: list[tuple[str, str]] = []

    for fname, src in pdfs:
        name = fname[:-4] if fname.lower().endswith(".pdf") else fname
        alias_id = aliases.get(_norm(name))
        if alias_id:
            school = by_id.get(alias_id)
            if not school:
                errors.append((fname, f"--alias {alias_id} not in district {args.district_id}"))
                print(f"[batch] ERROR      {fname}: alias school_id {alias_id} not in district", file=sys.stderr)
                continue
        else:
            school = resolve(name, by_norm)
        if not school:
            unmatched.append(fname)
            print(f"[batch] UNMATCHED  {fname}", file=sys.stderr)
            continue
        print(f"[batch] {fname}  ->  {school['school_name']} (NCES {school['school_id']})", file=sys.stderr)
        if args.dry_run:
            matched.append((fname, school["school_id"]))
            continue
        ctx = build_context(school, baselines.get(school["school_id"], {}), district_context)
        try:
            plan = extract(
                src,
                district_id=args.district_id,
                school_id_nces=school["school_id"],
                plan_year_hint=args.plan_year,
                gs_uri=src,
                context=ctx,
                max_tokens=args.max_tokens,
            )
        except RuntimeError as e:
            errors.append((fname, str(e)))
            print(f"[batch] ERROR      {fname}: {e}", file=sys.stderr)
            continue
        out = args.out_prefix.rstrip("/") + "/" + name + ".json"
        with fsspec.open(out, "w", encoding="utf-8") as fh:
            fh.write(plan.model_dump_json(indent=2))
        matched.append((fname, school["school_id"]))
        print(f"[batch] wrote {out}  ({len(plan.goals)} goals)", file=sys.stderr)

    print(f"\n[batch] done: {len(matched)} matched, {len(unmatched)} unmatched, {len(errors)} errors")
    if unmatched:
        print("  unmatched (need a name fix or manual --school-id): " + ", ".join(unmatched))
    for f, e in errors:
        print(f"  error {f}: {e}")
    return 1 if errors or unmatched else 0


if __name__ == "__main__":
    raise SystemExit(main())
