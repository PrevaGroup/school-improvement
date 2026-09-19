"""a configuration declares how stage D turns evidence into a band

The first anchor wave came back compressed: our scores spanned 0.87 where the humans spanned 5 —
17% of their scale — with ZERO 6s awarded across 334 papers.

`measurement.span_diagnostic` then ruled out the cheap explanation. Verified evidence rises
monotonically with the human score (588 characters at human 1, 909 at human 6), and in 9 of 10
traits that evidence predicts the HUMAN score better than our own score does. The signal arrives
and is lost at the moment it becomes a category.

So a configuration may now declare which stage-D form it is:

    category    — one call naming a band. Every score written before this.
    cumulative  — one call per band asking whether the writing meets or exceeds it, with the band
                  computed from the answers by `scoring.score.level_from`.

The model is never asked to pick a band under the second form. There is no middle to retreat to
in a question that has no middle.

## Why it is on the configuration and part of the rater

It is the largest difference between two raters this system can express — larger than a model
change. Two configurations differing only in this produce entirely different bodies of scores, so
`definition_hash` covers it and MFRM holds them apart as the different raters they are. That is
also what makes the comparison publishable: the old and new forms can be estimated on the same
anchor papers and placed on one scale.

## `level_threshold`

The probability a band must clear, default 0.5. Hashed even under `category`, which ignores it: a
rater is its parameters, and a hash that omits a field because the current method does not read it
stops describing the rater the moment the method changes.

It is a candidate for fitting on the calibration partition later — a single monotone correction
for spread and severity, which is a very different thing from learning a free-form map onto the
human scores. Not fitted here, because nothing has been scored with this method yet.

## The hash changes again

Same as 0036 and 0037: the parts changed, so every stored hash is re-stamped. `prompt_versions`
is untouched — `fingerprint()` returns only the stage-D prompt a rater actually uses, so a
category configuration still fingerprints exactly as it did.

Revision ID: 0038
Revises: 0037
"""
from __future__ import annotations

import hashlib
import json

import sqlalchemy as sa
from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None

STAGES = ("fit", "evidence", "score", "band", "feedback")
_DEFAULT_POLICY = {"budget": 2, "triggers": ["abstained", "no_verified_evidence"],
                   "escalated_effort": "high", "terminal_action": "route_to_human"}


def _resolve_policy(raw):
    if not raw:
        return dict(_DEFAULT_POLICY)
    return {"budget": int(raw.get("budget", _DEFAULT_POLICY["budget"])),
            "triggers": list(raw.get("triggers") or _DEFAULT_POLICY["triggers"]),
            "escalated_effort": str(raw.get("escalated_effort")
                                    or _DEFAULT_POLICY["escalated_effort"]),
            "terminal_action": str(raw.get("terminal_action")
                                   or _DEFAULT_POLICY["terminal_action"])}


def _stamp(conn, *, with_level: bool) -> None:
    cols = ("config_id, model_id, effort, prompt_versions, normalization_version, escalation, "
            "stage_models")
    if with_level:
        cols += ", level_method, level_threshold"
    for r in conn.execute(sa.text(
            f"SELECT {cols} FROM registry_scoring_configuration")).mappings().all():
        body = {"models": {s: (r["stage_models"] or {}).get(s) or r["model_id"] for s in STAGES},
                "effort": r["effort"], "prompt_versions": r["prompt_versions"],
                "normalization_version": r["normalization_version"],
                "escalation": _resolve_policy(r["escalation"])}
        if with_level:
            body |= {"level_method": r["level_method"] or "category",
                     "level_threshold": float(r["level_threshold"]
                                              if r["level_threshold"] is not None else 0.5)}
        h = hashlib.sha256(json.dumps(body, sort_keys=True,
                                      separators=(",", ":")).encode("utf8")).hexdigest()[:32]
        conn.execute(sa.text("""UPDATE registry_scoring_configuration
                                   SET definition_hash = :h WHERE config_id = :c"""),
                     {"h": h, "c": r["config_id"]})


def upgrade() -> None:
    op.add_column("registry_scoring_configuration",
                  sa.Column("level_method", sa.Text(), nullable=False,
                            server_default="category"))
    op.add_column("registry_scoring_configuration",
                  sa.Column("level_threshold", sa.Numeric(), nullable=False,
                            server_default="0.5"))
    op.create_check_constraint(
        "level_method_is_known", "registry_scoring_configuration",
        "level_method IN ('category','cumulative')")
    # Strictly between 0 and 1. At 0 every band clears and every paper is a 6; at 1 none does and
    # every paper is a 1. Both are configurations that score without judging.
    op.create_check_constraint(
        "level_threshold_is_a_probability", "registry_scoring_configuration",
        "level_threshold > 0 AND level_threshold < 1")
    _stamp(op.get_bind(), with_level=True)


def downgrade() -> None:
    _stamp(op.get_bind(), with_level=False)
    op.drop_constraint("ck_registry_scoring_configuration_level_threshold_is_a_probability",
                       "registry_scoring_configuration")
    op.drop_constraint("ck_registry_scoring_configuration_level_method_is_known",
                       "registry_scoring_configuration")
    op.drop_column("registry_scoring_configuration", "level_threshold")
    op.drop_column("registry_scoring_configuration", "level_method")
