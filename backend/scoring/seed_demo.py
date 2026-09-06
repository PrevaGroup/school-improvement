"""Seed the artifacts for an end-to-end run, and remove them again.

    python -m registry.seed_demo --prompt-versions "$(python -m scoring.prompts)"   # the rubric
    python -m scoring.seed_demo --text-dir /tmp/sip-demo                            # the papers
    python -m scoring.run_scoring --config-key writing-default                         # score
    python -m scoring.seed_demo --purge && python -m registry.seed_demo --purge     # clean up

TWO COMMANDS, NOT ONE, AND THAT IS THE POINT. This file used to seed the rubric too — six
`registry_node_version` rows inserted straight to `published` from the scoring module, bypassing
the linter that exists to gate exactly that. The import boundary test could not see it, because
there was no import; `tests/test_table_ownership.py` was written afterwards and does.

"A produced table is the contract" only means something if one module produces it. Two writers is
not a contract, it is a shared mutable global with a longer name. Authoring a rubric is registry's
job and scoring may read it, so the seed is split the same way the modules are.

The papers are synthetic — written for the slice-1 prototype, not handed in by anyone. There is no
real student writing in this subsystem and there will not be until a hardening phase.

## Identifiers here name a RUN, and that is a different thing from a trait identifier

`registry/seed_demo.py` explains why reference identifiers are meaningless UUIDs: a trait
identifier that spells `demo-ci` puts a lifecycle fact inside an identity, and identities have to
outlive the facts that were true when they were minted.

Artifacts are not reference content. An artifact belongs to a RUN, a run legitimately has a name,
and naming it is the point rather than a leak — so `--purge` scopes by `run_id` and the ids stay
readable. The distinction is worth holding onto: identity of reference content must mean nothing,
identity of an operational row may say what produced it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import tempfile

from sqlalchemy import text

from ._db import engine

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "freespeech_papers.json"

RUN_ID = "fixture-run-1"
SECTION_ID = "fixture-section-1"
# Duplicated from registry.seed_demo rather than imported — the boundary rule, and the same honest
# duplication `_db.py` and `_ids.py` already carry. A binding key NAMES a task; it does not import
# one. `tests/test_seed_demo.py` asserts the two files still agree.
TASK_ID = "fs10-oped"
CONFIG_KEY = "writing-default"


def load() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf8"))


def seed(text_dir: pathlib.Path) -> dict:
    fx = load()
    text_dir.mkdir(parents=True, exist_ok=True)
    artifacts = []

    with engine().begin() as conn:
        conn.execute(text("SELECT set_config('app.tenant', 'public', true)"))
        conn.execute(text("SELECT set_config('app.actor_type', 'teacher', true)"))
        conn.execute(text("SELECT set_config('app.actor_id', 'fixture-seed', true)"))

        for key, paper in fx["papers"].items():
            body = paper["text"]
            path = text_dir / f"{key}.txt"
            path.write_text(body, encoding="utf8")
            aid = f"{RUN_ID}:{key}"
            conn.execute(text("""
                INSERT INTO artifact (artifact_id, run_id, student_id, section_id, task_id,
                                      iteration, window_label, content_hash, source_uri,
                                      resolution_path, state, tenant_id, visibility)
                VALUES (:a, :r, :s, :sec, :t, 'final', 'fall 2026', :h, :uri,
                        CAST(:rp AS jsonb), 'unbound', 'public', 'public')
                ON CONFLICT (artifact_id) DO NOTHING"""),
                {"a": aid, "r": RUN_ID, "s": f"student-{key}", "sec": SECTION_ID,
                 "t": TASK_ID, "h": hashlib.sha256(body.encode("utf8")).hexdigest(),
                 "uri": str(path),
                 "rp": json.dumps({k: "looked_up" for k in
                                   ("student", "section", "task", "iteration")})})
            # unbound -> bound as a TEACHER, through the trigger, rather than inserting straight
            # into `bound`. The transition trigger is BEFORE UPDATE, so an INSERT bypasses the
            # state machine entirely — seeding the end state would have the demo exercising a path
            # no real artifact takes, and producing no audit row.
            conn.execute(text(
                "UPDATE artifact SET state = 'bound' WHERE artifact_id = :a AND state = 'unbound'"),
                {"a": aid})
            artifacts.append(aid)

    return {"artifacts": artifacts, "text_dir": str(text_dir), "config_key": CONFIG_KEY}


# Children before the parent. Every table that references `artifact` has to be listed, and
# `test_the_purge_deletes_every_table_that_references_an_artifact` derives that list from the
# models rather than trusting this one — `artifact_composition` arrived in migration 0017 and this
# function was not updated, so the next purge failed on a foreign key with two papers already
# scored. A tuple that has to be remembered is a tuple that will be forgotten.
#
# The scope column differs: score_event and artifact carry `run_id` directly, while the two audit
# tables only reference the artifact. Scoping those by a subquery keeps one run's rows together
# even when another run's artifacts exist beside them.
_PURGE_ORDER = (
    ("artifact_composition", "artifact"),
    ("score_event", "run"),
    ("artifact_state_transition", "artifact"),
    ("artifact", "run"),
)

_BY_RUN = "run_id = :run"
_BY_ARTIFACT = "artifact_id IN (SELECT artifact_id FROM artifact WHERE run_id = :run)"

# Both are append-only by trigger, so the triggers come off for this transaction. That is why
# purging is a maintenance script and not something the pipeline can reach: the append-only rule
# must not be negotiable from inside the pipeline, and a cleanup path the scorer could call would
# make it so.
_APPEND_ONLY = (("score_event", "trg_score_event_append_only"),
                ("artifact_composition", "trg_artifact_composition_append_only"))


def purge() -> dict:
    """Remove one run's artifacts, their events and their review packets.

    No try/finally around the trigger disable. ALTER TABLE is transactional in Postgres, so a
    failure rolls the DISABLE back with everything else and the triggers are never left off. The
    finally that used to be here could not have run anyway — the transaction was already aborted,
    so it raised InFailedSqlTransaction on top of the real error and buried it.
    """
    counts = {}
    with engine().begin() as conn:
        conn.execute(text("SELECT set_config('app.tenant', 'public', true)"))
        for table, trigger in _APPEND_ONLY:
            conn.execute(text(f"ALTER TABLE {table} DISABLE TRIGGER {trigger}"))

        for table, scope in _PURGE_ORDER:
            where = _BY_RUN if scope == "run" else _BY_ARTIFACT
            counts[table] = conn.execute(
                text(f"DELETE FROM {table} WHERE {where}"), {"run": RUN_ID}).rowcount

        for table, trigger in _APPEND_ONLY:
            conn.execute(text(f"ALTER TABLE {table} ENABLE TRIGGER {trigger}"))
    return counts


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--text-dir", default=None,
                    help="where to write the papers (default: a temp directory)")
    ap.add_argument("--purge", action="store_true",
                    help=f"remove run {RUN_ID} and everything it produced (the rubric is "
                         f"`python -m registry.seed_demo --purge`)")
    args = ap.parse_args()

    if args.purge:
        print(json.dumps(purge(), indent=1))
        return
    d = pathlib.Path(args.text_dir) if args.text_dir else pathlib.Path(
        tempfile.mkdtemp(prefix="sip-demo-"))
    print(json.dumps(seed(d), indent=1))
    print(f"\nNow: python -m scoring.run_scoring --config-key {CONFIG_KEY}")


if __name__ == "__main__":
    main()
