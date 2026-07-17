#!/usr/bin/env python
"""Generate SCHEMA_REFERENCE.md from the SQLAlchemy models — single source of truth.

The models are authoritative. This script documents the **as-built** schema so the
reference can't drift from the code. Run it after any model change (and it can be wired
into the migration flow):

    python scripts/gen_schema_reference.py

The conceptual design lives in California/docs/TARGET_SCHEMA.md; this is the concrete,
generated reflection of what the code actually creates.
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

from app.models import Base, PRIVATE_TABLES  # noqa: E402

# Same rule as migrations/env.py: module-owned tables live with their module, and a model only
# reaches Base.metadata if something imports it. Without these, this generator silently emits a
# reference that's missing every module table — documenting a schema the database doesn't have.
# Add a line when a module starts owning tables. (This is tooling, not core, so it may know them.)
import etl.ca.sip.models  # noqa: E402,F401  — plan_extraction, plan, plan_goal, plan_action
import likeschools.models  # noqa: E402,F401  — feat_match_vector, mart_school_peer, model_partition_stats
import evals.models  # noqa: E402,F401  — trace, eval_case, eval_run, eval_result, feedback

OUT = ROOT / "SCHEMA_REFERENCE.md"


def col_row(col) -> str:
    flags: list[str] = []
    if col.primary_key:
        flags.append("PK")
    if not col.nullable:
        flags.append("NOT NULL")
    for fk in col.foreign_keys:
        flags.append(f"FK→`{fk.target_fullname}`")
    if col.server_default is not None:
        try:
            flags.append(f"default `{col.server_default.arg}`")
        except Exception:
            pass
    return f"| `{col.name}` | {col.type} | {', '.join(flags)} |"


def main() -> None:
    lines = [
        "# Schema Reference (generated)",
        "",
        "_Auto-generated from the SQLAlchemy models by `backend/scripts/gen_schema_reference.py` "
        "— do not edit by hand._",
        "",
        "Documents the **as-built** database. The conceptual design is in "
        "[`../California/docs/TARGET_SCHEMA.md`](../California/docs/TARGET_SCHEMA.md).",
        "",
    ]
    for name in sorted(Base.metadata.tables):
        table = Base.metadata.tables[name]
        tag = "private (RLS)" if name in PRIVATE_TABLES else "public reference"
        lines += [f"## `{name}` — {tag}", "", "| Column | Type | Constraints |", "|---|---|---|"]
        lines += [col_row(c) for c in table.columns]
        lines.append("")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({len(Base.metadata.tables)} tables)")


if __name__ == "__main__":
    main()
