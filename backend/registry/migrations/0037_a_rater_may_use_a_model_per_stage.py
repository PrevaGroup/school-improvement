"""a scoring configuration may name a model per stage

`model_id` was one string, so the rater was one model everywhere. That made a mixed harness
unrepresentable — which was a good accident, because it meant nobody could do it silently, and a
bad limitation, because the stages carry genuinely different risk.

## Why the stages are not equally risky

Stage C proposes spans, and every span it proposes is then verified as an exact substring of the
paper. A weaker model's failure there is caught mechanically: it costs verified spans, and a
criterion with no verified evidence ABSTAINS rather than producing a wrong number.

Stage D assigns a level, and nothing downstream checks it.

Those two do not deserve the same model. Stage C is also where the tokens are — it carries the
whole essay in its prompt, once per trait, and the first corpus wave ran 5.66M input tokens
against 1.31M output.

## An override map, not four required fields

`model_id` stays the answer to "what model is this rater", and a single-model configuration does
not have to say the same string four times. `stage_models` names only the exceptions.

The RESOLVED map is what enters `definition_hash`, so a configuration that declares nothing and
one that declares the same model at every stage are the same rater and collide. Same reasoning as
the escalation policy in 0036: what is hashed is what the rater DOES, not how verbosely it was
written down.

## The hash changes again, so the rows are re-stamped again

`definition_hash` now covers `models` (the resolved map) where it covered `model_id`. Every stored
hash therefore changes, and `check_configuration` compares them, so this re-stamps — same shape as
0036 and for the same reason.

Nothing is re-scored. A rater that named one model still named one model; the record now says so
per stage.

Revision ID: 0037
Revises: 0036
"""
from __future__ import annotations

import hashlib
import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None

# Frozen at this revision, for the same reason as 0036: a migration must reproduce the hash as of
# its own point in history, not as of whenever it is replayed.
STAGES = ("fit", "evidence", "score", "feedback")
_DEFAULT_POLICY = {"budget": 2,
                   "triggers": ["abstained", "no_verified_evidence"],
                   "escalated_effort": "high",
                   "terminal_action": "route_to_human"}


def _resolve_policy(raw):
    if not raw:
        return dict(_DEFAULT_POLICY)
    return {"budget": int(raw.get("budget", _DEFAULT_POLICY["budget"])),
            "triggers": list(raw.get("triggers") or _DEFAULT_POLICY["triggers"]),
            "escalated_effort": str(raw.get("escalated_effort")
                                    or _DEFAULT_POLICY["escalated_effort"]),
            "terminal_action": str(raw.get("terminal_action")
                                   or _DEFAULT_POLICY["terminal_action"])}


def _models(model_id, stage_models):
    return {s: (stage_models or {}).get(s) or model_id for s in STAGES}


def _stamp(conn, *, with_stages: bool) -> None:
    cols = "config_id, model_id, effort, prompt_versions, normalization_version, escalation"
    if with_stages:
        cols += ", stage_models"
    for r in conn.execute(sa.text(
            f"SELECT {cols} FROM registry_scoring_configuration")).mappings().all():
        body = {"effort": r["effort"], "prompt_versions": r["prompt_versions"],
                "normalization_version": r["normalization_version"],
                "escalation": _resolve_policy(r["escalation"])}
        body |= ({"models": _models(r["model_id"], r["stage_models"])} if with_stages
                 else {"model_id": r["model_id"]})
        h = hashlib.sha256(json.dumps(body, sort_keys=True,
                                      separators=(",", ":")).encode("utf8")).hexdigest()[:32]
        conn.execute(sa.text("""UPDATE registry_scoring_configuration
                                   SET definition_hash = :h WHERE config_id = :c"""),
                     {"h": h, "c": r["config_id"]})


def upgrade() -> None:
    op.add_column("registry_scoring_configuration",
                  sa.Column("stage_models", postgresql.JSONB()))
    # A stage that does not exist is a model nobody calls, and nothing would say so. The valid
    # stages are checked in `scoring/rater.py` too; this is the copy the database can enforce.
    op.create_check_constraint(
        "stage_models_names_real_stages", "registry_scoring_configuration",
        "stage_models IS NULL OR ("
        " SELECT bool_and(k IN ('fit','evidence','score','feedback'))"
        " FROM jsonb_object_keys(stage_models) AS k)")
    _stamp(op.get_bind(), with_stages=True)


def downgrade() -> None:
    # Re-stamp WITHOUT the per-stage map first, while the column still exists, so a downgraded
    # database matches a downgraded codebase.
    _stamp(op.get_bind(), with_stages=False)
    op.drop_constraint("ck_registry_scoring_configuration_stage_models_names_real_stages",
                       "registry_scoring_configuration")
    op.drop_column("registry_scoring_configuration", "stage_models")
