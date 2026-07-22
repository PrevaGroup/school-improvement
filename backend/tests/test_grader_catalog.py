"""Keep the served grader reference honest to the code.

`app/evals_view.py` (serving) can't import `evals.graders` at runtime — that would cross the
module boundary. So it carries a static GRADER_CATALOG, and this test — tooling, which IS
allowed to import across modules — asserts the catalog matches the real registry. Add a grader
to `graders.py` without documenting it here and this fails.
"""
from app.evals_view import GRADER_CATALOG, TIER_LABEL
from evals.graders import GRADERS


def test_catalog_covers_every_grader_including_the_judge():
    documented = {g["name"] for g in GRADER_CATALOG}
    # GRADERS holds the deterministic graders; the judge is dispatched separately in run_graders.
    actual = set(GRADERS) | {"usefulness_judge"}
    assert documented == actual, (
        f"grader reference drifted from graders.py — "
        f"undocumented: {sorted(actual - documented)}, stale: {sorted(documented - actual)}"
    )


def test_catalog_tiers_are_known():
    assert all(g["tier"] in TIER_LABEL for g in GRADER_CATALOG)
