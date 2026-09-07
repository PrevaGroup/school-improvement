"""The OAuth flow, and the two ways it silently produces a connection that does not work.

Most of this file is about `state`. Without a signed one, anybody can send a signed-in teacher a
link to a consent screen and have the callback attach an attacker-chosen Drive to that teacher's
account — the classic OAuth CSRF, and the whole security of this flow is the one check that the
state names the principal making the request.

The rest is about two failures that look like success on every screen: a connection stored without
a refresh token, and a connection missing a scope the user unticked.
"""
from __future__ import annotations

import pytest

from intake.drive import SCOPES
from intake.oauth import (OAuthError, STATE_TTL_SECONDS, authorize_url, make_state,
                          missing_scopes, read_state, read_token_response)

SECRET = "a-signing-secret"


# ------------------------------------------------------------------ state

def test_a_state_names_the_principal_it_was_issued_to():
    """The callback compares this against the principal making the request. Without that, the
    callback attaches whichever Google account completed a flow to whichever console session
    happened to arrive — which is the attack, not an edge case."""
    assert read_state(make_state("uid-1", SECRET), SECRET) == "uid-1"


def test_a_forged_state_is_refused():
    forged = make_state("uid-1", SECRET).split(".")[0] + ".not-a-signature"
    with pytest.raises(OAuthError):
        read_state(forged, SECRET)


def test_a_state_signed_with_another_secret_is_refused():
    with pytest.raises(OAuthError):
        read_state(make_state("uid-1", "someone-elses-secret"), SECRET)


def test_a_tampered_principal_is_refused():
    """The signature covers the claims, so swapping the subject invalidates it. If it did not, the
    state would be a suggestion rather than a control."""
    import base64
    import json

    body = json.dumps({"sub": "uid-2", "iat": 0}, separators=(",", ":"),
                      sort_keys=True).encode("utf8")
    good = make_state("uid-1", SECRET)
    tampered = base64.urlsafe_b64encode(body).decode().rstrip("=") + "." + good.split(".", 1)[1]
    with pytest.raises(OAuthError):
        read_state(tampered, SECRET)


def test_an_expired_state_is_refused():
    old = make_state("uid-1", SECRET, now=1000)
    with pytest.raises(OAuthError):
        read_state(old, SECRET, now=1000 + STATE_TTL_SECONDS + 1)
    assert read_state(old, SECRET, now=1000 + STATE_TTL_SECONDS - 1) == "uid-1"


def test_every_state_failure_says_the_same_thing():
    """A message that distinguished "expired" from "forged" would be a free oracle, and there is
    nothing a legitimate user does differently: both mean start again."""
    messages = set()
    for bad in ("garbage", make_state("uid-1", "wrong").replace(".", "."), "a.b"):
        try:
            read_state(bad, SECRET)
        except OAuthError as exc:
            messages.add(str(exc))
    expired = make_state("uid-1", SECRET, now=0)
    try:
        read_state(expired, SECRET, now=10**9)
    except OAuthError as exc:
        messages.add(str(exc))
    assert len(messages) == 1, messages


def test_a_malformed_state_does_not_raise_something_other_than_oautherror():
    """A ValueError escaping here becomes a 500 with a stack trace on a callback URL, which is
    both a worse message and more information than a caller should get."""
    for bad in ("", ".", "...", "!!!.???", "a" * 5000):
        with pytest.raises(OAuthError):
            read_state(bad, SECRET)


# ------------------------------------------------------------------ the authorize URL

def test_the_url_asks_for_offline_access_and_forces_consent():
    """Both are what make Google return a refresh token. Without them a second connection from an
    account that already granted access returns only an access token, and the connection dies
    silently within the hour."""
    url = authorize_url(client_id="cid", redirect_uri="https://x/cb", state="s")
    assert "access_type=offline" in url
    assert "prompt=consent" in url


def test_the_url_asks_only_for_the_read_only_scopes():
    url = authorize_url(client_id="cid", redirect_uri="https://x/cb", state="s")
    for s in SCOPES:
        assert s.replace(":", "%3A").replace("/", "%2F") in url or s in url
    assert "auth%2Fdrive&" not in url and "auth/drive&" not in url


def test_the_state_travels_in_the_url():
    assert "state=abc" in authorize_url(client_id="c", redirect_uri="https://x/cb", state="abc")


# ------------------------------------------------------------------ the token response

def test_a_response_with_no_refresh_token_is_refused_rather_than_stored():
    """The single most common way to end up with a dead connection. A row with no refresh token
    looks connected on every screen and stops working in an hour."""
    with pytest.raises(OAuthError, match="already granted access"):
        read_token_response({"access_token": "at", "scope": " ".join(SCOPES)})


def test_the_refusal_says_how_to_fix_it():
    """Because the fix is non-obvious: revoke at myaccount.google.com and connect again. A message
    that only said "no refresh token" would leave a person stuck."""
    try:
        read_token_response({"access_token": "at"})
    except OAuthError as exc:
        assert "myaccount.google.com/permissions" in str(exc)


def test_the_scopes_stored_are_the_ones_granted_not_the_ones_asked_for():
    """A user can untick a scope. Recording the request would produce a connection that looks
    complete and fails at the first export."""
    only_drive = SCOPES[0]
    got = read_token_response({"refresh_token": "rt", "scope": only_drive})
    assert got["granted_scopes"] == only_drive


def test_a_missing_scope_is_named_before_it_becomes_a_403():
    """So the console can say "you did not grant access to Docs" rather than surfacing an error
    from three layers down at the moment a teacher is reading a folder."""
    assert missing_scopes(" ".join(SCOPES)) == []
    assert missing_scopes(SCOPES[0]) == [SCOPES[1]]
    assert set(missing_scopes("")) == set(SCOPES)
