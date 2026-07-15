"""Resolve the caller's identity — and, separately, their tenant. The trust boundary (§10.3).

The client never sends its own tenant_id. It signs in via Google Cloud Identity
Platform (GCIP) and sends the resulting **Firebase/Identity Platform ID token** as
`Authorization: Bearer <token>`. We cryptographically verify that token here, then map
the verified identity to a tenant. The app binds that tenant with SET LOCAL (app/db.py),
and Postgres RLS does the rest. If verification were skipped or spoofed, a caller could
claim any district and read/write another district's private data — hence this is the
one seam that must be right.

**Two questions, two dependencies** (ARCHITECTURE.md §1). They are different questions, and
conflating them breaks the app in opposite directions:

  get_current_principal  "who are you?"        Verify the token, return claims. Requires NO
                                               tenant. Public /api routes use this. It is what
                                               makes public exposure safe.
  get_current_tenant     "what may you see?"   Verify, then map claims -> tenant_id; 403 if
                                               unmapped. Guards /plans and future private
                                               routes.

Gating *public* data on get_current_tenant would 403 every signed-in user who isn't district
staff — i.e. every outside tester, since everything served today is public. Gating *private*
data on get_current_principal would serve one district's plans to another. Pick deliberately.

Token type note: GCIP issues Firebase ID tokens (issuer
`https://securetoken.google.com/<project>`, audience = the GCP project id), which is why
we use `verify_firebase_token` — NOT `verify_oauth2_token` (that's for Google Sign-In
tokens from accounts.google.com). No `firebase-admin` dependency is needed to verify;
`google-auth` (already a dependency) does it. `firebase-admin`/the Admin API is only
needed to *provision* users and *set* the tenant custom claim, which is a one-time
onboarding action, not part of the request path.
"""
from __future__ import annotations

import os

from fastapi import Depends, Header, HTTPException, status
from google.auth.transport import requests as g_requests
from google.oauth2 import id_token

from .config import settings

# Reused across requests; it caches Google's public signing certs internally.
_google_request = g_requests.Request()


# --------------------------------------------------------------------------- #
# DEV_MODE containment
#
# `X-Dev-Tenant` is an UNVERIFIED header: whatever it claims, you become. Behind the Cloud Run
# IAM gate that's a harmless convenience. On a publicly reachable service it is tenant
# impersonation by request header — any caller reads any district. It is the worst outcome
# available when the IAM gate opens and this service becomes publicly reachable.
#
# `DEV_MODE=false` in the deploy command is NOT sufficient: it is one hurried `--set-env-vars`
# edit away from true, and nothing would complain. So the dev path is gated on the *environment*
# — structurally — not on the flag alone.
# --------------------------------------------------------------------------- #
def _production_signals() -> tuple[str, ...]:
    """Evidence that this is a real deployment. Cheap, no I/O — safe to call per-request.

    K_SERVICE is injected by Cloud Run itself, so an external caller cannot unset it.
    INSTANCE_CONNECTION_NAME means we are pointed at a real Cloud SQL instance.

    **Accepted edge — the assumption this rests on.** These signals detect the *environment*,
    not the *image*. A production-built image run somewhere that is not Cloud Run (a laptop, a
    plain VM, a local container) has no K_SERVICE, so DEV_MODE could activate there. That is
    accepted **because Cloud Run is the only production target**: anywhere without K_SERVICE is,
    by definition of this deployment, not production. If that ever stops being true — a second
    runtime, a VM, GKE — this function is the thing that must change first, because the dev
    path's containment is only as good as this list.

    Note the direction of the failure: a missing signal makes dev mode *silently off in prod*
    only if it is somewhere we don't deploy; on Cloud Run K_SERVICE is always present. The
    dangerous inverse — dev mode silently ON in prod — requires this list to be wrong about
    Cloud Run specifically, which the import-time assert in app/main.py would also catch.
    """
    found = []
    if os.getenv("K_SERVICE"):
        found.append("K_SERVICE")
    if settings.instance_connection_name:
        found.append("INSTANCE_CONNECTION_NAME")
    return tuple(found)


def dev_mode_active() -> bool:
    """True only when DEV_MODE is on AND nothing indicates production. Fails closed."""
    return settings.dev_mode and not _production_signals()


def assert_dev_mode_not_in_production() -> None:
    """Refuse to boot with DEV_MODE on in a production-shaped environment.

    Called at import of app/main.py, so a misconfiguration is a loud startup crash (a failed
    deploy) rather than a silent hole nobody inspects. `dev_mode_active()` already fails closed
    by itself; this exists so the mistake is *impossible to miss* rather than merely inert.
    """
    if settings.dev_mode and (signals := _production_signals()):
        raise RuntimeError(
            f"DEV_MODE=true, but this looks like production ({', '.join(signals)}). "
            "The X-Dev-Tenant header would let any caller impersonate any district. "
            "Refusing to start. Set DEV_MODE=false."
        )


async def get_current_principal(
    authorization: str | None = Header(default=None),
    x_dev_tenant: str | None = Header(default=None),
) -> dict:
    """Verify the caller's identity and return their claims. Does NOT require a tenant.

    The gate for public /api routes: it proves *someone signed in*, which is the whole reason
    the service can be exposed. It deliberately says nothing about tenancy.
    """
    # DEV ONLY: trust a header so you can exercise RLS locally without OIDC. Inert in any
    # production-shaped environment — see the DEV_MODE containment note above.
    if dev_mode_active() and x_dev_tenant:
        return {settings.tenant_claim: x_dev_tenant, "email": None, "dev_mode": True}

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")

    token = authorization.split(" ", 1)[1]
    return _verify_identity_token(token)


async def get_current_tenant(principal: dict = Depends(get_current_principal)) -> str:
    """Map a *verified* identity to its tenant. 403 when it maps to no district.

    Caller contract is unchanged: routes still write `Depends(get_current_tenant)` and still
    receive a `str`. Only the verification half moved out, so public routes can reuse it
    without inheriting this 403.
    """
    tenant = _tenant_for_claims(principal)
    if not tenant:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"no tenant mapped for {principal.get('email') or 'this identity'}",
        )
    return tenant


def _verify_identity_token(token: str) -> dict:
    """Verify a GCIP/Firebase ID token and return its claims.

    Checks signature, issuer, audience, and expiry against Google's certs. Any failure
    (tampered, expired, wrong audience) becomes a 401 — never falls through.
    """
    audience = settings.gcip_audience
    if not audience:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "auth not configured: set GCP_PROJECT (the GCIP token audience)",
        )
    try:
        claims = id_token.verify_firebase_token(token, _google_request, audience=audience)
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid identity token")
    if not claims:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid identity token")
    return claims


def _tenant_for_claims(claims: dict) -> str | None:
    """Map a verified identity to a tenant_id.

    Primary: a custom claim set on the user at provisioning (`settings.tenant_claim`),
    so the token itself carries the — verified, server-set — tenant. Fallback: map the
    email's hosted domain via `settings.domain_tenant_map` (e.g. lbschools.net -> lbusd).
    This is the only place identity becomes tenancy; keep it server-side.
    """
    claimed = claims.get(settings.tenant_claim)
    if claimed:
        return str(claimed)

    email = claims.get("email")
    if email and "@" in email:
        domain = email.rsplit("@", 1)[1].lower()
        return settings.domain_tenant_map.get(domain)
    return None
