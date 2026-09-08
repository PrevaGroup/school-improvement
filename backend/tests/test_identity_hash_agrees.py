"""The rater identity hash is computed in two modules, and they must not drift.

`scoring.rater.RaterIdentity.definition_hash` computes it for the rater that scores. Whoever
writes a configuration row has to store the same value, and today that is `registry.seed_demo`.
`registry` may not import `scoring` — modules integrate through tables — so the computation is
duplicated, and duplication without a check is drift with a delay on it.

A divergence is not subtle in effect: `check_configuration` now compares the stored hash against
the computed one, so any seeded configuration would refuse to load. It would be subtle in CAUSE,
which is what this test is for.
"""
from __future__ import annotations

import hashlib
import json

from registry import seed_demo
from scoring.escalate import Policy
from scoring.rater import STAGES, RaterIdentity


def test_the_seed_and_the_rater_hash_the_same_parts():
    prompt_versions = {"evidence": {"version": "ev.3", "sha256": "abc123"},
                       "score": {"version": "sc.2", "sha256": "def456"}}

    seeded = hashlib.sha256(
        json.dumps({"models": {stage: seed_demo.MODEL_ID for stage in STAGES},
                    "effort": seed_demo.EFFORT,
                    "prompt_versions": prompt_versions, "normalization_version": "1",
                    "escalation": seed_demo.DEFAULT_ESCALATION,
                    "level_method": "category", "level_threshold": 0.5},
                   sort_keys=True, separators=(",", ":")).encode("utf8")).hexdigest()[:32]

    rater = RaterIdentity(config_id="cfg", model_id=seed_demo.MODEL_ID, effort=seed_demo.EFFORT,
                          prompt_versions=prompt_versions, normalization_version="1",
                          escalation=Policy().as_dict()).definition_hash

    assert seeded == rater


def test_the_seeds_stage_list_is_the_real_stage_list():
    """`seed_demo.STAGES` is retyped by hand across the import boundary, like the policy. A stage
    added to the rater and not here silently drops out of every seeded configuration's hash."""
    assert tuple(seed_demo.STAGES) == tuple(STAGES)


def test_the_seeds_default_policy_is_the_real_default_policy():
    """`seed_demo.DEFAULT_ESCALATION` is `Policy().as_dict()` retyped by hand, because of the
    import boundary. If the real default changes and this copy does not, every seeded
    configuration's stored hash becomes wrong."""
    assert seed_demo.DEFAULT_ESCALATION == Policy().as_dict()
