"""Promote a scoring configuration — that is, publish a rater.

    python -m scoring.prompts --method cumulative \\
      | python -m registry.promote_configuration --config-key writing-cumulative \\
          --model-id claude-opus-5 --effort high --level-method cumulative \\
          --promoted-by you@example.org --rationale "why this rater exists"

## Why this exists rather than an INSERT somebody types

A configuration IS a rater. Every score points at one, severity is estimated per rater, and a
promotion is the moment somebody becomes answerable for a body of scores. The database already
refuses an `active` row without `promoted_by` and `rationale`; hand-written SQL is how those end
up as "me" and "testing".

It also computes `definition_hash`, which nobody should be doing by hand: `check_configuration`
compares the stored value against the parts, so a hash typed in wrong makes the configuration
refuse to load with an error about a rater being edited after promotion.

## The fingerprint arrives on stdin

`registry` may not import `scoring`, so it cannot compute the prompt fingerprint itself. It comes
from `python -m scoring.prompts --method <method>` through a pipe — the same seam as
`corpus.draw_anchor | scoring.bind_corpus`, and better operationally too, because what is about to
be stamped can be looked at before anything is written.

The METHOD must match: a cumulative rater fingerprints the band prompt and a category rater
fingerprints the score prompt, and a configuration stamped with the wrong one is refused by
`check_configuration` at the first paper rather than here. So this checks it up front.

## One active configuration per key

Enforced by a unique index. A second active row under the same key is an ambiguous rater, and an
ambiguous rater cannot have a severity estimated. To replace a live rater, pass `--supersede`,
which moves the current one to `superseded` in the same transaction. To run two raters side by
side — which is the point of a calibration comparison — give them different keys.
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone

from sqlalchemy import text

from ._db import engine
from .config_hash import (DEFAULT_ESCALATION, DEFAULT_LEVEL_THRESHOLD, definition_hash,
                          resolve_models)

_ACTIVE = text("""
    SELECT config_id, version FROM registry_scoring_configuration
     WHERE config_key = :k AND status = 'active'
""")

_MAX_VERSION = text("""
    SELECT COALESCE(MAX(version), 0) FROM registry_scoring_configuration WHERE config_key = :k
""")

_INSERT = text("""
    INSERT INTO registry_scoring_configuration
        (config_id, config_key, version, model_id, effort, prompt_versions,
         normalization_version, escalation, stage_models, level_method, level_threshold,
         definition_hash, status, supersedes_config_id, promoted_at, promoted_by,
         second_approver, rationale)
    VALUES
        (:config_id, :config_key, :version, :model_id, :effort, CAST(:prompt_versions AS jsonb),
         :normalization_version, CAST(:escalation AS jsonb), CAST(:stage_models AS jsonb),
         :level_method, :level_threshold,
         :definition_hash, 'active', :supersedes, :promoted_at, :promoted_by,
         :second_approver, :rationale)
""")

_SUPERSEDE = text("""
    UPDATE registry_scoring_configuration SET status = 'superseded' WHERE config_id = :c
""")


def promote(*, config_key: str, model_id: str, effort: str | None, prompt_versions: dict,
            normalization_version: str, escalation: dict | None, stage_models: dict | None,
            level_method: str, level_threshold: float, promoted_by: str, rationale: str,
            second_approver: str | None = None, supersede: bool = False,
            dry_run: bool = False) -> dict:
    eng = engine()
    with eng.begin() as conn:
        active = conn.execute(_ACTIVE, {"k": config_key}).mappings().all()
        if active and not supersede:
            raise SystemExit(
                f"{config_key} already has an active configuration ({active[0]['config_id']}). "
                f"Pass --supersede to replace it, or use a different --config-key to run two "
                f"raters side by side. Two active rows under one key is an ambiguous rater.")

        row = {
            "config_id": str(uuid.uuid4()),
            "config_key": config_key,
            "version": int(conn.execute(_MAX_VERSION, {"k": config_key}).scalar()) + 1,
            "model_id": model_id,
            "effort": effort,
            "prompt_versions": json.dumps(prompt_versions),
            "normalization_version": normalization_version,
            "escalation": json.dumps(escalation) if escalation else None,
            "stage_models": json.dumps(stage_models) if stage_models else None,
            "level_method": level_method,
            "level_threshold": level_threshold,
            "definition_hash": definition_hash(
                model_id=model_id, effort=effort, prompt_versions=prompt_versions,
                normalization_version=normalization_version, escalation=escalation,
                stage_models=stage_models, level_method=level_method,
                level_threshold=level_threshold),
            "supersedes": active[0]["config_id"] if active else None,
            "promoted_at": datetime.now(timezone.utc),
            "promoted_by": promoted_by,
            "second_approver": second_approver,
            "rationale": rationale,
        }

        if dry_run:
            conn.rollback()
            return {"dry_run": True, **{k: v for k, v in row.items() if k != "promoted_at"},
                    "models": resolve_models(model_id, stage_models)}

        if active:
            conn.execute(_SUPERSEDE, {"c": active[0]["config_id"]})
        conn.execute(_INSERT, row)

    return {"config_id": row["config_id"], "config_key": config_key,
            "version": row["version"], "definition_hash": row["definition_hash"],
            "level_method": level_method, "level_threshold": level_threshold,
            "models": resolve_models(model_id, stage_models),
            "superseded": row["supersedes"], "promoted_by": promoted_by}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config-key", required=True,
                    help="stable across versions; two raters side by side need two keys")
    ap.add_argument("--model-id", required=True, help="exact, never a floating alias")
    ap.add_argument("--effort", default="high")
    ap.add_argument("--normalization-version", default="1")
    ap.add_argument("--level-method", default="category", choices=("category", "cumulative"))
    ap.add_argument("--level-threshold", type=float, default=DEFAULT_LEVEL_THRESHOLD)
    ap.add_argument("--escalation", default=None,
                    help="JSON; omit for the default policy (they hash the same)")
    ap.add_argument("--stage-models", default=None,
                    help='JSON per-stage overrides, e.g. \'{"evidence": "claude-haiku-4-5-..."}\'')
    ap.add_argument("--promoted-by", required=True,
                    help="a person. The database refuses an active configuration without one.")
    ap.add_argument("--rationale", required=True, help="why this rater exists, in a sentence")
    ap.add_argument("--second-approver", default=None)
    ap.add_argument("--supersede", action="store_true",
                    help="retire the current active configuration under this key")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if sys.stdin.isatty():
        raise SystemExit(
            "the prompt fingerprint arrives on stdin:\n"
            f"  python -m scoring.prompts --method {a.level_method} "
            f"| python -m registry.promote_configuration ...")
    prompt_versions = json.load(sys.stdin)

    # A configuration stamped with the other method's prompts is refused by
    # `check_configuration` at the first paper. Catching it here costs nothing and there is no
    # reason to find out later.
    expected = {"band"} if a.level_method == "cumulative" else {"score"}
    if not expected <= set(prompt_versions):
        raise SystemExit(
            f"--level-method {a.level_method} needs the {expected} prompt in the fingerprint, and "
            f"stdin carried {sorted(prompt_versions)}. Pipe from "
            f"`python -m scoring.prompts --method {a.level_method}`.")

    print(json.dumps(promote(
        config_key=a.config_key, model_id=a.model_id, effort=a.effort,
        prompt_versions=prompt_versions, normalization_version=a.normalization_version,
        escalation=json.loads(a.escalation) if a.escalation else None,
        stage_models=json.loads(a.stage_models) if a.stage_models else None,
        level_method=a.level_method, level_threshold=a.level_threshold,
        promoted_by=a.promoted_by, rationale=a.rationale,
        second_approver=a.second_approver, supersede=a.supersede, dry_run=a.dry_run),
        indent=1, default=str))


if __name__ == "__main__":
    main()
