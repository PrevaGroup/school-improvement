"""Reverse proxy for Firebase's reserved `/__/*` namespace — the custom-authDomain fix.

Why: with `authDomain: "sip.prevagroup.com"` in the SPA (frontend/src/firebase.ts), the
Google account-chooser reads "to continue to sip.prevagroup.com" instead of the project's
firebaseapp.com domain — Google shows the OAuth redirect's domain while the brand is
unverified, so the fix is to make that domain OURS. It also ends the auth handler's life as
a third-party origin, which is the root of the Safari/ITP popup flakiness firebase.ts
documents. This is Firebase's documented pattern: serve `/__/auth/*` (plus
`/__/firebase/init.json`) from your own domain by reverse-proxying to
`<project>.firebaseapp.com`, and add `https://<your-domain>/__/auth/handler` as an
authorized redirect URI on the OAuth client (console step, recorded in DEPLOY.md).

Scope, deliberately narrow:
- Proxies ONLY the fixed origin `https://<gcp_project>.firebaseapp.com`, ONLY under `/__/`
  (Firebase's reserved namespace, which no SPA route or API route may ever use). This is
  not an open proxy — the caller controls the path suffix, never the host.
- UNGATED by design: it serves the sign-in flow to users who by definition have no token
  yet. Same access class as /health and the SPA shell, and mounted the same way (main.py,
  without the /api sign-in dependency).
- `include_in_schema=False`: infrastructure, not published API surface — it does not
  belong in the frozen route contract (tests/test_route_contract.py), same as `/`.
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException, Request, Response, status

from .config import settings

router = APIRouter()

# Module-level client: connection reuse across sign-ins. 10s covers Google's static
# handler content with room to spare; a hung upstream must not hold requests forever.
_client = httpx.AsyncClient(timeout=10.0)

# Request headers worth forwarding. Everything else (host, authorization, x-forwarded-*)
# is either wrong for the upstream or none of its business.
_FORWARD_REQUEST_HEADERS = frozenset(
    {"accept", "accept-language", "content-type", "cookie", "referer", "user-agent"}
)
# Response headers preserved verbatim so browser caching of the handler's static JS works.
_FORWARD_RESPONSE_HEADERS = ("cache-control", "etag", "expires", "vary")


@router.api_route("/__/{path:path}", methods=["GET", "POST"], include_in_schema=False)
async def firebase_reserved_namespace(path: str, request: Request) -> Response:
    if not settings.gcp_project:
        # Bare local dev without GCP_PROJECT: nothing to proxy to. Say so rather than 404 —
        # sign-in against a local backend needs the deployed handler or DEV_MODE anyway.
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "auth proxy unavailable: GCP_PROJECT is not set",
        )
    upstream = await _client.request(
        request.method,
        f"https://{settings.gcp_project}.firebaseapp.com/__/{path}",
        params=request.query_params,
        content=await request.body(),
        headers={
            k: v for k, v in request.headers.items() if k.lower() in _FORWARD_REQUEST_HEADERS
        },
    )
    response = Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type"),
    )
    for header in _FORWARD_RESPONSE_HEADERS:
        if header in upstream.headers:
            response.headers[header] = upstream.headers[header]
    for cookie in upstream.headers.get_list("set-cookie"):
        response.headers.append("set-cookie", cookie)
    return response
