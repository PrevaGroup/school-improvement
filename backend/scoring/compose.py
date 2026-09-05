"""Assemble what a teacher reviews, and move the artifact from `scored` to `composed`.

    python -m scoring.compose --tenant public [--limit N]

THE RULE THIS FILE FOLLOWS: compose what cannot be derived, and store what was seen. Nearly all of
the packet IS derivable from score_event, and a stored copy of derivable data is usually a second
source of truth waiting to drift. It is not here, because score_event is append-only: a teacher
override APPENDS, so re-deriving after a review yields a different packet than the one the teacher
was looking at when they decided. What was in front of a person at the moment of judgment is not
derivable from anything.

## The prior-observations panel, which is where the care goes

The review console shows each criterion's earlier levels for that student. It is the most useful
thing on the screen and the easiest place in the whole product to state something false, because
two numbers side by side are an invitation to read a trend. Three rules, none of them cosmetic:

**Same node only.** A prior level is comparable only if it came from the same node — same standard,
same criterion, same scale structure, same grade band. Two criteria that both sound like "evidence"
are two nodes, and putting their levels in one row compares two different things. The node
identifier is the identity, so this is a join, not a judgment.

**Measurement occasions only.** A draft is scored and is not an occasion. A draft level beside a
final level reads as growth within an assignment, and a draft is not a valid comparison point:
drafts are low stakes, mistakes there are useful, and the point of the draft is exploration.

**The rater is named, and a change is flagged.** The configuration pin holds within one section x
task x iteration — deliberately, because that is the scope a teacher compares within. ACROSS tasks
it does not hold, so two prior levels can come from two raters. Raw levels from two raters are not
directly comparable; the comparison that survives lives on the person metric, through an anchored
frame. This module cannot do that arithmetic and does not pretend to. It reports the mismatch and
says what it means, which is the honest available move.

## Where this stops

At `composed`. The student-facing feedback draft is not built here: it is a model call against the
highest-stakes surface in the system, `blocked` exists for the safety check that gates it, and
`models.py` and the review console disagree about whether that draft exists before or after review.
That is a question for a person.
"""
from __future__ import annotations

import argparse
import json
import logging

from sqlalchemy import bindparam, text

from ._db import engine
from ._ids import uuid7

log = logging.getLogger("scoring.compose")

COMPOSER_VERSION = "c.1"

# Criterion outcomes that route to a person rather than carrying a number.
NEEDS_HUMAN = ("abstained", "no_verified_evidence")

_PENDING = text("""
    SELECT artifact_id, run_id, student_id, section_id, task_id, iteration, window_label,
           tenant_id, visibility
      FROM artifact
     WHERE tenant_id = :tenant AND state = 'scored'
     ORDER BY created_at
     LIMIT :limit
""")

_EVENTS = text("""
    SELECT event_id, node_id, status, level, confidence, reason, reason_code, evidence,
           rubric_version, trait_set_version, form_variant, scoring_configuration_id,
           scorer_type, scrutiny_passes, is_measurement_occasion, created_at
      FROM score_event
     WHERE artifact_id = :artifact_id
     ORDER BY node_id
""")

_LABELS = text("""
    SELECT node_id, criterion_label, standard_code, scale_categories
      FROM registry_node
     WHERE node_id IN :nodes
""").bindparams(bindparam("nodes", expanding=True))

# Prior observations. The three rules in the module docstring are the three clauses here, and
# every one of them removes rows a naive version would have shown.
_PRIOR = text("""
    SELECT node_id, task_id, iteration, window_label, level, scoring_configuration_id,
           artifact_id, created_at
      FROM score_event
     WHERE tenant_id = :tenant
       AND student_id = :student_id
       AND node_id IN :nodes
       AND artifact_id <> :artifact_id
       AND status = 'scored'
       AND is_measurement_occasion IS TRUE
     ORDER BY node_id, created_at
""").bindparams(bindparam("nodes", expanding=True))

_INSERT = text("""
    INSERT INTO artifact_composition
        (composition_id, artifact_id, composer_version, packet, needs_human,
         prior_rater_mismatch, tenant_id, visibility)
    VALUES (:composition_id, :artifact_id, :composer_version, CAST(:packet AS jsonb),
            :needs_human, :prior_rater_mismatch, :tenant_id, :visibility)
""")

_SET_STATE = text("""
    UPDATE artifact SET state = 'composed'
     WHERE artifact_id = :artifact_id AND state = 'scored'
""")


# ------------------------------------------------------------------ pure (unit-tested)


def configuration_of(events: list[dict]) -> str | None:
    """The rater this artifact was scored by.

    More than one is a contradiction rather than something to summarise: the pin exists so that
    every event on one artifact carries one configuration, and a packet that averaged over two
    would be presenting two raters' work as one opinion.
    """
    configs = {e["scoring_configuration_id"] for e in events
               if e.get("scoring_configuration_id")}
    if len(configs) > 1:
        raise ValueError(
            f"artifact scored under {len(configs)} configurations {sorted(configs)} — the packet "
            f"cannot name one rater, and presenting two as one is the thing the pin prevents")
    return next(iter(configs), None)


def prior_for_node(rows: list[dict], node_id: str, current_config: str | None) -> list[dict]:
    """This node's earlier observations, each one honest about which rater produced it."""
    out = []
    for r in rows:
        if r["node_id"] != node_id:
            continue
        same = r.get("scoring_configuration_id") == current_config
        out.append({
            "task_id": r["task_id"],
            "iteration": r["iteration"],
            "window_label": r.get("window_label"),
            "level": float(r["level"]) if r["level"] is not None else None,
            "scoring_configuration_id": r.get("scoring_configuration_id"),
            "same_rater": same,
            "when": r["created_at"].isoformat() if r.get("created_at") else None,
        })
    return out


def build_packet(artifact: dict, events: list[dict], labels: dict[str, dict],
                 prior_rows: list[dict]) -> dict:
    """Everything a teacher needs to review one artifact, and nothing that overstates it."""
    config = configuration_of(events)
    criteria, needs_human = [], []

    for e in events:
        node_id = e["node_id"]
        label = labels.get(node_id, {})
        evidence = e.get("evidence") or {}
        flagged = e["status"] in NEEDS_HUMAN
        if flagged:
            needs_human.append(node_id)
        criteria.append({
            "node_id": node_id,
            "criterion_label": label.get("criterion_label"),
            "standard_code": label.get("standard_code"),
            "scale_categories": label.get("scale_categories"),
            "status": e["status"],
            "level": float(e["level"]) if e["level"] is not None else None,
            "confidence": e.get("confidence"),
            "reason": e.get("reason"),
            "reason_code": e.get("reason_code"),
            "needs_human": flagged,
            # The kept spans are what the teacher checks the reason against. The dropped ones are
            # a COUNT, not a list: showing a teacher the sentences a model invented invites them
            # to read the invention as evidence, and the reviewer who needs the full text is
            # debugging the pipeline, not reviewing a paper. score_event keeps them either way.
            "evidence": [k.get("span") for k in evidence.get("kept", [])],
            "evidence_dropped": len(evidence.get("dropped", [])),
            "rubric_version": e.get("rubric_version"),
            "prior": prior_for_node(prior_rows, node_id, config),
        })

    mismatch = any(not p["same_rater"] for c in criteria for p in c["prior"])
    return {
        "composer_version": COMPOSER_VERSION,
        "artifact_id": artifact["artifact_id"],
        "student_id": artifact.get("student_id"),
        "section_id": artifact.get("section_id"),
        "task_id": artifact.get("task_id"),
        "iteration": artifact.get("iteration"),
        "window_label": artifact.get("window_label"),
        # The facet stamp the console shows. Assembled from the events rather than re-read, so the
        # packet cannot claim a configuration the scores were not produced under.
        "stamp": {
            "scoring_configuration_id": config,
            "trait_set_version": next((e.get("trait_set_version") for e in events), None),
            "form_variant": next((e.get("form_variant") for e in events), None),
            "scrutiny_passes": max((e.get("scrutiny_passes") or 1 for e in events), default=1),
            "scorer_type": next((e.get("scorer_type") for e in events), None),
        },
        "criteria": criteria,
        "needs_human": needs_human,
        "prior_rater_mismatch": mismatch,
        # Said in words, in the packet, so a console that forgets to render the flag still carries
        # the qualification into whatever reads it next.
        "prior_note": (
            "Some earlier levels shown were produced by a different scoring configuration. Raw "
            "levels from two raters are not directly comparable — read them as separate "
            "observations, not as a trend." if mismatch else None),
    }


# ------------------------------------------------------------------ the loop


def compose_pending(*, tenant: str, limit: int = 100, dry_run: bool = False) -> dict:
    eng = engine()
    composed, failed = 0, []

    with eng.connect() as conn:
        conn.execute(text("SELECT set_config('app.tenant', :t, true)"), {"t": tenant})
        pending = [dict(r) for r in conn.execute(
            _PENDING, {"tenant": tenant, "limit": limit}).mappings()]
    log.info("%d artifact(s) in scored", len(pending))

    for artifact in pending:
        try:
            _compose_one(eng, artifact, tenant=tenant, dry_run=dry_run)
        except Exception as exc:
            log.error("artifact %s: %s", artifact["artifact_id"], exc)
            failed.append({"artifact_id": artifact["artifact_id"], "error": str(exc)})
            continue
        composed += 1

    return {"pending": len(pending), "composed": composed, "failed": failed}


def _compose_one(eng, artifact: dict, *, tenant: str, dry_run: bool) -> None:
    aid = artifact["artifact_id"]
    with eng.begin() as conn:
        conn.execute(text("SELECT set_config('app.tenant', :t, true)"), {"t": tenant})
        conn.execute(text("SELECT set_config('app.actor_type', 'machine', true)"))

        events = [dict(r) for r in conn.execute(_EVENTS, {"artifact_id": aid}).mappings()]
        if not events:
            raise RuntimeError(
                f"{aid} is in `scored` with no score events. The state and the record disagree, "
                f"which is worse than either being wrong on its own.")

        nodes = sorted({e["node_id"] for e in events})
        labels = {r["node_id"]: dict(r)
                  for r in conn.execute(_LABELS, {"nodes": nodes}).mappings()}
        prior = [dict(r) for r in conn.execute(
            _PRIOR, {"tenant": tenant, "student_id": artifact.get("student_id"),
                     "nodes": nodes, "artifact_id": aid}).mappings()]

        packet = build_packet(artifact, events, labels, prior)

        if dry_run:
            log.info("%s (dry run): %d criteria, %d need a human, prior mismatch=%s",
                     aid, len(packet["criteria"]), len(packet["needs_human"]),
                     packet["prior_rater_mismatch"])
            return

        conn.execute(_INSERT, {
            "composition_id": uuid7(), "artifact_id": aid,
            "composer_version": COMPOSER_VERSION, "packet": json.dumps(packet, default=str),
            "needs_human": len(packet["needs_human"]),
            "prior_rater_mismatch": packet["prior_rater_mismatch"],
            "tenant_id": artifact["tenant_id"], "visibility": artifact["visibility"]})

        moved = conn.execute(_SET_STATE, {"artifact_id": aid}).rowcount
        if moved != 1:
            raise RuntimeError(
                f"{aid} was not in `scored` when the transition ran ({moved} rows). Another "
                f"worker has it; rolling back rather than storing a second packet.")

    log.info("%s -> composed: %d criteria, %d need a human", aid, len(packet["criteria"]),
             len(packet["needs_human"]))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tenant", default="public")
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    print(json.dumps(compose_pending(tenant=args.tenant, limit=args.limit,
                                     dry_run=args.dry_run), indent=1))


if __name__ == "__main__":
    main()
