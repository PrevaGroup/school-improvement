"""Load an approved `ExtractedPlan` into the augment tables (plan/plan_goal/plan_action).

This is the write half of the SIP pipeline — the counterpart to `etl/ca/sip/extract_sip.py`.
It runs *inside the app's tenant boundary*: the caller's session has already done
`SET LOCAL app.tenant = <tenant>` (app/db.py), so every row we insert must stamp that
same `tenant_id` or the RLS WITH CHECK (`tenant_id = current_setting('app.tenant')`)
rejects it. We never trust a tenant from the payload.

Review gate: only metric links a human marked `confirmed` are written onto the goal/
action columns. `proposed` / `rejected` links stay in the source JSON for audit and are
NOT loaded — that is the whole point of the proposed→confirmed step.

Idempotent: deterministic ids (schema.py) + ON CONFLICT DO UPDATE mean re-loading the
same approved plan overwrites in place. (It does not delete goals/actions that were
dropped between extractions — orphan pruning is a later concern; see the module note.)

Lossiness (current minimal schema): the augment tables hold ONE linked metric per goal/
action and no provenance. Multi-metric goals and page-level provenance are preserved in
the JSON but not yet in the DB — they land when `bridge_action_metric` + a provenance
table are added.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from etl.ca.sip.schema import (
    ExtractedGoal,
    ExtractedPlan,
    LinkStatus,
    MetricLinkProposal,
)

from etl.ca.sip.models import Plan, PlanAction, PlanGoal


def _first_confirmed(links: list[MetricLinkProposal]) -> Optional[MetricLinkProposal]:
    """The first metric link a reviewer confirmed, or None. Enforces the review gate."""
    for link in links:
        if link.link_status == LinkStatus.confirmed:
            return link
    return None


def _upsert(session: Session, model, rows: list[dict], pk: str) -> None:
    if not rows:
        return
    stmt = pg_insert(model).values(rows)
    update_cols = {c.name: c for c in stmt.excluded if c.name != pk}
    session.execute(stmt.on_conflict_do_update(index_elements=[pk], set_=update_cols))


def _goal_row(g: ExtractedGoal, *, plan_id: str, tenant_id: str) -> dict:
    link = _first_confirmed(g.metric_links)
    return dict(
        goal_id=g.goal_id,
        plan_id=plan_id,
        tenant_id=tenant_id,
        visibility="private",
        lcff_priority=g.lcff_priority,
        linked_metric_id=link.proposed_metric_id if link else None,
        target_group_id=g.target_group_id or (link.target_group_id if link else None),
        baseline_value=link.baseline_value if link else None,
        baseline_year=link.baseline_year if link else None,
        target_value=link.target_value if link else None,
        target_year=link.target_year if link else None,
        prior_status=None,
        narrative=g.statement,
    )


def _action_rows(g: ExtractedGoal, *, tenant_id: str) -> list[dict]:
    rows = []
    for a in g.actions:
        link = _first_confirmed(a.metric_links)
        rows.append(
            dict(
                action_id=a.action_id,
                goal_id=g.goal_id,
                tenant_id=tenant_id,
                visibility="private",
                strategy_text=a.strategy_text,
                category_id=a.category_id,
                target_metric_id=link.proposed_metric_id if link else None,
                target_group_id=link.target_group_id if link else None,
                budgeted_amount=a.budgeted_amount,
                funding_source_id=a.funding_source_id,
                fte=a.fte,
                role_type=a.role_type,
                is_district_provided=a.is_district_provided,
            )
        )
    return rows


def load_plan(session: Session, tenant_id: str, plan: ExtractedPlan) -> dict:
    """Upsert plan -> goals -> actions under `tenant_id`. Returns the row counts.

    Insert order respects the FKs (plan <- plan_goal <- plan_action). The caller's
    `get_db` session commits on success.
    """
    plan_row = dict(
        plan_id=plan.plan_id,
        tenant_id=tenant_id,
        visibility="private",
        school_id=plan.school_id,
        plan_year=plan.plan_year,
        plan_type=plan.plan_type.value,
        status=plan.status,
        adopted_date=plan.adopted_date,
        total_budget=plan.total_budget,
        source_url=plan.source.file,
    )
    _upsert(session, Plan, [plan_row], "plan_id")

    goal_rows = [_goal_row(g, plan_id=plan.plan_id, tenant_id=tenant_id) for g in plan.goals]
    _upsert(session, PlanGoal, goal_rows, "goal_id")

    action_rows: list[dict] = []
    for g in plan.goals:
        action_rows.extend(_action_rows(g, tenant_id=tenant_id))
    _upsert(session, PlanAction, action_rows, "action_id")

    return {"goals": len(goal_rows), "actions": len(action_rows)}
