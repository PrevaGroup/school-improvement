"""Assemble what a teacher reviews, draft the message a student will read, and hand it over.

    python -m scoring.compose --tenant public [--limit N] [--dry-run]

`scored` -> `composed` -> `in_review`, or `composed` -> `blocked` when the draft failed a check.
All three are machine moves; only a teacher moves it out of `in_review` or `blocked`.

THE RULE THIS FILE FOLLOWS: compose what cannot be derived, and store what was seen. Nearly all of
the packet IS derivable from score_event, and a stored copy of derivable data is usually a second
source of truth waiting to drift. It is not here, because score_event is append-only: a teacher
override APPENDS, so re-deriving after a review yields a different packet than the one the teacher
was looking at when they decided. What was in front of a person at the moment of judgment is not
derivable from anything.

## The teacher reviews the scores and the drafted message together

A score approved without seeing the message it produces is half a review, so stage E runs here
rather than after approval. Blind scoring and other bias reducers are a later question — this is a
teacher productivity tool first, and `score_event.human_blind` is already there for when it becomes
one.

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
"""
from __future__ import annotations

import argparse
import json
import logging

from sqlalchemy import bindparam, text

from . import feedback
from ._db import engine
from ._ids import uuid7
from .rater import AnthropicRater, RaterIdentity
from .run_scoring import read_text

log = logging.getLogger("scoring.compose")

COMPOSER_VERSION = "c.1"

# Criterion outcomes that route to a person rather than carrying a number.
NEEDS_HUMAN = ("abstained", "no_verified_evidence")

_PENDING = text("""
    SELECT artifact_id, run_id, student_id, section_id, task_id, iteration, window_label,
           source_uri, tenant_id, visibility
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

_STUDENT = text("SELECT display_name FROM roster_student WHERE student_id = :student_id")

# model_id and effort come from the configuration the SCORES were produced under, so one artifact
# is one model's work end to end. `check_configuration` is deliberately NOT run here: the scores
# are already written, and refusing to compose them because a scoring prompt has since moved would
# strand finished work behind a check about producing levels rather than describing them.
_CONFIG = text("""
    SELECT config_id, model_id, effort, prompt_versions, normalization_version
      FROM registry_scoring_configuration WHERE config_id = :config_id
""")

_INSERT = text("""
    INSERT INTO artifact_composition
        (composition_id, artifact_id, composer_version, packet, needs_human,
         prior_rater_mismatch, tenant_id, visibility)
    VALUES (:composition_id, :artifact_id, :composer_version, CAST(:packet AS jsonb),
            :needs_human, :prior_rater_mismatch, :tenant_id, :visibility)
""")

_SET_STATE = text("""
    UPDATE artifact SET state = :state, state_reason_code = :reason_code
     WHERE artifact_id = :artifact_id AND state = :from_state
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
        out.append({
            "task_id": r["task_id"],
            "iteration": r["iteration"],
            "window_label": r.get("window_label"),
            "level": float(r["level"]) if r["level"] is not None else None,
            "scoring_configuration_id": r.get("scoring_configuration_id"),
            "same_rater": r.get("scoring_configuration_id") == current_config,
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


def next_state(holds: list) -> str:
    """Where a composed artifact goes.

    A held draft costs a teacher one click — `blocked` -> `in_review` is a move a teacher may
    make. A draft that goes out having misquoted a student costs something that cannot be clicked
    back. So any hold at all routes to `blocked`, and there is no severity ladder here to argue
    about at three in the afternoon.
    """
    return "blocked" if holds else "in_review"


# ------------------------------------------------------------------ the loop


def compose_pending(*, tenant: str, limit: int = 100, dry_run: bool = False,
                    rater_factory=AnthropicRater) -> dict:
    eng = engine()
    composed, held, failed = 0, 0, []

    with eng.connect() as conn:
        conn.execute(text("SELECT set_config('app.tenant', :t, true)"), {"t": tenant})
        pending = [dict(r) for r in conn.execute(
            _PENDING, {"tenant": tenant, "limit": limit}).mappings()]
    log.info("%d artifact(s) in scored", len(pending))

    for artifact in pending:
        try:
            state = _compose_one(eng, artifact, tenant=tenant, dry_run=dry_run,
                                 rater_factory=rater_factory)
        except Exception as exc:
            log.error("artifact %s: %s", artifact["artifact_id"], exc)
            failed.append({"artifact_id": artifact["artifact_id"], "error": str(exc)})
            continue
        composed += 1
        held += state == "blocked"

    return {"pending": len(pending), "composed": composed, "held_for_safety": held,
            "failed": failed}


def _compose_one(eng, artifact: dict, *, tenant: str, dry_run: bool, rater_factory) -> str:
    aid = artifact["artifact_id"]

    # Read, then call the model, then write — the same shape as run_scoring and for the same
    # reason: a transaction held open across a model call holds a connection for minutes and
    # loses the work anyway when the process dies.
    with eng.connect() as conn:
        conn.execute(text("SELECT set_config('app.tenant', :t, true)"), {"t": tenant})

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
        student_name = conn.execute(
            _STUDENT, {"student_id": artifact.get("student_id")}).scalar()
        cfg = conn.execute(
            _CONFIG, {"config_id": packet["stamp"]["scoring_configuration_id"]}).mappings().first()

    if cfg is None:
        raise RuntimeError(
            f"{aid} was scored under configuration "
            f"{packet['stamp']['scoring_configuration_id']!r}, which is not in the registry. "
            f"The scores name a rater that does not exist.")

    body = read_text(artifact)
    identity = RaterIdentity(config_id=cfg["config_id"], model_id=cfg["model_id"],
                             effort=cfg["effort"], prompt_versions=dict(cfg["prompt_versions"]),
                             normalization_version=cfg["normalization_version"])
    drafted, usage = feedback.draft(body, packet, rater_factory(identity), student_name)
    holds = feedback.check(drafted, body)

    # The paper itself is part of what the teacher saw. Stored with the packet rather than fetched
    # from `source_uri` at read time: the review console runs as the API role on Cloud Run, which
    # cannot reach a batch job's local file, and a source that has moved would leave a reviewed
    # artifact with no readable text. Duplication of student writing is a deliberate prototype
    # tradeoff — a real deployment points this at a text store instead.
    packet["text"] = body

    packet["feedback"] = {
        "message": drafted.message,
        "quotations": drafted.quotations,
        "composer_version": drafted.composer_version,
        "fingerprint": drafted.fingerprint,
        "holds": [{"code": h.code, "detail": h.detail} for h in holds],
    }
    state = next_state(holds)

    if dry_run:
        log.info("%s (dry run): %d criteria, %d need a human, prior mismatch=%s, "
                 "%d hold(s) -> %s, %d call(s)",
                 aid, len(packet["criteria"]), len(packet["needs_human"]),
                 packet["prior_rater_mismatch"], len(holds), state, usage.calls)
        return state

    with eng.begin() as conn:
        conn.execute(text("SELECT set_config('app.tenant', :t, true)"), {"t": tenant})
        conn.execute(text("SELECT set_config('app.actor_type', 'machine', true)"))

        conn.execute(_INSERT, {
            "composition_id": uuid7(), "artifact_id": aid,
            "composer_version": COMPOSER_VERSION, "packet": json.dumps(packet, default=str),
            "needs_human": len(packet["needs_human"]),
            "prior_rater_mismatch": packet["prior_rater_mismatch"],
            "tenant_id": artifact["tenant_id"], "visibility": artifact["visibility"]})

        moved = conn.execute(_SET_STATE, {
            "artifact_id": aid, "from_state": "scored", "state": "composed",
            "reason_code": None}).rowcount
        if moved != 1:
            raise RuntimeError(
                f"{aid} was not in `scored` when the transition ran ({moved} rows). Another "
                f"worker has it; rolling back rather than storing a second packet.")

        # Two transitions, both recorded, because they are two facts: the packet was built, and
        # the draft did or did not clear its checks. Collapsing them into one move would lose
        # which of the two a `blocked` artifact failed.
        conn.execute(_SET_STATE, {
            "artifact_id": aid, "from_state": "composed", "state": state,
            "reason_code": holds[0].code if holds else None})

    log.info("%s -> %s: %d criteria, %d need a human, %d hold(s), %d call(s)",
             aid, state, len(packet["criteria"]), len(packet["needs_human"]),
             len(holds), usage.calls)
    return state


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tenant", default="public")
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--dry-run", action="store_true",
                    help="call the model and check the draft, write nothing")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    print(json.dumps(compose_pending(tenant=args.tenant, limit=args.limit,
                                     dry_run=args.dry_run), indent=1))


if __name__ == "__main__":
    main()
