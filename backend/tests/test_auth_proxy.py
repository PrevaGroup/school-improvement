"""The /__/* reverse proxy (app/auth_proxy.py) — custom-authDomain sign-in.

What's load-bearing here:
- /__/auth/handler must answer WITHOUT a bearer token (it serves people who are mid-sign-in
  and have no token yet) — and must NOT be swallowed by the SPA catch-all, which would hand
  Google's redirect an HTML shell and break sign-in with no error anywhere.
- The upstream host is FIXED (the project's firebaseapp.com); callers control only the path
  under /__/. Pinning that here is what keeps this from quietly becoming an open proxy.

The upstream call is faked at the httpx-client seam — no network in unit tests.
"""
import httpx
import pytest
from fastapi.testclient import TestClient

from app import auth_proxy
from app.main import app

client = TestClient(app)


class _StubClient:
    """Captures the outbound request; returns a canned upstream response."""

    def __init__(self, response: httpx.Response):
        self.response = response
        self.calls: list[dict] = []

    async def request(self, method, url, params=None, content=b"", headers=None):
        self.calls.append(
            {"method": method, "url": url, "params": dict(params or {}), "headers": headers}
        )
        return self.response


def _stub(monkeypatch, *, status=200, headers=None, content=b"<!doctype html>ok"):
    stub = _StubClient(httpx.Response(status, headers=headers or {}, content=content))
    monkeypatch.setattr(auth_proxy, "_client", stub)
    monkeypatch.setattr(auth_proxy.settings, "gcp_project", "school-improvement-501916")
    return stub


def test_auth_handler_is_reachable_without_a_token(monkeypatch):
    """The whole point: a user mid-sign-in has no token. If this route ever lands behind the
    /api gate, sign-in dies with a 401 nobody can see."""
    stub = _stub(monkeypatch, headers={"content-type": "text/html; charset=utf-8"})
    r = client.get("/__/auth/handler?apiKey=abc")
    assert r.status_code == 200
    assert r.text == "<!doctype html>ok"
    assert r.headers["content-type"].startswith("text/html")


def test_upstream_host_is_fixed_and_path_scoped(monkeypatch):
    """Not an open proxy: whatever the caller does with the path, the host is the project's
    firebaseapp.com and the path stays under /__/."""
    stub = _stub(monkeypatch)
    client.get("/__/auth/iframe", params={"apiKey": "k"})
    (call,) = stub.calls
    assert call["url"] == "https://school-improvement-501916.firebaseapp.com/__/auth/iframe"
    assert call["params"] == {"apiKey": "k"}


def test_spa_fallback_does_not_swallow_the_namespace(monkeypatch):
    """If the proxy route were registered after the catch-all (or dropped), /__/auth/handler
    would return index.html with a 200 — sign-in broken, nothing red anywhere. The stub proves
    the request reached the proxy, not the SPA."""
    stub = _stub(monkeypatch, content=b"proxied")
    r = client.get("/__/firebase/init.json")
    assert r.text == "proxied"
    assert stub.calls, "request never reached the proxy"


def test_authorization_header_is_not_forwarded(monkeypatch):
    """A signed-in user's browser may attach nothing here, but if a bearer token ever rode
    along, forwarding it to a third party (even Google) would leak it. Allowlist, not block-
    list, and this pins it."""
    stub = _stub(monkeypatch)
    client.get("/__/auth/handler", headers={"Authorization": "Bearer secret", "Accept": "*/*"})
    (call,) = stub.calls
    assert "authorization" not in {k.lower() for k in call["headers"]}
    assert call["headers"].get("accept") == "*/*"


def test_unset_gcp_project_is_a_clear_503(monkeypatch):
    """Bare local dev without GCP_PROJECT: say what's wrong, don't 404 into confusion."""
    _stub(monkeypatch)
    monkeypatch.setattr(auth_proxy.settings, "gcp_project", None)
    r = client.get("/__/auth/handler")
    assert r.status_code == 503
    assert "GCP_PROJECT" in r.json()["detail"]


def test_not_in_the_published_contract():
    """Infrastructure, not API surface — the frozen route contract must not see it (same
    treatment as `/`). If this fails someone removed include_in_schema=False."""
    assert not any(p.startswith("/__") for p in app.openapi()["paths"])
