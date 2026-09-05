"""Author the demo rubric, lint it, and publish it only if the linter allows.

    python -m registry.seed_demo --prompt-versions "$(python -m scoring.prompts)"
    python -m registry.seed_demo --purge

THIS FILE EXISTS BECAUSE THE LINTER DID NOT. `registry/lint.py` is eight rules, fully tested, and
until now it was called by nothing but its own test file. Six node versions went to `published` in
the first end-to-end run without any of them running. A rule that is not on the path is not a rule.

So publication is a two-step here, and that is the real shape rather than a demo convenience:
versions are inserted as `draft`, the registry is read BACK OUT of the database, lint runs against
what is actually stored, and only then do the drafts become `published`. Linting the in-memory
intent instead would check what we meant to write rather than what is there.

Blocking findings refuse publication and leave the drafts in place — which is the useful state,
because a draft can be fixed and a published version cannot. Advisory findings print and do not
block: they are judgments the linter cannot make, and in production they clear with a recorded
acknowledgment that becomes part of the version record.

WHY THE PROMPT VERSIONS COME IN FROM OUTSIDE. A scoring configuration stamps the prompt fingerprint
of the pipeline it was promoted against, and that value belongs to `scoring`, not here — registry
may not import it (modules integrate through tables). Passing it on the command line is not a
workaround for the boundary rule; it is what promotion actually is. An administrator reads the
pipeline's identity off a release and records it. If the two ever disagree, `run_scoring` refuses
to score rather than quietly using a rater nobody approved.

The `demo-` prefix is a safety property, not a naming convention: node identifiers are issued once
and never recycled, so a demo that squatted on a real one would poison the registry permanently,
and `--purge` deletes by prefix.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib

from sqlalchemy import text

from ._db import engine
from .lint import ADVISORY, BLOCKING, Registry, blocks_publication, lint

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "demo_freespeech_rubric.json"

PREFIX = "demo-"
TASK_ID = f"{PREFIX}fs10-oped"
SITE_ID = f"{PREFIX}fs10-oped-final"
DRAFT_SITE_ID = f"{PREFIX}fs10-oped-draft"
CONFIG_KEY = f"{PREFIX}writing"
CONFIG_ID = f"{PREFIX}cfg-1"
MODEL_ID = "claude-opus-5"
EFFORT = "high"


def load() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf8"))


def _read_registry(conn) -> Registry:
    """Load what is actually stored, so lint checks the database rather than our intentions."""
    def rows(sql: str) -> list[dict]:
        return [dict(r) for r in conn.execute(text(sql), {"p": f"{PREFIX}%"}).mappings()]

    return Registry(
        nodes=rows("SELECT node_id, standard_code, criterion_label, grade_band, scale_categories,"
                   " kind, source FROM registry_node WHERE node_id LIKE :p"),
        versions=rows("SELECT node_version_id, node_id, version, descriptors, status,"
                      " change_note, construct_unchanged_ack FROM registry_node_version"
                      " WHERE node_id LIKE :p"),
        tasks=rows("SELECT task_id, module_key, name, ordinal, grade_band, standards"
                   " FROM registry_task WHERE task_id LIKE :p"),
        sites=rows("SELECT site_id, task_id, iteration, is_measurement_occasion"
                   " FROM registry_scoring_site WHERE task_id LIKE :p"),
        site_nodes=rows("SELECT site_id, node_id, ordinal FROM registry_scoring_site_node"
                        " WHERE site_id LIKE :p"),
        # Without this the advisory class is a warning log: lint() drops an advisory finding whose
        # "rule:subject" appears here, and nothing else populates it.
        acknowledgments={f"{a['rule']}:{a['subject']}": a["reason"] for a in
                         rows("SELECT rule, subject, reason FROM registry_lint_acknowledgment"
                              " WHERE subject LIKE :p")},
    )


def seed(prompt_versions: dict) -> dict:
    fx = load()
    node_ids = [f"{PREFIX}{n['id']}" for n in fx["nodes"]]
    definition_hash = hashlib.sha256(
        json.dumps({"model_id": MODEL_ID, "effort": EFFORT, "prompt_versions": prompt_versions,
                    "normalization_version": "1"}, sort_keys=True,
                   separators=(",", ":")).encode("utf8")).hexdigest()[:32]

    with engine().begin() as conn:
        conn.execute(text("SELECT set_config('app.tenant', 'public', true)"))

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
            # DRAFT. Publication is the linter's decision, below, not this loop's.
            conn.execute(text("""
                INSERT INTO registry_node_version
                    (node_version_id, node_id, version, descriptors, status, change_note)
                VALUES (:v, :n, 1, CAST(:d AS jsonb), 'draft', 'demo seed')
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
             "pv": json.dumps(prompt_versions), "h": definition_hash})

        findings = lint(_read_registry(conn))
        blocked = blocks_publication(findings)

        if not blocked:
            published = conn.execute(text("""
                UPDATE registry_node_version SET status = 'published'
                 WHERE node_id LIKE :p AND status = 'draft'"""),
                {"p": f"{PREFIX}%"}).rowcount
        else:
            published = 0

    return {
        "task": TASK_ID, "sites": [DRAFT_SITE_ID, SITE_ID], "nodes": node_ids,
        "config_key": CONFIG_KEY, "config_id": CONFIG_ID,
        "blocking": [str(f) for f in findings if f.severity == BLOCKING],
        "advisory": [str(f) for f in findings if f.severity == ADVISORY],
        "published": published,
        "note": ("versions left as DRAFT — the linter refused publication" if blocked
                 else f"{published} version(s) published after a clean lint"),
    }


def purge() -> dict:
    counts = {}
    with engine().begin() as conn:
        conn.execute(text("SELECT set_config('app.tenant', 'public', true)"))
        for table, col in (("registry_scoring_site_node", "site_id"),
                           ("registry_scoring_configuration", "config_id"),
                           ("registry_node_version", "node_version_id"),
                           ("registry_scoring_site", "site_id"),
                           ("registry_node", "node_id"),
                           ("registry_task", "task_id")):
            counts[table] = conn.execute(
                text(f"DELETE FROM {table} WHERE {col} LIKE :p"), {"p": f"{PREFIX}%"}).rowcount
    return counts


def acknowledge(rule: str, subject: str, reason: str, by: str,
                node_version_id: str | None = None) -> None:
    """Record a judgment about one advisory finding.

    The linter says what it cannot decide; this is where somebody decides it. The reason is stored
    rather than the fact of an acknowledgment, because "acknowledged" alone is indistinguishable
    from the check having been skipped — which is the whole difference the two severity classes
    exist to preserve. A CHECK constraint refuses a reason under twelve characters.
    """
    with engine().begin() as conn:
        conn.execute(text("""
            INSERT INTO registry_lint_acknowledgment
                (ack_id, rule, subject, node_version_id, reason, acknowledged_by)
            VALUES (:i, :r, :s, :v, :why, :who)
            ON CONFLICT (rule, subject) DO UPDATE
                SET reason = EXCLUDED.reason, acknowledged_by = EXCLUDED.acknowledged_by,
                    created_at = now()"""),
            {"i": f"{rule}:{subject}", "r": rule, "s": subject, "v": node_version_id,
             "why": reason, "who": by})


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--acknowledge", nargs=4, metavar=("RULE", "SUBJECT", "REASON", "BY"),
                    help="record a judgment about one advisory finding and re-run the lint")
    ap.add_argument("--prompt-versions",
                    help='the pipeline fingerprint, as JSON. Get it with '
                         '`python -m scoring.prompts`.')
    ap.add_argument("--purge", action="store_true")
    args = ap.parse_args()

    if args.purge:
        print(json.dumps(purge(), indent=1))
        return
    if args.acknowledge:
        rule, subject, reason, by = args.acknowledge
        acknowledge(rule, subject, reason, by)
        print(json.dumps({"acknowledged": f"{rule}:{subject}", "by": by, "reason": reason},
                         indent=1))
        return
    if not args.prompt_versions:
        ap.error("--prompt-versions is required: the configuration records the prompt fingerprint "
                 "of the pipeline it was promoted against. `python -m scoring.prompts` prints it.")
    result = seed(json.loads(args.prompt_versions))
    print(json.dumps(result, indent=1))
    if result["blocking"]:
        raise SystemExit("the linter refused publication — the drafts are still there to fix")


if __name__ == "__main__":
    main()
