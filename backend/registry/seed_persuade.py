"""Publish PERSUADE 2.0's four rubrics into the registry.

    python -m registry.seed_persuade [--dry-run]

The instruments themselves are data in `registry/persuade_rubrics.py`, transcribed from the rating
forms in `docs/rubrics/`. This writes them, runs the linter, and publishes only what the linter
allows — the same discipline as `seed_demo`, for the same reason: a rubric that reached
`published` without passing the linter is a rubric nobody checked, and every score written against
it inherits that.

## Not a fixture

`seed_demo` writes synthetic papers and says so in every `source` field. This is a real published
instrument, used to score real student writing by real raters, and the anchor estimates that come
out of it are the ones a promotion decision will rest on. The `source` fields say that instead.

They do NOT say the licence. An earlier version of this file wrote "CC BY 4.0" into every rubric's
`source`, which was this project asserting somebody else's terms from memory — and a test locked
it in, so CI defended it. `TERMS_URL` points at the publisher, who can answer; see
`persuade_rubrics.TERMS_URL` and `corpus._shared.read_licence`.

## Six shared traits, written once

Lead, Position, Claim, Counterclaim, Rebuttal and Concluding summary appear in both element
rubrics under ONE identifier each. The node is inserted once and `registry_rubric_trait` gets two
rows — which is the many-to-many doing exactly what it exists for, and the only thing that can
place both halves of PERSUADE on one metric.

## A task and a scoring site per form — a reversal, and why

An earlier version of this file refused to write either, on the grounds that a task would put
corpus papers in the same shape as student work and they would eventually be counted as it. The
objection was right and the conclusion was wrong.

`run_scoring` resolves WHICH traits to score by joining `registry_scoring_site` on task and
iteration. That join is the seam. Routing around it would mean a second way of deciding which
traits apply to a paper, and two ways of deciding that is exactly how two scoring paths drift
until the severity estimated on one no longer describes the other.

What actually prevents corpus papers being counted as student work is the `corpus` TENANT
(migration 0032), not the absence of a task. Every artifact carries `tenant_id`, the console scopes
to `public`, and the counts are then right by construction rather than by a filter somebody
remembers.

Two tasks rather than two iterations of one: independent and text-dependent are different
instruments, not two attempts at the same one, and `iteration` means draft-versus-final everywhere
else in this system. The iteration here is `anchor`.

`is_measurement_occasion` is FALSE on both. These are reference papers, not a declared occasion in
anybody's class, and a true here would put them in an estimation frame that is about students.

## Still no skill

A skill is a sub-standard: a claim about what a standards document says. PERSUADE's holistic scale
is its own instrument and its elements are argumentative functions, neither of which is a
sub-standard of anything. `registry_skill.rubric_id` is nullable in the other direction — a skill
may have no rubric — and a rubric with no skill is equally legitimate. Writing one here would
assert an alignment nobody made.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import replace

from sqlalchemy import text

from ._db import engine
from .lint import ADVISORY, BLOCKING, blocks_publication, lint
from .persuade_rubrics import (TERMS_URL, all_rubrics, distinct_traits, elements,
                               holistic)
from .seed_demo import _read_acknowledgments, _read_registry

SOURCE = ("PERSUADE 2.0 rating forms, transcribed 2026-09-08 — terms as stated at "
          f"{TERMS_URL}")

# The scoring sites corpus papers bind to. Kept in step with `scoring.bind_corpus`,
# which writes the same task ids onto the artifacts.
CORPUS_TASK_PREFIX = "corpus:persuade20"


def seed(*, dry_run: bool = False) -> dict:
    rubrics = all_rubrics()
    traits = distinct_traits()

    with engine().begin() as conn:
        conn.execute(text("SELECT set_config('app.tenant', 'public', true)"))

        # Nodes first, ONCE each. A shared trait inserted twice would either conflict or — worse,
        # under a different id per rubric — become two traits that measure the same thing and can
        # never be brought onto one scale.
        for t in traits.values():
            conn.execute(text("""
                INSERT INTO registry_node (node_id, standard_code, criterion_label, grade_band,
                                           scale_categories, kind, source, external_ref)
                VALUES (:n, :std, :label, :gb, CAST(:cats AS jsonb), :kind, :src, :ref)
                ON CONFLICT (node_id) DO NOTHING"""),
                {"n": t["node_id"], "std": t["standard_code"], "label": t["criterion_label"],
                 "gb": t["grade_band"], "cats": json.dumps(t["scale_categories"]),
                 "kind": t["kind"], "src": t["source"], "ref": t["external_ref"]})
            # DRAFT. Publication is the linter's decision, below, never this loop's.
            conn.execute(text("""
                INSERT INTO registry_node_version
                    (node_version_id, node_id, version, descriptors, status, change_note)
                VALUES (:v, :n, 1, CAST(:d AS jsonb), 'draft', :note)
                ON CONFLICT (node_version_id) DO NOTHING"""),
                {"v": f"{t['node_id']}:1", "n": t["node_id"],
                 "d": json.dumps(t["descriptors"]),
                 # Provenance travels with the version, so a reader meeting these descriptors
                 # later can tell transcription from authoring without leaving the row.
                 "note": t["provenance"]})

        for r in rubrics:
            conn.execute(text("""
                INSERT INTO registry_rubric (rubric_id, name, publisher, source, grade_band,
                                             external_ref, status)
                VALUES (:r, :n, :p, :src, :gb, :ref, 'draft')
                ON CONFLICT (rubric_id) DO NOTHING"""),
                {"r": r["rubric_id"], "n": r["name"], "p": r["publisher"], "src": SOURCE,
                 "gb": r["grade_band"], "ref": r["external_ref"]})
            for t in r["traits"]:
                conn.execute(text("""
                    INSERT INTO registry_rubric_trait (rubric_id, node_id, ordinal)
                    VALUES (:r, :n, :o) ON CONFLICT DO NOTHING"""),
                    {"r": r["rubric_id"], "n": t["node_id"], "o": t.get("ordinal", 1)})

        # One task and one scoring site per form, so `run_scoring` can resolve the traits through
        # the same join it uses for student work. The site names this form's eight nodes: the
        # holistic trait plus the seven elements, with the evidence trait that matches the form.
        for form, rubrics_for_form in (("independent", ("independent",)),
                                       ("text_dependent", ("text_dependent",))):
            task_id = f"{CORPUS_TASK_PREFIX}:{form}"
            site_id = f"{task_id}:anchor"
            holistic_rubric = holistic(form)
            element_rubric = elements(form)
            conn.execute(text("""
                INSERT INTO registry_task (task_id, module_key, name, ordinal, grade_band)
                VALUES (:t, :mk, :n, NULL, :gb)
                ON CONFLICT (task_id) DO NOTHING"""),
                {"t": task_id, "mk": "persuade20",
                 "n": ("PERSUADE 2.0 — text dependent" if form == "text_dependent"
                       else "PERSUADE 2.0 — independent"),
                 "gb": holistic_rubric["grade_band"]})
            conn.execute(text("""
                INSERT INTO registry_scoring_site
                    (site_id, task_id, rubric_id, iteration, is_measurement_occasion, note)
                VALUES (:s, :t, :r, 'anchor', false, :note)
                ON CONFLICT (site_id) DO NOTHING"""),
                {"s": site_id, "t": task_id, "r": holistic_rubric["rubric_id"],
                 # NOT a measurement occasion: reference papers, not a declared occasion in
                 # anybody's class. A true here would admit them to a frame about students.
                 "note": "PERSUADE 2.0 reference papers — corpus tenant, not student work"})
            for ordinal, t in enumerate(
                    holistic_rubric["traits"] + element_rubric["traits"], start=1):
                conn.execute(text("""
                    INSERT INTO registry_scoring_site_node (site_id, node_id, ordinal)
                    VALUES (:s, :n, :o) ON CONFLICT DO NOTHING"""),
                    {"s": site_id, "n": t["node_id"], "o": ordinal})

        acks = _read_acknowledgments(conn)
        registry = _read_registry(conn, acks)
        findings = lint(registry)
        blocked = blocks_publication(findings)
        # Lint again with no acknowledgments, so a cleared finding reads as a judgment somebody
        # made rather than a check that never ran.
        cleared = [f for f in lint(replace(registry, acknowledgments={})) if f not in findings]

        ids = tuple(traits)
        drafts = conn.execute(text(
            "SELECT count(*) FROM registry_node_version"
            " WHERE node_id = ANY(:ids) AND status = 'draft'"), {"ids": list(ids)}).scalar_one()

        published = 0
        if drafts and not blocked and not dry_run:
            published = conn.execute(text(
                "UPDATE registry_node_version SET status = 'published'"
                " WHERE node_id = ANY(:ids) AND status = 'draft'"),
                {"ids": list(ids)}).rowcount
            conn.execute(text(
                "UPDATE registry_rubric SET status = 'published' WHERE rubric_id = ANY(:ids)"),
                {"ids": [r["rubric_id"] for r in rubrics]})

        if dry_run:
            conn.rollback()

    if dry_run:
        note = f"DRY RUN — {drafts} draft version(s) would be considered, nothing written"
    elif blocked:
        note = f"{drafts} version(s) left as DRAFT — the linter refused publication"
    elif published:
        note = f"{published} version(s) published"
    else:
        note = "nothing to publish — no drafts were waiting"

    return {
        "rubrics": {r["name"]: r["rubric_id"] for r in rubrics},
        "distinct_traits": len(traits),
        "trait_slots": sum(len(r["traits"]) for r in rubrics),
        "note": note,
        "tasks": [f"{CORPUS_TASK_PREFIX}:independent", f"{CORPUS_TASK_PREFIX}:text_dependent"],
        "blocking": [str(f) for f in findings if f.severity == BLOCKING],
        "advisory": [str(f) for f in findings if f.severity == ADVISORY],
        # Named, not counted: an acknowledged registry must not report identically to a spotless
        # one, or the two severity classes mean nothing.
        "cleared_by_acknowledgment": [str(f) for f in cleared],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true",
                    help="lint and report, roll back without writing")
    args = ap.parse_args()
    print(json.dumps(seed(dry_run=args.dry_run), indent=1))


if __name__ == "__main__":
    main()
