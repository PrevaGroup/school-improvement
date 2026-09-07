"""Drive, and the reasons a folder read must survive its own failures.

Drive is not here for speed. It is here for `owner_email`: a local folder carries no owner, so
every match today is inferred from a filename and `inferred_rate` reads 1.0 on every run. The
contract is blunt about the cost — "A score whose binding was inferred has a different error
profile from one looked up; pooling them pools two populations" — and this is the module that
supplies the account.

Everything with a decision in it (`to_file`, `is_listable`) is pure and tested here without
credentials, which is the same split that lets `reconcile` be tested exhaustively.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from intake.drive import (DOC_MIME, EXPORT_MIME, FILE_FIELDS, FOLDER_MIME, SCOPES, Drive,
                          DriveError, DriveFile, is_listable, to_file)


def raw(**kw) -> dict:
    r = {"id": "1AbC", "name": "Maya Okonkwo - op-ed final",
         "mimeType": DOC_MIME, "modifiedTime": "2026-09-05T14:03:00.000Z",
         "owners": [{"emailAddress": "maya.okonkwo@school.org"}]}
    r.update(kw)
    return r


# ------------------------------------------------------------------ the field that matters

def test_the_owner_account_survives_the_listing():
    """The whole reason for the integration. Without it Drive is a faster way to reach the same
    inferred matches."""
    assert to_file(raw()).owner_email == "maya.okonkwo@school.org"


def test_the_listing_asks_for_owners_explicitly():
    """A default Drive listing returns id, name and mimeType. Relying on the default would drop
    `owners` silently — the integration would work, enumerate correctly, and still infer every
    match, which is the failure that looks exactly like success."""
    assert "owners(emailAddress)" in FILE_FIELDS
    assert "lastModifyingUser" in FILE_FIELDS
    assert "trashed" in FILE_FIELDS


def test_the_last_editor_is_kept_when_it_is_not_the_owner():
    """On a Doc a teacher created FOR a student, the owner is the teacher and the only address
    naming the writer is the last editor. Both are lookups; `reconcile` already scores them
    differently."""
    f = to_file(raw(lastModifyingUser={"emailAddress": "devon.reyes@school.org"}))
    assert f.editor_emails == ["devon.reyes@school.org"]


def test_the_owner_is_not_repeated_as_an_editor():
    f = to_file(raw(lastModifyingUser={"emailAddress": "maya.okonkwo@school.org"}))
    assert f.editor_emails == []


def test_a_file_with_no_owner_is_not_a_failure():
    """Shared drives and some org configurations return no owners. That is a file matched by name,
    which is what the system did for every file before this module existed."""
    f = to_file(raw(owners=[]))
    assert f.owner_email is None and f.editor_emails == []


# ------------------------------------------------------------------ the identity of a file

def test_the_drive_id_is_the_stable_reference():
    """`source_ref` is what makes a second read of the same folder a supersession rather than a
    duplicate. A filename is not stable — a student renaming their document must not create a
    second artifact — and this is exactly why the column was never the name."""
    assert to_file(raw()).source_ref == "1AbC"
    assert to_file(raw(name="renamed.docx")).source_ref == "1AbC"


def test_a_missing_name_falls_back_to_the_id_rather_than_to_empty():
    """An unnamed file still has to be nameable in the console, or a teacher is shown a blank row
    and no way to say which file it is."""
    assert to_file(raw(name=None)).name == "1AbC"


def test_a_size_drive_did_not_report_is_none_not_zero():
    """Google Docs report no size. Zero would read as an empty document, which is a real and
    different state — a student who submitted a blank file."""
    assert to_file(raw()).size_bytes is None
    assert to_file(raw(size="4096")).size_bytes == 4096


def test_timestamps_parse_and_a_bad_one_does_not_raise():
    assert isinstance(to_file(raw()).modified_at, datetime)
    assert to_file(raw(modifiedTime="not a date")).modified_at is None
    assert to_file(raw(modifiedTime=None)).modified_at is None


# ------------------------------------------------------------------ what is not a candidate

def test_a_trashed_file_is_not_read():
    """A teacher who deleted something meant it."""
    assert not is_listable(raw(trashed=True))
    assert is_listable(raw())


def test_a_subfolder_is_not_recursed_into():
    """The plan flags nested folders as one of the cases that breaks the flat-folder assumption,
    and says a refusal is an acceptable answer: "detect and decline rather than guess". Silently
    flattening a nested structure is the guess."""
    assert not is_listable(raw(mimeType=FOLDER_MIME))


# ------------------------------------------------------------------ failures that must not spread

class FakeFiles:
    def __init__(self, pages, export=b"the paper", boom=None):
        self.pages, self.export_data, self.boom = pages, export, boom
        self.calls = []

    def list(self, **kw):
        self.calls.append(kw)
        page = self.pages[len([c for c in self.calls if "q" in c]) - 1]
        return type("R", (), {"execute": staticmethod(lambda: page)})

    def export(self, **kw):
        if self.boom:
            raise RuntimeError(self.boom)
        return type("R", (), {"execute": staticmethod(lambda: self.export_data)})

    def get_media(self, **kw):
        return self.export(**kw)


class FakeService:
    def __init__(self, files):
        self._files = files

    def files(self):
        return self._files

    def revisions(self):
        class R:
            def list(self, **kw):
                raise RuntimeError("no history here")
        return R()


def drive(pages, **kw):
    return Drive(FakeService(FakeFiles(pages, **kw)))


def test_one_unreadable_document_does_not_lose_the_other_twenty_seven():
    """A folder read must survive a document it cannot open. One unreadable file is an inventory
    discrepancy the manifest reports; an exception would take the whole set down."""
    d = drive([{"files": [raw()]}], boom="permission denied")
    f = d.extract(DriveFile(source_ref="1AbC", name="x", mime=DOC_MIME))
    assert f.text is None
    assert "could not read" in f.unreadable_reason


def test_an_unreadable_file_says_why():
    d = drive([{"files": []}], boom="the owner removed sharing")
    f = d.extract(DriveFile(source_ref="1AbC", name="x", mime=DOC_MIME))
    assert "the owner removed sharing" in f.unreadable_reason


def test_a_readable_document_gets_its_text():
    d = drive([{"files": []}], export=b"Students should have a voice.")
    f = d.extract(DriveFile(source_ref="1AbC", name="x", mime=DOC_MIME))
    assert f.text == "Students should have a voice." and f.unreadable_reason is None


def test_missing_revision_history_is_not_an_error():
    """Revision history is unavailable on plenty of files. A folder read must not fail because one
    document would not describe its own history."""
    d = drive([{"files": []}])
    f = d.history(DriveFile(source_ref="1AbC", name="x"))
    assert f.revisions is None


def test_a_partial_enumeration_raises_rather_than_returning_a_short_list():
    """Papers missing from a manifest read as students who handed in nothing. A truncated
    enumeration is the inventory-discrepancy-as-absence failure, arriving silently."""
    endless = [{"files": [raw()], "nextPageToken": "more"} for _ in range(30)]
    with pytest.raises(DriveError, match="Refusing to return a partial list"):
        drive(endless).enumerate("folder-1", page_limit=3)


def test_a_listing_failure_names_the_folder():
    class Boom:
        def list(self, **kw):
            raise RuntimeError("404 not found")

    with pytest.raises(DriveError, match="folder-1"):
        Drive(FakeService(Boom())).enumerate("folder-1")


def test_pagination_collects_every_page():
    pages = [{"files": [raw(id="a")], "nextPageToken": "2"},
             {"files": [raw(id="b")]}]
    got = drive(pages).enumerate("folder-1")
    assert [f.source_ref for f in got] == ["a", "b"]


# ------------------------------------------------------------------ the consent screen

def test_the_scopes_are_read_only():
    """Each scope is a sentence a person reads before granting. Asking for write access months
    before anything writes is how a pilot loses the benefit of the doubt."""
    assert all(s.endswith(".readonly") for s in SCOPES)
    assert not any(s == "https://www.googleapis.com/auth/drive" for s in SCOPES)


def test_docs_are_exported_as_text_rather_than_html():
    assert EXPORT_MIME == "text/plain"


# ------------------------------------------------------------------ the seam holds

def test_a_drive_read_produces_the_same_shape_a_local_read_does():
    """The whole point of the seam. `classify`, `reconcile` and `rows_for` never learn where a
    file came from, so a Drive manifest and a local manifest are comparable and the five statuses
    keep meaning the same five things."""
    from intake.read_folder import SourceFile, read_drive

    class Client:
        def enumerate(self, folder_id):
            return [to_file(raw())]

        def extract(self, f):
            f.text = "Students should have a voice in school rules."
            return f

        def history(self, f):
            f.revisions = 12
            return f

    got = read_drive(Client(), "folder-1")
    assert len(got) == 1 and isinstance(got[0], SourceFile)
    assert got[0].owner_email == "maya.okonkwo@school.org"
    assert got[0].source_ref == "1AbC"


def test_an_unreadable_drive_file_arrives_as_unreadable_not_as_empty():
    """`unreadable` and `empty` are different statuses and mean different things to a teacher: a
    document we could not open, versus a student who submitted nothing. Collapsing them turns an
    inventory discrepancy into an absence, which is what the statuses exist to prevent."""
    from intake.read_folder import classify, read_drive

    class Client:
        def enumerate(self, folder_id):
            return [to_file(raw())]

        def extract(self, f):
            f.unreadable_reason = "could not read this document: permission denied"
            return f

        def history(self, f):
            return f

    got = read_drive(Client(), "folder-1")[0]
    assert got.unreadable_reason
    assert classify(got)[0] == "unreadable"


def test_a_google_doc_takes_the_plain_text_path_extract_already_documents():
    """Rather than a second extraction route existing for one provider. `extract` already names
    this case: "a Google Docs export with no suffix is the common case"."""
    from intake.extract import extract

    body = extract("Maya Okonkwo - op-ed final", "The court said.".encode("utf8"), "text/plain")
    assert body == "The court said."


def test_the_roster_query_selects_the_address_the_matcher_reads():
    """`reconcile` scores an account match at 100 against a name similarity of at most 1.0 and
    reads `student["email"]` to do it. Without this column in the SELECT the account path can
    never fire, and every match stays inferred however good the Drive data is."""
    from intake.read_folder import _ROSTER

    assert "s.email" in str(_ROSTER)
