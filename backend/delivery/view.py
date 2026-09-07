"""What happened to a hand-back, for the console to show.

READ ONLY, and that is a constraint rather than a stage. The `file` channel writes beside the
paper, which means it only works where the folder is — a batch job on the machine holding it. The
API runs on Cloud Run with no access to that filesystem, so a "send it" button here would produce
a `failed` row every time and teach a teacher that delivery is broken.

When Drive arrives the channel is reachable from anywhere and this becomes the natural place for
the action. Until then the console shows what happened and the batch job makes it happen, which is
honest about where the capability actually is.

`serving` would normally own a read like this. It lives here because the module that owns the table
is the one that knows what an attempt MEANS — that a `failed` row is not an error to hide, that the
latest attempt is the current state, and that a `sent` row for a superseded composition is a
student holding an older message than the one on screen.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import get_db_public
from app.security import get_current_principal

log = logging.getLogger(__name__)
router = APIRouter(prefix="/delivery", tags=["delivery"])

# Every attempt, newest last, so a chain reads the way it happened.
_ATTEMPTS = text("""
    SELECT delivery_id, composition_id, channel, target_ref, status, detail,
           message_hash, attempted_at, delivered_at, attempted_by
      FROM artifact_delivery
     WHERE artifact_id = :artifact_id
     ORDER BY attempted_at
""")

# The count for the queue's last segment. `sent` only — a failed attempt is not a hand-back, and
# counting it as one is the silence the whole table exists to prevent.
_COUNTS = text("""
    SELECT count(DISTINCT artifact_id) FILTER (WHERE status = 'sent')   AS delivered,
           count(DISTINCT artifact_id) FILTER (WHERE status = 'failed'
                 AND artifact_id NOT IN (SELECT artifact_id FROM artifact_delivery
                                          WHERE status = 'sent'))       AS failing
      FROM artifact_delivery
     WHERE tenant_id = :tenant
""")


@router.get("/{artifact_id}")
def attempts(artifact_id: str, db: Session = Depends(get_db_public),
             principal: dict = Depends(get_current_principal)) -> dict:
    """Every attempt to hand this paper back, and what the student is currently holding."""
    try:
        rows = [dict(r) for r in db.execute(
            _ATTEMPTS, {"artifact_id": artifact_id}).mappings()]
    except SQLAlchemyError as exc:
        db.rollback()
        log.info("delivery table not available yet: %s", exc)
        return {"available": False, "attempts": []}

    for r in rows:
        for f in ("attempted_at", "delivered_at"):
            r[f] = r[f].isoformat() if r.get(f) else None

    sent = [r for r in rows if r["status"] == "sent"]
    return {
        "available": True,
        "attempts": rows,
        # What the student is holding, which is not the same as the latest attempt: a failed retry
        # after a successful send leaves them with the earlier message, and the screen must not
        # imply they have nothing.
        "delivered": sent[-1] if sent else None,
        "last_attempt": rows[-1] if rows else None,
    }


@router.get("")
def summary(db: Session = Depends(get_db_public),
            principal: dict = Depends(get_current_principal)) -> dict:
    """Counts for the queue: handed back, and failing with nothing delivered."""
    try:
        row = db.execute(_COUNTS, {"tenant": "public"}).mappings().first()
    except SQLAlchemyError as exc:
        db.rollback()
        log.info("delivery table not available yet: %s", exc)
        return {"available": False, "delivered": 0, "failing": 0}
    return {"available": True, **dict(row)}
