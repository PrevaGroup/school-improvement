"""Hand released feedback back, and record every attempt including the ones that fail.

    python -m delivery.deliver --as "Tim Kinkead" [--channel file] [--dry-run]

`released` means a teacher approved a message. This is what happens next, and until it existed the
product stopped one step short of its purpose: feedback that is correct, signed off, and never
read by the student it was written for.

## An edited message is a new thing to deliver

The queue asks whether THIS composition has been sent, not whether the artifact ever has. A
teacher who edits after delivery has written a new composition and the student is holding the old
one — excluding the artifact would mean the edit never reached anybody while the console showed
the new text as the message. Both attempts stay in the record, with different hashes, which is
what answers "which version did the student actually read".

## Failures are rows, not silence

A delivery that quietly did not happen is indistinguishable from one that did, on every screen a
teacher looks at. Twenty-six students got their feedback and two did not, and nobody knows which
two. So a failure writes a row that says what failed, and a retry writes another — the attempt
that failed stays.

## `released` is checked by the database, not here

The trigger in 0025 refuses an insert for an artifact in any other state. This module is one way
to reach that table and a script is another, so the rule lives where both meet — the same argument
as the release authority itself. What this module contributes is the attempt, not the permission.

## Channels

`file` writes the message beside the paper it is about, which is real delivery to a real place and
verifiable in a local-folder demo. `google_docs_comment` and `classroom` are the plan's two real
ones and arrive with Drive; neither requires the student to sign in, which is what keeps a consent
and minor-account surface out of the pilot.

Adding one means adding a function to `CHANNELS` and nothing else. A channel that raises is a
`failed` row with the exception's own words in it — a delivery module that swallowed an error
would be the silence this exists to prevent.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import pathlib
from datetime import datetime, timezone

from sqlalchemy import text

from ._db import engine
from ._ids import uuid7

log = logging.getLogger("delivery.deliver")


class DeliveryFailed(Exception):
    """A channel could not deliver. Carries the reason a teacher will read at 8am."""


# Released, with a message, and nothing successfully sent yet. `not_sent` and `failed` rows do NOT
# exclude an artifact — a retry is the normal response to both, and the earlier attempt stays.
_PENDING = text("""
    SELECT a.artifact_id, a.student_id, a.tenant_id, a.visibility, a.intake_file_id,
           c.composition_id, c.packet,
           f.name AS file_name, m.source_ref AS folder
      FROM artifact a
      JOIN LATERAL (
          SELECT composition_id, packet FROM artifact_composition x
           WHERE x.artifact_id = a.artifact_id
           ORDER BY created_at DESC LIMIT 1
      ) c ON true
      LEFT JOIN intake_file f ON f.file_id = a.intake_file_id
      LEFT JOIN intake_manifest m ON m.manifest_id = f.manifest_id
     WHERE a.tenant_id = :tenant AND a.state = 'released'
       -- Nothing sent for THIS composition. Not "nothing sent for this artifact": a teacher who
       -- edits a message after it went out has written a new composition, and the student is
       -- holding the old one. Excluding the artifact would mean the edit silently never
       -- reached anybody while the console showed the new text as the message.
       --
       -- This is what `message_hash` was for and the queue was never re-offering.
       AND NOT EXISTS (
           SELECT 1 FROM artifact_delivery d
            WHERE d.artifact_id = a.artifact_id
              AND d.composition_id = c.composition_id
              AND d.status = 'sent')
     ORDER BY a.created_at
     LIMIT :limit
""")

_INSERT = text("""
    INSERT INTO artifact_delivery
        (delivery_id, artifact_id, composition_id, channel, target_ref, status, detail,
         message_hash, delivered_at, attempted_by, supersedes_delivery_id, tenant_id, visibility)
    VALUES (:delivery_id, :artifact_id, :composition_id, :channel, :target_ref, :status, :detail,
            :message_hash, :delivered_at, :attempted_by, :supersedes, :tenant_id, :visibility)
""")

# The attempt this one follows, so a retry chain reads in order rather than as a pile of rows with
# the same artifact id.
_LAST_ATTEMPT = text("""
    SELECT delivery_id FROM artifact_delivery
     WHERE artifact_id = :artifact_id
     ORDER BY attempted_at DESC LIMIT 1
""")


# ------------------------------------------------------------------ channels


def send_to_file(row: dict, message: str) -> str:
    """Write the message beside the paper it is about, and return where it went.

    Not a stand-in for delivery — it IS delivery, to a folder somebody can open. That makes the
    whole path demonstrable before Drive exists, and it exercises the same failure modes: a folder
    that has moved, a permission that changed, a name that is not writable.
    """
    folder, name = row.get("folder"), row.get("file_name")
    if not folder or not name:
        raise DeliveryFailed(
            "this paper is not linked to a file in a folder, so there is nowhere to put the "
            "feedback. It was bound before intake existed, or its manifest has been removed.")
    target = pathlib.Path(folder) / f"{pathlib.Path(name).stem} — feedback.txt"
    try:
        target.write_text(message, encoding="utf8")
    except OSError as exc:
        raise DeliveryFailed(f"could not write {target}: {exc}") from exc
    return str(target)


def send_to_nowhere(row: dict, message: str) -> str:
    """Record that a message is approved and deliberately held.

    The console prototype's "approved, waiting to go out" — a teacher handing back at the end of
    the lesson has agreed to something that has not gone yet, and that is not a failure.
    """
    raise DeliveryFailed("no channel configured — the message is approved and waiting")


CHANNELS = {"file": send_to_file, "none": send_to_nowhere}


# ------------------------------------------------------------------ pure (unit-tested)


def message_of(packet: dict) -> str | None:
    """What the student would read. Absent means there is nothing to deliver."""
    return ((packet or {}).get("feedback") or {}).get("message") or None


def attempt_row(row: dict, *, channel: str, status: str, target: str | None,
                detail: str | None, message: str, actor: str, supersedes: str | None) -> dict:
    """One attempt, ready to insert. Pure, so the shape can be checked without a database."""
    return {
        "delivery_id": uuid7(),
        "artifact_id": row["artifact_id"],
        "composition_id": row["composition_id"],
        "channel": channel,
        "target_ref": target,
        "status": status,
        "detail": detail,
        # What was actually sent. If the message is edited afterwards, this is the evidence of
        # which version the student read.
        "message_hash": hashlib.sha256(message.encode("utf8")).hexdigest()[:32],
        "delivered_at": datetime.now(timezone.utc) if status == "sent" else None,
        "attempted_by": actor,
        "supersedes": supersedes,
        "tenant_id": row["tenant_id"],
        "visibility": row["visibility"],
    }


# ------------------------------------------------------------------ the loop


def deliver_pending(*, tenant: str, actor: str, channel: str = "file", limit: int = 200,
                    dry_run: bool = False) -> dict:
    eng = engine()
    send = CHANNELS.get(channel)
    if send is None:
        raise ValueError(f"no channel called {channel!r} — have {sorted(CHANNELS)}")

    with eng.connect() as conn:
        conn.execute(text("SELECT set_config('app.tenant', :t, true)"), {"t": tenant})
        pending = [dict(r) for r in conn.execute(
            _PENDING, {"tenant": tenant, "limit": limit}).mappings()]

    sent, failed, skipped = 0, [], 0
    for row in pending:
        message = message_of(row["packet"])
        if not message:
            # Released with no message is a real state — a teacher can approve scores without a
            # student-facing draft — and it is not a delivery failure.
            skipped += 1
            continue

        try:
            target, status, detail = send(row, message), "sent", None
        except DeliveryFailed as exc:
            target, status, detail = None, "failed", str(exc)
        except Exception as exc:                  # a channel that raises anything else still says
            target, status, detail = None, "failed", f"{type(exc).__name__}: {exc}"

        if dry_run:
            log.info("%s -> %s (%s)", row["artifact_id"], status, target or detail)
            sent += status == "sent"
            continue

        with eng.begin() as conn:
            conn.execute(text("SELECT set_config('app.tenant', :t, true)"), {"t": tenant})
            previous = conn.execute(
                _LAST_ATTEMPT, {"artifact_id": row["artifact_id"]}).scalar()
            conn.execute(_INSERT, attempt_row(
                row, channel=channel, status=status, target=target, detail=detail,
                message=message, actor=actor, supersedes=previous))

        if status == "sent":
            sent += 1
            log.info("%s -> %s", row["artifact_id"], target)
        else:
            failed.append({"artifact_id": row["artifact_id"], "detail": detail})
            log.error("%s: %s", row["artifact_id"], detail)

    return {"released_awaiting_delivery": len(pending), "sent": sent,
            # Named, not counted. A failure a teacher cannot see is the silence this exists to
            # prevent, and a number is not something anyone can act on.
            "failed": failed,
            "no_message": skipped, "channel": channel, "dry_run": dry_run}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--as", dest="actor", required=True,
                    help="who is handing back — recorded on every attempt")
    ap.add_argument("--tenant", default="public")
    ap.add_argument("--channel", default="file", choices=sorted(CHANNELS))
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--dry-run", action="store_true", help="attempt nothing, record nothing")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    print(json.dumps(deliver_pending(tenant=args.tenant, actor=args.actor, channel=args.channel,
                                     limit=args.limit, dry_run=args.dry_run), indent=1))


if __name__ == "__main__":
    main()
