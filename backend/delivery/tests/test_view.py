"""What the console shows about a hand-back — and the three states it must keep apart.

A delivery panel that collapses these is worse than none: a teacher acts differently on "they have
it", "they have an older one", and "they have nothing", and two of those look like success from a
distance.
"""
from __future__ import annotations

import inspect

from delivery import view


def test_the_panel_is_read_only():
    """The `file` channel writes where the folder is, which Cloud Run cannot reach. A send button
    here would produce a `failed` row every time and teach a teacher that delivery is broken."""
    src = inspect.getsource(view)
    assert "INSERT INTO artifact_delivery" not in src
    assert "@router.post" not in src


def test_what_the_student_holds_is_the_last_SUCCESSFUL_send():
    """Not the last attempt. A failed retry after a successful send leaves them holding the
    earlier message, and a screen that showed the failure as the state would tell a teacher they
    have nothing when they have something."""
    src = inspect.getsource(view.attempts)
    assert 'sent = [r for r in rows if r["status"] == "sent"]' in src
    assert '"delivered": sent[-1] if sent else None' in src
    assert '"last_attempt"' in src, "the latest attempt is reported separately, not as the state"


def test_a_failed_attempt_is_not_counted_as_a_hand_back():
    """The queue's last segment is papers the student actually has. Counting a failure as one is
    the silence the whole table exists to prevent."""
    sql = str(view._COUNTS)
    assert "FILTER (WHERE status = 'sent')" in sql
    # And a paper that failed but succeeded earlier is not "failing" — it is delivered.
    assert "NOT IN (SELECT artifact_id FROM artifact_delivery" in sql


def test_the_attempts_read_in_the_order_they_happened():
    """"Tried at 09:41, moved, tried again at 14:02 and it went" only reads that way in order."""
    assert "ORDER BY attempted_at" in str(view._ATTEMPTS)
    assert "DESC" not in str(view._ATTEMPTS)


def test_a_missing_table_is_an_empty_answer_not_a_500():
    """Before the migration runs, a console that errored would look broken rather than empty."""
    src = inspect.getsource(view)
    assert src.count('"available": False') == 2
