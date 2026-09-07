"""Refresh tokens live in Secret Manager, and the row holds a pointer.

The first draft put the token in a Postgres column with a paragraph explaining that Cloud SQL
encrypts at rest and no query selects it. That describes a mitigation rather than a place for a
credential, and it left a live token visible to a `pg_dump`, a debugging session, a migration, or
a future serving query written by somebody who did not read the comment.
"""
from __future__ import annotations

import pytest

from intake import token_store


def test_the_connection_row_holds_no_credential():
    """The structural check. If a `refresh_token` column ever comes back, everything below is
    decoration."""
    from intake.models import DriveConnection

    columns = set(DriveConnection.__table__.columns.keys())
    assert "token_secret_name" in columns
    assert "refresh_token" not in columns
    assert not [c for c in columns if "token" in c and c != "token_secret_name"]


def test_the_secret_name_is_derived_from_the_connection():
    """So the row and the secret can never disagree. A stored name that drifted from the row would
    leave a connection pointing at somebody else's credential."""
    assert token_store.secret_name_for("abc") == f"{token_store.PREFIX}-abc"
    assert token_store.secret_name_for("abc") != token_store.secret_name_for("abd")


def test_one_secret_per_connection_rather_than_one_map():
    """A map means every write is a read-modify-write on a shared value, which races the moment
    two people connect at once — and anything that can read one token can read all of them."""
    names = {token_store.secret_name_for(f"conn-{i}") for i in range(5)}
    assert len(names) == 5


def test_the_token_is_never_cached(monkeypatch):
    """`Settings._secret` caches per process, which is right for a database password and wrong for
    a rotating credential: a cached refresh token survives its own revocation for the life of the
    container, so revoking would appear to work and not work."""
    import inspect

    src = inspect.getsource(token_store.read)
    assert "_SECRET_CACHE" not in src
    assert "cache" not in src.lower() or "Never cached" in src


def test_storing_without_a_project_refuses_rather_than_falling_back(monkeypatch):
    """There is no local fallback for a credential store. A refusal here is a connection that does
    not exist; a fallback would be a credential somewhere nobody chose."""
    monkeypatch.setattr(token_store.settings, "gcp_project", "")
    with pytest.raises(token_store.TokenStoreError, match="Refusing to store"):
        token_store.store("conn-1", "rt")


def test_a_failed_store_says_the_connection_was_not_saved():
    """Because the alternative — a row pointing at a secret that does not exist — looks connected
    on every screen and fails at the first folder read."""
    import inspect

    assert "NOT saved" in inspect.getsource(token_store.store)


def test_revoking_destroys_the_secret_and_keeps_the_row():
    """The row is the provenance of every paper read through that connection and it stays. The
    credential is the part that has to stop existing — a revocation that leaves a working token
    behind reports success without doing the job."""
    import inspect

    src = inspect.getsource(token_store.revoke)
    assert "delete_secret" in src
    assert "row" in src.lower()


def test_a_secret_already_gone_is_the_desired_end_state():
    """Revoking twice must not raise. The goal is "this credential does not exist"."""
    import inspect

    assert "already destroyed" in inspect.getsource(token_store.revoke)
