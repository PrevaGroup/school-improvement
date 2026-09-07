"""Refresh tokens live in Secret Manager. The database holds a pointer.

The first version of this put the refresh token in a Postgres column and wrote a paragraph
explaining that Cloud SQL encrypts at rest and no query selects it. That is a description of a
mitigation, not a place for a credential, and the project already had the right place:
`app/config.py` reads every other secret this system holds from Secret Manager.

## What moving it actually buys, beyond tidiness

A database backup is not a credential store. Anything that reads the connection table — a
migration, a debugging session, a `pg_dump` on a laptop, a future serving query written by
somebody who did not read the comment — sees a live token. With a pointer, all of those see a
resource name and nothing more.

It also puts the token under IAM rather than under a table grant, so access is auditable in Cloud
Audit Logs per read, revocable without a deploy, and grantable to exactly the one service account
that needs it. A `GRANT SELECT` cannot express any of that.

## One secret per connection, not one secret holding a map

A map means every write is a read-modify-write on a shared value, which races the moment two
people connect at once, and it means anything that can read one person's token can read
everyone's. Per-connection secrets cost about six cents a month each and make the blast radius one
person — the same argument that made this per-teacher OAuth instead of domain-wide delegation.

## Deliberately not cached

`Settings._secret` caches per process, which is right for a database password that changes about
once a year and wrong for a credential that rotates. A cached refresh token survives its own
revocation for the life of the container, so revoking access would appear to work and not work.

## Deleting is destroying

`revoke` destroys the secret rather than removing the row. The row is the provenance of every
paper read through that connection and it stays; the credential is the part that must actually
stop existing. A revocation that leaves a working token behind is the same class of defect as a
delivery that reports success without sending.
"""
from __future__ import annotations

import logging

from app.config import settings

log = logging.getLogger("intake.token_store")

# A visible, greppable prefix, so somebody looking at a project's secrets can see what these are
# and which subsystem owns them without opening the code.
PREFIX = "intake-drive-refresh"


class TokenStoreError(Exception):
    """Secret Manager would not do it, in words a person can act on."""


def secret_name_for(connection_id: str) -> str:
    """The secret id for one connection. Derived, so it can never disagree with the row."""
    return f"{PREFIX}-{connection_id}"


def _client():
    from google.cloud import secretmanager

    if not settings.gcp_project:
        raise TokenStoreError(
            "GCP_PROJECT is not set, so there is nowhere to put a refresh token. Refusing to "
            "store a credential outside Secret Manager.")
    return secretmanager.SecretManagerServiceClient()


def store(connection_id: str, refresh_token: str) -> str:
    """Put the token in Secret Manager and return the secret id the row should record.

    Creating and adding a version are two calls, and the create is allowed to fail as
    already-exists: reconnecting the same Drive is a person clicking again, and the second
    connection adds a NEW VERSION rather than replacing the secret. Versions are what make a
    reconnect auditable — the previous token is superseded, and when it stopped being current is
    recoverable.
    """
    client = _client()
    secret_id = secret_name_for(connection_id)
    parent = f"projects/{settings.gcp_project}"
    try:
        try:
            client.create_secret(request={
                "parent": parent, "secret_id": secret_id,
                "secret": {"replication": {"automatic": {}}},
            })
        except Exception as exc:
            if "already exists" not in str(exc).lower() and "AlreadyExists" not in type(exc).__name__:
                raise
        client.add_secret_version(request={
            "parent": f"{parent}/secrets/{secret_id}",
            "payload": {"data": refresh_token.encode("utf8")},
        })
    except Exception as exc:
        raise TokenStoreError(
            f"could not store the Drive credential in Secret Manager: {exc}. The connection was "
            f"NOT saved — a row pointing at a secret that does not exist would look connected and "
            f"fail at the first folder read.") from exc
    return secret_id


def read(secret_id: str) -> str:
    """The current refresh token. Never cached — see the module docstring."""
    client = _client()
    name = f"projects/{settings.gcp_project}/secrets/{secret_id}/versions/latest"
    try:
        return client.access_secret_version(request={"name": name}).payload.data.decode("utf8")
    except Exception as exc:
        raise TokenStoreError(
            f"the Drive credential for this connection is gone or unreadable: {exc}. Reconnect "
            f"the account from the console.") from exc


def revoke(secret_id: str) -> None:
    """Destroy the secret. The connection ROW stays.

    The row is the provenance of every paper read through this connection, and deleting it would
    make "where did these papers come from" unanswerable six weeks later. The credential is the
    part that has to stop existing, and a revocation that leaves a working token behind reports
    success without doing the job.
    """
    client = _client()
    name = f"projects/{settings.gcp_project}/secrets/{secret_id}"
    try:
        client.delete_secret(request={"name": name})
    except Exception as exc:
        # Already gone is the desired end state, not a failure.
        if "not found" in str(exc).lower() or "NotFound" in type(exc).__name__:
            log.info("%s was already destroyed", secret_id)
            return
        raise TokenStoreError(
            f"could not destroy the Drive credential {secret_id}: {exc}. The connection is marked "
            f"revoked and the token may still work — revoke it at "
            f"myaccount.google.com/permissions as well.") from exc
