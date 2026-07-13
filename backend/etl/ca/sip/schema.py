"""Extraction contract for California school-improvement plans (SPSA / LCAP / CSI…).

This is the *staging* shape: the reviewable JSON that a PDF→JSON extractor emits and
that the augment loader consumes. It mirrors the augment tables
(`plan` / `plan_goal` / `plan_action`) and adds two things the tables don't carry:

  * **provenance** — page + verbatim quote for every extracted fact, so an evaluation
    finding can be traced back to a spot in the source PDF; and
  * **metric-link proposals** — the model *proposes* action/goal → metric links
    (the future `bridge_action_metric`); a human confirms them before the loader writes.

Pipeline:  raw/ca/districts/<LEAID>/sip/*.pdf  →  <this JSON>  →  augment plan_* rows
The JSON is the human-review gate between "what the model read" and "what the DB believes".
IDs are deterministic (see `*_id` builders) so re-extraction / re-load is idempotent.
"""
from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Controlled vocabularies
# --------------------------------------------------------------------------- #
class PlanType(str, Enum):
    SPSA = "SPSA"   # Single Plan for Student Achievement (school level)
    LCAP = "LCAP"   # Local Control & Accountability Plan (district level)
    CSI = "CSI"     # Comprehensive Support & Improvement
    TSI = "TSI"     # Targeted Support & Improvement
    ATSI = "ATSI"   # Additional Targeted Support & Improvement


class ReviewStatus(str, Enum):
    draft = "draft"          # freshly extracted, untouched
    reviewed = "reviewed"    # a human read it
    approved = "approved"    # cleared to load into augment


class LinkStatus(str, Enum):
    proposed = "proposed"    # model's guess, awaiting review
    confirmed = "confirmed"  # human accepted the metric mapping
    rejected = "rejected"    # human rejected it (kept for audit, not loaded)


class Direction(str, Enum):
    increase = "increase"    # a higher value is the goal (e.g. grad rate)
    decrease = "decrease"    # a lower value is the goal (e.g. chronic absenteeism)


# --------------------------------------------------------------------------- #
# Provenance — attached to everything extracted
# --------------------------------------------------------------------------- #
class Provenance(BaseModel):
    """Where in the PDF this fact came from. Verbatim quote, no paraphrase."""
    page: int = Field(..., ge=1, description="1-based page in the source PDF")
    quote: str = Field(..., description="verbatim source text the fact was read from")
    confidence: float = Field(1.0, ge=0.0, le=1.0, description="extractor self-rating")


# --------------------------------------------------------------------------- #
# Metric-link proposal — the bridge_action_metric, proposed for human confirmation
# --------------------------------------------------------------------------- #
class MetricLinkProposal(BaseModel):
    """A plan's claimed measure/target, mapped (tentatively) onto a conformed metric.

    `proposed_metric_id` must be a `dim_metric.metric_id` (e.g. "chronic_absenteeism_rate")
    or null when the plan names something we don't yet conform — `raw_metric_text` always
    preserves what the plan literally wrote.
    """
    raw_metric_text: str = Field(..., description="metric as written in the plan, verbatim")
    proposed_metric_id: Optional[str] = Field(None, description="dim_metric.metric_id, or null if unmapped")
    target_group_id: Optional[str] = Field(None, description="dim_student_group.group_id")
    direction: Optional[Direction] = None

    baseline_value: Optional[float] = None
    baseline_year: Optional[str] = None      # school-year label, e.g. "2023-24"
    target_value: Optional[float] = None
    target_year: Optional[str] = None

    link_status: LinkStatus = LinkStatus.proposed
    provenance: Provenance


# --------------------------------------------------------------------------- #
# Action  ->  plan_action
# --------------------------------------------------------------------------- #
class ExtractedAction(BaseModel):
    action_id: str = Field(..., description="deterministic; see build_action_id()")
    action_number: Optional[str] = Field(None, description="label as printed, e.g. '1.2'")
    strategy_text: str = Field(..., description="what the district will do")

    category_id: Optional[str] = Field(None, description="controlled category (instruction, PD, staffing, SEL, …)")
    budgeted_amount: Optional[float] = None
    funding_source_raw: Optional[str] = Field(None, description="funding source as written")
    funding_source_id: Optional[str] = Field(None, description="mapped funding source, if resolvable")
    fte: Optional[float] = None
    role_type: Optional[str] = None
    is_district_provided: Optional[bool] = None

    metric_links: list[MetricLinkProposal] = Field(default_factory=list)
    provenance: Provenance


# --------------------------------------------------------------------------- #
# Goal  ->  plan_goal
# --------------------------------------------------------------------------- #
class ExtractedGoal(BaseModel):
    goal_id: str = Field(..., description="deterministic; see build_goal_id()")
    goal_number: Optional[str] = Field(None, description="label as printed, e.g. 'Goal 1'")
    goal_type: Optional[str] = Field(
        None,
        description="flexible, district-specific label for the goal's role in the plan "
        "structure (free text, not an enum), e.g. strategic_5yr | subject | accountability_measure",
    )
    statement: str = Field(..., description="the goal statement / narrative")
    lcff_priority: Optional[int] = Field(None, ge=1, le=8, description="LCFF state priority 1-8 (LCAP only)")
    target_group_id: Optional[str] = Field(None, description="dim_student_group.group_id")

    metric_links: list[MetricLinkProposal] = Field(default_factory=list, description="goal-level measures/targets")
    actions: list[ExtractedAction] = Field(default_factory=list)
    provenance: Provenance


# --------------------------------------------------------------------------- #
# Source + review metadata
# --------------------------------------------------------------------------- #
class SourceRef(BaseModel):
    file: str = Field(..., description="gs:// URI of the source PDF")
    sha256: str = Field(..., description="hash of the PDF bytes — detects source change")
    page_count: int = Field(..., ge=1)
    extracted_by: str = Field(..., description="model id that produced this JSON, e.g. claude-opus-4-8")
    extracted_at: str = Field(..., description="ISO-8601 timestamp, stamped by the extractor")


# --------------------------------------------------------------------------- #
# Plan  ->  plan   (root document, one per PDF)
# --------------------------------------------------------------------------- #
class ExtractedPlan(BaseModel):
    plan_id: str = Field(..., description="deterministic; see build_plan_id()")
    # Identity keys on the *federal NCES* ids; state-native codes ride alongside as attributes.
    school_id: Optional[str] = Field(None, description="NCES school id (12-digit ncessch); null for district-level LCAP")
    district_id: str = Field(..., description="federal NCES LEAID (7-digit), e.g. '0622710'")
    state_school_id: Optional[str] = Field(None, description="state-native school code (CA 14-digit CDS)")
    state_district_id: Optional[str] = Field(None, description="state-native district code (CA 7-digit CDS district)")
    plan_type: PlanType
    plan_year: str = Field(..., description="school-year label, e.g. '2024-25'")

    status: Optional[str] = None
    adopted_date: Optional[date] = None
    total_budget: Optional[float] = None

    goals: list[ExtractedGoal] = Field(default_factory=list)

    # things the extractor saw but could not confidently place (never silently dropped)
    unresolved: list[str] = Field(default_factory=list)

    source: SourceRef
    review_status: ReviewStatus = ReviewStatus.draft
    reviewer: Optional[str] = None


# --------------------------------------------------------------------------- #
# Deterministic IDs — stable across re-extraction so ON CONFLICT is idempotent
# --------------------------------------------------------------------------- #
def build_plan_id(district_id: str, school_id: Optional[str], plan_type: str, plan_year: str) -> str:
    scope = school_id or district_id
    return f"{scope}:{plan_type}:{plan_year}".lower()


def build_goal_id(plan_id: str, goal_number: str) -> str:
    return f"{plan_id}:g{goal_number}".lower().replace(" ", "")


def build_action_id(goal_id: str, action_number: str) -> str:
    return f"{goal_id}:a{action_number}".lower().replace(" ", "")
