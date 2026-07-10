"""Resolve the caller's tenant from *verified* identity — the trust boundary (§10.3).

The client never sends its own tenant_id. In prod we verify a Google ID token and
map the identity to a tenant; the app then binds it via SET LOCAL (app/db.py).
"""
from __future__ import annotations

from fastapi import Header, HTTPException, status

from .config import settings


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
    email = _verify_google_id_token(token)
    tenant = _tenant_for_identity(email)
    if not tenant:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"no tenant mapped for {email}")
    return tenant


def _verify_google_id_token(token: str) -> str:
    """Verify a Google-issued ID token and return the verified email.

    Wire-up (one function to implement for prod):
        from google.oauth2 import id_token
        from google.auth.transport import requests as g_requests
        claims = id_token.verify_oauth2_token(
            token, g_requests.Request(), audience=settings.google_oauth_audience
        )
        return claims["email"]
    Raise on any verification failure — never fall through to a default tenant.
    """
    raise NotImplementedError(
        "Implement Google ID-token verification (google-auth) before enabling prod."
    )


def _tenant_for_identity(email: str) -> str | None:
    """Map a verified identity to a tenant_id.

    Typically a lookup keyed on the hosted domain (the Google Workspace `hd` claim,
    e.g. lbschools.net -> 'lbusd') or an explicit user->tenant table. Keep this
    server-side; it is the only place identity becomes tenancy.
    """
    return None
