"""The manifest gate: a teacher agrees with a folder once, instead of correcting it file by file.

The plan calls this the largest single saving in the design — one confirmation replacing
twenty-eight corrections — and it is the difference between a script with arguments and a product.
Until this existed, the declaration ("this folder is period 4's final op-ed") arrived as
command-line flags, which works only because the person typing them is the person who would have
agreed to them.

`intake` owns these endpoints because it owns the tables they write, the same cut `scoring` uses
for the teacher's moves. Nothing here creates an artifact; confirming a manifest is what lets
`scoring.bind` do that, and bind reads `confirmed_at` rather than trusting a caller.

## What a confirmation asserts, and what it does not

It does not assert that every match is right — a teacher can be wrong about a name, and correcting
one before confirming is exactly what the per-file endpoint is for. It asserts that the SET is what
they think it is: this folder is that class's work on that task, these files are the submissions,
and the ones the system could not place are genuinely unplaceable rather than a broken integration.

The corrections are the exception the set confirmation exists to make rare. If a teacher is
correcting half the folder, the reconciliation is broken and `inferred_rate` will already have said
so — that number is on the manifest for this reason.

## Why a confirmed read is frozen

The trigger in 0024 refuses an edit to any file under a confirmed manifest. By then `scoring.bind`
may already have made artifacts from those rows, and changing a match afterwards would rewrite what
somebody agreed to without their agreeing again. A correction after confirmation means reading the
folder again — which produces a second manifest, which is what a second read IS.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.db import get_db_public
from app.security import get_current_principal

log = logging.getLogger("intake.review")
router = APIRouter(prefix="/intake", tags=["intake"])

_MANIFESTS = text("""
    SELECT m.manifest_id, m.source_kind, m.source_ref, m.read_at, m.read_by,
           m.declared_section_id, m.declared_task_id, m.declared_iteration,
           m.declared_window_label, m.file_count, m.inferred_rate,
           m.confirmed_at, m.confirmed_by,
           count(*) FILTER (WHERE f.status = 'resolved')         AS resolved,
           count(*) FILTER (WHERE f.status = 'unresolved')       AS unresolved,
           count(*) FILTER (WHERE f.status = 'not_student_work') AS not_student_work,
           count(*) FILTER (WHERE f.status = 'unreadable')       AS unreadable,
           count(*) FILTER (WHERE f.status = 'empty')            AS empty
      FROM intake_manifest m
      LEFT JOIN intake_file f ON f.manifest_id = m.manifest_id
     WHERE m.tenant_id = :tenant
     GROUP BY m.manifest_id
     ORDER BY m.read_at DESC
     LIMIT :limit
""")

_ONE = text("""
    SELECT manifest_id, source_kind, source_ref, read_at, read_by, declared_section_id,
           declared_task_id, declared_iteration, declared_window_label, file_count,
           inferred_rate, confirmed_at, confirmed_by
      FROM intake_manifest WHERE manifest_id = :manifest_id AND tenant_id = :tenant
""")

# The set, in the order a teacher reads it: what needs them first, then what is settled. A folder
# sorted by filename buries the three files that need attention among twenty-five that do not.
_FILES = text("""
    SELECT f.file_id, f.name, f.status, f.reason_code, f.word_count, f.candidates,
           f.resolved_student_id, f.resolution_basis, f.resolution_path, f.match_score,
           s.display_name
      FROM intake_file f
      LEFT JOIN roster_student s ON s.student_id = f.resolved_student_id
     WHERE f.manifest_id = :manifest_id
     ORDER BY CASE f.status WHEN 'unresolved' THEN 0 WHEN 'unreadable' THEN 1
                            WHEN 'empty' THEN 2 WHEN 'not_student_work' THEN 3 ELSE 4 END,
              f.name
""")

# Who is on the roster but has nothing in the folder. A teacher wants this more than they want the
# matched list, and it is the one thing a per-file view can never show.
_MISSING = text("""
    SELECT s.student_id, s.display_name
      FROM roster_student s
      JOIN roster_enrollment e ON e.student_id = s.student_id
     WHERE e.tenant_id = :tenant AND e.section_id = :section_id
       AND (e.active_to IS NULL OR e.active_to > now())
       AND NOT EXISTS (SELECT 1 FROM intake_file f
                        WHERE f.manifest_id = :manifest_id
                          AND f.resolved_student_id = s.student_id)
     ORDER BY s.display_name
""")

_ROSTER = text("""
    SELECT s.student_id, s.display_name
      FROM roster_student s
      JOIN roster_enrollment e ON e.student_id = s.student_id
     WHERE e.tenant_id = :tenant AND e.section_id = :section_id
       AND (e.active_to IS NULL OR e.active_to > now())
     ORDER BY s.display_name
""")

_CONFIRM = text("""
    UPDATE intake_manifest SET confirmed_at = now(), confirmed_by = :who
     WHERE manifest_id = :manifest_id AND tenant_id = :tenant AND confirmed_at IS NULL
""")

_ASSIGN = text("""
    UPDATE intake_file
       SET resolved_student_id = :student_id, status = 'resolved',
           resolution_basis = 'teacher', resolution_path = 'looked_up', reason_code = NULL
     WHERE file_id = :file_id AND tenant_id = :tenant
""")

_UNASSIGN = text("""
    UPDATE intake_file
       SET resolved_student_id = NULL, status = :status,
           resolution_basis = NULL, resolution_path = NULL, reason_code = :reason
     WHERE file_id = :file_id AND tenant_id = :tenant
""")

# A student may hand in once. Two files pointing at one person under one manifest is a correction
# that needs undoing rather than a second submission.
_TAKEN = text("""
    SELECT file_id, name FROM intake_file
     WHERE manifest_id = :manifest_id AND resolved_student_id = :student_id
       AND file_id <> :file_id
""")

_MANIFEST_OF = text("SELECT manifest_id FROM intake_file WHERE file_id = :file_id")


def _who(principal: dict) -> str:
    return principal.get("email") or principal.get("sub") or "unknown"


@router.get("/manifests")
def manifests(limit: int = 50, db: Session = Depends(get_db_public),
              principal: dict = Depends(get_current_principal)) -> dict:
    """Every folder read, newest first, with what each read found."""
    try:
        rows = [dict(r) for r in db.execute(
            _MANIFESTS, {"tenant": "public", "limit": limit}).mappings()]
    except Exception as exc:                       # before the migration has run
        db.rollback()
        log.info("intake tables not available yet: %s", exc)
        return {"available": False, "manifests": []}

    for r in rows:
        r["read_at"] = r["read_at"].isoformat() if r.get("read_at") else None
        r["confirmed_at"] = r["confirmed_at"].isoformat() if r.get("confirmed_at") else None
        r["inferred_rate"] = float(r["inferred_rate"]) if r["inferred_rate"] is not None else None
    return {"available": True, "manifests": rows}


@router.get("/manifest/{manifest_id}")
def manifest(manifest_id: str, db: Session = Depends(get_db_public),
             principal: dict = Depends(get_current_principal)) -> dict:
    """One read: the declaration, every file, and who on the roster handed in nothing."""
    row = db.execute(_ONE, {"manifest_id": manifest_id, "tenant": "public"}).mappings().first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such folder read")

    files = [dict(f) for f in db.execute(_FILES, {"manifest_id": manifest_id}).mappings()]
    for f in files:
        f["match_score"] = float(f["match_score"]) if f["match_score"] is not None else None

    section = row["declared_section_id"]
    missing = ([dict(m) for m in db.execute(
        _MISSING, {"tenant": "public", "section_id": section,
                   "manifest_id": manifest_id}).mappings()] if section else [])
    roster = ([dict(r) for r in db.execute(
        _ROSTER, {"tenant": "public", "section_id": section}).mappings()] if section else [])

    return {
        "available": True,
        **{k: v for k, v in dict(row).items() if k not in ("read_at", "confirmed_at",
                                                           "inferred_rate")},
        "read_at": row["read_at"].isoformat() if row["read_at"] else None,
        "confirmed_at": row["confirmed_at"].isoformat() if row["confirmed_at"] else None,
        "inferred_rate": float(row["inferred_rate"]) if row["inferred_rate"] is not None else None,
        "files": files,
        # Not a footnote. Who is missing is what a teacher chases, and it is the one thing a
        # file-by-file view structurally cannot show.
        "missing_students": missing,
        "roster": roster,
    }


@router.post("/file/{file_id}/assign")
def assign(file_id: str, payload: dict = Body(...), db: Session = Depends(get_db_public),
           principal: dict = Depends(get_current_principal)) -> dict:
    """Correct one file's student before the set is confirmed.

    Stamped `looked_up` with basis `teacher`: a person read the paper and knew. That is a stronger
    resolution than any string match, and recording it as such keeps `inferred_rate` meaning what
    it says — the share of bindings nobody confirmed.
    """
    student_id = payload.get("student_id")
    manifest_id = db.execute(_MANIFEST_OF, {"file_id": file_id}).scalar()
    if manifest_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such file")

    if student_id:
        taken = db.execute(_TAKEN, {"manifest_id": manifest_id, "student_id": student_id,
                                    "file_id": file_id}).mappings().first()
        if taken:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"{taken['name']} is already attached to that student in this folder. A student "
                f"hands in once — detach that file first if this is the correction.")

    try:
        if student_id:
            n = db.execute(_ASSIGN, {"file_id": file_id, "student_id": student_id,
                                     "tenant": "public"}).rowcount
        else:
            n = db.execute(_UNASSIGN, {"file_id": file_id, "tenant": "public",
                                       "status": "unresolved",
                                       "reason": "detached_by_teacher"}).rowcount
        db.commit()
    except DBAPIError as exc:
        db.rollback()
        # The freeze trigger's own words: it names the manifest and when it was confirmed.
        orig = getattr(exc, "orig", None)
        raise HTTPException(status.HTTP_409_CONFLICT,
                            str(orig or exc).strip().splitlines()[0]) from exc

    if n != 1:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such file")
    log.info("file %s assigned to %s by %s", file_id, student_id, _who(principal))
    return {"file_id": file_id, "student_id": student_id}


@router.post("/manifest/{manifest_id}/confirm")
def confirm(manifest_id: str, db: Session = Depends(get_db_public),
            principal: dict = Depends(get_current_principal)) -> dict:
    """Agree with the set. This is the gate `scoring.bind` reads.

    One confirmation for the folder, not one per paper. What it asserts is that the SET is what
    the teacher thinks it is — not that every match is right, which is why corrections come first
    and this comes once.
    """
    who = _who(principal)
    row = db.execute(_ONE, {"manifest_id": manifest_id, "tenant": "public"}).mappings().first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such folder read")
    if row["confirmed_at"] is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"this folder was already confirmed by {row['confirmed_by']}. Read it again to pick "
            f"up anything that has changed since.")

    n = db.execute(_CONFIRM, {"manifest_id": manifest_id, "tenant": "public", "who": who}).rowcount
    db.commit()
    if n != 1:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "somebody confirmed this while you were looking at it — reload")
    log.info("manifest %s confirmed by %s", manifest_id, who)
    return {"manifest_id": manifest_id, "confirmed_by": who}
