"""Freeze the published HTTP surface.

The backend is mid-reorg: `app/marts.py` is being split along the module line into
plan_marts and likeschools (docs/MODULES.md). Those moves must be invisible from the
outside — the frontend is being rewritten in parallel against these exact URLs, and a
refactor that silently renames or drops one would break it with no test failure.

So this pins the whole inventory rather than a sample. It reads `app.openapi()`, which
is the contract FastAPI actually publishes (this FastAPI keeps included routers lazy,
so `app.routes` does NOT flatten them — it reports only main.py's own routes, which is
why enumerating that instead would silently pass while checking almost nothing).

If this fails you either (a) moved code and broke a URL — fix the move, not the test,
or (b) deliberately added/changed an endpoint — update EXPECTED in the same commit, so
the contract change is visible in review.

`/` is absent by design: it's `include_in_schema=False` (serves the UI's index.html).
"""
from app.main import app

# path -> the HTTP methods it answers.
EXPECTED: dict[str, set[str]] = {
    "/health": {"GET"},
    "/schools": {"GET"},
    "/schools/{school_id}/metrics": {"GET"},
    # --- plan_marts ---
    "/marts/attendance-plans": {"GET"},
    "/marts/attendance-diagnostic": {"GET"},
    "/marts/subgroup-metrics": {"GET"},
    "/marts/districts": {"GET"},
    "/marts/school-detail": {"GET"},
    # --- likeschools (currently living in app/marts.py; moving to backend/likeschools/) ---
    "/marts/like-schools": {"GET"},
    "/marts/peer-benchmark": {"GET"},
    # --- sip ---
    "/plans/extract": {"POST"},
    "/plans/load": {"POST"},
    # --- chat ---
    "/chat": {"POST"},
}


def _published() -> dict[str, set[str]]:
    return {
        path: {method.upper() for method in operations}
        for path, operations in app.openapi()["paths"].items()
    }


def test_no_endpoint_is_added_or_removed():
    published = _published()
    assert set(published) == set(EXPECTED), (
        f"HTTP surface changed.\n"
        f"  added:   {sorted(set(published) - set(EXPECTED))}\n"
        f"  removed: {sorted(set(EXPECTED) - set(published))}\n"
        "If a refactor moved code, restore the URL. If the change is deliberate, "
        "update EXPECTED in tests/test_route_contract.py in the same commit."
    )


def test_methods_are_unchanged():
    published = _published()
    mismatched = {
        path: {"expected": sorted(methods), "published": sorted(published[path])}
        for path, methods in EXPECTED.items()
        if path in published and published[path] != methods
    }
    assert not mismatched, f"HTTP methods changed: {mismatched}"


def test_frontend_endpoints_survive_the_module_split():
    """The URLs backend/app/static/index.html actually fetches.

    Called out separately from the full inventory so the split's blast radius on the UI
    is explicit: these four are what breaks the app if a module move renames them.
    """
    published = _published()
    for path in ("/marts/attendance-diagnostic", "/marts/districts",
                 "/marts/like-schools", "/marts/school-detail", "/chat"):
        assert path in published, f"{path} is fetched by the UI but is no longer published"
