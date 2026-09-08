"""The rater identity hash, as the side that WRITES configuration rows computes it.

`scoring.rater.RaterIdentity.definition_hash` computes the same value for the side that reads
them. There are two copies because `registry` may not import `scoring` — modules integrate through
tables — and a copy without a check is drift with a delay on it, so
`tests/test_identity_hash_agrees.py` pins them together.

The delay would be short and the failure loud: `check_configuration` compares the stored hash to
the computed one, so a divergence means every configuration refuses to load. Loud in effect,
silent in cause, which is exactly the kind of thing worth a test.

This module exists so there is ONE registry-side copy rather than one per writer. Before it,
`seed_demo` held the only copy, and the promotion CLI would have made a third.
"""
from __future__ import annotations

import hashlib
import json

# `scoring.rater.STAGES`.
STAGES = ("fit", "evidence", "score", "band", "feedback")

# `scoring.escalate.Policy().as_dict()` — the RESOLVED default. Resolved rather than NULL, because
# a configuration that declares nothing and one that spells the defaults out are the same rater.
DEFAULT_ESCALATION = {"budget": 2,
                      "triggers": ["abstained", "no_verified_evidence"],
                      "escalated_effort": "high",
                      "terminal_action": "route_to_human"}

DEFAULT_LEVEL_METHOD = "category"
DEFAULT_LEVEL_THRESHOLD = 0.5


def resolve_models(model_id: str, stage_models: dict | None) -> dict:
    """Every stage's model. Absent stages fall back to `model_id`."""
    return {s: (stage_models or {}).get(s) or model_id for s in STAGES}


def definition_hash(*, model_id: str, effort: str | None, prompt_versions: dict,
                    normalization_version: str, escalation: dict | None = None,
                    stage_models: dict | None = None,
                    level_method: str = DEFAULT_LEVEL_METHOD,
                    level_threshold: float = DEFAULT_LEVEL_THRESHOLD) -> str:
    """What the rater IS, hashed. Not `config_id` — two configurations describing the same rater
    under different ids must collide, because that is how a replay proves it replayed the same
    thing."""
    return hashlib.sha256(json.dumps(
        {"models": resolve_models(model_id, stage_models),
         "effort": effort,
         "prompt_versions": prompt_versions,
         "normalization_version": normalization_version,
         "escalation": escalation or dict(DEFAULT_ESCALATION),
         "level_method": level_method,
         "level_threshold": float(level_threshold)},
        sort_keys=True, separators=(",", ":")).encode("utf8")).hexdigest()[:32]
