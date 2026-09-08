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

# ARTIFACT-first, composition optional. An `unbound` paper has no packet — nothing has scored it
# and nothing can until a person says whose it is — and 404-ing on it would hide the one artifact a
# teacher most needs to open. That was the shape of this query until the stuck queue existed to
# look at.
_PACKET = text("""
    SELECT a.state, a.state_reason_code, a.student_id, a.section_id, a.task_id, a.iteration,
           a.window_label, a.intake_file_id,
           c.composition_id, c.packet, c.needs_human, c.prior_rater_mismatch, c.created_at
      FROM artifact a
      LEFT JOIN LATERAL (
          SELECT composition_id, packet, needs_human, prior_rater_mismatch, created_at
            FROM artifact_composition x
           WHERE x.artifact_id = a.artifact_id
           ORDER BY created_at DESC LIMIT 1
      ) c ON true
     WHERE a.artifact_id = :artifact_id
""")

# What intake made of the file, for a paper nobody could be matched to. `candidates` is the near
# misses; an EMPTY list is a different answer from three names, and the console has to be able to
# say "we have nothing to go on" rather than implying a shortlist exists.
_INTAKE = text("""
    SELECT f.name, f.status, f.reason_code, f.candidates, f.word_count, f.text,
           f.resolution_basis, f.resolution_path, m.source_ref AS folder, m.read_at
      FROM intake_file f
      JOIN intake_manifest m ON m.manifest_id = f.manifest_id
     WHERE f.file_id = :file_id
""")

# The class, for the picker. A teacher resolving by hand needs the whole roster, not just the near
# misses — the right answer is routinely somebody the filename gave no hint of.
_SECTION_ROSTER = text("""
    SELECT s.student_id, s.display_name
      FROM roster_student s
      JOIN roster_enrollment e ON e.student_id = s.student_id
     WHERE e.tenant_id = :tenant AND e.section_id = :section_id
       AND (e.active_to IS NULL OR e.active_to > now())
     ORDER BY s.display_name
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


# ---------------------------------------------------------------------------------------- #
# The assignment home: where a SET stands, which is the question the per-paper queue cannot
# answer. A teacher does not hold twenty-eight papers in mind; they hold "5B's op-ed" and want
# to know whether it is done. That is one row here and twenty-eight rows in /queue.
#
# WHY ONE QUERY. Every stage below is derived from the same per-artifact CTE, so the pipeline
# bar and the per-assignment counts cannot disagree — a bar that sums to a different number
# than the rows beneath it is worse than no bar, because it invites the reader to trust it.
#
# WHY THE STAGES ARE MUTUALLY EXCLUSIVE. They are drawn as one stacked bar, and a paper counted
# in two segments makes the bar longer than the work. `stage` is a CASE, so each artifact lands
# in exactly one — and `delivered` is checked BEFORE `reviewed` because a released paper whose
# feedback has gone is further along, not both.
_STAGES = """
    WITH sent AS (
        SELECT DISTINCT artifact_id FROM artifact_delivery WHERE status = 'sent'
    ),
    failing AS (
        -- Tried and did not land, with nothing successful since. A paper that failed and was
        -- then delivered is NOT failing; the failure stays in the record without following the
        -- student around.
        SELECT DISTINCT d.artifact_id FROM artifact_delivery d
         WHERE d.status = 'failed'
           AND d.artifact_id NOT IN (SELECT artifact_id FROM sent)
    ),
    staged AS (
        SELECT a.artifact_id, a.section_id, a.task_id, a.iteration, a.window_label, a.state,
               CASE
                 WHEN a.state IN ('unbound','blocked','not_scorable') THEN 'stuck'
                 WHEN a.state IN ('bound','scored','composed')        THEN 'working'
                 WHEN a.state = 'in_review'                           THEN 'ready'
                 WHEN s.artifact_id IS NOT NULL                       THEN 'delivered'
                 ELSE 'reviewed'
               END AS stage,
               (f.artifact_id IS NOT NULL) AS failing
          FROM artifact a
          LEFT JOIN sent s    ON s.artifact_id = a.artifact_id
          LEFT JOIN failing f ON f.artifact_id = a.artifact_id
    )
"""

_PIPELINE = text(_STAGES + """
    SELECT stage, count(*) AS n FROM staged GROUP BY stage
""")

# One row per assignment, where an assignment is the binding key a teacher actually names: this
# class, this task, this iteration. `window_label` rides along because two windows of the same
# task are two sets of work, not one set scored twice.
_ASSIGNMENTS = text(_STAGES + """
    SELECT g.section_id, g.task_id, g.iteration, g.window_label,
           sec.name AS section_name, t.name AS task_name, t.module_key, t.ordinal,
           count(*)                                        AS total,
           count(*) FILTER (WHERE g.stage = 'working')     AS working,
           count(*) FILTER (WHERE g.stage = 'stuck')       AS stuck,
           count(*) FILTER (WHERE g.stage = 'ready')       AS ready,
           count(*) FILTER (WHERE g.stage = 'reviewed')    AS reviewed,
           count(*) FILTER (WHERE g.stage = 'delivered')   AS delivered,
           count(*) FILTER (WHERE g.failing)               AS failing
      FROM staged g
      LEFT JOIN roster_section sec ON sec.section_id = g.section_id
      LEFT JOIN registry_task  t   ON t.task_id      = g.task_id
     GROUP BY g.section_id, g.task_id, g.iteration, g.window_label,
              sec.name, t.name, t.module_key, t.ordinal
     ORDER BY t.module_key NULLS LAST, t.ordinal NULLS LAST, sec.name NULLS LAST, g.iteration
""")

# The two things that stop a paper before anything is scored: we do not know whose it is, or we
# could not read it. Both are fixed on this page, so both are named here rather than counted.
_STUCK = text("""
    SELECT a.artifact_id, a.state, a.state_reason_code, a.section_id, a.task_id,
           sec.name AS section_name, t.name AS task_name,
           f.name AS file_name, s.display_name
      FROM artifact a
      LEFT JOIN roster_section sec ON sec.section_id = a.section_id
      LEFT JOIN registry_task  t   ON t.task_id      = a.task_id
      LEFT JOIN intake_file    f   ON f.file_id      = a.intake_file_id
      LEFT JOIN roster_student s   ON s.student_id   = a.student_id
     WHERE a.state IN ('unbound','blocked','not_scorable')
     ORDER BY a.created_at
     LIMIT :limit
""")

# Order and words are the contract with the bar: the console renders these left to right and
# never invents a label. "Stuck" sits second because it is where the paper stopped, not where it
# is furthest along — the bar is a pipeline, not a ranking.
# The words are a teacher's, not the pipeline's. "Stuck" described how the system felt about the
# paper rather than what the teacher has to do about it, and "attached" is a database verb.
PIPELINE_STAGES: tuple[tuple[str, str], ...] = (
    ("working",   "Being scored"),
    ("stuck",     "Missing information"),
    ("ready",     "Scored, ready for you"),
    ("reviewed",  "You reviewed"),
    ("delivered", "Feedback on the doc"),
)


# "Not loaded yet" and "you may not read this" are different answers, and only the first is
# allowed to render as a calm empty page. Collapsing the second into `available: false` would show
# a teacher a tidy screen saying nothing has been read, when in fact the read was refused — the
# recurring defect in this codebase, a thing reporting success while not doing the job.
_NOT_LOADED_YET = ("UndefinedTable", "UndefinedColumn")


def _is_not_loaded_yet(exc: Exception) -> bool:
    orig = getattr(exc, "orig", None)
    return type(orig).__name__ in _NOT_LOADED_YET


def _unavailable(exc: Exception) -> dict:
    log.info("review tables not available yet: %s", exc)
    return {"available": False, "queue": [], "counts": {}}


def _empty_or_raise(exc: SQLAlchemyError, empty: dict) -> dict:
    """An absent table is `available: false`; anything else is an error and says so."""
    if _is_not_loaded_yet(exc):
        log.info("review tables not available yet: %s", exc)
        return {"available": False, **empty}
    log.error("review read failed: %s", exc)
    raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                        f"the review tables could not be read: {exc}") from exc


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
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such artifact")
        intake = db.execute(
            _INTAKE, {"file_id": row["intake_file_id"]}).mappings().first()             if row["intake_file_id"] else None
        roster = ([dict(r) for r in db.execute(
            _SECTION_ROSTER, {"tenant": "public", "section_id": row["section_id"]}).mappings()]
            if row["state"] == "unbound" and row["section_id"] else [])
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
        "student_id": row["student_id"],
        "composition_id": row["composition_id"],
        "composed_at": row["created_at"].isoformat() if row["created_at"] else None,
        "needs_human": row["needs_human"],
        "prior_rater_mismatch": row["prior_rater_mismatch"],
        "packet": row["packet"],
        # Present for an unbound paper, absent otherwise: the file it came from, what intake made
        # of it, and the class to choose from.
        "intake": ({**dict(intake),
                    "read_at": intake["read_at"].isoformat() if intake["read_at"] else None}
                   if intake else None),
        "roster": roster,
        "events": events,
        "transitions": transitions,
    }


@router.get("/home")
def home(limit: int = 500, db: Session = Depends(get_db_public),
         principal: dict = Depends(get_current_principal)) -> dict:
    """Where every set stands — the page a teacher opens before they open a paper.

    The per-paper queue answers "what is waiting for me". It cannot answer "is 5B's op-ed done",
    which is the question a teacher actually has, because that answer is a property of a SET and
    the queue has no notion of one. This is that page.

    Still no aggregation over anyone's writing: every number is a count of papers in a state.
    There is no class average here for the same reason there is none in the queue.
    """
    try:
        stages = {r["stage"]: r["n"] for r in db.execute(_PIPELINE).mappings()}
        rows = [dict(r) for r in db.execute(_ASSIGNMENTS).mappings()]
        stuck = [dict(r) for r in db.execute(_STUCK, {"limit": limit}).mappings()]
    except SQLAlchemyError as exc:
        db.rollback()
        return _empty_or_raise(exc, {"pipeline": [], "assignments": [], "stuck": []})

    return {
        "available": True,
        # Every stage, including the empty ones. A segment that disappears at zero is how a
        # teacher stops noticing that nothing has been handed back — the same argument as the
        # manifest gate showing all five counts.
        "pipeline": [{"key": k, "label": label, "n": stages.get(k, 0)}
                     for k, label in PIPELINE_STAGES],
        "assignments": rows,
        "stuck": stuck,
    }
