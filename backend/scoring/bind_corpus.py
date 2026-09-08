"""Corpus papers into artifacts, so they go through the pipeline student work goes through.

    python -m corpus.draw_anchor --json | python -m scoring.bind_corpus --wave 1

## Why not a separate scoring path

The whole point of scoring corpus papers is to characterise OUR rater. A severity estimated from
papers that skipped the fit gate, skipped span verification, or ran under a configuration nobody
pinned describes a rater that never touches student writing — and the number would look exactly
as legitimate. So a corpus paper becomes an `artifact` in state `bound`, and `run_scoring` picks
it up without knowing where it came from.

## The tenant is what keeps them out of the console

`corpus`, from migration 0032. Six hundred and sixty-four PERSUADE essays in a teacher's review
queue would make the console useless. Tenancy is the mechanism this system already uses to keep
one district's papers away from another's, so corpus papers are invisible by default rather than
by somebody remembering a filter.

## The task exists so the scorer can find the traits

`run_scoring` resolves what to score by joining `registry_scoring_site` on task and iteration.
That is the seam, and routing around it would mean a second way of deciding which traits apply —
which is exactly how two scoring paths drift apart.

So there are two tasks, one per PERSUADE form, and the iteration is `anchor`. Two tasks rather
than two iterations of one, because independent and text-dependent are different instruments
rather than two attempts at the same one, and `iteration` means draft-versus-final everywhere else
in this system.

## The student id is the paper id

A PERSUADE essay was written by a real student whose identity nobody has. `student_id` is the
de-identified corpus paper id — not NULL, because `bound` means somebody knows whose paper this is
and the state machine is right to insist on it, and not a synthetic name, because a fabricated
student would eventually be counted as one.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from sqlalchemy import text

from ._db import engine
from ._ids import uuid7

log = logging.getLogger("scoring.bind_corpus")

TENANT = "corpus"
ITERATION = "anchor"
SECTION_ID = "corpus:persuade20"

# One task per PERSUADE form. The scoring site under each names the traits for that form, so the
# text-dependent papers are scored on the sourced evidence trait and the independent ones are not.
TASKS = {"Independent": "corpus:persuade20:independent",
         "Text dependent": "corpus:persuade20:text_dependent"}

# The papers this wave covers, with everything the artifact needs. `task` comes from the corpus and
# decides which form's traits apply.
_PAPERS = text("""
    SELECT p.paper_id, p.text_hash, p.task_type, p.source_id, p.external_id
      FROM corpus_paper p
     WHERE p.paper_id = ANY(:paper_ids)
""")

# What is already bound, so a re-run adds only what is missing. The anchor set is scored in waves
# and a second wave must not re-create the first.
_EXISTING = text("""
    SELECT student_id FROM artifact
     WHERE tenant_id = :tenant AND student_id = ANY(:paper_ids)
""")

_INSERT = text("""
    INSERT INTO artifact
        (artifact_id, run_id, student_id, section_id, task_id, iteration, window_label,
         content_hash, source_uri, intake_file_id, handed_in_at, resolution_path, state,
         state_reason_code, tenant_id, visibility)
    VALUES (:artifact_id, :run_id, :student_id, :section_id, :task_id, :iteration, NULL,
            :content_hash, :source_uri, NULL, NULL, CAST(:resolution_path AS jsonb),
            'unbound', NULL, :tenant_id, 'public')
""")

# Bound in the same transaction as the insert. There is no teacher here to make the move, and no
# ambiguity for one to resolve: the corpus says whose paper it is. Writing it `unbound` and leaving
# it there would put 664 papers into a queue waiting for a decision nobody can make.
_BIND = text("""
    UPDATE artifact SET state = 'bound'
     WHERE artifact_id = :artifact_id AND state = 'unbound'
""")


def resolution_path(paper: dict) -> dict:
    """How this artifact's binding key was arrived at. Every part is `declared`.

    Nothing here was inferred from a filename or matched against a roster — the corpus states the
    paper's identity and its task form. Recording that as `declared` rather than `looked_up` keeps
    `looked_up` meaning what it means everywhere else: an account matched a roster address.
    """
    return {"student": "declared", "section": "declared", "task": "declared",
            "iteration": "declared",
            "basis": f"corpus:{paper['source_id']}:{paper['external_id']}"}


def rows_for(papers: list[dict], run_id: str) -> list[dict]:
    """Artifacts for one wave. Pure, so what gets written can be asserted without a database."""
    out = []
    for p in papers:
        task_id = TASKS.get(p["task_type"])
        if task_id is None:
            # Named by the caller, never skipped silently: a paper whose form we cannot tell is a
            # paper that would be scored against the wrong instrument.
            continue
        out.append({
            "artifact_id": uuid7(),
            "run_id": run_id,
            # The de-identified corpus subject. Real student, identity nobody has.
            "student_id": p["paper_id"],
            "section_id": SECTION_ID,
            "task_id": task_id,
            "iteration": ITERATION,
            "content_hash": p["text_hash"],
            "source_uri": f"corpus:{p['source_id']}:{p['external_id']}",
            "resolution_path": json.dumps(resolution_path(p)),
            "tenant_id": TENANT,
        })
    return out


def bind(paper_ids: list[str], *, run_id: str, dry_run: bool = False) -> dict:
    eng = engine()
    with eng.connect() as conn:
        conn.execute(text("SELECT set_config('app.tenant', :t, true)"), {"t": TENANT})
        papers = [dict(r) for r in conn.execute(
            _PAPERS, {"paper_ids": paper_ids}).mappings()]
        already = {r[0] for r in conn.execute(
            _EXISTING, {"tenant": TENANT, "paper_ids": paper_ids}).all()}

    missing = [p for p in paper_ids if p not in {x["paper_id"] for x in papers}]
    fresh = [p for p in papers if p["paper_id"] not in already]
    rows = rows_for(fresh, run_id)
    unknown_form = [p["paper_id"] for p in fresh if p["task_type"] not in TASKS]

    if not dry_run and rows:
        with eng.begin() as conn:
            conn.execute(text("SELECT set_config('app.tenant', :t, true)"), {"t": TENANT})
            # The corpus states whose paper this is, so the machine may make the move a teacher
            # would otherwise make. `app.actor_type` stays machine and the transition trigger is
            # satisfied because unbound -> bound is not the move it reserves for a person.
            conn.execute(text("SELECT set_config('app.actor_type', 'machine', true)"))
            for r in rows:
                conn.execute(_INSERT, r)
                conn.execute(_BIND, {"artifact_id": r["artifact_id"]})

    return {
        "asked": len(paper_ids),
        "created": 0 if dry_run else len(rows),
        "would_create": len(rows) if dry_run else 0,
        # Already bound is the normal case on a second wave, not a problem.
        "already_bound": len(already),
        # Both named rather than counted: a paper the corpus does not have, and one whose form we
        # cannot tell, are different failures and both need a person.
        "not_in_corpus": missing,
        "unknown_task_form": unknown_form,
        "tenant": TENANT,
        "dry_run": dry_run,
    }


def main() -> None:
    """Paper ids arrive on stdin, from `corpus.draw_anchor --json`.

        python -m corpus.draw_anchor --json | python -m scoring.bind_corpus --wave 1

    NOT an import of `corpus.anchor`. Modules integrate through produced tables and process
    boundaries, never through imports — the boundary test caught the first version of this file
    reaching into the corpus module for the draw. The seam is better operationally too: the draw
    is printed and can be looked at before anything is bound.
    """
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--wave", type=int, default=1,
                    help="which wave of the piped draw to bind (1 or 2)")
    ap.add_argument("--run-id", default=None, help="default: a new id per invocation")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    payload = json.load(sys.stdin)
    key = f"wave{a.wave}"
    if key not in payload:
        raise SystemExit(
            f"the draw on stdin has no {key!r} — it carries {sorted(payload)}. Pipe it from "
            f"`python -m corpus.draw_anchor --json`.")
    ids = payload[key]
    if not ids:
        raise SystemExit(f"{key} is empty; nothing to bind.")

    print(json.dumps(bind(ids, run_id=a.run_id or f"anchor-{uuid7()[:8]}",
                          dry_run=a.dry_run), indent=1))


if __name__ == "__main__":
    main()
