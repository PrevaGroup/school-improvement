"""Read a folder of student work, work out whose each file is, and record what was there.

    python -m intake.read_folder --folder /tmp/11b-oped --section 11b --task fs10-oped \\
                                 --iteration final --window "fall 2026" [--dry-run]

WHAT THIS PRODUCES is a manifest: one row for the read, one row per file, and a status on each. It
creates no artifacts — `artifact` belongs to `scoring`, and `scoring/bind.py` reads these rows to
make them. The writes run one way only.

## The declaration and the inference are different things

Three of the four binding elements are DECLARED. A teacher says "this folder is period 4's final
op-ed", and that is an assertion about the folder, not something worked out from evidence. Only the
student is inferred, per file, from whatever the file carries.

Keeping them apart is why `resolution_path` means anything. A score whose student was inferred from
a filename has a different error profile from one looked up from an account, and pooling them pools
two populations. It is also the earliest signal an integration has broken: `inferred_rate` rising
on a folder means account matching stopped working, and it shows up here before it shows up as
somebody else's score on a student's record.

## Reading the same folder twice is the normal case

Papers arrive late. Students keep editing after the deadline. A teacher presses sync again. So a
second read produces a second manifest rather than an update, `source_ref` is stable across both,
and a changed `text_hash` under one `source_ref` is a student who kept working — which becomes a
new artifact superseding the old, not an edit to one already scored. None of that logic lives here;
it lives in `bind.py`, because it is a fact about artifacts.

## Local folders now, Drive behind the same seam

`--folder` reads a directory, which is enough to exercise the whole path today and needs no OAuth
consent screen. A Drive reader fills the same `File` shape — id, name, mime, owner, editors, bytes
— and everything downstream of `_read_local` is indifferent to which one produced it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import pathlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import text

from ._db import engine
from ._ids import uuid7
from .extract import Unreadable, extract, looks_like_the_prompt, word_count
from .reconcile import reconcile

log = logging.getLogger("intake.read_folder")

# Files a folder holds that are nobody's submission and not an error either.
IGNORED_NAMES = {".ds_store", "thumbs.db", "desktop.ini"}

_ROSTER = text("""
    SELECT s.student_id, s.display_name
      FROM roster_student s
      JOIN roster_enrollment e ON e.student_id = s.student_id
     WHERE e.tenant_id = :tenant AND e.section_id = :section_id
       AND (e.active_to IS NULL OR e.active_to > now())
""")

_INSERT_MANIFEST = text("""
    INSERT INTO intake_manifest
        (manifest_id, source_kind, source_ref, read_by, declared_section_id, declared_task_id,
         declared_iteration, declared_window_label, file_count, inferred_rate, run_id,
         tenant_id, visibility)
    VALUES (:manifest_id, :source_kind, :source_ref, :read_by, :section_id, :task_id,
            :iteration, :window_label, :file_count, :inferred_rate, :run_id,
            :tenant_id, 'public')
""")

_INSERT_FILE = text("""
    INSERT INTO intake_file
        (file_id, manifest_id, source_ref, name, mime, modified_at, size_bytes, owner_email,
         editor_emails, text, text_hash, word_count, status, reason_code, resolved_student_id,
         resolution_basis, resolution_path, match_score, candidates, tenant_id, visibility)
    VALUES (:file_id, :manifest_id, :source_ref, :name, :mime, :modified_at, :size_bytes,
            :owner_email, CAST(:editor_emails AS jsonb), :text, :text_hash, :word_count,
            :status, :reason_code, :resolved_student_id, :resolution_basis, :resolution_path,
            :match_score, CAST(:candidates AS jsonb), :tenant_id, 'public')
""")


@dataclass
class SourceFile:
    """One file as a source provider hands it over. Drive fills the same shape."""
    source_ref: str                      # stable across reads: a Drive id, or a relative path
    name: str
    data: bytes = b""
    mime: str | None = None
    modified_at: datetime | None = None
    size_bytes: int | None = None
    owner_email: str | None = None
    editor_emails: list[str] = field(default_factory=list)
    unreadable_reason: str | None = None   # the provider itself could not hand over the bytes


# ------------------------------------------------------------------ pure (unit-tested)


def name_signals(name: str) -> list[str]:
    """The parts of a filename that might be a person's name.

    A submission is called "Maya Okonkwo - final draft.docx" or "okonkwo_maya_oped" far more often
    than it is called anything tidy. The whole stem is offered alongside the pieces either side of
    the separators, because the reconciler scores each signal and takes the best — and the whole
    stem is what matches when a student simply used their name.
    """
    stem = re.sub(r"\.[A-Za-z0-9]{1,8}$", "", name).strip()
    parts = [p.strip() for p in re.split(r"[-_–—|,]+", stem) if p.strip()]
    signals = [stem, *parts]
    # Longest first: "Maya Okonkwo" should be tried before "Maya".
    return sorted({s for s in signals if len(s) > 2}, key=len, reverse=True)


def classify(f: SourceFile) -> tuple[str, str, str | None]:
    """(status, text, reason_code) for one file, before anyone asks whose it is.

    Order matters. A file the provider could not hand over is unreadable whatever its name says; a
    file that opens and holds nothing is empty, which is a different fact; and the assignment
    prompt is neither — it is the task statement, worth keeping and not worth scoring.
    """
    if f.unreadable_reason:
        return "unreadable", "", "source_unreadable"
    if f.name.lower() in IGNORED_NAMES:
        return "not_student_work", "", "system_file"
    try:
        body = extract(f.name, f.data, f.mime)
    except Unreadable as exc:
        return "unreadable", "", str(exc)[:200]
    if not body.strip():
        return "empty", "", "no_text"
    if looks_like_the_prompt(f.name, body):
        return "not_student_work", body, "looks_like_the_assignment"
    return "resolved", body, None      # provisional: reconciliation decides if a person is named


def rows_for(files: list[SourceFile], roster: list[dict],
             manifest_id: str, tenant: str) -> tuple[list[dict], float]:
    """Every intake_file row for one read, and the inferred rate. Pure — no database, no clock.

    The reconciliation runs over the whole set at once rather than file by file, because a student
    can only have handed in one paper: matching greedily lets one strong filename claim a student
    that a weaker-but-correct match then cannot have.
    """
    prepared, by_ref = [], {}
    for f in files:
        status, body, reason = classify(f)
        by_ref[f.source_ref] = (f, status, body, reason)
        prepared.append({
            "file_id": f.source_ref,
            "owner_email": f.owner_email,
            "editor_emails": f.editor_emails,
            "name_signals": name_signals(f.name),
            "is_non_student": status == "not_student_work",
            # `empty` files still want a student: an empty submission is a non-attempt by a named
            # person, which is a `not_scorable` artifact rather than a file nobody claims.
            "unreadable": status == "unreadable",
        })

    manifest = reconcile(prepared, roster)
    matched = {m.file_id: m for m in manifest.matched}
    names = {s["student_id"]: s.get("display_name") for s in roster}

    rows = []
    for ref, (f, status, body, reason) in by_ref.items():
        match = matched.get(ref)

        # `classify` said whether the file COULD be somebody's paper; the reconciler says whether
        # anybody was actually matched. Only the four combinations below exist, and writing them
        # out beats the compressed version this replaced — which was correct and unreadable, and
        # unreadable is how the next edit to it becomes wrong.
        if status in ("not_student_work", "unreadable"):
            match = None                                     # cannot be anyone's, by definition
        elif status == "empty":
            pass                                             # attributable or not; both are real
        elif match is None:
            status, reason = "unresolved", "no_student_matched"

        m = match
        rows.append({
            "file_id": uuid7(),
            "manifest_id": manifest_id,
            "source_ref": ref,
            "name": f.name,
            "mime": f.mime,
            "modified_at": f.modified_at,
            "size_bytes": f.size_bytes if f.size_bytes is not None else len(f.data),
            "owner_email": f.owner_email,
            "editor_emails": json.dumps(f.editor_emails or []),
            "text": body or None,
            "text_hash": hashlib.sha256(body.encode("utf8")).hexdigest() if body else None,
            "word_count": word_count(body) if body else 0,
            "status": status,
            "reason_code": reason,
            "resolved_student_id": m.student_id if m else None,
            "resolution_basis": m.basis if m else None,
            "resolution_path": m.resolution_path if m else None,
            "match_score": round(m.score, 3) if m else None,
            # The stuck queue is this column rendered: who this might be, best first.
            "candidates": json.dumps(
                candidates_for(f, roster, names) if status == "unresolved" else []),
            "tenant_id": tenant,
        })
    return rows, manifest.inferred_rate


def candidates_for(f: SourceFile, roster: list[dict], names: dict,
                   limit: int = 3) -> list[dict]:
    """Who an unresolved file might belong to, best first.

    Not a guess presented as an answer — the console asks a person. An unresolved file with no
    candidates at all is a different problem from one with three, and a teacher needs to see which
    they have.
    """
    from .reconcile import name_similarity

    scored = []
    for s in roster:
        best = max((name_similarity(sig, s.get("display_name") or "")
                    for sig in name_signals(f.name)), default=0.0)
        if best > 0:
            scored.append({"student_id": s["student_id"],
                           "display_name": names.get(s["student_id"]),
                           "score": round(best, 3)})
    return sorted(scored, key=lambda c: -c["score"])[:limit]


# ------------------------------------------------------------------ the local reader


def read_local(folder: pathlib.Path) -> list[SourceFile]:
    """Every file in a directory, one level deep.

    Not recursive: a folder of student work is flat, and walking into subdirectories would sweep
    up whatever else a teacher keeps nearby. If that turns out to be wrong it should be a flag
    somebody chose, not a default that quietly scored a backup directory.
    """
    out = []
    for path in sorted(p for p in folder.iterdir() if p.is_file()):
        try:
            data = path.read_bytes()
            reason = None
        except OSError as exc:
            data, reason = b"", f"could not read the file: {exc}"
        stat = path.stat()
        out.append(SourceFile(
            source_ref=path.name, name=path.name, data=data,
            modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            size_bytes=stat.st_size, unreadable_reason=reason))
    return out


def read(*, folder: pathlib.Path, tenant: str, section_id: str, task_id: str, iteration: str,
         window_label: str | None, read_by: str | None = None, run_id: str | None = None,
         dry_run: bool = False) -> dict:
    eng = engine()
    files = read_local(folder)
    manifest_id = uuid7()

    with eng.connect() as conn:
        conn.execute(text("SELECT set_config('app.tenant', :t, true)"), {"t": tenant})
        roster = [dict(r) for r in conn.execute(
            _ROSTER, {"tenant": tenant, "section_id": section_id}).mappings()]

    rows, inferred_rate = rows_for(files, roster, manifest_id, tenant)
    summary = {
        "manifest_id": manifest_id, "folder": str(folder), "files": len(rows),
        "roster": len(roster), "inferred_rate": round(inferred_rate, 3),
        "by_status": {s: sum(r["status"] == s for r in rows)
                      for s in sorted({r["status"] for r in rows})},
    }
    if dry_run:
        summary["dry_run"] = True
        return summary

    with eng.begin() as conn:
        conn.execute(text("SELECT set_config('app.tenant', :t, true)"), {"t": tenant})
        conn.execute(_INSERT_MANIFEST, {
            "manifest_id": manifest_id, "source_kind": "local", "source_ref": str(folder),
            "read_by": read_by, "section_id": section_id, "task_id": task_id,
            "iteration": iteration, "window_label": window_label, "file_count": len(rows),
            "inferred_rate": inferred_rate, "run_id": run_id, "tenant_id": tenant})
        for row in rows:
            conn.execute(_INSERT_FILE, row)
    log.info("%s: %d file(s) %s", folder, len(rows), summary["by_status"])
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--folder", required=True)
    ap.add_argument("--tenant", default="public")
    ap.add_argument("--section", required=True)
    ap.add_argument("--task", required=True)
    ap.add_argument("--iteration", default="final")
    ap.add_argument("--window", default=None)
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--read-by", default=None)
    ap.add_argument("--dry-run", action="store_true", help="read and classify, write nothing")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    print(json.dumps(read(
        folder=pathlib.Path(args.folder), tenant=args.tenant, section_id=args.section,
        task_id=args.task, iteration=args.iteration, window_label=args.window,
        read_by=args.read_by, run_id=args.run_id, dry_run=args.dry_run), indent=1))


if __name__ == "__main__":
    main()
