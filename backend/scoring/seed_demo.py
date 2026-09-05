"""Seed enough registry and artifact rows to run the pipeline end to end, then remove them.

    python -m scoring.seed_demo --text-dir /tmp/sip-demo          # seed
    python -m scoring.run_scoring --config-key demo-writing       # score
    python -m scoring.seed_demo --purge                           # remove every demo- row

Why this exists: every piece of the pipeline is tested and none of it has ever run. The unit
tests use a scripted rater, and the SQL smoke test provokes the triggers with fixtures that carry
no text. Neither one has made a model call, read a registry row, or watched an artifact change
state. That is a gap you can only close by doing it.

WHAT THIS IS NOT. The node identifiers here are prefixed `demo-` and marked `diagnostic_only`,
which is the kind that is excluded from linking and estimated sparsely. They are NOT the Free
Speech module's real node identifiers: those are an LDC product manager's to assign, once, and
never to be recycled — so a demo that squatted on one would poison the registry permanently in
exactly the way the node rule exists to prevent. `--purge` deletes only rows whose ids begin
`demo-`, and it deletes score_event rows through the artifact, not by editing them.

The papers are synthetic — written for the slice-1 prototype, not handed in by anyone. The
subsystem has no real student writing in it and will not until a hardening phase.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import tempfile

from sqlalchemy import text

from ._db import engine
from .prompts import fingerprint
from .rater import RaterIdentity

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "demo_freespeech.json"

PREFIX = "demo-"
TASK_ID = f"{PREFIX}fs10-oped"
SITE_ID = f"{PREFIX}fs10-oped-final"
SECTION_ID = f"{PREFIX}sec-1"
CONFIG_KEY = f"{PREFIX}writing"
CONFIG_ID = f"{PREFIX}cfg-1"
RUN_ID = f"{PREFIX}run-1"
MODEL_ID = "claude-opus-5"
EFFORT = "high"

# The demo scores the FINAL iteration and declares it the measurement occasion. A draft site is
# seeded too, deliberately not the occasion: it is the one place the draft/final distinction is
# visible as data rather than as prose, and a seed that only created the easy case would hide it.
DRAFT_SITE_ID = f"{PREFIX}fs10-oped-draft"


def load() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf8"))


def seed(text_dir: pathlib.Path) -> dict:
    fx = load()
    text_dir.mkdir(parents=True, exist_ok=True)

    identity = RaterIdentity(CONFIG_ID, MODEL_ID, EFFORT, fingerprint(), "1")
    node_ids = [f"{PREFIX}{n['id']}" for n in fx["nodes"]]

    with engine().begin() as conn:
        conn.execute(text("SELECT set_config('app.tenant', 'public', true)"))
        conn.execute(text("SELECT set_config('app.actor_type', 'teacher', true)"))
        conn.execute(text("SELECT set_config('app.actor_id', 'demo-seed', true)"))

        conn.execute(text("""
            INSERT INTO registry_task (task_id, module_key, name, ordinal, grade_band, standards)
            VALUES (:t, 'demo-free-speech', 'Culminating op-ed', 1, '11-12', NULL)
            ON CONFLICT (task_id) DO NOTHING"""), {"t": TASK_ID})

        for site, iteration, occasion in ((DRAFT_SITE_ID, "draft", False),
                                          (SITE_ID, "final", True)):
            conn.execute(text("""
                INSERT INTO registry_scoring_site
                    (site_id, task_id, iteration, is_measurement_occasion, note)
                VALUES (:s, :t, :i, :o, 'demo fixture — synthetic papers, not student work')
                ON CONFLICT (site_id) DO NOTHING"""),
                {"s": site, "t": TASK_ID, "i": iteration, "o": occasion})

        for ordinal, node in enumerate(fx["nodes"]):
            nid = f"{PREFIX}{node['id']}"
            cats = sorted(float(k) if "." in k else int(k) for k in node["levels"])
            conn.execute(text("""
                INSERT INTO registry_node (node_id, standard_code, criterion_label, grade_band,
                                           scale_categories, kind, source)
                VALUES (:n, :std, :label, '11-12', CAST(:cats AS jsonb), 'diagnostic_only', :src)
                ON CONFLICT (node_id) DO NOTHING"""),
                {"n": nid, "std": f"DEMO.{node['id'].upper()}", "label": node["name"],
                 "cats": json.dumps(cats), "src": node.get("source", "demo fixture")})
            conn.execute(text("""
                INSERT INTO registry_node_version
                    (node_version_id, node_id, version, descriptors, status, change_note)
                VALUES (:v, :n, 1, CAST(:d AS jsonb), 'published', 'demo seed')
                ON CONFLICT (node_version_id) DO NOTHING"""),
                {"v": f"{nid}-v1", "n": nid, "d": json.dumps(node["levels"])})
            for site in (DRAFT_SITE_ID, SITE_ID):
                conn.execute(text("""
                    INSERT INTO registry_scoring_site_node (site_id, node_id, ordinal)
                    VALUES (:s, :n, :o) ON CONFLICT DO NOTHING"""),
                    {"s": site, "n": nid, "o": ordinal})

        conn.execute(text("""
            INSERT INTO registry_scoring_configuration
                (config_id, config_key, version, model_id, effort, prompt_versions,
                 normalization_version, definition_hash, status, promoted_at, promoted_by,
                 rationale)
            VALUES (:c, :k, 1, :m, :e, CAST(:pv AS jsonb), '1', :h, 'active', now(),
                    'demo-seed', 'Demo configuration for the end-to-end run. Not a promotion.')
            ON CONFLICT (config_id) DO NOTHING"""),
            {"c": CONFIG_ID, "k": CONFIG_KEY, "m": MODEL_ID, "e": EFFORT,
             "pv": json.dumps(identity.prompt_versions), "h": identity.definition_hash})

        artifacts = []
        for key, paper in fx["papers"].items():
            body = paper["text"]
            path = text_dir / f"{PREFIX}{key}.txt"
            path.write_text(body, encoding="utf8")
            aid = f"{PREFIX}art-{key}"
            conn.execute(text("""
                INSERT INTO artifact (artifact_id, run_id, student_id, section_id, task_id,
                                      iteration, window_label, content_hash, source_uri,
                                      resolution_path, state, tenant_id, visibility)
                VALUES (:a, :r, :s, :sec, :t, 'final', 'fall 2026', :h, :uri,
                        CAST(:rp AS jsonb), 'unbound', 'public', 'public')
                ON CONFLICT (artifact_id) DO NOTHING"""),
                {"a": aid, "r": RUN_ID, "s": f"{PREFIX}stu-{key}", "sec": SECTION_ID,
                 "t": TASK_ID, "h": hashlib.sha256(body.encode("utf8")).hexdigest(),
                 "uri": str(path),
                 "rp": json.dumps({k: "looked_up" for k in
                                   ("student", "section", "task", "iteration")})})
            # unbound -> bound as a TEACHER, through the trigger, rather than inserting
            # straight into `bound`. An INSERT bypasses the state machine entirely (the trigger
            # is BEFORE UPDATE), so seeding the end state would leave the demo exercising a path
            # no real artifact takes and producing no audit row.
            conn.execute(text(
                "UPDATE artifact SET state = 'bound' WHERE artifact_id = :a AND state = 'unbound'"),
                {"a": aid})
            artifacts.append(aid)

    return {"task": TASK_ID, "sites": [DRAFT_SITE_ID, SITE_ID], "nodes": node_ids,
            "config_key": CONFIG_KEY, "artifacts": artifacts, "text_dir": str(text_dir)}


def purge() -> dict:
    """Remove every demo- row. score_event is append-only by trigger for UPDATE and DELETE, so a
    demo run's events are removed by dropping the trigger for this transaction — which is why
    this is a maintenance script and not something the pipeline can do."""
    with engine().begin() as conn:
        conn.execute(text("SELECT set_config('app.tenant', 'public', true)"))
        conn.execute(text("ALTER TABLE score_event DISABLE TRIGGER trg_score_event_append_only"))
        try:
            counts = {
                "score_event": conn.execute(text(
                    "DELETE FROM score_event WHERE artifact_id LIKE :p"), {"p": f"{PREFIX}%"}
                ).rowcount,
                "artifact_state_transition": conn.execute(text(
                    "DELETE FROM artifact_state_transition WHERE artifact_id LIKE :p"),
                    {"p": f"{PREFIX}%"}).rowcount,
                "artifact": conn.execute(text(
                    "DELETE FROM artifact WHERE artifact_id LIKE :p"), {"p": f"{PREFIX}%"}
                ).rowcount,
            }
        finally:
            conn.execute(text(
                "ALTER TABLE score_event ENABLE TRIGGER trg_score_event_append_only"))

        for table, col in (("registry_scoring_site_node", "site_id"),
                           ("registry_scoring_configuration", "config_id"),
                           ("registry_node_version", "node_version_id"),
                           ("registry_scoring_site", "site_id"),
                           ("registry_node", "node_id"),
                           ("registry_task", "task_id")):
            counts[table] = conn.execute(
                text(f"DELETE FROM {table} WHERE {col} LIKE :p"), {"p": f"{PREFIX}%"}).rowcount
    return counts


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--text-dir", default=None,
                    help="where to write the papers (default: a temp directory)")
    ap.add_argument("--purge", action="store_true", help="remove every demo- row and exit")
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
