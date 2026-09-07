"""The gate: a folder read is a proposal until a teacher agrees with the set.

The plan calls this the largest single saving in the design — one confirmation replacing
twenty-eight corrections. What makes it a gate rather than a screen is that `scoring.bind` reads
`confirmed_at`, so a second entry point cannot bind a read nobody agreed to.
"""
from __future__ import annotations

import inspect
import re

from intake import review
from scoring import bind


def test_bind_only_takes_files_from_a_confirmed_read():
    """THE test. If confirmation lived only in the interface, a cron, a retry, or somebody running
    the module directly would bind an unconfirmed read — and the papers would be scored against a
    declaration nobody made."""
    assert "m.confirmed_at IS NOT NULL" in str(bind._PENDING)


def test_the_gate_is_in_the_query_bind_actually_runs():
    """Not in a caller, not in a flag. `_PENDING` is what selects the work."""
    src = inspect.getsource(bind.bind_pending)
    assert "_PENDING" in src


def test_a_confirmation_names_who_made_it():
    """A gate that opened by itself is not a gate. The CHECK in 0024 refuses an anonymous one;
    this refuses to write one."""
    src = inspect.getsource(review)
    assert "confirmed_by = :who" in src
    assert "_who(principal)" in src


def test_a_confirmation_cannot_be_made_twice():
    """The second one would assert agreement with a set that may have been bound already, and
    would silently overwrite who agreed to it."""
    assert "confirmed_at IS NULL" in str(review._CONFIRM)
    src = inspect.getsource(review.confirm)
    assert "already confirmed" in src


def test_a_teacher_correction_is_recorded_as_stronger_than_a_string_match():
    """A person read the paper and knew. Recording that as `looked_up` with basis `teacher` keeps
    `inferred_rate` meaning what it says — the share of bindings nobody confirmed."""
    sql = str(review._ASSIGN)
    assert "resolution_basis = 'teacher'" in sql
    assert "resolution_path = 'looked_up'" in sql


def test_detaching_a_file_clears_the_student_and_says_why():
    """Half a correction — a status of resolved with no student, or a student with no status —
    is exactly what the CHECK in 0021 refuses, and it would be a paper attributed to nobody."""
    sql = str(review._UNASSIGN)
    assert "resolved_student_id = NULL" in sql
    assert ":status" in sql and ":reason" in sql


def test_two_files_cannot_be_attached_to_one_student():
    """A student hands in once. Two files on one person under one manifest is a correction that
    needs undoing, not a second submission, and binding both would give one student two papers on
    the same task."""
    src = inspect.getsource(review.assign)
    assert "_TAKEN" in src
    assert "hands in once" in src


def test_the_set_is_ordered_by_what_needs_a_person_first():
    """A folder sorted by filename buries the three files that need attention among twenty-five
    that do not — which is the file-by-file review the set confirmation exists to replace."""
    sql = str(review._FILES)
    order = sql[sql.index("ORDER BY"):]
    for earlier, later in (("'unresolved'", "'unreadable'"), ("'unreadable'", "'empty'"),
                           ("'empty'", "'not_student_work'")):
        assert order.index(earlier) < order.index(later), f"{earlier} should sort before {later}"


def test_who_handed_in_nothing_is_part_of_the_answer():
    """The one thing a per-file view structurally cannot show, and the thing a teacher chases."""
    sql = str(review._MISSING)
    assert "NOT EXISTS" in sql
    assert "roster_enrollment" in sql


def test_the_manifest_list_counts_every_status():
    """Five outcomes and none of them is "missing". A summary that counted only the resolved would
    be the twenty-seven-files-twenty-four-scores failure with a nicer interface."""
    sql = str(review._MANIFESTS)
    for status in ("resolved", "unresolved", "not_student_work", "unreadable", "empty"):
        assert f"'{status}'" in sql, f"{status} is not counted"


def test_the_inferred_rate_travels_with_the_folder():
    """The integration-health signal. A rise means account matching stopped working, and a teacher
    correcting half a folder should be able to see that it was not their fault."""
    assert "inferred_rate" in str(review._MANIFESTS)
    assert "inferred_rate" in str(review._ONE)


def test_intake_writes_no_artifacts():
    """`artifact` belongs to scoring. Confirming a manifest is what LETS bind make them; it does
    not make them. Two writers to one table is not a contract."""
    src = inspect.getsource(review)
    assert "INSERT INTO artifact" not in src
    assert re.search(r"UPDATE\s+artifact", src) is None
