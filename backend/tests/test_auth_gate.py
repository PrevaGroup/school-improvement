"""The /api gate: every mounted route requires a verified, invited identity.

This is the change that lets `--no-allow-unauthenticated` eventually come off: once IAM stops
gating the service, THIS is the front door. The dependency is applied at the mount in main.py
(composition root), so a new endpoint added to any module is gated by construction — which is
also why these tests check a *sample across every router* rather than one route: the property
being pinned is "the mount covers everything," not "this endpoint has auth".

No DB, no network: 401s reject before any handler runs, and the accepted-path test overrides
`get_current_principal` and probes /api/me, which touches nothing but the principal.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.security import get_current_principal

client = TestClient(app)


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/me"),
    ("GET", "/api/marts/districts"),           # marts router
    ("GET", "/api/marts/attendance-diagnostic"),
    ("POST", "/api/chat"),                     # chat router
    ("POST", "/api/plans/extract"),            # plans router (was tenant-gated; still is, deeper)
])
def test_every_router_401s_without_a_token(method, path):
    """No token, no service — across every mounted router, not just one."""
    r = client.request(method, path)
    assert r.status_code == 401, f"{method} {path} -> {r.status_code}"
    assert "text/html" not in r.headers.get("content-type", "")


def test_garbage_token_is_401_not_500(monkeypatch):
    """A malformed bearer must be rejected as unauthorized, not crash into a 500.

    The audience must be configured first: without it the server 500s "auth not configured"
    BEFORE judging the token — which is correct (a misconfigured deploy should be loud), but
    it's a different property than the one this test pins."""
    from app import security
    monkeypatch.setattr(security.settings, "google_oauth_audience", "school-improvement-501916")
    r = client.get("/api/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert r.status_code == 401


def test_unconfigured_audience_is_a_loud_500_not_a_quiet_401():
    """The inverse, pinned on purpose: no GCP_PROJECT means auth CANNOT verify anything, and
    that must surface as a server error (fix the deploy), never as "invalid token" (blame the
    user and hunt ghosts)."""
    r = client.get("/api/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert r.status_code == 500
    assert "auth not configured" in r.json()["detail"]


def test_me_returns_the_email_for_an_invited_principal():
    """The SPA's invite probe: 200 + the display email, nothing else from the claims."""
    app.dependency_overrides[get_current_principal] = lambda: {
        "email": "tester@prevagroup.com", "sub": "uid-1", "email_verified": True,
    }
    try:
        r = client.get("/api/me")
        assert r.status_code == 200
        assert r.json() == {"email": "tester@prevagroup.com"}  # exact — no claim leakage
    finally:
        app.dependency_overrides.clear()


def test_health_and_shell_stay_open():
    """The liveness probe and the sign-in page itself must never sit behind the gate —
    gate them and Cloud Run can't health-check the service and nobody can reach the
    login screen to sign in at all."""
    assert client.get("/health").status_code == 200
    assert client.get("/").status_code in (200, 501)  # shell, or explicit 'frontend not built'
