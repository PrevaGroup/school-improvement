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
    # NOT under /api — an unauthenticated liveness probe, not an API route. It must stay
    # outside the prefix, which now carries the sign-in dependency.
    "/health": {"GET"},
    # The invite probe: the SPA's AuthGate calls it after sign-in, before loading the app.
    "/api/me": {"GET"},
    # Admin-status hint: any signed-in user may ask whether they're an admin (Workspace group).
    "/api/admin/status": {"GET"},
    # --- everything below is under /api (see app/main.py; docs/GO_LIVE_PLAN.md §3.1c) ---
    "/api/schools": {"GET"},
    "/api/schools/{school_id}/metrics": {"GET"},
    # --- serving: plan marts ---
    "/api/marts/attendance-plans": {"GET"},
    "/api/marts/attendance-diagnostic": {"GET"},
    "/api/marts/subgroup-metrics": {"GET"},
    "/api/marts/districts": {"GET"},
    "/api/marts/workspace-defaults": {"GET"},
    # school-detail retired 2026-07-16: the panel reads POST /api/marts/workspace now
    # (agentic-workspace-and-sessions.md phase 4), and nothing else ever consumed it.
    # --- serving: peer endpoints (likeschools is engine-only; these serve its tables) ---
    "/api/marts/like-schools": {"GET"},
    "/api/marts/peer-benchmark": {"GET"},
    # --- serving: Claude-controlled workspace (agentic-workspace-and-sessions.md) ---
    # POST because the body is a nested WorkspaceSpec; used for session restore.
    "/api/marts/workspace": {"POST"},
    # --- sip ---
    "/api/plans/extract": {"POST"},
    "/api/plans/load": {"POST"},
    # --- serving: chat ---
    "/api/chat": {"POST"},
    # --- serving: read-only admin eval view over the trace store ---
    "/api/evals/summary": {"GET"},
    "/api/evals/traces": {"GET"},
    # --- serving: the loop's later stages (cases -> runs -> per-case results) ---
    "/api/evals/cases": {"GET"},
    "/api/evals/runs": {"GET"},
    "/api/evals/runs/{run_id}/results": {"GET"},
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
    """The URLs the SPA actually fetches (frontend/src/App.tsx + components/Chat.tsx).

    Called out separately from the full inventory so the module split's blast radius on the UI
    is explicit: these five are what breaks the app if a move renames them.

    Keep this list in step with the `api.get`/`api.post` calls in frontend/src — it is
    hand-maintained, so a NEW call is invisible to it. It still earns its keep for the renames
    it does catch: when /api landed, this test failed loudly and correctly, because the URLs the
    UI depended on had moved (the UI moved with them in that same commit).
    """
    published = _published()
    for path in ("/api/marts/attendance-diagnostic", "/api/marts/districts",
                 "/api/marts/like-schools", "/api/marts/workspace", "/api/chat"):
        assert path in published, f"{path} is fetched by the UI but is no longer published"
