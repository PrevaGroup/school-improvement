"""Mint an Identity Platform ID token for the eval principal — the runner's key into /api/chat.

The chat endpoint accepts only Firebase/Identity Platform ID tokens (there is no
service-account path), so the eval runner signs in as a dedicated Identity Platform user whose
email is in ALLOWED_EMAILS and whose email is `EVAL_PRINCIPAL_EMAIL` (which makes the server
stamp its turns `source="eval"`). We exchange email+password for an ID token via the public
Identity Toolkit REST API — the same call a browser SDK makes.

Secrets come from the environment (set in Cloud Shell / the Cloud Run job), never committed:
    EVAL_PRINCIPAL_EMAIL      (also read by serving to stamp source=eval)
    EVAL_PRINCIPAL_PASSWORD
    IDENTITY_PLATFORM_API_KEY (the project's Web API key)
This module is pure HTTP — no serving import.
"""
from __future__ import annotations

import os

_SIGNIN = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"


def fetch_id_token(email: str, password: str, api_key: str, *, timeout: float = 15.0) -> str:
    """Exchange email+password for an Identity Platform ID token. Raises on any failure."""
    import httpx

    resp = httpx.post(
        _SIGNIN, params={"key": api_key},
        json={"email": email, "password": password, "returnSecureToken": True},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()["idToken"]


def eval_token_from_env() -> str:
    """Convenience for the runner: pull the three env values and mint a token."""
    email = os.environ.get("EVAL_PRINCIPAL_EMAIL", "").strip()
    password = os.environ.get("EVAL_PRINCIPAL_PASSWORD", "")
    api_key = os.environ.get("IDENTITY_PLATFORM_API_KEY", "").strip()
    missing = [k for k, v in [("EVAL_PRINCIPAL_EMAIL", email),
                              ("EVAL_PRINCIPAL_PASSWORD", password),
                              ("IDENTITY_PLATFORM_API_KEY", api_key)] if not v]
    if missing:
        raise SystemExit(f"eval auth: missing env {', '.join(missing)}")
    return fetch_id_token(email, password, api_key)
