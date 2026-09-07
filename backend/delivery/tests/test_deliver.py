"""Handing feedback back, and the failures that must not become silence.

The plan's sentence is the whole specification: "a hand-back can fail because the teacher no
longer has edit access to a student's document, and that is recorded as not sent rather than
silently as delivered. Released and delivered are different facts."

A delivery that quietly did not happen is indistinguishable from one that did, on every screen a
teacher looks at. Twenty-six students got their feedback and two did not, and nobody knows which
two — so most of this file is about the two.
"""
from __future__ import annotations

import pathlib

import pytest

from delivery.deliver import (CHANNELS, DeliveryFailed, attempt_row, message_of, send_to_file,
                              send_to_nowhere)
from delivery.models import CHANNELS as MODEL_CHANNELS, DELIVERY_STATUSES


def row(**kw):
    r = {"artifact_id": "art-1", "composition_id": "comp-1", "tenant_id": "public",
         "visibility": "public", "file_name": "Maya Okonkwo - op-ed final.txt",
         "folder": None, "student_id": "stu-1"}
    r.update(kw)
    return r


MESSAGE = "Maya, the last two lines are the best thing in this draft."


# ------------------------------------------------------------------ what actually goes out


def test_the_file_channel_writes_beside_the_paper(tmp_path):
    """Real delivery to a real place — which is what makes the whole path demonstrable before
    Drive exists, rather than a stub that proves nothing."""
    target = send_to_file(row(folder=str(tmp_path)), MESSAGE)
    written = pathlib.Path(target)
    assert written.exists()
    assert written.read_text(encoding="utf8") == MESSAGE
    assert "Maya Okonkwo" in written.name and "feedback" in written.name


def test_a_paper_with_nowhere_to_deliver_fails_rather_than_pretending(tmp_path):
    """Bound before intake existed, or its manifest removed. That is a failure with a reason, not
    a quiet success."""
    with pytest.raises(DeliveryFailed, match="nowhere to put the feedback"):
        send_to_file(row(folder=None), MESSAGE)


def test_a_folder_that_has_gone_is_a_failure_that_says_so(tmp_path):
    """The commonest real cause — a teacher moved or unshared the folder — and the message names
    the path so somebody can go and look."""
    with pytest.raises(DeliveryFailed, match="could not write"):
        send_to_file(row(folder=str(tmp_path / "not-here")), MESSAGE)


def test_holding_a_message_deliberately_is_not_a_success():
    """The console's "approved, waiting to go out". A teacher handing back at the end of the
    lesson has agreed to something that has not gone yet — and it must not be recorded as sent."""
    with pytest.raises(DeliveryFailed, match="approved and waiting"):
        send_to_nowhere(row(), MESSAGE)


# ------------------------------------------------------------------ what gets recorded


def test_a_sent_attempt_says_where_and_when():
    """The CHECK in 0025 refuses a `sent` row without both. A claim that something arrived, with
    no timestamp and no destination, is a claim with nothing behind it."""
    a = attempt_row(row(), channel="file", status="sent", target="/tmp/x.txt", detail=None,
                    message=MESSAGE, actor="tim", supersedes=None)
    assert a["delivered_at"] is not None
    assert a["target_ref"] == "/tmp/x.txt"


def test_a_failed_attempt_carries_no_delivered_at():
    """A timestamp on a failure would make it indistinguishable from a success in any query that
    looked at the column rather than the status."""
    a = attempt_row(row(), channel="file", status="failed", target=None,
                    detail="could not write", message=MESSAGE, actor="tim", supersedes=None)
    assert a["delivered_at"] is None
    assert a["detail"]


def test_every_attempt_records_what_was_sent():
    """If the message is edited after delivery, the hash is the evidence of which version the
    student actually read — and 'the feedback was changed afterwards' is otherwise unanswerable."""
    a = attempt_row(row(), channel="file", status="sent", target="/tmp/x", detail=None,
                    message=MESSAGE, actor="tim", supersedes=None)
    b = attempt_row(row(), channel="file", status="sent", target="/tmp/x", detail=None,
                    message=MESSAGE + " Edited.", actor="tim", supersedes=None)
    assert a["message_hash"] != b["message_hash"]


def test_every_attempt_names_who_made_it():
    a = attempt_row(row(), channel="file", status="sent", target="/tmp/x", detail=None,
                    message=MESSAGE, actor="tkinkead@prevagroup.com", supersedes=None)
    assert a["attempted_by"] == "tkinkead@prevagroup.com"


def test_a_retry_points_at_the_attempt_it_follows():
    """So a chain reads in order — tried at 09:41, moved, tried again at 14:02 — rather than as a
    pile of rows sharing an artifact id."""
    a = attempt_row(row(), channel="file", status="sent", target="/tmp/x", detail=None,
                    message=MESSAGE, actor="tim", supersedes="delivery-0")
    assert a["supersedes"] == "delivery-0"


def test_the_channel_is_recorded_on_every_attempt():
    """A hand-back from before Drive existed stays legible afterwards, instead of looking like a
    Drive delivery that left no trace."""
    a = attempt_row(row(), channel="file", status="sent", target="/tmp/x", detail=None,
                    message=MESSAGE, actor="tim", supersedes=None)
    assert a["channel"] == "file"


# ------------------------------------------------------------------ nothing to send


def test_a_released_paper_with_no_message_is_not_a_delivery_failure():
    """A teacher can approve scores without a student-facing draft. Counting that as a failure
    would put a red mark against a decision nothing went wrong with."""
    assert message_of({"feedback": {"message": ""}}) is None
    assert message_of({}) is None
    assert message_of({"feedback": {"message": MESSAGE}}) == MESSAGE


# ------------------------------------------------------------------ the vocabulary


def test_the_module_and_the_migration_agree_on_the_vocabulary():
    """Two copies of an enum drift, and the one that drifts is always the one nobody is looking
    at when a CHECK starts rejecting rows."""
    from delivery.migrations import __name__ as _  # noqa: F401
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "m25", pathlib.Path(__file__).resolve().parents[1] / "migrations"
        / "0025_delivery_attempts.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert tuple(m.STATUSES) == DELIVERY_STATUSES
    assert tuple(m.CHANNELS) == MODEL_CHANNELS


def test_the_plan_s_two_real_channels_are_both_representable():
    """Comments on the student's own document, or Classroom — neither of which asks a student to
    sign in, which is what keeps a consent and minor-account surface out of the pilot."""
    assert "google_docs_comment" in MODEL_CHANNELS
    assert "classroom" in MODEL_CHANNELS


def test_only_implemented_channels_can_be_asked_for():
    """A channel in the vocabulary and absent from the dispatch would fail at the point of use
    rather than at the point of asking."""
    for name in CHANNELS:
        assert name in MODEL_CHANNELS
