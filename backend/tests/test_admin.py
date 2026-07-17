"""Administrator = membership in the Workspace admin group (security.is_admin / require_admin).

The network call to Cloud Identity (`_is_group_member`) is patched at its seam, so these pin
the part that must be right regardless of GCP wiring: the caching, and — above all — that admin
FAILS CLOSED. Admin is elevation; every unhappy path must withhold it, never grant it.
"""
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import security
from app.main import app
from app.security import get_current_principal, is_admin


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    security._admin_cache.clear()
    monkeypatch.setattr(security.settings, "admin_group", "usersupport@prevagroup.com")
    yield
    security._admin_cache.clear()


def _member(monkeypatch, value):
    """Patch the Cloud Identity call; `value` may be a bool or an Exception to raise."""
    calls = {"n": 0}

    def fake(email, group):
        calls["n"] += 1
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(security, "_is_group_member", fake)
    return calls


def test_group_member_is_admin(monkeypatch):
    _member(monkeypatch, True)
    assert is_admin({"email": "tim@prevagroup.com"}) is True


def test_non_member_is_not_admin(monkeypatch):
    _member(monkeypatch, False)
    assert is_admin({"email": "someone@prevagroup.com"}) is False


def test_dev_mode_principal_is_admin(monkeypatch):
    """Local DEV_MODE (non-prod only) is admin for convenience — no network call needed."""
    calls = _member(monkeypatch, RuntimeError("should not be called"))
    assert is_admin({"dev_mode": True, "email": None}) is True
    assert calls["n"] == 0


def test_no_group_configured_means_nobody_is_admin(monkeypatch):
    monkeypatch.setattr(security.settings, "admin_group", "")
    calls = _member(monkeypatch, True)  # even if the group would say yes
    assert is_admin({"email": "tim@prevagroup.com"}) is False
    assert calls["n"] == 0  # short-circuits before the API


def test_no_email_is_not_admin(monkeypatch):
    _member(monkeypatch, True)
    assert is_admin({"email": None}) is False
    assert is_admin({}) is False


def test_api_error_fails_closed_and_is_not_cached(monkeypatch):
    """The load-bearing property: a membership check that ERRORS withholds admin AND is not
    cached — a transient outage must not lock an admin out for the whole TTL."""
    calls = _member(monkeypatch, ConnectionError("cloud identity is having a day"))
    assert is_admin({"email": "tim@prevagroup.com"}) is False
    assert is_admin({"email": "tim@prevagroup.com"}) is False
    assert calls["n"] == 2  # retried, not served from a cached negative


def test_result_is_cached_within_ttl(monkeypatch):
    calls = _member(monkeypatch, True)
    assert is_admin({"email": "tim@prevagroup.com"}) is True
    assert is_admin({"email": "tim@prevagroup.com"}) is True
    assert calls["n"] == 1  # second call served from cache


def test_require_admin_403s_a_non_admin(monkeypatch):
    import asyncio
    _member(monkeypatch, False)
    with pytest.raises(HTTPException) as e:
        asyncio.get_event_loop().run_until_complete(
            security.require_admin({"email": "nope@prevagroup.com"})
        )
    assert e.value.status_code == 403


# --- the /api/admin/status endpoint (UI hint) ------------------------------------------- #
client = TestClient(app)


def test_admin_status_endpoint_reports_membership(monkeypatch):
    _member(monkeypatch, True)
    app.dependency_overrides[get_current_principal] = lambda: {"email": "tim@prevagroup.com"}
    try:
        r = client.get("/api/admin/status")
        assert r.status_code == 200
        assert r.json() == {"is_admin": True}
    finally:
        app.dependency_overrides.clear()


def test_admin_status_endpoint_false_for_non_member(monkeypatch):
    _member(monkeypatch, False)
    app.dependency_overrides[get_current_principal] = lambda: {"email": "someone@prevagroup.com"}
    try:
        r = client.get("/api/admin/status")
        assert r.json() == {"is_admin": False}
    finally:
        app.dependency_overrides.clear()
