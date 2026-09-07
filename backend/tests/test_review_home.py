"""The assignment home — where a SET stands.

The per-paper queue answers "what is waiting for me". It cannot answer "is 5B's op-ed done",
because that is a property of a set and the queue has no notion of one. A teacher holds the
second question, not the first: they do not carry twenty-eight papers in mind, they carry one
assignment and want to know whether it is finished.

Most of this file is about the stacked bar, because a bar is a claim about proportions and a
wrong one is worse than none — it invites the reader to trust it.
"""
from __future__ import annotations

import re

from app.review_view import (PIPELINE_STAGES, _ASSIGNMENTS, _PIPELINE, _STAGES, _STUCK)

STAGE_KEYS = {k for k, _ in PIPELINE_STAGES}


# ------------------------------------------------------------------ the bar cannot lie

def test_every_paper_lands_in_exactly_one_stage():
    """The stages are drawn as one stacked bar. A paper counted twice makes the bar longer than
    the work, and a paper counted nowhere makes it shorter — so the classifier is a single CASE
    with an unconditional ELSE, not a set of overlapping predicates."""
    case = re.search(r"CASE(.*?)END AS stage", _STAGES, re.S)
    assert case, "the stage classifier is no longer a single CASE expression"
    body = case.group(1)
    assert "ELSE" in body, "a CASE with no ELSE drops papers out of the bar silently"
    # Every arm names a stage the console knows how to draw.
    named = set(re.findall(r"THEN\s+'([a-z_]+)'", body)) | set(
        re.findall(r"ELSE\s+'([a-z_]+)'", body))
    assert named == STAGE_KEYS, f"stages in SQL {named} do not match the console's {STAGE_KEYS}"


def test_delivered_is_decided_before_reviewed():
    """A released paper whose feedback has gone is further along, not both. If `reviewed` were
    tested first it would swallow every delivered paper and the last segment would always be
    empty — which reads as "nothing has been handed back" and is the exact false negative the
    delivery table exists to prevent."""
    order = re.findall(r"THEN\s+'([a-z_]+)'|ELSE\s+'([a-z_]+)'", _STAGES)
    flat = [a or b for a, b in order]
    assert flat.index("delivered") < flat.index("reviewed")


def test_the_bar_and_the_rows_are_derived_from_the_same_query():
    """Two queries counting the same thing drift, and the one that drifts is the one nobody is
    looking at. A bar that sums to a different number than the rows beneath it is the failure
    this shares one CTE to prevent."""
    assert _STAGES in str(_PIPELINE)
    assert _STAGES in str(_ASSIGNMENTS)


def test_a_failed_delivery_that_later_succeeded_is_not_reported_as_failing():
    """A retry is the normal response to a failure. Leaving the paper in `failing` forever would
    put a red mark on a student who has their feedback — and the console would be reporting the
    record's history as its present state."""
    sql = _STAGES
    assert "status = 'failed'" in sql
    assert "NOT IN (SELECT artifact_id FROM sent)" in sql


def test_delivery_is_read_by_sent_not_by_any_attempt():
    """`sent` is the only status that means the student has something. Counting attempts would
    report a paper as handed back on the strength of an attempt that failed."""
    sent = re.search(r"sent AS \((.*?)\)", sql := _STAGES, re.S)
    assert sent and "status = 'sent'" in sent.group(1)
    assert "artifact_delivery" in sql


# ------------------------------------------------------------------ what a set is

def test_an_assignment_is_the_binding_key_a_teacher_names():
    """This class, this task, this iteration — and the window, because two windows of the same
    task are two sets of work rather than one set scored twice. Group by less than this and a
    draft's counts silently merge into the final's."""
    sql = str(_ASSIGNMENTS)
    group = re.search(r"GROUP BY(.*?)ORDER BY", sql, re.S).group(1)
    for key in ("section_id", "task_id", "iteration", "window_label"):
        assert key in group, f"assignments are not separated by {key}"


def test_a_set_with_no_task_or_section_still_appears():
    """A paper whose task was never declared is precisely the one a teacher needs to find. An
    inner join to the name tables would drop it, and the set would be missing from the page with
    no error anywhere — an inventory discrepancy reported as an absence."""
    sql = str(_ASSIGNMENTS)
    joins = re.findall(r"(\w+)\s+JOIN\s+(\w+)", sql)
    assert joins, "no joins found"
    for kind, table in joins:
        assert kind.upper() == "LEFT", f"{table} is joined with {kind} JOIN, which drops rows"


def test_the_stuck_list_names_papers_rather_than_counting_them():
    """"Two are stuck" is not something anyone can act on. The two reasons a paper stops before
    scoring — we do not know whose it is, we could not read it — are both fixed by opening the
    paper, so the page has to hand over the papers."""
    sql = str(_STUCK)
    assert "artifact_id" in sql
    assert "file_name" in sql or "f.name" in sql
    assert "state_reason_code" in sql


def test_stuck_states_match_the_stage_that_counts_them():
    """The bar's `stuck` segment and the list underneath must be the same set of papers, or the
    page says two is stuck and shows three."""
    bar = set(re.findall(r"a\.state IN \(([^)]*)\)\s*THEN 'stuck'", _STAGES)[0].split(","))
    listed = set(re.findall(r"a\.state IN \(([^)]*)\)", str(_STUCK))[0].split(","))
    assert {s.strip() for s in bar} == {s.strip() for s in listed}


# ------------------------------------------------------------------ the vocabulary

def test_every_stage_has_words_a_teacher_would_use():
    """The labels are the contract with the console, which never invents one. They are also the
    only explanation a reader gets of what a segment means."""
    assert len(PIPELINE_STAGES) == len(STAGE_KEYS) == 5
    for key, label in PIPELINE_STAGES:
        assert label and label[0].isupper()
        assert key.islower() and " " not in key


def test_the_home_page_aggregates_papers_and_never_writing():
    """The queue's rule holds here: every number is a count of PAPERS in a state. A mean over
    criterion levels is a number nobody assigned, and the scale is criterion-referenced — a level
    says the writing meets a descriptor, not that it ranks anywhere. Averaging arrives on a page
    like this one first, so the guard belongs here."""
    for sql in (str(_PIPELINE), str(_ASSIGNMENTS), str(_STUCK)):
        assert not re.search(r"\b(avg|sum|percentile_cont|stddev)\s*\(", sql, re.I), (
            "the home page has started aggregating over scores")
        assert "score_event" not in sql, (
            "the home page reads scores; it is a view over the queue, not over anyone's writing")


# ------------------------------------------------------------------ honest degradation

def test_a_refused_read_is_not_reported_as_an_empty_page():
    """`available: false` renders as "nothing has been read yet", which is the right answer
    before the migrations have run and a lie if the read was REFUSED. A permission error
    collapsed into that flag would show a teacher a calm, tidy, entirely wrong page with no error
    anywhere — the defect this codebase keeps finding, a thing reporting success while not doing
    the job."""
    import pytest
    from fastapi import HTTPException
    from sqlalchemy.exc import SQLAlchemyError

    from app.review_view import _empty_or_raise

    class Undefined(Exception):
        pass

    Undefined.__name__ = "UndefinedTable"
    absent = SQLAlchemyError("relation does not exist")
    absent.orig = Undefined()
    assert _empty_or_raise(absent, {"pipeline": []})["available"] is False

    class InsufficientPrivilege(Exception):
        pass

    refused = SQLAlchemyError("permission denied for table registry_task")
    refused.orig = InsufficientPrivilege()
    with pytest.raises(HTTPException) as caught:
        _empty_or_raise(refused, {"pipeline": []})
    assert caught.value.status_code == 503
    assert "permission denied" in str(caught.value.detail)


def test_the_names_a_set_is_known_by_are_granted_to_the_api_role():
    """The home page renders `roster_section.name` and `registry_task.name`. Every other table it
    touches was granted by the module that owns it; a missing grant here would surface only as
    the empty page the test above exists to prevent."""
    import importlib.util
    import pathlib

    spec = importlib.util.spec_from_file_location(
        "m26", pathlib.Path(__file__).resolve().parents[1]
        / "migrations" / "versions" / "0026_home_read_grants.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    assert set(m.TABLES) == {"registry_task", "roster_section"}

    # What upgrade() actually executes, rather than what the file says about it — a comment
    # explaining why NOT to write a blanket grant reads identically to one.
    issued: list[str] = []
    m.op = type("op", (), {"execute": staticmethod(issued.append)})
    m.upgrade()
    assert len(issued) == len(m.TABLES), "one grant per named table"
    for sql in issued:
        assert sql.startswith("GRANT SELECT ON ")
        assert "ALL TABLES" not in sql, "a blanket grant hands over every future table too"
        assert "INSERT" not in sql and "UPDATE" not in sql, "serving owns no tables and writes none"
