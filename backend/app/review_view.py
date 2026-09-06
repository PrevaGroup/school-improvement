"""The teacher's review queue — `serving`'s read side of the writing subsystem.

Reads `artifact`, `artifact_composition` and `score_event` with SQL and imports nothing from
`scoring`. The write side (release, withhold, override) lives in `scoring` itself, because it owns
those tables and an authority claim implemented twice is an authority claim.

Degrades honestly: before the scoring migrations have run, or before anything has been composed,
the endpoints return `available: false` and an empty queue rather than a 500. A console that says
"nothing here yet" is right; one that says "something broke" when nothing has been loaded is not.

WHAT THE QUEUE DELIBERATELY DOES NOT DO. It does not aggregate. There is no class average, no total
per student, no completion percentage across criteria. Every number a teacher sees is one criterion
of one paper, because a mean over criterion levels is a number nobody assigned and the scale is
criterion-referenced — a level says the writing meets that descriptor, not that it ranks anywhere.
The counts here are counts of PAPERS in a state, which is a fact about the queue rather than a
claim about anyone's writing.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .db import get_db_public
from .security import get_current_principal

log = logging.getLogger(__name__)
router = APIRouter(prefix="/review", tags=["review"])

# States a teacher is looking at. `scored` and `composed` are transient machine states — an
# artifact sitting in one is mid-pipeline, not waiting for a person.
TEACHER_STATES = ("in_review", "blocked", "released", "withheld", "not_scorable", "unbound")

_QUEUE = text("""
    SELECT a.artifact_id, a.state, a.state_reason_code, a.student_id, a.section_id,
           a.task_id, a.iteration, a.window_label, a.created_at,
           -- The roster's name when there is one. Falling back to the identifier is honest: it
           -- shows a key, which is what an unrostered student IS, rather than a tidied-up key that
           -- looks like a name.
           s.display_name,
           c.composition_id, c.needs_human, c.prior_rater_mismatch,
           jsonb_array_length(coalesce(c.packet->'feedback'->'holds', '[]'::jsonb)) AS holds,
           jsonb_array_length(coalesce(c.packet->'criteria', '[]'::jsonb))          AS criteria
      FROM artifact a
      LEFT JOIN LATERAL (
          SELECT composition_id, needs_human, prior_rater_mismatch, packet
            FROM artifact_composition x
           WHERE x.artifact_id = a.artifact_id
           ORDER BY created_at DESC LIMIT 1
      ) c ON true
      LEFT JOIN roster_student s ON s.student_id = a.student_id
     WHERE a.state = ANY(:states)
     ORDER BY a.state, a.created_at
     LIMIT :limit
""")

_PACKET = text("""
    SELECT c.composition_id, c.packet, c.needs_human, c.prior_rater_mismatch, c.created_at,
           a.state, a.state_reason_code
      FROM artifact_composition c
      JOIN artifact a USING (artifact_id)
     WHERE c.artifact_id = :artifact_id
     ORDER BY c.created_at DESC
     LIMIT 1
""")

# The live scores, which are NOT the packet's copy. After an override the packet still holds what
# the teacher saw when they decided, and this holds what the record now says. Showing the packet's
# copy after an override would show a teacher their own change had not happened.
_EVENTS = text("""
    SELECT event_id, node_id, status, level, confidence, reason, scorer_type, scorer_id,
           supersedes_event_id, created_at
      FROM score_event
     WHERE artifact_id = :artifact_id
     ORDER BY node_id, created_at
""")

_TRANSITIONS = text("""
    SELECT from_state, to_state, actor_type, actor_id, created_at
      FROM artifact_state_transition
     WHERE artifact_id = :artifact_id
     ORDER BY created_at
""")


def _unavailable(exc: Exception) -> dict:
    log.info("review tables not available yet: %s", exc)
    return {"available": False, "queue": [], "counts": {}}


@router.get("/queue")
def queue(limit: int = 200, db: Session = Depends(get_db_public),
          principal: dict = Depends(get_current_principal)) -> dict:
    """Every paper waiting on a person, and what each is waiting for."""
    try:
        rows = [dict(r) for r in db.execute(
            _QUEUE, {"states": list(TEACHER_STATES), "limit": limit}).mappings()]
    except SQLAlchemyError as exc:
        db.rollback()
        return _unavailable(exc)

    counts: dict[str, int] = {}
    for r in rows:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
        r["created_at"] = r["created_at"].isoformat() if r.get("created_at") else None
    return {"available": True, "queue": rows, "counts": counts}


@router.get("/artifact/{artifact_id}")
def artifact(artifact_id: str, db: Session = Depends(get_db_public),
             principal: dict = Depends(get_current_principal)) -> dict:
    """One paper: the packet the teacher reviews, the live scores, and the audit trail."""
    try:
        row = db.execute(_PACKET, {"artifact_id": artifact_id}).mappings().first()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND,
                                "no review packet for this artifact yet")
        events = [dict(e) for e in db.execute(
            _EVENTS, {"artifact_id": artifact_id}).mappings()]
        transitions = [dict(t) for t in db.execute(
            _TRANSITIONS, {"artifact_id": artifact_id}).mappings()]
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "the review tables are not available yet") from exc

    for e in events:
        e["created_at"] = e["created_at"].isoformat() if e.get("created_at") else None
        e["level"] = float(e["level"]) if e["level"] is not None else None
    for t in transitions:
        t["created_at"] = t["created_at"].isoformat() if t.get("created_at") else None

    # Which event currently stands for each criterion: the newest one, override or not. The
    # superseded rows stay in the list so the console can show that a change was made and by whom.
    superseded = {e["supersedes_event_id"] for e in events if e["supersedes_event_id"]}
    for e in events:
        e["current"] = e["event_id"] not in superseded

    return {
        "available": True,
        "artifact_id": artifact_id,
        "state": row["state"],
        "state_reason_code": row["state_reason_code"],
        "composition_id": row["composition_id"],
        "composed_at": row["created_at"].isoformat() if row["created_at"] else None,
        "needs_human": row["needs_human"],
        "prior_rater_mismatch": row["prior_rater_mismatch"],
        "packet": row["packet"],
        "events": events,
        "transitions": transitions,
    }
