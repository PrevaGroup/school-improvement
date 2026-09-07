"""Author the fixture rubric, lint it, and publish it only if the linter allows.

    python -m registry.seed_demo --prompt-versions "$(python -m scoring.prompts)"
    python -m registry.seed_demo --acknowledge RULE SUBJECTS REASON BY
    python -m registry.seed_demo --purge

THIS FILE EXISTS BECAUSE THE LINTER DID NOT. `registry/lint.py` is a dozen rules, fully tested, and
until it was wired here it was called by nothing but its own test file. Six node versions went to
`published` in the first end-to-end run without one of them running. A rule that is not on the path
is not a rule.

Publication is therefore two steps, and that is the real shape rather than a fixture convenience:
versions insert as `draft`, the registry is read BACK OUT of the database, lint runs against what is
actually stored, and only then do drafts become `published`. Blocking findings refuse and leave the
drafts — a draft can be fixed, a published version cannot.

## Identifiers carry no meaning, and that is the fix for `demo-ci`

The old identifiers made one string do three jobs, and all three were wrong at once.

`demo-` was a LIFECYCLE fact wedged into an IDENTITY. An identifier that encodes facts invites
people to read the facts off it — and then the fact changes, and the identifier is left asserting
something false about a row nobody can safely rename. It was load-bearing for deletion too, since
`--purge` matched the prefix: three responsibilities in one string, none of them separable.

`ci` was an identifier standing in for a NAME. Nobody can read it, and a person who has to guess
what one identifier means will eventually guess wrong about another.

So the identifier is a UUID and means nothing at all. The name is `criterion_label` — "Controlling
idea" — which is what a human reads. The publisher's own short code goes in `external_ref`, where
"ci" is CoreTools' business and never ours. And the fixture is scoped by its RUBRIC rather than by
a prefix: everything hangs off one rubric identifier, so `--purge` walks the graph.

The fixture's UUIDs are derived with `uuid5` from a fixed namespace, so re-seeding is idempotent and
a trait keeps its identifier across runs. Real content does not work this way — a product manager
issues an identifier once, deliberately. A deterministic derivation is right for a fixture that must
be reproducible and wrong for anything that must be unique forever.

## Why the prompt versions come in from outside

A scoring configuration stamps the prompt fingerprint of the pipeline it was promoted against, and
that value belongs to `scoring`, not here — registry may not import it. Passing it on the command
line is not a workaround for the boundary rule; it is what promotion actually is. An administrator
reads the pipeline's identity off a release and records it. If the two ever disagree, `run_scoring`
refuses to score rather than quietly using a rater nobody approved.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import uuid
from dataclasses import replace

from sqlalchemy import text

from ._db import engine
from .lint import ADVISORY, BLOCKING, Registry, blocks_publication, lint

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "freespeech_rubric.json"

# A fixed namespace, so the fixture's identifiers are stable across re-seeds. Content authored for
# real gets a fresh uuid4 from a person, once, and never a derivation.
NS = uuid.UUID("6f2a1c94-0d3b-4f8e-9a71-5c2d8e4b17aa")

RUBRIC_ID = str(uuid.uuid5(NS, "rubric:ldc-argumentation-11-12"))
SKILL_ID = str(uuid.uuid5(NS, "skill:WHST.11-12.1"))
CONFIG_ID = str(uuid.uuid5(NS, "configuration:writing-default"))

# Operational keys rather than reference identities: readable on purpose, and scoped by the rubric
# rather than by anything spelled into them.
TASK_ID = "fs10-oped"
SITE_ID = "fs10-oped-final"
DRAFT_SITE_ID = "fs10-oped-draft"
CONFIG_KEY = "writing-default"
MODEL_ID = "claude-opus-5"
EFFORT = "high"

RUBRIC_NAME = "LDC Student Work Rubric — Argumentation Task"
PUBLISHER = "Literacy Design Collaborative"
GRADE_BAND = "11-12"
STANDARD = "WHST.11-12.1"


def trait_id(external_ref: str) -> str:
    """The identifier for one fixture trait. Derived, so re-seeding is idempotent."""
    return str(uuid.uuid5(NS, f"trait:{external_ref}"))


def load() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf8"))


def _read_acknowledgments(conn) -> dict[str, dict]:
    """The recorded judgments, keyed the way lint() looks them up."""
    return {f"{a['rule']}:{a['subject']}": dict(a) for a in conn.execute(text(
        "SELECT rule, subject, reason, acknowledged_by, decision_id"
        "  FROM registry_lint_acknowledgment")).mappings()}


def _read_registry(conn, acks: dict[str, dict]) -> Registry:
    """Load what is actually stored, so lint checks the database rather than our intentions."""
    def rows(sql: str) -> list[dict]:
        return [dict(r) for r in conn.execute(text(sql)).mappings()]

    return Registry(
        skills=rows("SELECT skill_id, standard_code, sub_code, statement, derivation, grade_band,"
                    " rubric_id FROM registry_skill"),
        rubrics=rows("SELECT rubric_id, name, publisher, grade_band, status FROM registry_rubric"),
        rubric_traits=rows("SELECT rubric_id, node_id, ordinal FROM registry_rubric_trait"),
        nodes=rows("SELECT node_id, standard_code, criterion_label, grade_band, scale_categories,"
                   " kind, source, external_ref FROM registry_node"),
        versions=rows("SELECT node_version_id, node_id, version, descriptors, status,"
                      " change_note, construct_unchanged_ack FROM registry_node_version"),
        tasks=rows("SELECT task_id, module_key, name, ordinal, grade_band, standards"
                   " FROM registry_task"),
        sites=rows("SELECT site_id, task_id, iteration, is_measurement_occasion, rubric_id"
                   " FROM registry_scoring_site"),
        site_nodes=rows("SELECT site_id, node_id, ordinal FROM registry_scoring_site_node"),
        # Without this the advisory class is a warning log: lint() drops an advisory finding whose
        # "rule:subject" appears here, and nothing else populates it.
        acknowledgments={k: v["reason"] for k, v in acks.items()},
    )


def seed(prompt_versions: dict) -> dict:
    fx = load()
    definition_hash = hashlib.sha256(
        json.dumps({"model_id": MODEL_ID, "effort": EFFORT, "prompt_versions": prompt_versions,
                    "normalization_version": "1"}, sort_keys=True,
                   separators=(",", ":")).encode("utf8")).hexdigest()[:32]

    with engine().begin() as conn:
        conn.execute(text("SELECT set_config('app.tenant', 'public', true)"))

        conn.execute(text("""
            INSERT INTO registry_rubric (rubric_id, name, publisher, source, grade_band,
                                         external_ref, status)
            VALUES (:r, :n, :p, :src, :gb, 'ldc-argumentation-11-12', 'draft')
            ON CONFLICT (rubric_id) DO NOTHING"""),
            {"r": RUBRIC_ID, "n": RUBRIC_NAME, "p": PUBLISHER, "gb": GRADE_BAND,
             "src": "CoreTools export 2024-09-23 (fixture — synthetic papers, not student work)"})

        # `whole`, not `clause`: this treats WHST.11-12.1 as one skill rather than splitting it,
        # and a split nobody made needs nobody's name on it.
        conn.execute(text("""
            INSERT INTO registry_skill (skill_id, standard_code, sub_code, statement, derivation,
                                        grade_band, rubric_id, source)
            VALUES (:s, :std, NULL, :stmt, 'whole', :gb, :r, 'fixture')
            ON CONFLICT (skill_id) DO NOTHING"""),
            {"s": SKILL_ID, "std": STANDARD, "gb": GRADE_BAND, "r": RUBRIC_ID,
             "stmt": "Write arguments focused on discipline-specific content."})

        conn.execute(text("""
            INSERT INTO registry_task (task_id, module_key, name, ordinal, grade_band, standards)
            VALUES (:t, 'free-speech', 'Culminating op-ed', 1, :gb, NULL)
            ON CONFLICT (task_id) DO NOTHING"""), {"t": TASK_ID, "gb": GRADE_BAND})

        for site, iteration, occasion in ((DRAFT_SITE_ID, "draft", False),
                                          (SITE_ID, "final", True)):
            conn.execute(text("""
                INSERT INTO registry_scoring_site
                    (site_id, task_id, rubric_id, iteration, is_measurement_occasion, note)
                VALUES (:s, :t, :r, :i, :o, 'fixture — synthetic papers, not student work')
                ON CONFLICT (site_id) DO NOTHING"""),
                {"s": site, "t": TASK_ID, "r": RUBRIC_ID, "i": iteration, "o": occasion})

        for ordinal, node in enumerate(fx["nodes"]):
            nid = trait_id(node["id"])
            cats = sorted(float(k) if "." in k else int(k) for k in node["levels"])
            conn.execute(text("""
                INSERT INTO registry_node (node_id, standard_code, criterion_label, grade_band,
                                           scale_categories, kind, source, external_ref)
                VALUES (:n, :std, :label, :gb, CAST(:cats AS jsonb),
                        'diagnostic_only', :src, :ref)
                ON CONFLICT (node_id) DO NOTHING"""),
                {"n": nid, "std": STANDARD, "label": node["name"], "gb": GRADE_BAND,
                 "cats": json.dumps(cats), "src": node.get("source", "fixture"),
                 # "ci" belongs to CoreTools. It is a reference, never an identity.
                 "ref": node["id"]})
            conn.execute(text("""
                INSERT INTO registry_rubric_trait (rubric_id, node_id, ordinal)
                VALUES (:r, :n, :o) ON CONFLICT DO NOTHING"""),
                {"r": RUBRIC_ID, "n": nid, "o": ordinal})
            # DRAFT. Publication is the linter's decision, below, not this loop's.
            conn.execute(text("""
                INSERT INTO registry_node_version
                    (node_version_id, node_id, version, descriptors, status, change_note)
                VALUES (:v, :n, 1, CAST(:d AS jsonb), 'draft', 'fixture seed')
                ON CONFLICT (node_version_id) DO NOTHING"""),
                {"v": f"{nid}:1", "n": nid, "d": json.dumps(node["levels"])})
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
                    'fixture-seed',
                    'Fixture configuration for the end-to-end run. Not a promotion.')
            ON CONFLICT (config_id) DO NOTHING"""),
            {"c": CONFIG_ID, "k": CONFIG_KEY, "m": MODEL_ID, "e": EFFORT,
             "pv": json.dumps(prompt_versions), "h": definition_hash})

        acks = _read_acknowledgments(conn)
        registry = _read_registry(conn, acks)
        findings = lint(registry)
        blocked = blocks_publication(findings)

        # Lint AGAIN with no acknowledgments, to name what was cleared and by whose decision.
        # Without this an acknowledged registry reports identically to a spotless one, which is
        # precisely the difference the two severity classes exist to preserve: a reader must be
        # able to see a judgment that was made rather than a check that was skipped.
        cleared = [f for f in lint(replace(registry, acknowledgments={})) if f not in findings]

        drafts = conn.execute(text(
            "SELECT count(*) FROM registry_node_version v"
            "  JOIN registry_rubric_trait t ON t.node_id = v.node_id"
            " WHERE t.rubric_id = :r AND v.status = 'draft'"), {"r": RUBRIC_ID}).scalar_one()
        published = 0
        if drafts and not blocked:
            published = conn.execute(text("""
                UPDATE registry_node_version v SET status = 'published'
                  FROM registry_rubric_trait t
                 WHERE t.node_id = v.node_id AND t.rubric_id = :r AND v.status = 'draft'"""),
                {"r": RUBRIC_ID}).rowcount
            conn.execute(text(
                "UPDATE registry_rubric SET status = 'published' WHERE rubric_id = :r"),
                {"r": RUBRIC_ID})

    if blocked:
        note = f"{drafts} version(s) left as DRAFT — the linter refused publication"
    elif published:
        note = f"{published} version(s) published"
    else:
        note = "nothing to publish — no drafts were waiting"

    return {
        "rubric_id": RUBRIC_ID, "rubric": RUBRIC_NAME, "skill_id": SKILL_ID,
        "task": TASK_ID, "sites": [DRAFT_SITE_ID, SITE_ID],
        "traits": {n["name"]: trait_id(n["id"]) for n in fx["nodes"]},
        "config_key": CONFIG_KEY, "config_id": CONFIG_ID,
        "blocking": [str(f) for f in findings if f.severity == BLOCKING],
        "advisory": [str(f) for f in findings if f.severity == ADVISORY],
        "acknowledged": [
            {"finding": str(f),
             "decision": acks.get(f"{f.rule}:{f.subject}", {}).get("decision_id"),
             "by": acks.get(f"{f.rule}:{f.subject}", {}).get("acknowledged_by"),
             "reason": acks.get(f"{f.rule}:{f.subject}", {}).get("reason")}
            for f in cleared],
        "published": published,
        "note": note,
    }


def acknowledge(rule: str, subjects: list[str], reason: str, by: str) -> dict:
    """Record ONE judgment answering one or more advisory findings.

    The linter says what it cannot decide; this is where somebody decides it. Two things are
    deliberate. The REASON is stored, not the fact of an acknowledgment — "acknowledged" alone is
    indistinguishable from the check having been skipped, which is the whole difference the two
    severity classes exist to preserve, and a CHECK refuses a reason under twelve characters. And
    several subjects share one `decision_id`, because a rubric row that stacks conditionals in all
    four cells produces four findings and gets one review; four unlinked rows would later read as
    four reviews. Same reasoning as `score_event.set_override_id`.
    """
    decision_id = f"dec-{uuid.uuid4().hex[:12]}"
    with engine().begin() as conn:
        for subject in subjects:
            conn.execute(text("""
                INSERT INTO registry_lint_acknowledgment
                    (ack_id, rule, subject, node_version_id, reason, acknowledged_by, decision_id)
                VALUES (:i, :r, :s, :v, :why, :who, :d)
                ON CONFLICT (rule, subject) DO UPDATE
                    SET reason = EXCLUDED.reason, acknowledged_by = EXCLUDED.acknowledged_by,
                        decision_id = EXCLUDED.decision_id, created_at = now()"""),
                {"i": f"{rule}:{subject}", "r": rule, "s": subject,
                 "v": subject if ":" not in subject else subject.rsplit(":", 1)[0],
                 "why": reason, "who": by, "d": decision_id})
    return {"decision_id": decision_id, "rule": rule, "subjects": subjects, "by": by,
            "reason": reason}


def purge() -> dict:
    """Remove the fixture by walking the graph from its rubric, not by matching a name.

    A trait shared with another rubric is NOT deleted, and that is the many-to-many being taken
    seriously rather than worked around. Removing a trait because this fixture happened to
    introduce it would silently destroy an identifier some other rubric had declared common with
    it — which is the one thing the node rule exists to prevent.
    """
    counts: dict[str, int] = {}
    with engine().begin() as conn:
        conn.execute(text("SELECT set_config('app.tenant', 'public', true)"))
        sites = [r[0] for r in conn.execute(text(
            "SELECT site_id FROM registry_scoring_site WHERE rubric_id = :r"),
            {"r": RUBRIC_ID}).all()]
        traits = [r[0] for r in conn.execute(text(
            "SELECT node_id FROM registry_rubric_trait WHERE rubric_id = :r"),
            {"r": RUBRIC_ID}).all()]

        counts["registry_scoring_site_node"] = conn.execute(text(
            "DELETE FROM registry_scoring_site_node WHERE site_id = ANY(CAST(:s AS text[]))"),
            {"s": sites}).rowcount
        counts["registry_scoring_site"] = conn.execute(text(
            "DELETE FROM registry_scoring_site WHERE rubric_id = :r"), {"r": RUBRIC_ID}).rowcount
        counts["registry_task"] = conn.execute(text(
            "DELETE FROM registry_task WHERE task_id = :t"), {"t": TASK_ID}).rowcount
        counts["registry_rubric_trait"] = conn.execute(text(
            "DELETE FROM registry_rubric_trait WHERE rubric_id = :r"), {"r": RUBRIC_ID}).rowcount

        # Only traits no OTHER rubric claims. A shared identifier is somebody else's anchor.
        still_claimed = {r[0] for r in conn.execute(text(
            "SELECT node_id FROM registry_rubric_trait WHERE node_id = ANY(CAST(:n AS text[]))"),
            {"n": traits}).all()}
        orphans = [t for t in traits if t not in still_claimed]

        counts["registry_lint_acknowledgment"] = conn.execute(text(
            "DELETE FROM registry_lint_acknowledgment"
            " WHERE split_part(subject, ':', 1) = ANY(CAST(:n AS text[]))"),
            {"n": orphans}).rowcount
        counts["registry_node_version"] = conn.execute(text(
            "DELETE FROM registry_node_version WHERE node_id = ANY(CAST(:n AS text[]))"),
            {"n": orphans}).rowcount
        counts["registry_node"] = conn.execute(text(
            "DELETE FROM registry_node WHERE node_id = ANY(CAST(:n AS text[]))"),
            {"n": orphans}).rowcount
        counts["registry_node_kept_because_shared"] = len(still_claimed)

        counts["registry_skill"] = conn.execute(text(
            "DELETE FROM registry_skill WHERE skill_id = :s"), {"s": SKILL_ID}).rowcount
        counts["registry_scoring_configuration"] = conn.execute(text(
            "DELETE FROM registry_scoring_configuration WHERE config_id = :c"),
            {"c": CONFIG_ID}).rowcount
        counts["registry_rubric"] = conn.execute(text(
            "DELETE FROM registry_rubric WHERE rubric_id = :r"), {"r": RUBRIC_ID}).rowcount
    return counts


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--acknowledge", nargs=4, metavar=("RULE", "SUBJECTS", "REASON", "BY"),
                    help="record ONE judgment answering one or more advisory findings. SUBJECTS "
                         "is comma-separated; they share a decision id.")
    ap.add_argument("--prompt-versions",
                    help="the pipeline fingerprint, as JSON. Get it with "
                         "`python -m scoring.prompts`.")
    ap.add_argument("--purge", action="store_true")
    args = ap.parse_args()

    if args.purge:
        print(json.dumps(purge(), indent=1))
        return
    if args.acknowledge:
        rule, subjects, reason, by = args.acknowledge
        print(json.dumps(acknowledge(rule, [s.strip() for s in subjects.split(",") if s.strip()],
                                     reason, by), indent=1))
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
