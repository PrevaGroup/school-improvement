"""The confirmation itself — one statement, so the gate has one implementation.

    python -m intake.gate --manifest <id> --as "Tim Kinkead"
    python -m intake.gate --list

`review.py` serves this to a teacher through the API and this module runs it from a terminal. Both
go through `CONFIRM` below, because a gate implemented twice is a gate that can be opened two ways
and closed one.

## Why this is a separate command and not a flag on `read_folder`

A `--confirm` flag on the reader would let one invocation both propose a set and agree with it,
which is the thing the gate exists to prevent — and it would be reached for the first time somebody
automated a nightly sync, at which point every folder confirms itself forever. Two tests assert
`read_folder` cannot touch the confirmation columns.

Running it as its own command keeps the shape honest: the confirmation is a separate act, by a
named person, after looking. That the person is at a terminal rather than in a browser does not
change what they are asserting.

`--as` is required for the same reason the CHECK in 0024 is: a confirmation nobody signed is a gate
that opened by itself.
"""
from __future__ import annotations

import argparse
import json

from sqlalchemy import text

from ._db import engine

# THE statement. Both callers use it; neither writes its own.
CONFIRM = text("""
    UPDATE intake_manifest SET confirmed_at = now(), confirmed_by = :who
     WHERE manifest_id = :manifest_id AND tenant_id = :tenant AND confirmed_at IS NULL
""")

_UNCONFIRMED = text("""
    SELECT m.manifest_id, m.source_ref, m.read_at, m.declared_task_id, m.declared_iteration,
           m.file_count, m.inferred_rate,
           count(*) FILTER (WHERE f.status = 'unresolved') AS needs_you
      FROM intake_manifest m
      LEFT JOIN intake_file f ON f.manifest_id = m.manifest_id
     WHERE m.tenant_id = :tenant AND m.confirmed_at IS NULL
     GROUP BY m.manifest_id
     ORDER BY m.read_at DESC
""")


def confirm(conn, manifest_id: str, who: str, tenant: str = "public") -> int:
    """Agree with one read. Returns rows affected — 0 means somebody already did."""
    return conn.execute(CONFIRM, {"manifest_id": manifest_id, "who": who,
                                  "tenant": tenant}).rowcount


def unconfirmed(tenant: str = "public") -> list[dict]:
    with engine().connect() as conn:
        return [dict(r) for r in conn.execute(_UNCONFIRMED, {"tenant": tenant}).mappings()]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--manifest", help="the read to agree with")
    ap.add_argument("--as", dest="who",
                    help="who is agreeing. Required: a confirmation nobody signed is a gate that "
                         "opened by itself")
    ap.add_argument("--list", action="store_true", help="every read still waiting")
    ap.add_argument("--tenant", default="public")
    args = ap.parse_args()

    if args.list or not args.manifest:
        rows = unconfirmed(args.tenant)
        for r in rows:
            r["read_at"] = r["read_at"].isoformat() if r.get("read_at") else None
            r["inferred_rate"] = (float(r["inferred_rate"])
                                  if r["inferred_rate"] is not None else None)
        print(json.dumps({"waiting": rows}, indent=1))
        if not args.manifest:
            return

    if not args.who:
        ap.error("--as is required: a confirmation nobody signed is a gate that opened by itself")

    with engine().begin() as conn:
        n = confirm(conn, args.manifest, args.who, args.tenant)
    if n != 1:
        raise SystemExit(
            f"{args.manifest} was not waiting — it does not exist, belongs to another tenant, or "
            f"somebody has already confirmed it.")
    print(json.dumps({"manifest_id": args.manifest, "confirmed_by": args.who}, indent=1))


if __name__ == "__main__":
    main()
