"""Eval-principal token helper — the Identity Toolkit exchange, faked; no real network."""
from __future__ import annotations

import sys
import types

import pytest

import evals.auth as auth


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_fetch_id_token_returns_the_id_token(monkeypatch):
    captured = {}

    def fake_post(url, params=None, json=None, timeout=None):
        captured.update(url=url, params=params, json=json)
        return _Resp({"idToken": "ID-123", "refreshToken": "r"})

    monkeypatch.setitem(sys.modules, "httpx", types.SimpleNamespace(post=fake_post))
    tok = auth.fetch_id_token("eval@x.com", "pw", "APIKEY")
    assert tok == "ID-123"
    assert captured["params"] == {"key": "APIKEY"}
    assert captured["json"]["email"] == "eval@x.com" and captured["json"]["returnSecureToken"]


def test_eval_token_from_env_requires_all_three(monkeypatch):
    for k in ("EVAL_PRINCIPAL_EMAIL", "EVAL_PRINCIPAL_PASSWORD", "IDENTITY_PLATFORM_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(SystemExit):
        auth.eval_token_from_env()


def test_eval_token_from_env_mints_when_present(monkeypatch):
    monkeypatch.setenv("EVAL_PRINCIPAL_EMAIL", "eval@x.com")
    monkeypatch.setenv("EVAL_PRINCIPAL_PASSWORD", "pw")
    monkeypatch.setenv("IDENTITY_PLATFORM_API_KEY", "APIKEY")
    monkeypatch.setattr(auth, "fetch_id_token", lambda e, p, k: "TOK")
    assert auth.eval_token_from_env() == "TOK"
