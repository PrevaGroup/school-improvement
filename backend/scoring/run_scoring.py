"""Score every artifact waiting in `bound`, and move it to `scored`.

    python -m scoring.run_scoring --run-id R --tenant public --config-key writing-default
                                  [--limit N] [--dry-run]

The driver. Everything that touches the world is here — the registry read, the id minting, the
transaction, the state transition — so that `score.py` above it can stay a pure function of
(text, criteria, rater) and be tested without a network or a dollar.

FOUR THINGS THIS FILE IS CAREFUL ABOUT.

**Model calls happen outside the transaction.** One artifact is scored in memory, then one
transaction writes its events and moves its state. A process killed mid-run loses the API spend for
at most one artifact and leaves the record consistent — there is no such thing as a half-scored
artifact. The reverse arrangement (open a transaction, then make twelve calls over four minutes)
holds a database connection for the length of a model call and still loses the work when it dies.

**The configuration pin is derived, not stored.** A configuration must not change inside one
section x task x iteration — a teacher looking at their class's scores is looking at one rater's
work or the comparison is meaningless. There is no pin table: the pin is read back out of
`score_event`, which is the only place that cannot drift from what actually happened. If that scope
already has scores, their configuration is the one this run uses, even if it has since been
superseded. If it has two, the run stops, because the damage is already done and writing a third
does not help.

**A configuration whose prompts have moved is refused.** `registry_scoring_configuration` stamps
prompt versions AND hashes; `prompts.fingerprint()` computes them from the text on disk. A mismatch
means the rater is not the rater the administrator promoted, and that is a stop, not a warning.

**The transition to `scored` is a machine move and stays one.** `app.actor_type` is set to
`machine` for the whole transaction. Reaching `released` from this code path is impossible, and
impossible in the database rather than by not writing the line — proven by the smoke test in
`sql/20_scoring_smoketest.sql`, which watches a machine try it and be refused.

WHERE THIS STOPS. At `scored`. Composition (the rationale packet), output safety, and review are
later phases; the artifact sits in `scored` until one of them moves it, which is what "nothing in
the pipeline halts" means in practice — the queue is a view over states, not a stalled worker.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
from dataclasses import replace

from sqlalchemy import text

from app.vocab import SCORE_STATUS_IDS

from ._db import engine
from ._ids import uuid7
from .prompts import fingerprint
from .rater import AnthropicRater, RaterIdentity, Usage
from . import escalate, fit, score
from .score import Criterion, Outcome, score_artifact, score_criterion

log = logging.getLogger("scoring.run_scoring")

# The first look. An escalated criterion is written at pass 2 — see `scoring/escalate.py` for
# why the budget is per artifact, why the trigger list is short, and why there is no pass 3.
SCRUTINY_PASS = 1
ESCALATED_PASS = 2

# --------------------------------------------------------------------------- #
# Reads against other modules' tables. `registry` is read with SQL and never imported: a produced
# table is the contract, and that is the whole reason the boundary rule survives contact with a
# pipeline that legitimately needs four modules' data.
# --------------------------------------------------------------------------- #
_TRAIT_SET = text("""
    SELECT n.node_id, n.criterion_label, n.scale_categories,
           v.node_version_id, v.version, v.descriptors,
           s.site_id, s.is_measurement_occasion
      FROM registry_scoring_site s
      JOIN registry_scoring_site_node sn ON sn.site_id = s.site_id
      JOIN registry_node n               ON n.node_id  = sn.node_id
      JOIN registry_node_version v       ON v.node_id  = n.node_id AND v.status = 'published'
     WHERE s.task_id = :task_id AND s.iteration = :iteration
       AND n.retired_at IS NULL
     ORDER BY sn.ordinal NULLS LAST, n.node_id
""")

_ACTIVE_CONFIG = text("""
    SELECT config_id, model_id, effort, prompt_versions, normalization_version, escalation
      FROM registry_scoring_configuration
     WHERE config_key = :config_key AND status = 'active'
""")

_CONFIG_BY_ID = text("""
    SELECT config_id, model_id, effort, prompt_versions, normalization_version, escalation
      FROM registry_scoring_configuration
     WHERE config_id = :config_id
""")

# The pin, read back out of the record itself.
_PINNED_CONFIG = text("""
    SELECT DISTINCT scoring_configuration_id
      FROM score_event
     WHERE tenant_id = :tenant AND section_id = :section_id
       AND task_id = :task_id AND iteration = :iteration
       AND scorer_type = 'ai' AND scoring_configuration_id IS NOT NULL
""")

# The CAST on :run_id is load-bearing, not decoration. An optional parameter that appears only
# beside IS NULL gives the planner nothing to infer a type from, and Postgres refuses the whole
# statement with `could not determine data type of parameter $2` — at execution, against a real
# server, which is the one place none of the unit tests look. Naming the type once fixes it.
_PENDING = text("""
    SELECT a.artifact_id, a.run_id, a.student_id, a.section_id, a.task_id, a.iteration,
           a.window_label, a.content_hash, a.source_uri, a.intake_file_id, f.text AS intake_text,
           cp.text AS corpus_text,
           a.tenant_id, a.visibility
      FROM artifact a
      LEFT JOIN intake_file f ON f.file_id = a.intake_file_id
      -- A reference paper's text is a column in the corpus, not a file. Read with SQL, never by
      -- importing `corpus` — a produced table is the seam between modules. The join is on
      -- `student_id` because `bind_corpus` writes the de-identified paper id there, and it is
      -- narrowed to the corpus tenant so a student id can never collide with a paper id.
      LEFT JOIN corpus_paper cp
             ON a.tenant_id = 'corpus' AND cp.paper_id = a.student_id
     WHERE a.tenant_id = :tenant AND a.state = 'bound'
       AND (CAST(:run_id AS text) IS NULL OR a.run_id = CAST(:run_id AS text))
     ORDER BY a.created_at
     LIMIT :limit
""")

# The task statement, which is the file intake classified as `not_student_work` in the same
# folder. The plan is specific that it is kept for this: "non-student classification that retains
# the prompt as the task statement". Without it the fit gate has no task to be an attempt AT, and
# the question collapses into "is this good writing" — the drift the gate is built to avoid.
_TASK_STATEMENT = text("""
    SELECT p.text
      FROM intake_file f
      JOIN intake_file p ON p.manifest_id = f.manifest_id
     WHERE f.file_id = :file_id AND p.status = 'not_student_work'
       AND p.text IS NOT NULL AND length(p.text) > 0
     ORDER BY length(p.text) DESC
     LIMIT 1
""")

_ALREADY_SCORED = text("""
    SELECT node_id FROM score_event
     WHERE artifact_id = :artifact_id AND scoring_configuration_id = :config_id
       AND scrutiny_passes = :pass_n
""")

_INSERT_EVENT = text("""
    INSERT INTO score_event (
        event_id, artifact_id, run_id, student_id, section_id, task_id, iteration, window_label,
        node_id, trait_set_version, rubric_version, form_variant,
        scoring_configuration_id, scorer_type, scorer_id, human_blind,
        scrutiny_passes, escalation_trigger,
        status, level, confidence, reason, reason_code, evidence,
        is_measurement_occasion, enters_calibration, revised_after_feedback,
        supersedes_event_id, set_override_id, idempotency_key, tenant_id, visibility)
    VALUES (
        :event_id, :artifact_id, :run_id, :student_id, :section_id, :task_id, :iteration,
        :window_label, :node_id, :trait_set_version, :rubric_version, :form_variant,
        :scoring_configuration_id, :scorer_type, :scorer_id, :human_blind,
        :scrutiny_passes, :escalation_trigger,
        :status, :level, :confidence, :reason, :reason_code, CAST(:evidence AS jsonb),
        :is_measurement_occasion, :enters_calibration, :revised_after_feedback,
        :supersedes_event_id, :set_override_id, :idempotency_key, :tenant_id, :visibility)
""")

_SET_STATE = text("""
    UPDATE artifact SET state = :state, state_reason_code = :reason_code
     WHERE artifact_id = :artifact_id AND state = 'bound'
""")


class ConfigurationError(RuntimeError):
    """The rater is not the rater it says it is. Always a stop, never a warning."""


# ------------------------------------------------------------------ pure (unit-tested)


def trait_set_version(node_version_ids: list[str]) -> str:
    """A stable name for exactly this ordered set of node versions.

    Recorded on every event so "which traits was this artifact scored on, at which wordings" is
    answerable from one column instead of reconstructed from the registry as it stands today —
    which is the reconstruction that stops being possible the moment a version is published.
    """
    joined = "|".join(node_version_ids)
    return "ts-" + hashlib.sha256(joined.encode("utf8")).hexdigest()[:16]


def idempotency_key(artifact_id: str, node_id: str, config_id: str, pass_n: int) -> str:
    """One observation is (this text, this item, this rater, this pass).

    Note what is NOT in it: the run id. A resumed run is the same run doing the same work, and
    keying on the run would make every retry a fresh observation — a measurement bug wearing a
    throughput bug's clothes. The artifact id already carries the text, because a new submission
    under the same binding key is a new artifact, not an edit to this one.
    """
    return f"{artifact_id}|{node_id}|{config_id}|p{pass_n}"


def enters_calibration(outcome: Outcome, is_measurement_occasion: bool) -> bool:
    """The pipeline's proposal, and only from policy that has actually been decided.

    Two rules, both settled: a non-scored outcome carries no observation, and a draft is not a
    measurement occasion — drafts are low stakes for the student and mistakes there are useful, so
    driving revision from them is the opposite of what the draft is for.

    Everything else about admission is open (the four measurement policy questions), and this
    column cannot answer them: the row is immutable, so it can only ever mean "what was true at
    write time". Real membership lives in `estimation_frame_member`, where a frame can narrow this
    later. Nothing downstream may WIDEN it.
    """
    return outcome.status == "scored" and bool(is_measurement_occasion)


def event_rows(artifact: dict, outcomes: list[Outcome], identity: RaterIdentity,
               ts_version: str, is_measurement_occasion: bool, *,
               scrutiny_passes: int = SCRUTINY_PASS,
               triggers: dict[str, str] | None = None,
               supersedes: dict[str, str] | None = None) -> list[dict]:
    """Outcomes -> score_event rows. Pure, so the facet stamp can be asserted without a database.

    `rubric_version` holds the node_version_id rather than the integer version: an integer is only
    meaningful beside its node, and a column that needs a second column to be read is a column that
    will eventually be read without it. `form_variant` stays NULL and stays a separate column —
    there are no alternate forms yet, and folding one into the version later would make its effect
    unrecoverable, which is the hidden-facet failure this schema was shaped to avoid.
    """
    rows = []
    for o in outcomes:
        if o.status not in SCORE_STATUS_IDS:
            raise ValueError(f"{o.status!r} is not in core's SCORE_STATUSES vocabulary")
        rows.append({
            "event_id": uuid7(),
            "artifact_id": artifact["artifact_id"],
            "run_id": artifact["run_id"],
            "student_id": artifact["student_id"],
            "section_id": artifact["section_id"],
            "task_id": artifact["task_id"],
            "iteration": artifact["iteration"],
            "window_label": artifact["window_label"],
            "node_id": o.node_id,
            "trait_set_version": ts_version,
            "rubric_version": o.node_version_id,
            "form_variant": None,
            "scoring_configuration_id": identity.config_id,
            "scorer_type": "ai",
            "scorer_id": None,          # a machine rater IS its configuration
            "human_blind": None,
            "scrutiny_passes": scrutiny_passes,
            # WHICH declared rule fired. Without it an escalated row says a second look happened
            # and not what prompted it, and "escalated papers are not a random subset" becomes
            # unanalysable — the subset is defined by the trigger.
            "escalation_trigger": (triggers or {}).get(o.node_id),
            "status": o.status,
            "level": o.level,
            "confidence": o.confidence,
            "reason": o.reason,
            "reason_code": o.reason_code,
            "evidence": json.dumps(o.evidence),
            "is_measurement_occasion": is_measurement_occasion,
            "enters_calibration": enters_calibration(o, is_measurement_occasion),
            "revised_after_feedback": None,
            # The pass-1 event this deeper look replaces. Both rows survive — the table is
            # append-only — so the pair is the scrutiny-invariance comparison Phase 5 wants. This
            # only says which one STANDS.
            "supersedes_event_id": (supersedes or {}).get(o.node_id),
            "set_override_id": None,
            "idempotency_key": idempotency_key(
                artifact["artifact_id"], o.node_id, identity.config_id, scrutiny_passes),
            "tenant_id": artifact["tenant_id"],
            "visibility": artifact["visibility"],
        })
    return rows


def next_state(outcomes: list[Outcome]) -> tuple[str, str | None]:
    """Where the artifact goes once every criterion has an outcome.

    `not_scorable` only when EVERY criterion says so — which, since the only producer of it is an
    empty document, means the whole artifact was a non-attempt. A mixture cannot happen today and
    should be loud if it ever does, rather than silently rounding to whichever is more common.
    """
    statuses = {o.status for o in outcomes}
    if statuses == {"not_scorable"}:
        return "not_scorable", (outcomes[0].reason_code if outcomes else None)
    if "not_scorable" in statuses:
        raise ValueError(
            "some criteria are not_scorable and others are not. not_scorable is a fact about the "
            f"artifact, not about a criterion — got {sorted(statuses)}")
    return "scored", None


def check_configuration(identity: RaterIdentity) -> None:
    """Refuse a configuration whose prompt text has moved since it was promoted."""
    live, stamped = fingerprint(), identity.prompt_versions
    if stamped != live:
        raise ConfigurationError(
            f"configuration {identity.config_id} stamps {stamped} but the prompts on disk "
            f"fingerprint {live}. The rater is not the one that was promoted. Either restore the "
            f"text, or bump the prompt version and promote a new configuration — do not score "
            f"papers with a rater nobody approved.")


# ------------------------------------------------------------------ database reads


def load_criteria(conn, task_id: str, iteration: str) -> tuple[list[Criterion], bool]:
    """The frozen trait set for one scoring site, from the registry, by SQL.

    Two published versions of one node would silently double the trait set here and make
    `rubric_version` ambiguous for every event. Migration 0014 makes that impossible with a partial
    unique index; this check stays anyway, because a join whose correctness depends on a constraint
    somewhere else should say so where it is read.
    """
    rows = conn.execute(_TRAIT_SET, {"task_id": task_id, "iteration": iteration}).mappings().all()
    if not rows:
        raise ConfigurationError(
            f"no scoring site for task {task_id!r} iteration {iteration!r}, or its nodes have no "
            f"published version. Nothing to score against is a configuration error, not an "
            f"empty result.")

    seen: dict[str, str] = {}
    for r in rows:
        if r["node_id"] in seen:
            raise ConfigurationError(
                f"node {r['node_id']} has more than one published version "
                f"({seen[r['node_id']]}, {r['node_version_id']}). Publishing must supersede.")
        seen[r["node_id"]] = r["node_version_id"]

    criteria = [Criterion(node_id=r["node_id"], criterion_label=r["criterion_label"],
                          categories=list(r["scale_categories"]), descriptors=dict(r["descriptors"]),
                          node_version_id=r["node_version_id"])
                for r in rows]
    return criteria, bool(rows[0]["is_measurement_occasion"])


def resolve_configuration(conn, *, tenant: str, section_id: str | None, task_id: str,
                          iteration: str,
                          config_key: str) -> tuple[RaterIdentity, escalate.Policy]:
    """The pinned configuration for this scope, or the active one if the scope is new.

    Returns the rater AND its escalation policy, because they are two halves of one published
    decision: what the model is, and how many times it is allowed to look.
    """
    pinned = [r[0] for r in conn.execute(
        _PINNED_CONFIG, {"tenant": tenant, "section_id": section_id,
                         "task_id": task_id, "iteration": iteration}).all()]
    if len(pinned) > 1:
        raise ConfigurationError(
            f"section {section_id} / {task_id} / {iteration} already holds scores from "
            f"{len(pinned)} configurations {sorted(pinned)} — two raters inside one comparison. "
            f"That has to be resolved before more scores are added to it.")

    q, params = ((_CONFIG_BY_ID, {"config_id": pinned[0]}) if pinned
                 else (_ACTIVE_CONFIG, {"config_key": config_key}))
    rows = conn.execute(q, params).mappings().all()
    if len(rows) != 1:
        raise ConfigurationError(
            f"expected exactly one configuration for {params}, found {len(rows)}. "
            f"An ambiguous rater is not a rater.")
    r = rows[0]
    identity = RaterIdentity(config_id=r["config_id"], model_id=r["model_id"], effort=r["effort"],
                             prompt_versions=dict(r["prompt_versions"]),
                             normalization_version=r["normalization_version"])
    check_configuration(identity)
    # Escalation behaviour is a property of the published configuration somebody approved, not of
    # whichever constants were in this file that week. A row with no policy gets the default,
    # which is what every configuration written before this column existed has.
    policy = escalate.Policy.from_config(r.get("escalation"))
    return identity, policy


# ------------------------------------------------------------------ the loop


class AlreadyRunning(RuntimeError):
    """Another scorer holds this tenant's lock. See `_LOCK_NS`."""


# One scorer per tenant at a time, enforced by Postgres rather than by remembering.
#
# `_PENDING` selects artifacts in `bound`, and an artifact stays `bound` until every one of its
# traits is written. So two scorers started minutes apart select the SAME papers and both pay for
# them. The unique constraint on `idempotency_key` stops the duplicate ROW, and it stops it after
# the API call has been made and billed — the protection is against a corrupt table, not against
# the money.
#
# It became a live risk the moment there were two ways to launch: a shell and a Cloud Run job.
# Nobody holds both in their head at 1am.
#
# An advisory lock rather than a row: it is released when the connection dies, so a killed job —
# which is exactly how the first corpus run ended — leaves nothing to clean up by hand. A lock
# row would need a heartbeat and a reaper, and a stale one would block every future run.
_LOCK_NS = 0x5C04  # "SCOR", so a `pg_locks` reading names the owner
_LOCK = text("SELECT pg_try_advisory_lock(:ns, hashtext(:tenant))")


def score_pending(*, tenant: str, config_key: str, run_id: str | None = None,
                  limit: int = 50, dry_run: bool = False, rater_factory=AnthropicRater,
                  concurrency: int = score.DEFAULT_CONCURRENCY) -> dict:
    """Score every `bound` artifact for one tenant. Returns a summary the caller can log.

    Raises `AlreadyRunning` if another scorer holds this tenant — refusing costs a re-run, and
    proceeding costs the price of every paper twice.
    """
    eng = engine()
    total, scored, skipped, failed = Usage(), 0, 0, []

    # Held for the whole batch, so it must be its own connection — the per-artifact connections
    # below are opened and closed inside the loop, and a session lock dies with its session.
    lock_conn = eng.connect()
    try:
        if not lock_conn.execute(_LOCK, {"ns": _LOCK_NS, "tenant": tenant}).scalar():
            raise AlreadyRunning(
                f"another scorer already holds tenant {tenant!r}. Two scorers select the same "
                f"`bound` artifacts and both pay for them, so this one is refusing. If you are "
                f"sure the other is gone, its lock died with its connection — check "
                f"`SELECT * FROM pg_locks WHERE locktype = 'advisory'`.")

        with eng.connect() as conn:
            conn.execute(text("SELECT set_config('app.tenant', :t, true)"), {"t": tenant})
            pending = conn.execute(
                _PENDING, {"tenant": tenant, "run_id": run_id, "limit": limit}).mappings().all()
        log.info("%d artifact(s) in bound", len(pending))

        for row in pending:
            artifact = dict(row)
            try:
                usage = _score_one(eng, artifact, tenant=tenant, config_key=config_key,
                                   dry_run=dry_run, rater_factory=rater_factory,
                                   concurrency=concurrency)
            except Exception as exc:                  # one bad artifact must not stop the batch
                log.error("artifact %s: %s", artifact["artifact_id"], exc)
                failed.append({"artifact_id": artifact["artifact_id"], "error": str(exc)})
                continue
            if usage is None:
                skipped += 1
            else:
                scored += 1
                total = total + usage

        return {"pending": len(pending), "scored": scored, "skipped": skipped,
                "failed": failed, "calls": total.calls,
                "input_tokens": total.input_tokens, "output_tokens": total.output_tokens}
    finally:
        # Closing releases the session's advisory locks, including on the path where acquiring it
        # failed — where `close()` is all this does.
        lock_conn.close()


def _score_one(eng, artifact: dict, *, tenant: str, config_key: str, dry_run: bool,
               rater_factory, concurrency: int = score.DEFAULT_CONCURRENCY) -> Usage | None:
    """Score one artifact and write it. Returns None when there was nothing left to do."""
    aid = artifact["artifact_id"]

    with eng.connect() as conn:
        conn.execute(text("SELECT set_config('app.tenant', :t, true)"), {"t": tenant})
        criteria, is_occasion = load_criteria(conn, artifact["task_id"], artifact["iteration"])
        identity, policy = resolve_configuration(
            conn, tenant=tenant, section_id=artifact["section_id"], task_id=artifact["task_id"],
            iteration=artifact["iteration"], config_key=config_key)
        done = {r[0] for r in conn.execute(
            _ALREADY_SCORED, {"artifact_id": aid, "config_id": identity.config_id,
                              "pass_n": SCRUTINY_PASS}).all()}
        task_statement = (conn.execute(
            _TASK_STATEMENT, {"file_id": artifact["intake_file_id"]}).scalar()
            if artifact.get("intake_file_id") else None)

    remaining = [c for c in criteria if c.node_id not in done]
    if not remaining:
        log.info("%s: already complete under %s", aid, identity.config_id)
        return None

    body = read_text(artifact)

    # The calls. Outside any transaction, on purpose — see the module docstring.
    rater = rater_factory(identity)

    # Stage B, first, because its entire purpose is to run before the expensive part. One call
    # decides whether the next several hundred are worth making. It resolves toward admitting on
    # anything ambiguous — see `scoring/fit.py` for why those two errors are not comparable.
    verdict, fit_usage = fit.check(task_statement, body, rater)
    usage = fit_usage
    if not verdict.admitted:
        outcomes = [Outcome(node_id=c.node_id, node_version_id=c.node_version_id,
                            status="not_scorable", reason_code=fit.NOT_THIS_TASK,
                            reason=verdict.reason,
                            evidence=verdict.as_evidence())
                    for c in remaining]
    else:
        scored_outcomes, score_usage = score_artifact(
            body, remaining, rater, concurrency=concurrency)
        outcomes = scored_outcomes
        usage = usage + score_usage

    # The second, deeper look — bounded, on declared triggers, at higher effort. This is the whole
    # of "escalation under a fixed budget" reaching a real path; the module beside it is where the
    # reasoning lives. A gated paper skips it: `not_scorable` is not a trigger, and paying twice
    # to confirm a document is not an attempt is the opposite of what the gate is for.
    escalated, plan, esc_usage, unchanged = escalate_pass(
        body, remaining, outcomes, policy, identity, rater_factory, concurrency=concurrency)
    usage = usage + esc_usage

    # What the record says now, per criterion: the escalated outcome where one stands, the first
    # pass otherwise. Both rows are written; this decides which is not superseded.
    stands = {o.node_id: o for o in outcomes}
    stands.update({o.node_id: o for o in escalated})
    state, reason_code = next_state(list(stands.values()))

    if dry_run:
        log.info("%s (dry run): %s, %d outcome(s), %d escalated, %d call(s)",
                 aid, state, len(outcomes), len(escalated), usage.calls)
        return usage

    ts_version = trait_set_version([c.node_version_id for c in criteria])
    rows = event_rows(artifact, outcomes, identity, ts_version, is_occasion)
    # An escalated row supersedes the pass-1 row written in this same transaction, so the id has
    # to come from the row about to be inserted rather than from a second read.
    first_ids = {r["node_id"]: r["event_id"] for r in rows}
    rows += event_rows(artifact, escalated, identity, ts_version, is_occasion,
                       scrutiny_passes=ESCALATED_PASS, triggers=plan.triggers,
                       supersedes=first_ids)

    # One transaction: every event and the transition, or neither. A partially scored artifact
    # left in `bound` would be picked up again and score its remaining criteria under whatever
    # configuration is active THEN — two raters inside one artifact.
    with eng.begin() as conn:
        conn.execute(text("SELECT set_config('app.tenant', :t, true)"), {"t": tenant})
        conn.execute(text("SELECT set_config('app.actor_type', 'machine', true)"))
        for r in rows:
            conn.execute(_INSERT_EVENT, r)
        moved = conn.execute(
            _SET_STATE, {"state": state, "reason_code": reason_code, "artifact_id": aid}).rowcount
        if moved != 1:
            raise RuntimeError(
                f"{aid} was not in `bound` when the transition ran ({moved} rows). Another worker "
                f"has it; rolling back rather than writing a second rater's scores.")

    if plan.escalate:
        log.info("%s: escalated %d criteria (%s); %d kept the first pass",
                 aid, len(plan.escalate), ", ".join(sorted(set(plan.triggers.values()))),
                 len(unchanged))
    if plan.unfunded:
        # Named, not counted. A criterion that met a declared trigger and got no second look
        # because the budget ran out is a different fact from one that never triggered, and this
        # log line is the only place anybody would ever see it.
        log.warning("%s: escalation budget %d spent; %d criteria triggered and were not "
                    "escalated: %s", aid, policy.budget, len(plan.unfunded),
                    ", ".join(plan.unfunded))

    if not verdict.admitted:
        log.info("%s: the fit gate refused it — %s (%s). %d scoring calls not made.",
                 aid, verdict.reason, verdict.document_is, len(remaining) * 2)

    log.info("%s -> %s: %d event(s), %d call(s)", aid, state, len(rows), usage.calls)
    return usage


def escalate_pass(body: str, criteria: list[Criterion], outcomes: list[Outcome],
                  policy: escalate.Policy, identity: RaterIdentity, rater_factory, *,
                  concurrency: int = score.DEFAULT_CONCURRENCY,
                  ) -> tuple[list[Outcome], escalate.Plan, Usage, dict[str, str]]:
    """The second, deeper look. Same criteria, same paper, higher effort.

    Returns the outcomes that STAND after escalation, the plan (so the run can report what it
    could not fund), the usage, and which node kept its pass-1 result — because an escalated pass
    that changed nothing is a fact worth having, not a no-op.

    Deeper is `effort`, and that is not cosmetic: effort is part of the rater's identity hash, so
    the escalated pass is stamped as coming from a rater that genuinely is not the pass-1 rater.
    `scrutiny_passes` is what lets measurement hold them apart.
    """
    p = escalate.plan(outcomes, policy)
    if not p:
        return [], p, Usage(), {}

    deeper = replace(identity, effort=policy.escalated_effort)
    rater = rater_factory(deeper)
    by_node = {c.node_id: c for c in criteria}
    first_by_node = {o.node_id: o for o in outcomes}

    # The calls concurrently; the KEEP decisions in plan order afterwards. Splitting it that way
    # is deliberate — `escalate.keep` is where a first-pass level survives or is replaced, and a
    # decision like that should not be reached in whatever order the network answered.
    seconds, total = score.gather_criteria(
        [(lambda n=n: score_criterion(body, by_node[n], rater)) for n in p.escalate], concurrency)

    stands, unchanged = [], {}
    for node_id, second in zip(p.escalate, seconds):
        winner, changed = escalate.keep(first_by_node[node_id], second)
        if changed:
            stands.append(winner)
        else:
            # The terminal action, reached early: a deeper look that found nothing does not get to
            # delete a level the first pass produced. The criterion keeps what it had.
            unchanged[node_id] = p.triggers[node_id]
    return stands, p, total, unchanged


def read_text(artifact: dict) -> str:
    """The artifact's text, from wherever the paper actually is.

    `intake` extracts once at read time and stores it, so a student's paper is a column rather than
    a file. A reference paper is a column too, in `corpus_paper`. The local-path branch below is
    what the fixture seeder used before intake existed, and it stays only until that seeder is
    retired — a batch job had a filesystem and the review console, which reads the same text
    through the packet, does not.

    The corpus branch exists because `source_uri` on a reference paper is a corpus locator
    (`corpus:persuade20:E1`), not a path. Falling through to the file branch made the first
    scoring run fail with `No such file or directory: corpus:persuade20:...` — which was at least
    loud, and cost nothing because it happened before any model call.
    """
    if artifact.get("intake_text"):
        return artifact["intake_text"]
    if artifact.get("corpus_text"):
        return artifact["corpus_text"]
    uri = artifact.get("source_uri")
    if not uri:
        raise RuntimeError(
            f"{artifact['artifact_id']} has no source_uri. Binding resolved but no text was "
            f"attached, which is an intake failure, not a scoring one.")
    if uri.startswith("file://"):
        uri = uri[len("file://"):]
    if "://" in uri:
        raise NotImplementedError(
            f"cannot read {uri!r} yet — only local files. GCS and Drive arrive with intake.")
    with open(uri, encoding="utf8") as fh:
        return fh.read()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tenant", default="public")
    ap.add_argument("--config-key", required=True)
    ap.add_argument("--run-id", default=None, help="limit to one run; default is every bound artifact")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--dry-run", action="store_true", help="call the model, write nothing")
    ap.add_argument("--concurrency", type=int, default=score.DEFAULT_CONCURRENCY,
                    help="criteria of ONE artifact in flight at once (1 = sequential)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    try:
        summary = score_pending(tenant=args.tenant, config_key=args.config_key,
                                run_id=args.run_id, limit=args.limit, dry_run=args.dry_run,
                                concurrency=args.concurrency)
    except AlreadyRunning as exc:
        # A refusal, not a crash. On a Cloud Run job a traceback reads as a bug and gets retried;
        # this exits non-zero with the reason on one line.
        raise SystemExit(str(exc))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
