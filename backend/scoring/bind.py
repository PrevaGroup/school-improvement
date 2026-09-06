"""Turn resolved intake files into artifacts, and supersede the ones a student kept working on.

    python -m scoring.bind --tenant public [--manifest ID] [--run-id R] [--dry-run]

`intake` reads folders and works out whose each file is. `artifact` belongs here, so this is what
creates them — reading intake's tables with SQL and never writing them. The writes run one way, and
`tests/test_table_ownership.py` is what keeps it that way.

## Three things can happen to a resolved file, and only one of them is "new"

**Nothing.** The same file, unchanged, seen in a second read of the same folder. `text_hash` and
binding key both match an artifact that already exists, so there is nothing to do. This is the
common case every time a teacher presses sync, and treating it as new would re-score the whole
class at the price of a whole class.

**A new artifact.** No artifact yet under this binding key.

**A supersession.** An artifact exists under this binding key and the text has CHANGED — the
student kept working after the deadline, or handed in again. That is a different TEXT, so it is a
new artifact pointing at the old one through `superseded_by_artifact_id`, and nothing is deleted:
the superseded artifact keeps its scores, its reviewer and its delivery record. That is what lets a
growth claim over the pair be qualified honestly, and it is a different relation from an override,
which is a new judgment about the SAME text.

## The binding key is declared plus inferred, and the record says which

Section, task, iteration and window come from the manifest — a teacher's declaration about the
folder. The student is inferred per file. `resolution_path` carries the distinction onto every
artifact, because a score whose student was inferred from a filename has a different error profile
from one looked up from an account, and pooling them pools two populations.

## `unbound` is a real destination, not a failure

A file nobody could be matched to still becomes an artifact — in `unbound`, carrying its candidates.
It has to: the alternative is a paper that exists in a folder and nowhere in the system, which is
precisely the "twenty-seven files, twenty-four scores" problem the intake statuses exist to prevent.
A teacher resolves it, and `unbound -> bound` is a move only a teacher may make.
"""
from __future__ import annotations

import argparse
import json
import logging

from sqlalchemy import text

from ._db import engine
from ._ids import uuid7

log = logging.getLogger("scoring.bind")

# Files that can become a paper. `not_student_work` and `unreadable` cannot — the first is the
# assignment, the second is an inventory discrepancy, and neither is anybody's writing.
BINDABLE = ("resolved", "empty", "unresolved")

_PENDING = text("""
    SELECT f.file_id, f.source_ref, f.name, f.text, f.text_hash, f.word_count, f.status,
           f.reason_code, f.resolved_student_id, f.resolution_basis, f.resolution_path,
           f.candidates, f.tenant_id, f.visibility,
           m.manifest_id, m.declared_section_id, m.declared_task_id, m.declared_iteration,
           m.declared_window_label, m.run_id AS manifest_run_id
      FROM intake_file f
      JOIN intake_manifest m ON m.manifest_id = f.manifest_id
     WHERE f.tenant_id = :tenant
       AND f.status = ANY(CAST(:bindable AS text[]))
       AND (CAST(:manifest_id AS text) IS NULL OR f.manifest_id = CAST(:manifest_id AS text))
       AND NOT EXISTS (SELECT 1 FROM artifact a WHERE a.intake_file_id = f.file_id)
     ORDER BY m.read_at, f.name
""")

# The artifact currently standing for this binding key, if any. `superseded_by_artifact_id IS NULL`
# is what makes it the current one — a chain of supersessions has exactly one open end.
_CURRENT = text("""
    SELECT artifact_id, content_hash, state
      FROM artifact
     WHERE tenant_id = :tenant AND student_id = :student_id AND section_id = :section_id
       AND task_id = :task_id AND iteration = :iteration
       AND superseded_by_artifact_id IS NULL
     ORDER BY created_at DESC
     LIMIT 1
""")

_INSERT = text("""
    INSERT INTO artifact
        (artifact_id, run_id, student_id, section_id, task_id, iteration, window_label,
         content_hash, source_uri, intake_file_id, handed_in_at, resolution_path, state,
         state_reason_code, tenant_id, visibility)
    VALUES (:artifact_id, :run_id, :student_id, :section_id, :task_id, :iteration, :window_label,
            :content_hash, :source_uri, :intake_file_id, NULL, CAST(:resolution_path AS jsonb),
            :state, :reason_code, :tenant_id, :visibility)
""")

_SUPERSEDE = text("""
    UPDATE artifact SET superseded_by_artifact_id = :new_id
     WHERE artifact_id = :old_id AND superseded_by_artifact_id IS NULL
""")

_BIND = text("""
    UPDATE artifact SET state = 'bound'
     WHERE artifact_id = :artifact_id AND state = 'unbound'
""")


# ------------------------------------------------------------------ pure (unit-tested)


def resolution_path(row: dict) -> dict:
    """Which parts of the binding key were declared, and which were worked out.

    Three of four are `declared`: a teacher asserted what the folder is. Only the student is
    evidence, and it is either `looked_up` (an account matched) or `inferred` (a name did). A
    rising inferred rate is the earliest signal an integration has broken.
    """
    student = row.get("resolution_path") or "unresolved"
    return {"student": student, "section": "declared", "task": "declared",
            "iteration": "declared", "basis": row.get("resolution_basis")}


def initial_state(row: dict) -> tuple[str, str | None]:
    """Where a new artifact starts, and why.

    Everything starts `unbound`, including files we DID resolve — the move to `bound` is a
    teacher's, and the state machine's trigger enforces that. What differs is whether this code
    then makes that move on their behalf, which it may do only when a student was actually named.
    """
    if row["status"] == "unresolved":
        return "unbound", row.get("reason_code") or "no_student_matched"
    return "unbound", None


def decide(row: dict, current: dict | None) -> tuple[str, str | None]:
    """(action, reason) for one intake file against whatever already stands for its binding key.

    `skip` is the important one. A teacher pressing sync twice must not re-score a class, and the
    thing that makes that safe is comparing the TEXT rather than the timestamp: Drive updates
    `modified_at` when a student opens a document and changes nothing.
    """
    if current is None:
        return "create", None
    if current["content_hash"] == row["text_hash"]:
        return "skip", "unchanged since the last read"
    return "supersede", f"text changed since {current['artifact_id']}"


# ------------------------------------------------------------------ the loop


def bind_pending(*, tenant: str, manifest_id: str | None = None, run_id: str | None = None,
                 dry_run: bool = False) -> dict:
    eng = engine()
    counts = {"created": 0, "superseded": 0, "skipped": 0, "unbound": 0}
    failed = []

    with eng.connect() as conn:
        conn.execute(text("SELECT set_config('app.tenant', :t, true)"), {"t": tenant})
        pending = [dict(r) for r in conn.execute(
            _PENDING, {"tenant": tenant, "bindable": list(BINDABLE),
                       "manifest_id": manifest_id}).mappings()]
    log.info("%d intake file(s) with no artifact yet", len(pending))

    for row in pending:
        try:
            action = _bind_one(eng, row, tenant=tenant, run_id=run_id, dry_run=dry_run)
        except Exception as exc:
            log.error("%s (%s): %s", row["name"], row["file_id"], exc)
            failed.append({"file_id": row["file_id"], "name": row["name"], "error": str(exc)})
            continue
        counts[action] = counts.get(action, 0) + 1
        if action in ("created", "superseded") and row["status"] == "unresolved":
            counts["unbound"] += 1

    return {"pending": len(pending), **counts, "failed": failed}


def _bind_one(eng, row: dict, *, tenant: str, run_id: str | None, dry_run: bool) -> str:
    student = row["resolved_student_id"]

    # An unresolved file has no binding key to compare against — there is no student to look one
    # up by — so it can only ever be created, and it lands in `unbound` carrying its candidates.
    current = None
    if student:
        with eng.connect() as conn:
            conn.execute(text("SELECT set_config('app.tenant', :t, true)"), {"t": tenant})
            found = conn.execute(_CURRENT, {
                "tenant": tenant, "student_id": student,
                "section_id": row["declared_section_id"], "task_id": row["declared_task_id"],
                "iteration": row["declared_iteration"]}).mappings().first()
            current = dict(found) if found else None

    action, reason = decide(row, current)
    if action == "skip":
        return "skipped"

    state, reason_code = initial_state(row)
    artifact_id = uuid7()
    if dry_run:
        log.info("%s -> %s (%s) %s", row["name"], action, state, reason or "")
        return "created" if action == "create" else "superseded"

    with eng.begin() as conn:
        conn.execute(text("SELECT set_config('app.tenant', :t, true)"), {"t": tenant})
        # The seed's own move: a teacher declared what this folder is, and binding a file whose
        # student was actually matched is that declaration being applied. `app.actor_type` says so
        # rather than the code claiming to be the pipeline — the trigger refuses a machine here.
        conn.execute(text("SELECT set_config('app.actor_type', 'teacher', true)"))
        conn.execute(text("SELECT set_config('app.actor_id', :a, true)"),
                     {"a": row.get("manifest_run_id") or "intake"})

        conn.execute(_INSERT, {
            "artifact_id": artifact_id,
            "run_id": run_id or row.get("manifest_run_id") or row["manifest_id"],
            "student_id": student,
            "section_id": row["declared_section_id"],
            "task_id": row["declared_task_id"],
            "iteration": row["declared_iteration"],
            "window_label": row["declared_window_label"],
            "content_hash": row["text_hash"] or "",
            # The intake row IS the source now. `source_uri` keeps the human-readable pointer so a
            # teacher asking "which file was this?" gets a filename rather than an identifier.
            "source_uri": f"intake://{row['manifest_id']}/{row['source_ref']}",
            "intake_file_id": row["file_id"],
            "resolution_path": json.dumps(resolution_path(row)),
            "state": state, "reason_code": reason_code,
            "tenant_id": row["tenant_id"], "visibility": row["visibility"]})

        if action == "supersede":
            moved = conn.execute(
                _SUPERSEDE, {"new_id": artifact_id, "old_id": current["artifact_id"]}).rowcount
            if moved != 1:
                raise RuntimeError(
                    f"{current['artifact_id']} was superseded by someone else while this ran — "
                    f"rolling back rather than leaving two current artifacts on one binding key")

        # Only a file whose student was actually named may be bound. An unresolved one stays in
        # `unbound` until a person says whose it is.
        if student:
            conn.execute(_BIND, {"artifact_id": artifact_id})

    log.info("%s -> %s %s (%s)", row["name"], action, artifact_id, reason or state)
    return "created" if action == "create" else "superseded"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tenant", default="public")
    ap.add_argument("--manifest", default=None, help="limit to one read; default is every unbound file")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    print(json.dumps(bind_pending(tenant=args.tenant, manifest_id=args.manifest,
                                  run_id=args.run_id, dry_run=args.dry_run), indent=1))


if __name__ == "__main__":
    main()
