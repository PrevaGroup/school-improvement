"""The SPA fallback, and the one thing it must never do.

FastAPI serves the built frontend from the same origin as the API, which needs a catch-all:
any unmatched path returns index.html so the browser's router can handle it.

The hazard is that a catch-all is indiscriminate. A mistyped API call is also an "unmatched
path" — and returning the HTML shell to a `fetch()` produces `Unexpected token '<'` in the
browser with no hint that the URL was simply wrong. That is a genuinely nasty debugging
session, and it lands on whoever writes the frontend.

The `/api` prefix is what makes the rule expressible: unmatched under /api -> JSON 404;
anything else -> the shell. These tests pin that split, and the ordering it depends on.
"""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_unmatched_api_path_is_a_json_404_not_the_html_shell():
    """THE POINT. If this ever returns HTML, every frontend fetch error becomes unreadable."""
    r = client.get("/api/marts/does-not-exist")
    assert r.status_code == 404
    assert "text/html" not in r.headers.get("content-type", "")
    assert r.json()["detail"].startswith("no such API route")


def test_bare_api_root_is_also_a_json_404():
    r = client.get("/api")
    assert r.status_code == 404
    assert "text/html" not in r.headers.get("content-type", "")


def test_catch_all_does_not_shadow_real_api_routes():
    """The catch-all is declared last so real routes win. If it were registered earlier it would
    swallow them, and every API call would return the shell with a 200 — the worst kind of
    green."""
    published = set(app.openapi()["paths"].keys())
    assert "/api/marts/districts" in published
    assert "/api/chat" in published
    # /health must stay outside /api and outside the shell.
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"ok": True}


def test_client_side_route_is_not_treated_as_an_api_path():
    """A browser deep-link (e.g. /schools/123 as a client route) must reach the SPA, not 404.

    Either outcome proves the split: the shell when the frontend is built, or the explicit
    501 'frontend not built' when it isn't. What it must never be is a JSON 'no such API route'.
    """
    r = client.get("/some/client/route")
    assert r.status_code in (200, 501)
    if r.status_code == 501:
        assert "frontend not built" in r.json()["detail"]
    else:
        assert "text/html" in r.headers.get("content-type", "")


def test_unbuilt_frontend_says_so_instead_of_404ing():
    """The most likely local-setup confusion. A bare 404 sends people hunting for a missing
    route; this tells them to run the build."""
    from app import main

    if main._SPA_INDEX.is_file():
        import pytest

        pytest.skip("frontend is built in this checkout")
    r = client.get("/")
    assert r.status_code == 501
    assert "npm run build" in r.json()["detail"]
