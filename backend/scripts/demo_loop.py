"""The whole path, end to end, in one command — so trying something is cheap.

    python -m scripts.demo_loop --as "Tim Kinkead"            # the full loop, ~$0.50
    python -m scripts.demo_loop --as "Tim" --reset            # tear it all down first
    python -m scripts.demo_loop --as "Tim" --stop-at bind     # no model calls, no cost
    python -m scripts.demo_loop --reset-only                  # just tear down

WHY THIS EXISTS. One iteration was five commands, a browser step and a redeploy, which is enough
friction that you stop trying things — and a system nobody pokes at is a system whose problems are
all still in it. This is the same entry points a person would run, in order, with one summary at
the end.

A SCRIPT, NOT A MODULE. `backend/scripts/` is tooling and exempt from the boundary rule, which is
why this may import from six modules when none of them may import each other. It owns no tables and
makes no decisions; every write here happens inside somebody else's entry point.

WHAT IT DOES NOT DO is skip the gate. `--as` is required for the same reason `intake.gate` requires
it: the confirmation is a separate act by a named person, and this script performs it as you rather
than around you. Your name lands in `intake_manifest.confirmed_by` exactly as it would from the
screen. If that ever feels like a formality, that is the moment the gate has stopped working.

STOP-AT is the cost control. `--stop-at bind` exercises reading, reconciliation, the gate and
binding without a single model call, which is the loop you want when changing anything upstream of
scoring — a rubric's traits, the candidate floor, the prompt classifier. Only `score` and `compose`
spend money.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import tempfile
import time

STAGES = ("seed", "read", "confirm", "bind", "score", "compose")
COSTS_MONEY = ("score", "compose")


def _step(name: str, fn):
    """Run one stage, time it, and keep going only while nothing has failed."""
    started = time.time()
    try:
        result = fn()
    except Exception as exc:                       # a stage that fails stops the loop, loudly
        return {"stage": name, "ok": False, "seconds": round(time.time() - started, 1),
                "error": f"{type(exc).__name__}: {exc}"}
    return {"stage": name, "ok": True, "seconds": round(time.time() - started, 1),
            "result": result}


def reset() -> dict:
    """Tear down everything the fixture made, in dependency order.

    Artifacts and their events first, then the registry, then the roster — a purge that ran the
    other way round would trip a foreign key halfway and leave the database in a state neither
    empty nor seeded, which is the worst of both for somebody trying to iterate.
    """
    from intake import gate  # noqa: F401  — import here so --help works without a database
    from registry import seed_demo as registry_seed
    from roster import seed_demo as roster_seed
    from scoring import seed_demo as scoring_seed

    # `include_intake_derived` because `bind` stamps the MANIFEST id as an artifact's run, not
    # the fixture's RUN_ID — so run-scoping alone left every bind-created artifact behind while
    # reporting a tidy count of the few it did remove.
    out = {"artifacts": scoring_seed.purge(include_intake_derived=True),
           "registry": registry_seed.purge(),
           "roster": roster_seed.purge()}
    # The manifests themselves: intake rows outlive an artifact purge, and a stale unconfirmed
    # read left behind would sit in the Folders list forever looking like work to do.
    from sqlalchemy import text

    from intake._db import engine
    with engine().begin() as conn:
        conn.execute(text("SELECT set_config('app.tenant', 'public', true)"))
        files = conn.execute(text("DELETE FROM intake_file")).rowcount
        manifests = conn.execute(text("DELETE FROM intake_manifest")).rowcount
    out["intake"] = {"intake_file": files, "intake_manifest": manifests}

    # WHAT IS STILL THERE, not what was attempted. Three teardown bugs in this session each
    # deleted some rows, returned a number, and left the ones that mattered — a `demo-` prefix
    # nothing carried any more, a table added after the delete list was written, and a run id the
    # creation path had stopped using. A count of survivors cannot make that mistake.
    left = scoring_seed.verify(include_intake_derived=True)
    out["still_there"] = left
    if any(left.values()):
        raise RuntimeError(
            f"the teardown reported success and left rows behind: {left}. The purge predicate "
            f"does not cover what the creation path writes.")
    return out


def run(*, who: str, folder: pathlib.Path, stop_at: str, tenant: str) -> list[dict]:
    from intake import read_folder
    from intake._db import engine as intake_engine
    from intake.gate import confirm
    from registry import seed_demo as registry_seed
    from roster import seed_demo as roster_seed
    from scoring import bind, compose, run_scoring, seed_demo as scoring_seed
    from scoring.prompts import fingerprint

    steps, state = [], {}
    wanted = STAGES[: STAGES.index(stop_at) + 1]

    def seed():
        roster = roster_seed.seed()
        rubric = registry_seed.seed(fingerprint())
        papers = scoring_seed.seed(folder)
        if rubric["blocking"]:
            raise RuntimeError(f"the linter refused the rubric: {rubric['blocking']}")
        return {"students": len(roster["students"]), "traits": len(rubric["traits"]),
                "published": rubric["published"], "files": len(papers["files"]),
                "advisory": len(rubric["advisory"]),
                "acknowledged": len(rubric["acknowledged"])}

    def read():
        r = read_folder.read(folder=folder, tenant=tenant,
                             section_id=roster_seed.SECTION_ID,
                             task_id=registry_seed.TASK_ID, iteration="final",
                             window_label="fall 2026", read_by=who)
        state["manifest_id"] = r["manifest_id"]
        return {k: r[k] for k in ("manifest_id", "files", "roster", "inferred_rate", "by_status")}

    def confirm_set():
        from sqlalchemy import text
        with intake_engine().begin() as conn:
            conn.execute(text("SELECT set_config('app.tenant', :t, true)"), {"t": tenant})
            n = confirm(conn, state["manifest_id"], who, tenant)
        if n != 1:
            raise RuntimeError("the read was not waiting — already confirmed, or gone")
        return {"confirmed_by": who, "manifest_id": state["manifest_id"]}

    runners = {
        "seed": seed,
        "read": read,
        "confirm": confirm_set,
        "bind": lambda: bind.bind_pending(tenant=tenant),
        "score": lambda: run_scoring.score_pending(
            tenant=tenant, config_key=registry_seed.CONFIG_KEY),
        "compose": lambda: compose.compose_pending(tenant=tenant),
    }

    for stage in wanted:
        step = _step(stage, runners[stage])
        steps.append(step)
        if not step["ok"]:
            break
    return steps


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--as", dest="who", default=None,
                    help="who is confirming the folder. Required unless --reset-only")
    ap.add_argument("--folder", default=None, help="default: a fresh temp directory")
    ap.add_argument("--tenant", default="public")
    ap.add_argument("--reset", action="store_true", help="tear everything down first")
    ap.add_argument("--reset-only", action="store_true", help="tear down and stop")
    ap.add_argument("--stop-at", choices=STAGES, default="compose",
                    help="`bind` runs the whole path with no model calls and no cost")
    args = ap.parse_args()

    out: dict = {}
    if args.reset or args.reset_only:
        out["reset"] = reset()
    if args.reset_only:
        print(json.dumps(out, indent=1))
        return

    if not args.who:
        ap.error("--as is required: the confirmation is a named person's, and this performs it "
                 "as you rather than around you")

    folder = pathlib.Path(args.folder) if args.folder else pathlib.Path(
        tempfile.mkdtemp(prefix="sip-loop-"))
    steps = run(who=args.who, folder=folder, stop_at=args.stop_at, tenant=args.tenant)

    out["folder"] = str(folder)
    out["steps"] = steps
    out["ok"] = all(s["ok"] for s in steps)
    out["seconds"] = round(sum(s["seconds"] for s in steps), 1)
    spent = [s["stage"] for s in steps if s["stage"] in COSTS_MONEY and s["ok"]]
    out["stages_that_cost_money"] = spent or "none — nothing called a model"
    print(json.dumps(out, indent=1, default=str))
    if not out["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
