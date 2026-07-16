"""Tests for the trust boundary — `app.security`.

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
import time

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
    monkeypatch.setattr(security.settings, "allowed_email_domains", {"prevagroup.com"})
    # Empty map -> the ALLOWED_EMAIL_DOMAINS fallback applies (every domain requires
    # google.com). Provider-binding tests set this explicitly instead.
    monkeypatch.setattr(security.settings, "allowed_domain_providers", {})
    monkeypatch.setattr(security.settings, "session_max_age_days", 7.0)


def _claims(email="staff@prevagroup.com", verified=True, provider="google.com", **extra) -> dict:
    """Claims as Identity Platform actually issues them: `firebase.sign_in_provider` is
    server-set at sign-in (a real Google-provider token always carries "google.com"), and
    `auth_time` is the moment of the actual sign-in (fresh here; the session-age tests
    override it)."""
    return {
        "email": email,
        "email_verified": verified,
        "sub": "uid-1",
        "firebase": {"sign_in_provider": provider},
        "auth_time": time.time(),
        **extra,
    }


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
    verified(_claims(email="tester@prevagroup.com"))
    principal = _run(security.get_current_principal(authorization="Bearer good.jwt",
                                                    x_dev_tenant=None))
    assert principal["email"] == "tester@prevagroup.com"


def test_principal_accepts_a_signed_in_user_with_no_tenant(verified):
    """THE POINT OF §3.2. An invited tester has no district and no tenant claim. They must still
    authenticate successfully — everything served today is public data. Before the split, the
    only dependency available 403'd them, which would have locked out exactly the people this
    cutover is for.

    The allowlist decides WHO gets in; it does not hand out districts. Invited-but-tenant-less
    is the normal case for a tester, not an error."""
    verified(_claims(email="tester@prevagroup.com", sub="uid-2"))
    principal = _run(security.get_current_principal(authorization="Bearer good.jwt",
                                                    x_dev_tenant=None))
    assert principal["sub"] == "uid-2"          # authenticated
    assert "tenant_id" not in principal          # and deliberately tenant-less


def test_principal_scheme_match_is_case_insensitive(verified):
    verified(_claims(sub="uid-3"))
    assert _run(security.get_current_principal(authorization="bearer good.jwt",
                                               x_dev_tenant=None))["sub"] == "uid-3"


# --------------------------------------------------------------------------- #
# the invite gate — authentication is not invitation
#
# With a Google provider enabled, ANY Gmail account can get a valid token for this project.
# So token verification gates nothing on its own; this is what makes "signed in" mean
# "invited". It is also what stands between the open internet and the Anthropic balance
# behind /api/chat.
# --------------------------------------------------------------------------- #
def test_allowed_domain_gets_in(verified, monkeypatch):
    monkeypatch.setattr(security.settings, "allowed_email_domains",
                        {"prevagroup.com", "gatesfoundation.org"})
    verified(_claims(email="someone@gatesfoundation.org"))
    principal = _run(security.get_current_principal(authorization="Bearer good.jwt",
                                                    x_dev_tenant=None))
    assert principal["email"] == "someone@gatesfoundation.org"


def test_any_gmail_is_rejected(verified):
    """The whole point. A real, valid, Google-issued token from an uninvited account: 403."""
    verified(_claims(email="rando@gmail.com"))
    with pytest.raises(HTTPException) as e:
        _run(security.get_current_principal(authorization="Bearer good.jwt", x_dev_tenant=None))
    assert e.value.status_code == 403
    assert "invite list" in e.value.detail


def test_unverified_email_is_rejected_even_on_an_allowed_domain(verified):
    """THE BYPASS THIS CLOSES — do not delete.

    A token proves Identity Platform issued it; it does NOT prove the address inside belongs to the caller.
    Identity Platform's email/password provider lets anyone register any address unverified. Check the
    domain without checking `email_verified` and the allowlist is an honour system: sign up as
    anyone@prevagroup.com, never click a link, walk straight in.
    """
    verified(_claims(email="attacker@prevagroup.com", verified=False))
    with pytest.raises(HTTPException) as e:
        _run(security.get_current_principal(authorization="Bearer good.jwt", x_dev_tenant=None))
    assert e.value.status_code == 403
    assert "not verified" in e.value.detail


def test_empty_allowlist_admits_nobody(verified, monkeypatch):
    """FAILS CLOSED. An unset allowlist must never mean "everyone" — a deploy that forgets it
    should lock people out (loud, fixable), not open the door (silent, expensive)."""
    monkeypatch.setattr(security.settings, "allowed_email_domains", set())
    verified(_claims(email="staff@prevagroup.com"))
    with pytest.raises(HTTPException) as e:
        _run(security.get_current_principal(authorization="Bearer good.jwt", x_dev_tenant=None))
    assert e.value.status_code == 403


@pytest.mark.parametrize("email", [
    "evil@notprevagroup.com",        # suffix trick
    "evil@prevagroup.com.attack.io",  # domain-in-a-domain
    "evil@mail.prevagroup.com",       # subdomain — exact match only, by design
    "evil@sub.gatesfoundation.org",
])
def test_lookalike_domains_are_rejected(verified, monkeypatch, email):
    """Exact match only. Suffix/`endswith` matching is how allowlists get bypassed; the list is
    short enough to spell out, so spell it out."""
    monkeypatch.setattr(security.settings, "allowed_email_domains",
                        {"prevagroup.com", "gatesfoundation.org"})
    verified(_claims(email=email))
    with pytest.raises(HTTPException) as e:
        _run(security.get_current_principal(authorization="Bearer good.jwt", x_dev_tenant=None))
    assert e.value.status_code == 403


def test_domain_match_is_case_insensitive(verified):
    """Email domains are case-insensitive; the check must not be trickable by shouting."""
    verified(_claims(email="Staff@PrevaGroup.COM"))
    assert _run(security.get_current_principal(authorization="Bearer good.jwt",
                                               x_dev_tenant=None))["sub"] == "uid-1"


def test_identity_without_an_email_is_rejected(verified):
    """No email → no domain → no decision possible → deny. (auth_time is fresh so the
    freshness gate — which runs first — passes and the no-email 403 is what's tested.)"""
    verified({"sub": "uid-9", "email_verified": True, "auth_time": time.time()})
    with pytest.raises(HTTPException) as e:
        _run(security.get_current_principal(authorization="Bearer good.jwt", x_dev_tenant=None))
    assert e.value.status_code == 403
    assert "no email" in e.value.detail


# --------------------------------------------------------------------------- #
# Session freshness — a sign-in is a lease, not a deed
#
# ID tokens expire hourly but the SDK renews them against a refresh token that NEVER
# expires — so without this gate a session, once granted, lasts forever. `auth_time` is
# set by Identity Platform at the actual sign-in and rides through every refresh
# unchanged; aging it out is the only offboarding bound the app itself controls.
# --------------------------------------------------------------------------- #
def test_fresh_session_is_admitted(verified):
    verified(_claims(auth_time=time.time() - 3600))  # signed in an hour ago
    principal = _run(security.get_current_principal(authorization="Bearer good.jwt",
                                                    x_dev_tenant=None))
    assert principal["sub"] == "uid-1"


def test_stale_session_is_401_not_403(verified):
    """Eight days after sign-in: 401 — 'sign in again', which the SPA routes to the
    sign-in screen. NOT 403, which would read as 'not invited' and dead-end the user."""
    verified(_claims(auth_time=time.time() - 8 * 86400))
    with pytest.raises(HTTPException) as e:
        _run(security.get_current_principal(authorization="Bearer good.jwt", x_dev_tenant=None))
    assert e.value.status_code == 401
    assert "sign in again" in e.value.detail


def test_session_age_limit_is_configurable(verified, monkeypatch):
    """The 7 is policy, not code: SESSION_MAX_AGE_DAYS=1 must reject a 2-day-old sign-in."""
    monkeypatch.setattr(security.settings, "session_max_age_days", 1.0)
    verified(_claims(auth_time=time.time() - 2 * 86400))
    with pytest.raises(HTTPException) as e:
        _run(security.get_current_principal(authorization="Bearer good.jwt", x_dev_tenant=None))
    assert e.value.status_code == 401


def test_missing_auth_time_fails_closed(verified):
    """Every real Identity Platform token carries auth_time; its absence means the token is
    not what it claims. Can't decide -> deny, like everything on this path."""
    claims = _claims()
    del claims["auth_time"]
    verified(claims)
    with pytest.raises(HTTPException) as e:
        _run(security.get_current_principal(authorization="Bearer good.jwt", x_dev_tenant=None))
    assert e.value.status_code == 401
    assert "auth_time" in e.value.detail


def test_garbled_auth_time_fails_closed(verified):
    verified(_claims(auth_time="not-a-number"))
    with pytest.raises(HTTPException) as e:
        _run(security.get_current_principal(authorization="Bearer good.jwt", x_dev_tenant=None))
    assert e.value.status_code == 401


# --------------------------------------------------------------------------- #
# Provider ↔ domain binding — "access must ride an identity the employer can revoke"
#
# The constraint (Tim, pre-agreed): if someone leaves preva, they lose their preva identity,
# they lose access — Security 101. A PERSONAL Google account registered on a work address
# survives offboarding, so each domain is bound to its organization's own IdP and any other
# arrival path is rejected. `firebase.sign_in_provider` is set by Identity Platform at
# sign-in; a client cannot claim a provider it didn't come through.
# --------------------------------------------------------------------------- #
def test_personal_google_account_on_an_entra_domain_is_rejected(verified, monkeypatch):
    """THE CASE THE BINDING EXISTS FOR. gatesfoundation.org is an Entra shop: a Google
    account on a gates address is by definition not the employer's identity — it would
    survive offboarding. Rejected even though the domain is invited and the email verified."""
    monkeypatch.setattr(security.settings, "allowed_domain_providers",
                        {"prevagroup.com": "google.com",
                         "gatesfoundation.org": "microsoft.com"})
    verified(_claims(email="analyst@gatesfoundation.org", provider="google.com"))
    with pytest.raises(HTTPException) as e:
        _run(security.get_current_principal(authorization="Bearer good.jwt", x_dev_tenant=None))
    assert e.value.status_code == 403
    assert "organization's identity provider" in e.value.detail


def test_microsoft_arrival_on_a_google_domain_is_rejected(verified, monkeypatch):
    """The mirror image: preva is Workspace-managed; an Entra-flavored token bearing a preva
    address didn't come from preva's IdP."""
    monkeypatch.setattr(security.settings, "allowed_domain_providers",
                        {"prevagroup.com": "google.com"})
    verified(_claims(email="staff@prevagroup.com", provider="microsoft.com"))
    with pytest.raises(HTTPException) as e:
        _run(security.get_current_principal(authorization="Bearer good.jwt", x_dev_tenant=None))
    assert e.value.status_code == 403


def test_right_provider_for_each_domain_is_admitted(verified, monkeypatch):
    monkeypatch.setattr(security.settings, "allowed_domain_providers",
                        {"prevagroup.com": "google.com",
                         "gatesfoundation.org": "microsoft.com"})
    verified(_claims(email="analyst@gatesfoundation.org", provider="microsoft.com"))
    principal = _run(security.get_current_principal(authorization="Bearer good.jwt",
                                                    x_dev_tenant=None))
    assert principal["email"] == "analyst@gatesfoundation.org"


def test_missing_sign_in_provider_claim_fails_closed(verified):
    """A token with no firebase.sign_in_provider matches no required provider. Same rule as
    everything on this path: can't decide -> deny."""
    claims = _claims()
    del claims["firebase"]
    verified(claims)
    with pytest.raises(HTTPException) as e:
        _run(security.get_current_principal(authorization="Bearer good.jwt", x_dev_tenant=None))
    assert e.value.status_code == 403


def test_legacy_allowlist_still_admits_google_arrivals(verified):
    """Backward compatibility is load-bearing: a deploy still setting only
    ALLOWED_EMAIL_DOMAINS (today's prod) must keep admitting Google sign-ins — the fallback
    maps every listed domain to google.com. The autouse fixture models exactly that state."""
    verified(_claims())  # provider defaults to google.com
    principal = _run(security.get_current_principal(authorization="Bearer good.jwt",
                                                    x_dev_tenant=None))
    assert principal["sub"] == "uid-1"


def test_provider_comparison_is_case_insensitive(verified, monkeypatch):
    monkeypatch.setattr(security.settings, "allowed_domain_providers",
                        {"prevagroup.com": "google.com"})
    verified(_claims(provider="GOOGLE.COM"))
    assert _run(security.get_current_principal(authorization="Bearer good.jwt",
                                               x_dev_tenant=None))["sub"] == "uid-1"


def test_dev_principal_skips_the_allowlist(monkeypatch):
    """The dev path has no email to check; it returns before the gate. Still inert in prod —
    that's test_dev_header_is_ignored_in_production's job, not this one's."""
    monkeypatch.setattr(security.settings, "dev_mode", True)
    monkeypatch.setattr(security.settings, "allowed_email_domains", set())  # even empty
    principal = _run(security.get_current_principal(authorization=None, x_dev_tenant="lbusd"))
    assert principal["tenant_id"] == "lbusd"


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
