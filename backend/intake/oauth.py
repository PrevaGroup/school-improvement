"""Connecting one person's Google account, and keeping the connection honest afterwards.

Per-teacher OAuth. The plan settles the alternative: domain-wide delegation only becomes the right
call at district scale, "where central provisioning starts to outweigh blast radius". A refresh
token here reaches one person's Drive; a delegated service account would reach everyone's.

## The state parameter is a CSRF control, not a convenience

Without it, anyone can send a signed-in teacher a link to Google's consent screen with their own
`client_id`-scoped state and have the callback attach an attacker-chosen Drive to the teacher's
account. So `state` is signed with the app's own secret, carries the principal it was issued to,
and expires — and the callback refuses a state that does not name the principal making the request.
That check is the whole security of this flow; everything else is bookkeeping.

## Two identities, again

`state` binds the CONSOLE principal. Google's token response tells us the GOOGLE account. They are
routinely different — in this pilot they are — and both are stored. A flow that assumed they
matched would silently attach one person's Drive to another person's row the first time somebody
had two accounts, which is most people.

## Scopes as granted, not as asked

Google returns the scopes actually granted, which can be fewer than requested if the user unticked
one. Recording the request instead of the grant produces a connection that looks complete and
fails at the first export with a 403 — so the grant is what is stored, and `missing_scopes` is what
the console shows.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from urllib.parse import urlencode

from .drive import SCOPES

log = logging.getLogger("intake.oauth")

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"

# Ten minutes. Long enough to read a consent screen and think about it, short enough that a state
# value copied out of a browser history is worthless.
STATE_TTL_SECONDS = 600


class OAuthError(Exception):
    """The flow could not complete. Carries what the person should be told."""


def _sign(payload: bytes, secret: str) -> str:
    return base64.urlsafe_b64encode(
        hmac.new(secret.encode("utf8"), payload, hashlib.sha256).digest()).decode().rstrip("=")


def make_state(principal_sub: str, secret: str, *, now: float | None = None) -> str:
    """A signed, expiring token naming who started the flow."""
    body = json.dumps({"sub": principal_sub, "iat": int(now or time.time())},
                      separators=(",", ":"), sort_keys=True).encode("utf8")
    return (base64.urlsafe_b64encode(body).decode().rstrip("=") + "." + _sign(body, secret))


def read_state(state: str, secret: str, *, now: float | None = None) -> str:
    """The principal a state was issued to, or raise.

    Every failure raises the SAME class with a message that does not distinguish a forged
    signature from an expired one. A callback that said which would be a free oracle, and there is
    nothing a legitimate user does differently in the two cases: both mean start again.
    """
    try:
        encoded, signature = state.split(".", 1)
        body = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    except Exception as exc:
        raise OAuthError("this sign-in link is not valid. Start again from the console.") from exc

    if not hmac.compare_digest(signature, _sign(body, secret)):
        raise OAuthError("this sign-in link is not valid. Start again from the console.")

    claims = json.loads(body)
    if (now or time.time()) - float(claims.get("iat", 0)) > STATE_TTL_SECONDS:
        raise OAuthError("this sign-in link is not valid. Start again from the console.")
    sub = str(claims.get("sub") or "")
    if not sub:
        raise OAuthError("this sign-in link is not valid. Start again from the console.")
    return sub


def authorize_url(*, client_id: str, redirect_uri: str, state: str) -> str:
    """Where to send the person.

    `access_type=offline` with `prompt=consent` is what makes Google return a refresh token. Not
    optional and not a default: without both, a second connection from the same account returns
    only an access token, the row is written with an empty refresh token, and the connection dies
    silently in an hour.
    """
    return AUTH_URL + "?" + urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    })


def read_token_response(raw: dict) -> dict:
    """Google's token response -> what the connection row needs.

    A response with no refresh token is refused rather than stored. It is the failure mode of
    re-consenting an account that has already granted access, and a row with no refresh token
    looks connected on every screen and stops working within the hour.
    """
    refresh = raw.get("refresh_token")
    if not refresh:
        raise OAuthError(
            "Google did not return a refresh token, which happens when this account has already "
            "granted access. Remove this app at myaccount.google.com/permissions and connect "
            "again.")
    return {"refresh_token": refresh,
            "granted_scopes": raw.get("scope") or "",
            "access_token": raw.get("access_token") or ""}


def missing_scopes(granted: str) -> list[str]:
    """What was asked for and not granted.

    A user who unticks one scope on the consent screen produces a connection that enumerates fine
    and fails at the first document export. Naming it here means the console can say "you did not
    grant access to Docs" rather than surfacing a 403 from three layers down.
    """
    have = set((granted or "").split())
    return [s for s in SCOPES if s not in have]
