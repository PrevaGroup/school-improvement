"""Tests for the trust boundary — `app.security`. See docs/GO_LIVE_PLAN.md §3.2 + §3.3.

Unlike test_chat_tools.py (which pins *existing* behavior), this file covers behavior the
§3.2/§3.3 patch *introduces*:

  §3.2  authentication (`get_current_principal`) split from tenancy (`get_current_tenant`),
        so public routes can require a signed-in user WITHOUT requiring a district. Gating
        public marts on tenancy would 403 every outside tester — the thing that would have
        quietly broken go-live.
  §3.3  DEV_MODE cannot reach production. `X-Dev-Tenant` is unverified — whatever it claims,
        you become — so on a public service it is tenant impersonation by header. It is gated
        on the ENVIRONMENT, not on the flag, because `DEV_MODE=false` in a deploy command is
        one hurried edit away from true.

No network, no DB: `_verify_identity_token` is patched wherever a real token would be needed.
`get_current_*` are async, driven here with asyncio.run() rather than adding a pytest-asyncio
dependency (see CLAUDE.md — the dependency list is frozen).
"""
import asyncio

import pytest
from fastapi import HTTPException

from app import security


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def isolate_env(monkeypatch):
    """Every test starts from a known-clean environment: no Cloud Run, no Cloud SQL, no dev."""
    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.setattr(security.settings, "instance_connection_name", None)
    monkeypatch.setattr(security.settings, "dev_mode", False)
    monkeypatch.setattr(security.settings, "tenant_claim", "tenant_id")
    monkeypatch.setattr(security.settings, "domain_tenant_map", {})


@pytest.fixture
def verified(monkeypatch):
    """Patch token verification; return the claims a 'valid' token yields."""
    def install(claims):
        monkeypatch.setattr(security, "_verify_identity_token", lambda token: claims)
    return install


# --------------------------------------------------------------------------- #
# §3.3 — DEV_MODE containment
# --------------------------------------------------------------------------- #
def test_dev_mode_off_by_default_is_not_active():
    assert security.dev_mode_active() is False


def test_dev_mode_active_only_when_no_production_signal(monkeypatch):
    monkeypatch.setattr(security.settings, "dev_mode", True)
    assert security.dev_mode_active() is True


@pytest.mark.parametrize("signal", ["K_SERVICE", "INSTANCE_CONNECTION_NAME"])
def test_dev_mode_fails_closed_when_production_signal_present(monkeypatch, signal):
    """The core of §3.3: DEV_MODE is inert in production even if someone sets the flag."""
    monkeypatch.setattr(security.settings, "dev_mode", True)
    if signal == "K_SERVICE":
        monkeypatch.setenv("K_SERVICE", "sip-api")          # Cloud Run injects this
    else:
        monkeypatch.setattr(security.settings, "instance_connection_name",
                            "proj:us-central1:school-improvement-sql")
    assert security.dev_mode_active() is False


def test_dev_header_is_ignored_in_production(monkeypatch):
    """THIS TEST IS §3.3. Do not delete it; it is the whole point of the mechanism.

    The attack it closes: DEV_MODE left on in prod + X-Dev-Tenant = become any district.
    The header must NOT be honored; the request falls through to real token verification and
    is rejected 401 for having no bearer token.

    Why gate on environment signals rather than the DEV_MODE flag alone — the failure modes are
    not symmetric. Keying on the environment means a bad config fails as "dev mode silently OFF
    in prod" (safe: legitimate users hit normal auth). Keying on the flag alone means a bad
    config fails as "dev mode silently ON in prod" — a breach, and a silent one. Always choose
    the mechanism whose misconfiguration is inert rather than exploitable.
    """
    monkeypatch.setattr(security.settings, "dev_mode", True)
    monkeypatch.setenv("K_SERVICE", "sip-api")
    with pytest.raises(HTTPException) as e:
        _run(security.get_current_principal(authorization=None, x_dev_tenant="other-district"))
    assert e.value.status_code == 401  # NOT a 200 impersonating 'other-district'


def test_dev_header_works_locally(monkeypatch):
    """The legitimate use: exercise RLS locally without OIDC."""
    monkeypatch.setattr(security.settings, "dev_mode", True)
    principal = _run(security.get_current_principal(authorization=None, x_dev_tenant="lbusd"))
    assert principal["tenant_id"] == "lbusd"
    assert principal["dev_mode"] is True
    assert _run(security.get_current_tenant(principal=principal)) == "lbusd"


@pytest.mark.parametrize("signal", ["K_SERVICE", "INSTANCE_CONNECTION_NAME"])
def test_assert_refuses_to_start_with_dev_mode_in_production(monkeypatch, signal):
    """Loud at startup (a failed deploy), not silent at request time."""
    monkeypatch.setattr(security.settings, "dev_mode", True)
    if signal == "K_SERVICE":
        monkeypatch.setenv("K_SERVICE", "sip-api")
    else:
        monkeypatch.setattr(security.settings, "instance_connection_name", "p:r:i")
    with pytest.raises(RuntimeError) as e:
        security.assert_dev_mode_not_in_production()
    assert signal in str(e.value)
    assert "impersonate" in str(e.value)      # says WHY, not just "bad config"


def test_assert_allows_dev_mode_locally(monkeypatch):
    monkeypatch.setattr(security.settings, "dev_mode", True)
    security.assert_dev_mode_not_in_production()  # must not raise


def test_assert_allows_production_without_dev_mode(monkeypatch):
    monkeypatch.setenv("K_SERVICE", "sip-api")
    security.assert_dev_mode_not_in_production()  # the normal prod path


# --------------------------------------------------------------------------- #
# §3.2 — authentication (principal), independent of tenancy
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("header", [None, "", "Basic abc", "token abc", "Bearer"])
def test_principal_requires_a_bearer_token(header):
    with pytest.raises(HTTPException) as e:
        _run(security.get_current_principal(authorization=header, x_dev_tenant=None))
    assert e.value.status_code == 401


def test_principal_returns_claims_for_a_valid_token(verified):
    verified({"email": "tester@example.org", "sub": "uid-1"})
    principal = _run(security.get_current_principal(authorization="Bearer good.jwt",
                                                    x_dev_tenant=None))
    assert principal["email"] == "tester@example.org"


def test_principal_accepts_a_signed_in_user_with_no_tenant(verified):
    """THE POINT OF §3.2. An outside tester has no district and no tenant claim. They must still
    authenticate successfully — everything served today is public data. Before the split, the
    only dependency available 403'd them, which would have locked out exactly the people this
    cutover is for."""
    verified({"email": "curious@nowhere.org", "sub": "uid-2"})
    principal = _run(security.get_current_principal(authorization="Bearer good.jwt",
                                                    x_dev_tenant=None))
    assert principal["sub"] == "uid-2"          # authenticated
    assert "tenant_id" not in principal          # and deliberately tenant-less


def test_principal_scheme_match_is_case_insensitive(verified):
    verified({"sub": "uid-3"})
    assert _run(security.get_current_principal(authorization="bearer good.jwt",
                                               x_dev_tenant=None))["sub"] == "uid-3"


def test_dev_header_ignored_when_dev_mode_off(verified):
    """DEV_MODE off → the header is just noise; a real token is still required."""
    with pytest.raises(HTTPException) as e:
        _run(security.get_current_principal(authorization=None, x_dev_tenant="lbusd"))
    assert e.value.status_code == 401


# --------------------------------------------------------------------------- #
# §3.2 — tenancy, on top of a verified principal
# --------------------------------------------------------------------------- #
def test_tenant_from_custom_claim():
    """Primary path: the token carries a server-set, verified tenant claim."""
    assert _run(security.get_current_tenant(principal={"tenant_id": "lbusd"})) == "lbusd"


def test_tenant_claim_is_coerced_to_str():
    assert _run(security.get_current_tenant(principal={"tenant_id": 42})) == "42"


def test_tenant_from_email_domain_fallback(monkeypatch):
    monkeypatch.setattr(security.settings, "domain_tenant_map", {"lbschools.net": "lbusd"})
    principal = {"email": "staff@LBSchools.net"}   # domain match is case-insensitive
    assert _run(security.get_current_tenant(principal=principal)) == "lbusd"


def test_custom_claim_wins_over_domain_map(monkeypatch):
    monkeypatch.setattr(security.settings, "domain_tenant_map", {"lbschools.net": "lbusd"})
    principal = {"tenant_id": "ventura", "email": "staff@lbschools.net"}
    assert _run(security.get_current_tenant(principal=principal)) == "ventura"


def test_tenant_403s_when_identity_maps_to_no_district():
    """Private routes stay closed to a signed-in user with no district — unchanged behavior,
    and the reason public routes must NOT use this dependency."""
    with pytest.raises(HTTPException) as e:
        _run(security.get_current_tenant(principal={"email": "curious@nowhere.org"}))
    assert e.value.status_code == 403
    assert "curious@nowhere.org" in e.value.detail


def test_tenant_403_detail_is_generic_without_an_email():
    with pytest.raises(HTTPException) as e:
        _run(security.get_current_tenant(principal={"sub": "uid-9"}))
    assert "this identity" in e.value.detail


def test_unmapped_domain_403s(monkeypatch):
    monkeypatch.setattr(security.settings, "domain_tenant_map", {"lbschools.net": "lbusd"})
    with pytest.raises(HTTPException) as e:
        _run(security.get_current_tenant(principal={"email": "someone@elsewhere.com"}))
    assert e.value.status_code == 403


# --------------------------------------------------------------------------- #
# token verification (unchanged, pinned)
# --------------------------------------------------------------------------- #
def test_verify_500s_when_audience_is_not_configured(monkeypatch):
    monkeypatch.setattr(security.settings, "gcp_project", None)
    monkeypatch.setattr(security.settings, "google_oauth_audience", None)
    with pytest.raises(HTTPException) as e:
        security._verify_identity_token("any.jwt")
    assert e.value.status_code == 500


def test_verify_401s_on_invalid_token(monkeypatch):
    """A tampered/expired/wrong-audience token raises ValueError inside google-auth → 401.
    It must never fall through to 'authenticated'."""
    monkeypatch.setattr(security.settings, "google_oauth_audience", "proj")
    def boom(*a, **k):
        raise ValueError("Token expired")
    monkeypatch.setattr(security.id_token, "verify_firebase_token", boom)
    with pytest.raises(HTTPException) as e:
        security._verify_identity_token("bad.jwt")
    assert e.value.status_code == 401


def test_verify_401s_on_empty_claims(monkeypatch):
    monkeypatch.setattr(security.settings, "google_oauth_audience", "proj")
    monkeypatch.setattr(security.id_token, "verify_firebase_token", lambda *a, **k: None)
    with pytest.raises(HTTPException) as e:
        security._verify_identity_token("empty.jwt")
    assert e.value.status_code == 401
