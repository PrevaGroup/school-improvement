"""The teacher's moves: override a level, release the work, or withhold it.

`scoring` owns these endpoints because it owns the tables they write, the same way `sip` owns its
own ingest routes. `serving` reads the queue with SQL and imports nothing — a produced table is the
contract, and a release implemented in two places is an authority claim implemented in two places.

## Only a teacher may release, and this file is not what enforces it

The trigger in migration 0008 is. Every request sets `app.actor_type` from the VERIFIED identity
rather than from anything the caller sends, and a code path that forgets to set it gets `machine`
and is refused. This module could be rewritten badly and the claim would still hold, which is the
only reason it is worth stating.

`app.actor_id` carries the principal's subject, so "who released this" is answerable from
`artifact_state_transition` rather than from an application log that may have rotated.

## An override appends

A teacher who disagrees with a level writes a NEW event referencing the one they disagree with. The
pairing survives — this configuration said 3, this named teacher said 2 — and that pairing is a
calibration observation about the configuration, which is most of why overrides are worth
collecting at all. Nothing is edited; `score_event` refuses UPDATE by trigger and the API role does
not hold the grant either.

The override is stamped `human_blind = false`: the teacher saw the model's score before disagreeing
with it. That is the honest record and it matters later — an informed second rating cannot serve as
an independent one in a calibration design, and a column that quietly said otherwise would corrupt
the analysis rather than the interface.

## What is NOT here yet

Section scoping. `roster_visible_sections()` exists, is tested, and fails closed, and nothing calls
it: the demo roster has no staff rows, so wiring it now would return an empty queue to everyone.
Until it is wired, any signed-in user can see any artifact in the tenant. That is acceptable only
because this subsystem holds synthetic papers and will hold no real student writing before a
hardening phase — the same posture that leaves RLS off these tables. It is written down here
because a gap nobody wrote down is a gap somebody will assume was closed.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.db import get_db_public
from app.security import get_current_principal

from ._ids import uuid7

log = logging.getLogger("scoring.review")
router = APIRouter(prefix="/review", tags=["review"])

# The teacher's own moves. Anything else is the pipeline's, and a request that named one would be
# asking the API to impersonate the machine.
TEACHER_MOVES = {"released", "withheld", "in_review"}

_ARTIFACT = text("""
    SELECT artifact_id, state, student_id, section_id, task_id, iteration, tenant_id
      FROM artifact WHERE artifact_id = :artifact_id
""")

_EVENT = text("""
    SELECT event_id, artifact_id, node_id, status, level, run_id, student_id, section_id,
           task_id, iteration, window_label, trait_set_version, rubric_version, form_variant,
           scoring_configuration_id, is_measurement_occasion, tenant_id, visibility
      FROM score_event WHERE event_id = :event_id
""")

_SET_STATE = text("""
    UPDATE artifact SET state = :state, state_reason_code = :reason_code
     WHERE artifact_id = :artifact_id AND state = :from_state
""")

_INSERT_OVERRIDE = text("""
    INSERT INTO score_event (
        event_id, artifact_id, run_id, student_id, section_id, task_id, iteration, window_label,
        node_id, trait_set_version, rubric_version, form_variant, scoring_configuration_id,
        scorer_type, scorer_id, human_blind, scrutiny_passes, status, level, confidence, reason,
        reason_code, evidence, is_measurement_occasion, enters_calibration,
        supersedes_event_id, set_override_id, idempotency_key, tenant_id, visibility)
    VALUES (
        :event_id, :artifact_id, :run_id, :student_id, :section_id, :task_id, :iteration,
        :window_label, :node_id, :trait_set_version, :rubric_version, :form_variant,
        :scoring_configuration_id,
        'teacher', :scorer_id, false, 1, :status, :level, NULL, :reason,
        'teacher_override', NULL, :is_measurement_occasion, false,
        :supersedes_event_id, :set_override_id, :idempotency_key, :tenant_id, :visibility)
""")


def _bind_teacher(db: Session, principal: dict) -> str:
    """Bind the acting identity for this transaction, from the VERIFIED principal.

    The trigger reads these. Nothing the client sends reaches them, which is what makes the
    release authority a property of the request rather than of the request body.
    """
    actor_id = principal.get("sub") or principal.get("email") or "unknown"
    db.execute(text("SELECT set_config('app.actor_type', 'teacher', true)"))
    db.execute(text("SELECT set_config('app.actor_id', :a, true)"), {"a": actor_id})
    return actor_id


def _artifact_or_404(db: Session, artifact_id: str) -> dict:
    row = db.execute(_ARTIFACT, {"artifact_id": artifact_id}).mappings().first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such artifact")
    return dict(row)


@router.post("/{artifact_id}/state")
def move(artifact_id: str, payload: dict = Body(...), db: Session = Depends(get_db_public),
         principal: dict = Depends(get_current_principal)) -> dict:
    """Make one of the teacher's moves. The database decides whether it is legal."""
    to_state = str(payload.get("state") or "")
    if to_state not in TEACHER_MOVES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{to_state!r} is not a teacher's move. A machine move requested through this "
            f"endpoint would be the API impersonating the pipeline.")

    artifact = _artifact_or_404(db, artifact_id)
    actor_id = _bind_teacher(db, principal)
    try:
        moved = db.execute(_SET_STATE, {
            "artifact_id": artifact_id, "from_state": artifact["state"], "state": to_state,
            "reason_code": payload.get("reason_code")}).rowcount
        db.commit()
    except DBAPIError as exc:
        db.rollback()
        # The trigger's own message names the states and says what was wrong with the move; it is
        # better than anything this layer could reconstruct, so it is passed through.
        raise HTTPException(status.HTTP_409_CONFLICT, _trigger_message(exc)) from exc

    if moved != 1:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "the artifact moved while you were looking at it — reload")
    log.info("%s %s -> %s by %s", artifact_id, artifact["state"], to_state, actor_id)
    return {"artifact_id": artifact_id, "from_state": artifact["state"], "state": to_state,
            "actor_id": actor_id}


@router.post("/{artifact_id}/override")
def override(artifact_id: str, payload: dict = Body(...), db: Session = Depends(get_db_public),
             principal: dict = Depends(get_current_principal)) -> dict:
    """Disagree with one criterion. Appends; never edits.

    `set_override_id` groups one judgment applied to several artifacts, so a decision made once is
    not later counted as N independent human ratings — which would inflate apparent disagreement
    and hide that a single judgment was made.
    """
    prior_id = str(payload.get("supersedes_event_id") or "")
    prior = db.execute(_EVENT, {"event_id": prior_id}).mappings().first()
    if prior is None or prior["artifact_id"] != artifact_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "no such score event on this artifact")

    new_status = str(payload.get("status") or "scored")
    level = payload.get("level")
    if (new_status == "scored") != (level is not None):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "a level exists if and only if the status is `scored`. An abstention with a number "
            "on it is a claim nobody made.")

    actor_id = _bind_teacher(db, principal)
    event_id = uuid7()
    try:
        db.execute(_INSERT_OVERRIDE, {
            "event_id": event_id,
            "artifact_id": artifact_id,
            "run_id": prior["run_id"],
            "student_id": prior["student_id"],
            "section_id": prior["section_id"],
            "task_id": prior["task_id"],
            "iteration": prior["iteration"],
            "window_label": prior["window_label"],
            "node_id": prior["node_id"],
            "trait_set_version": prior["trait_set_version"],
            "rubric_version": prior["rubric_version"],
            "form_variant": prior["form_variant"],
            # The override is ABOUT this configuration's judgment, so it keeps pointing at it.
            "scoring_configuration_id": prior["scoring_configuration_id"],
            "scorer_id": actor_id,
            "status": new_status,
            "level": level,
            "reason": payload.get("reason"),
            "is_measurement_occasion": prior["is_measurement_occasion"],
            "supersedes_event_id": prior_id,
            "set_override_id": payload.get("set_override_id"),
            "idempotency_key": f"{artifact_id}|{prior['node_id']}|override|{event_id}",
            "tenant_id": prior["tenant_id"],
            "visibility": prior["visibility"]})
        db.commit()
    except DBAPIError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, _trigger_message(exc)) from exc

    log.info("override on %s/%s by %s", artifact_id, prior["node_id"], actor_id)
    return {"event_id": event_id, "supersedes_event_id": prior_id,
            "node_id": prior["node_id"], "status": new_status, "level": level,
            "scorer_id": actor_id}


def _trigger_message(exc: DBAPIError) -> str:
    """The database's own words. A rewritten message loses the states it names."""
    orig = getattr(exc, "orig", None)
    detail = str(getattr(orig, "diag", None) and orig.diag.message_primary or orig or exc)
    return detail.strip().splitlines()[0] if detail else "the database refused the change"
