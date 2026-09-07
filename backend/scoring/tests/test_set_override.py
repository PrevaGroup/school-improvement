"""One judgment about a class, recorded once.

A teacher who decides "C3 is a 2 for this whole class" has made ONE judgment. Writing it as
twenty-eight independent teacher ratings would make a single decision look like twenty-eight
raters concurring — apparent agreement manufactured out of nothing — and would hide from anyone
reading the record later that the call was made once and applied.

`score_event.set_override_id` has existed since migration 0008 for exactly this, and
`measurement.frames` has known how to exclude a set override from an estimation frame since it was
written. Nothing had ever written the column. This file is about the ways that can go wrong.
"""
from __future__ import annotations

import re

import pytest
from fastapi import HTTPException

from scoring.review import _CURRENT_EVENTS_FOR_NODE, _INSERT_OVERRIDE, set_override


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self._rows


class FakeDB:
    """Just enough Session to watch what the endpoint writes."""

    def __init__(self, rows):
        self.rows = rows
        self.executed = []
        self.committed = False
        self.rolled_back = False

    def execute(self, stmt, params=None):
        self.executed.append((str(stmt), params or {}))
        if "supersedes_event_id = e.event_id" in str(stmt):
            return FakeResult(self.rows)
        return FakeResult([])

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


PRINCIPAL = {"sub": "uid-1", "email": "tkinkead@prevagroup.com"}


def event(artifact_id: str, level: float = 3, **kw) -> dict:
    row = {"event_id": f"ev-{artifact_id}", "artifact_id": artifact_id, "node_id": "node-c3",
           "status": "scored", "level": level, "run_id": "run-1", "student_id": f"stu-{artifact_id}",
           "section_id": "sec-1", "task_id": "task-1", "iteration": "final",
           "window_label": "fall 2026", "trait_set_version": "ts.1", "rubric_version": "rv.1",
           "form_variant": "fv.1", "scoring_configuration_id": "cfg-1",
           "is_measurement_occasion": True, "tenant_id": "public", "visibility": "public",
           "scorer_type": "ai", "scorer_id": "cfg-1"}
    row.update(kw)
    return row


def call(db, **payload):
    body = {"node_id": "node-c3", "artifact_ids": ["a1", "a2", "a3"],
            "status": "scored", "level": 2,
            "reason": "The class was taught counterclaim after this draft was collected."}
    body.update(payload)
    return set_override(payload=body, db=db, principal=PRINCIPAL)


# ------------------------------------------------------------------ the one column that matters

def test_every_paper_in_the_set_shares_one_override_id():
    """The whole point. Twenty-eight rows carrying twenty-eight ids are twenty-eight judgments;
    twenty-eight rows carrying ONE id are one judgment applied twenty-eight times, and only the
    second is true."""
    db = FakeDB([event("a1"), event("a2"), event("a3")])
    out = call(db)
    ids = {p["set_override_id"] for sql, p in db.executed if "INSERT INTO score_event" in sql}
    assert len(ids) == 1
    assert ids == {out["set_override_id"]}
    assert len(out["applied"]) == 3


def test_the_id_is_new_for_each_decision():
    """Two decisions about the same class on the same criterion are two judgments. Reusing an id
    would merge them, and the second would be invisible."""
    a = call(FakeDB([event("a1")]))["set_override_id"]
    b = call(FakeDB([event("a1")]))["set_override_id"]
    assert a != b


def test_each_row_still_supersedes_the_event_it_replaces():
    """A set override is still an override: the pairing "this configuration said 3, this named
    teacher said 2" is what makes it a calibration observation at all. Losing it would leave a
    bare teacher score with nothing to compare against."""
    db = FakeDB([event("a1", level=3), event("a2", level=4)])
    call(db)
    pairs = {(p["artifact_id"], p["supersedes_event_id"])
             for sql, p in db.executed if "INSERT INTO score_event" in sql}
    assert pairs == {("a1", "ev-a1"), ("a2", "ev-a2")}


# ------------------------------------------------------------------ what it disagrees with

def test_it_overrides_what_the_record_says_now_not_the_original_score():
    """A teacher who already corrected one paper by hand must not have that correction silently
    reverted by a decision about the class. So the query takes the event nothing supersedes, not
    the machine's first one."""
    sql = str(_CURRENT_EVENTS_FOR_NODE)
    assert "NOT EXISTS" in sql and "supersedes_event_id = e.event_id" in sql


def test_a_paper_with_no_score_on_this_criterion_is_named_not_skipped():
    """A teacher who selected twenty-eight papers and changed twenty-six is owed the two. Those
    two still carry whatever the machine said, and a silent skip is how they stay that way."""
    db = FakeDB([event("a1"), event("a3")])
    out = call(db, artifact_ids=["a1", "a2", "a3"])
    assert out["not_scored_on_this_criterion"] == ["a2"]
    assert len(out["applied"]) == 2


def test_nothing_to_override_is_an_error_rather_than_a_silent_success():
    """A 200 with an empty list reads as "done" on every screen. A teacher would believe the
    class had been changed."""
    with pytest.raises(HTTPException) as e:
        call(FakeDB([]))
    assert e.value.status_code == 404


def test_the_previous_level_comes_back_with_each_paper():
    """So the console can say what changed rather than only what it now is. "Was 4, now 2" is a
    different sentence from "2", and it is the one a teacher checks."""
    out = call(FakeDB([event("a1", level=4), event("a2", level=1)]))
    assert {p["artifact_id"]: p["was"] for p in out["applied"]} == {"a1": 4, "a2": 1}


# ------------------------------------------------------------------ refusals

def test_a_level_without_a_score_is_refused():
    """Same rule as the single-paper override: an abstention with a number on it is a claim
    nobody made."""
    with pytest.raises(HTTPException) as e:
        call(FakeDB([event("a1")]), status="abstained", level=2)
    assert e.value.status_code == 400


def test_a_score_without_a_level_is_refused():
    with pytest.raises(HTTPException) as e:
        call(FakeDB([event("a1")]), status="scored", level=None)
    assert e.value.status_code == 400


def test_a_set_override_must_say_why():
    """It is the only record of what the decision was ABOUT, and it is read by people who were
    not in the room. A per-paper override can lean on the paper; a class-wide one cannot."""
    for blank in ("", "   ", None):
        with pytest.raises(HTTPException) as e:
            call(FakeDB([event("a1")]), reason=blank)
        assert e.value.status_code == 400
        assert "why" in str(e.value.detail)


def test_a_request_that_names_no_papers_is_refused():
    with pytest.raises(HTTPException) as e:
        call(FakeDB([event("a1")]), artifact_ids=[])
    assert e.value.status_code == 400


def test_a_request_that_names_no_criterion_is_refused():
    """One judgment is about ONE criterion. A set override across every criterion at once would
    be a teacher re-scoring the class in a single click, which is not a judgment, it is a wipe."""
    with pytest.raises(HTTPException) as e:
        call(FakeDB([event("a1")]), node_id="")
    assert e.value.status_code == 400


# ------------------------------------------------------------------ all of it, or none of it

def test_a_failure_rolls_the_whole_set_back():
    """A set override that landed on nineteen of twenty-eight papers is not a partial success. It
    is a decision that no longer means what it says, and the nine left behind carry the machine's
    score with no record that anybody disagreed."""
    from sqlalchemy.exc import DBAPIError

    db = FakeDB([event("a1"), event("a2")])

    def boom(stmt, params=None):
        db.executed.append((str(stmt), params or {}))
        if "INSERT INTO score_event" in str(stmt):
            raise DBAPIError("insert", {}, Exception("append-only"))
        return FakeResult(db.rows if "supersedes_event_id = e.event_id" in str(stmt) else [])

    db.execute = boom
    with pytest.raises(HTTPException):
        call(db)
    assert db.rolled_back and not db.committed


def test_one_commit_for_the_whole_decision():
    db = FakeDB([event("a1"), event("a2"), event("a3")])
    call(db)
    assert db.committed


# ------------------------------------------------------------------ the honest record

def test_the_override_is_recorded_as_informed():
    """`human_blind = false` is hard-coded in the insert. The teacher saw the machine's score
    before disagreeing with it, and an informed second rating cannot serve as an independent one
    in a calibration design — a column that quietly said otherwise would corrupt the analysis
    rather than the interface."""
    assert re.search(r"'teacher',\s*:scorer_id,\s*false", str(_INSERT_OVERRIDE))


def test_a_set_override_does_not_enter_calibration():
    """It is one decision, not N observations, so admitting it would weight a single judgment by
    the size of the class."""
    assert re.search(r"'teacher_override',\s*NULL,\s*:is_measurement_occasion,\s*false",
                     str(_INSERT_OVERRIDE))


def test_the_acting_teacher_is_bound_from_the_verified_principal():
    """Not from the body. The release authority is a property of the request, and an override
    that took its scorer from the payload would let a caller sign somebody else's judgment."""
    import inspect
    src = inspect.getsource(set_override)
    assert "_bind_teacher(db, principal)" in src
    assert 'payload.get("scorer_id")' not in src


def test_the_idempotency_key_is_unique_per_paper_and_per_decision():
    """The unique constraint on `idempotency_key` is what stops a resumed run doubling an
    observation. A set override reuses that machinery: same decision applied twice cannot write
    two rows for one paper, and two different decisions are never confused for one."""
    db = FakeDB([event("a1"), event("a2")])
    out = call(db)
    keys = [p["idempotency_key"] for sql, p in db.executed if "INSERT INTO score_event" in sql]
    assert len(set(keys)) == len(keys) == 2
    for k in keys:
        assert out["set_override_id"] in k and "node-c3" in k
