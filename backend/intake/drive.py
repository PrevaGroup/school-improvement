"""Google Drive, behind the seam `read_folder` already has.

`intake_manifest.source_kind` has read `local | drive` since migration 0021 and `source_ref` has
been documented as "a Drive file id, or a path relative to the folder" for as long. This is the
half that was missing. Nothing downstream changes: a Drive read produces the same manifest a local
read does, and the five statuses mean the same five things.

## What Drive is actually for, and it is not speed

Enumeration is convenient. The reason it matters is `owner_email`: a local folder carries no owner,
so every match today is `inferred` from a filename and `Manifest.inferred_rate` reads 1.0 on every
run. `reconcile()` scores an account match at 100 against a name similarity of at most 1.0 — a
deliberate gap so an account always outbids a name — and it has never had an account to score.
Drive supplies one. That, with `roster_student.email` (migration 0028), is what turns inference
into lookup, and the contract is blunt about why it matters: "A score whose binding was inferred
has a different error profile from one looked up — pooling them pools two populations."

## Revision history

`revisions.list` gives the first and last modification of a Doc. The plan wants it for two
different reasons and only the first is obvious: it distinguishes a draft a student worked on from
one pasted in whole, and it is the evidence that a "revised after feedback" claim is about writing
rather than about a timestamp somebody set. Recorded, not judged — this module reports what Drive
says and nothing here decides what it means.

## Extraction

Docs export as plain text through Drive's `files.export`, which is one call and preserves paragraph
breaks. The Docs API's structural JSON is richer and this does not use it: the scoring path needs
the text a student wrote, span offsets are computed against normalised text anyway, and a second
API surface is a second thing to keep working.

## What this module refuses to do

It does not classify, match, or decide anything. `classify` and `reconcile` are deterministic,
exhaustively tested, and know nothing about where a file came from — which is what makes a Drive
read and a local read produce comparable manifests. This module's whole job is to turn a folder id
into the same list of dicts `read_folder` already builds from a directory.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

log = logging.getLogger("intake.drive")

# Read-only, and no more. Each one is a sentence a person reads on the consent screen, and asking
# for write access months before anything writes is how a pilot loses the benefit of the doubt.
# `drive` (read-write) is what comment delivery will need; it is deliberately absent until then.
SCOPES = (
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/documents.readonly",
)

# What Drive calls a Google Doc, versus a file that merely lives in Drive.
DOC_MIME = "application/vnd.google-apps.document"
FOLDER_MIME = "application/vnd.google-apps.folder"

# Exported as plain text. Not HTML: the scoring path wants what the student wrote, and every span
# offset is computed against normalised text anyway.
EXPORT_MIME = "text/plain"

# The fields Drive is asked for, named explicitly. A default listing returns id, name and mimeType
# and would silently drop `owners` — the one field this integration exists to obtain.
FILE_FIELDS = ("nextPageToken, files(id, name, mimeType, modifiedTime, size, "
               "owners(emailAddress), lastModifyingUser(emailAddress), trashed)")


@dataclass
class DriveFile:
    """One file as Drive describes it, before anything has judged what it is."""
    source_ref: str                       # the Drive file id: stable across reads
    name: str
    mime: str | None = None
    modified_at: datetime | None = None
    size_bytes: int | None = None
    owner_email: str | None = None
    editor_emails: list[str] = field(default_factory=list)
    # Absent until extraction runs, and None is different from "": a file we could not read is an
    # inventory discrepancy, and an empty one is a student who submitted a blank document.
    text: str | None = None
    unreadable_reason: str | None = None
    revisions: int | None = None
    first_modified_at: datetime | None = None


def _iso(v: str | None) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None


def to_file(raw: dict) -> DriveFile:
    """One Drive API file resource -> the shape intake works in. Pure."""
    owners = raw.get("owners") or []
    last = (raw.get("lastModifyingUser") or {}).get("emailAddress")
    owner = (owners[0].get("emailAddress") if owners else None)
    # The last person to modify is an editor, and on a Doc a teacher created FOR a student it is
    # routinely the only address that names the writer. `reconcile` scores it lower than an owner
    # match on purpose; both are lookups, and neither is a guess at a name.
    editors = [e for e in {last} if e and e != owner]
    return DriveFile(
        source_ref=raw["id"],
        name=raw.get("name") or raw["id"],
        mime=raw.get("mimeType"),
        modified_at=_iso(raw.get("modifiedTime")),
        size_bytes=int(raw["size"]) if str(raw.get("size") or "").isdigit() else None,
        owner_email=owner,
        editor_emails=editors,
    )


def is_listable(raw: dict) -> bool:
    """Whether a listing entry is a candidate at all.

    Trashed files are excluded because a teacher who deleted something meant it. Sub-folders are
    excluded and NOT recursed into: the plan flags nested folders as one of the cases that breaks
    the flat-folder assumption, and it is explicit that "a refusal is an acceptable answer: detect
    and decline rather than guess". Silently flattening a nested structure is the guess.
    """
    return not raw.get("trashed") and raw.get("mimeType") != FOLDER_MIME


class DriveError(Exception):
    """Drive said no. Carries the message a person will read in the console."""


class Drive:
    """The real client. One page of listing per call, one export per document.

    Constructed with an authorised `googleapiclient` service so that everything above this line
    stays testable without credentials — `to_file`, `is_listable` and the manifest assembly are the
    parts with decisions in them, and none of them need a network.
    """

    def __init__(self, service, docs_service=None) -> None:
        self._files = service.files()
        self._revisions = service.revisions()

    def enumerate(self, folder_id: str, *, page_limit: int = 20) -> list[DriveFile]:
        """Every candidate file in one folder, not recursing.

        `page_limit` bounds the walk. A folder with more pages than that is a folder this was not
        designed for, and it raises rather than returning a partial list — a truncated enumeration
        becomes missing students in the manifest, which is the inventory-discrepancy-as-absence
        failure the five statuses exist to prevent.
        """
        out: list[DriveFile] = []
        token, pages = None, 0
        while True:
            pages += 1
            if pages > page_limit:
                raise DriveError(
                    f"folder {folder_id} has more than {page_limit} pages of files. Refusing to "
                    f"return a partial list: papers missing from a manifest read as students who "
                    f"handed in nothing.")
            try:
                resp = self._files.list(
                    q=f"'{folder_id}' in parents",
                    fields=FILE_FIELDS, pageSize=200, pageToken=token,
                    supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
            except Exception as exc:
                raise DriveError(f"could not list folder {folder_id}: {exc}") from exc
            out += [to_file(r) for r in resp.get("files", []) if is_listable(r)]
            token = resp.get("nextPageToken")
            if not token:
                return out

    def extract(self, f: DriveFile) -> DriveFile:
        """Fill in `text`, or say why not. Never raises for one file.

        A folder read must survive a document it cannot open. One unreadable file is an inventory
        discrepancy the manifest reports; an exception here would lose the other twenty-seven.
        """
        try:
            if f.mime == DOC_MIME:
                data = self._files.export(fileId=f.source_ref, mimeType=EXPORT_MIME).execute()
            else:
                data = self._files.get_media(fileId=f.source_ref).execute()
            f.text = data.decode("utf8") if isinstance(data, bytes) else str(data)
        except Exception as exc:
            f.unreadable_reason = f"could not read this document: {exc}"
            log.info("%s (%s): %s", f.name, f.source_ref, f.unreadable_reason)
        return f

    def history(self, f: DriveFile) -> DriveFile:
        """How many revisions, and when the first was. Reported, never judged.

        Whether "few revisions" means pasted-in work is a question for a person looking at the
        paper. This module records what Drive says; a module that inferred plagiarism from a
        revision count would be making an accusation out of a timestamp.
        """
        try:
            resp = self._revisions.list(fileId=f.source_ref,
                                        fields="revisions(id, modifiedTime)").execute()
            revs = resp.get("revisions") or []
            f.revisions = len(revs)
            f.first_modified_at = _iso((revs[0] or {}).get("modifiedTime")) if revs else None
        except Exception as exc:
            # Not an error. Revision history is unavailable on plenty of files, and a folder read
            # must not fail because one document would not describe its own history.
            log.debug("no revision history for %s: %s", f.source_ref, exc)
        return f
