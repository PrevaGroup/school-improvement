"""Resolve the caller's tenant from *verified* identity — the trust boundary (§10.3).

The client never sends its own tenant_id. It signs in via Google Cloud Identity
Platform (GCIP) and sends the resulting **Firebase/Identity Platform ID token** as
`Authorization: Bearer <token>`. We cryptographically verify that token here, then map
the verified identity to a tenant. The app binds that tenant with SET LOCAL (app/db.py),
and Postgres RLS does the rest. If verification were skipped or spoofed, a caller could
claim any district and read/write another district's private data — hence this is the
one seam that must be right.

Token type note: GCIP issues Firebase ID tokens (issuer
`https://securetoken.google.com/<project>`, audience = the GCP project id), which is why
we use `verify_firebase_token` — NOT `verify_oauth2_token` (that's for Google Sign-In
tokens from accounts.google.com). No `firebase-admin` dependency is needed to verify;
`google-auth` (already a dependency) does it. `firebase-admin`/the Admin API is only
needed to *provision* users and *set* the tenant custom claim, which is a one-time
onboarding action, not part of the request path.
"""
from __future__ import annotations

from fastapi import Header, HTTPException, status
from google.auth.transport import requests as g_requests
from google.oauth2 import id_token

from .config import settings

# Reused across requests; it caches Google's public signing certs internally.
_google_request = g_requests.Request()


async def get_current_tenant(
    authorization: str | None = Header(default=None),
    x_dev_tenant: str | None = Header(default=None),
) -> str:
    # DEV ONLY: trust a header so you can exercise RLS locally without OIDC.
    if settings.dev_mode and x_dev_tenant:
        return x_dev_tenant

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")

    token = authorization.split(" ", 1)[1]
    claims = _verify_identity_token(token)
    tenant = _tenant_for_claims(claims)
    if not tenant:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"no tenant mapped for {claims.get('email') or 'this identity'}",
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
