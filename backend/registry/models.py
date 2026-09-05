"""The six tables the `registry` module owns — what may be scored, and by which rater.

Design: the SIP teacher-subsystem expansion plan §5 (the registry linter) and §10 (the node, its
identifier, and the scoring configuration), and agentic-scoring-pipeline-design v0.06 §3.4.3.

Configuration in the pipeline design's sense: authored before any folder URL is submitted, applying
to every artifact in scope, and reviewed on a release cadence rather than per artifact. It fails
**silently and at scale** — one error reaches every paper in a section — which is why the linter
exists and why so much of the shape here is a constraint rather than a convention.

THE NODE IS THE UNIT. Not the trait, not the rubric row: the node, identified by a stable
identifier and characterised by (standard, criterion, scale structure, grade band). Two criteria
addressing one standard are two nodes. The identifier IS the identity; the composite is the
integrity constraint — which turns two whole classes of authoring error into mechanical checks
instead of judgment calls.

Scale structure lives on the node and descriptors live on the version, and that split is what
enforces "one identifier, one scale structure" without a trigger: changing the category count
cannot be a new version, because the scale is not on the version. It is a new node, which is the
correct answer — a difference in category count is evidence the rubrics drew the construct
differently, not a scaling detail to normalise past.

WHAT IS DELIBERATELY ABSENT. No harmonised view across nodes, and no machinery to build one.
Comparability lives on the person metric: a four-category node beside a five-category node needs no
reconciliation, because both place persons on the same logit continuum. The urge to harmonise is a
raw-score instinct.

REGISTRATION — these classes only reach `Base.metadata` if something imports this module:
    * migrations/env.py                          -> autogenerate; unseen table means DROP TABLE
    * backend/tests/test_schema_inventory.py     -> mirrors that import list
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (CheckConstraint, ForeignKey, Index, Integer, Text, text, TIMESTAMP,
                        UniqueConstraint)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# A node version is drafted, published, then superseded. `withdrawn` is the escape for a version
# published in error — distinct from superseded, because "replaced" and "should never have existed"
# are different facts about a score already stamped with it.
VERSION_STATUSES: tuple[str, ...] = ("draft", "published", "superseded", "withdrawn")

# Whether a node is an anchor (appears across tasks and carries the linking) or module-local
# (estimated sparsely, excluded from linking, and that exclusion stated rather than silent).
NODE_KINDS: tuple[str, ...] = ("anchor", "module_local", "diagnostic_only")


class Node(Base):
    """One item: a standard, scored by one criterion, on one scale, at one grade band.

    Public reference content — no tenancy. A node means the same thing in every district, which is
    what makes cross-district anchoring possible without a cross-tenant query.

    The identifier is issued once and NEVER recycled: reassigning it makes every historical score
    stamped with it ambiguous. Changing what the node measures means issuing a new identifier, not
    editing this row — and because a descriptor edit can either clarify a construct or replace it,
    the linter holds any descriptor change on a published version for explicit confirmation. It
    cannot answer that question; it can refuse to let it go unasked.
    """
    __tablename__ = "registry_node"

    node_id: Mapped[str] = mapped_column(Text, primary_key=True)

    # --- the composite: the integrity constraint on the identity ---
    standard_code: Mapped[str] = mapped_column(Text, nullable=False)   # e.g. RH.11-12.6
    criterion_label: Mapped[str] = mapped_column(Text, nullable=False)
    grade_band: Mapped[str] = mapped_column(Text, nullable=False)      # e.g. "11-12"
    # The categories this node is scored on, in order: [1,2,3,4] or [1,1.5,...,4]. Partial credit —
    # thresholds are estimated per node from its own data, never pooled across items assumed to
    # share a structure. Immutable: a different category count is a different node.
    scale_categories: Mapped[list] = mapped_column(JSONB, nullable=False)

    kind: Mapped[str] = mapped_column(Text, nullable=False, server_default="module_local")
    source: Mapped[str | None] = mapped_column(Text)     # LDC rubric export, PERSUADE, authored
    retired_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()")

    __table_args__ = (
        CheckConstraint("kind IN (" + ",".join(f"'{k}'" for k in NODE_KINDS) + ")", name="kind"),
        # You cannot fit what you cannot read: a one-category scale is not a scale.
        CheckConstraint("jsonb_array_length(scale_categories) >= 2", name="scale_fittable"),
        Index("ix_registry_node_standard", "standard_code", "grade_band"),
        Index("ix_registry_node_kind", "kind"),
    )


class NodeVersion(Base):
    """The descriptors for one node, at one version.

    Separate from the node because descriptors are the part that legitimately evolves — a clearer
    wording of the same construct. The scale is NOT here: moving it to the version would let a
    category count change without changing the identity, which is the one thing the node rule
    exists to prevent.
    """
    __tablename__ = "registry_node_version"

    node_version_id: Mapped[str] = mapped_column(Text, primary_key=True)
    node_id: Mapped[str] = mapped_column(ForeignKey("registry_node.node_id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    # category -> descriptor. A descriptor that is a LIST is a cell stacking several conditional
    # judgments; the linter flags it, because two raters can score the same paper on different
    # clauses, and rendering it as prose would hide exactly that.
    descriptors: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    change_note: Mapped[str | None] = mapped_column(Text)
    # Set when an author confirms a descriptor edit clarified the construct rather than replacing
    # it. The linter blocks publication until it is present.
    construct_unchanged_ack: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()")

    __table_args__ = (
        UniqueConstraint("node_id", "version", name="uq_registry_node_version"),
        CheckConstraint(
            "status IN (" + ",".join(f"'{s}'" for s in VERSION_STATUSES) + ")", name="status"),
        Index("ix_registry_node_version_node", "node_id", "status"),
        # Exactly one published version per node. Two would make the driver's trait-set join
        # return the node twice — scored twice, under two wordings, with no error anywhere.
        # Superseded and withdrawn rows are unaffected: the history stays, only the count of
        # current ones is bounded. Migration 0014.
        Index("uq_registry_node_one_published", "node_id", unique=True,
              postgresql_where=text("status = 'published'")),
    )


class Task(Base):
    """A thing students hand in. Owns nothing about scoring except which sites it has."""
    __tablename__ = "registry_task"

    task_id: Mapped[str] = mapped_column(Text, primary_key=True)
    module_key: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    ordinal: Mapped[int | None] = mapped_column(Integer)   # taught position — an ANNOTATION, never
    grade_band: Mapped[str | None] = mapped_column(Text)   # an ordering principle for difficulty
    standards: Mapped[list | None] = mapped_column(JSONB)  # as tagged by the module
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()")

    __table_args__ = (
        Index("ix_registry_task_module", "module_key", "ordinal"),
    )


class ScoringSite(Base):
    """WHICH iterations of a task are scored, and on which nodes.

    v0.06 moved this from "the declared measurement occasion" (one field) to "which iterations are
    scored and on which rubric" — because the rough draft scored on the FINAL rubric is the
    strongest pre-final site, and a single occasion field cannot express two iterations sharing one
    node set.

    `is_measurement_occasion` is the narrower flag: a draft is scored, and is not the occasion. That
    is the difference between what a teacher sees and what enters the frame.
    """
    __tablename__ = "registry_scoring_site"

    site_id: Mapped[str] = mapped_column(Text, primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("registry_task.task_id"), nullable=False)
    iteration: Mapped[str] = mapped_column(Text, nullable=False)     # draft | final | only
    is_measurement_occasion: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    note: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("task_id", "iteration", name="uq_registry_scoring_site_iteration"),
        Index("ix_registry_scoring_site_task", "task_id"),
    )


class ScoringSiteNode(Base):
    """The trait set: which nodes a site is scored on. Frozen at binding, before stage C."""
    __tablename__ = "registry_scoring_site_node"

    site_id: Mapped[str] = mapped_column(
        ForeignKey("registry_scoring_site.site_id"), primary_key=True)
    node_id: Mapped[str] = mapped_column(
        ForeignKey("registry_node.node_id"), primary_key=True)
    ordinal: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        Index("ix_registry_site_node_node", "node_id"),
    )


class ScoringConfiguration(Base):
    """The rater, as a versioned object an administrator publishes.

    A configuration version IS a rater — model, prompts, effort and the span-verifier's
    normalization rules as one identity, which is what the score record stamps. Naming it makes
    literal what was otherwise reassembled from four columns after the fact.

    `model_id` is pinned exactly. A floating alias that resolves to a new version is precisely the
    silent rater change a freeze exists to prevent, and it does not announce itself. Note there are
    no sampling parameters: current models removed them, so `effort` is what "decoding parameters"
    means in practice.

    Promotion carries a two-person rule and a written rationale, stored here rather than in a
    ticket. Who qualifies as the second approver is an open decision — and with a single product
    manager as the MVP administrator, the sole-approver case is the expected state rather than the
    edge case.
    """
    __tablename__ = "registry_scoring_configuration"

    config_id: Mapped[str] = mapped_column(Text, primary_key=True)
    config_key: Mapped[str] = mapped_column(Text, nullable=False)   # stable across versions
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    model_id: Mapped[str] = mapped_column(Text, nullable=False)     # exact, never an alias
    effort: Mapped[str | None] = mapped_column(Text)
    prompt_versions: Mapped[dict] = mapped_column(JSONB, nullable=False)   # per pipeline function
    normalization_version: Mapped[str] = mapped_column(Text, nullable=False)  # span verifier rules
    definition_hash: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    supersedes_config_id: Mapped[str | None] = mapped_column(
        ForeignKey("registry_scoring_configuration.config_id"))

    # Change control. The anchor replay that justifies a promotion is Phase 6; the record of who
    # decided, and why, is cheap now and unrecoverable later.
    promoted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    promoted_by: Mapped[str | None] = mapped_column(Text)
    second_approver: Mapped[str | None] = mapped_column(Text)
    rationale: Mapped[str | None] = mapped_column(Text)
    replay_run_id: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()")

    __table_args__ = (
        UniqueConstraint("config_key", "version", name="uq_registry_configuration_version"),
        CheckConstraint(
            "status IN ('draft','active','superseded','withdrawn')", name="status"),
        # A promotion nobody recorded a reason for is a change nobody can explain later.
        CheckConstraint(
            "status <> 'active' OR (promoted_by IS NOT NULL AND rationale IS NOT NULL)",
            name="promotion_recorded"),
        Index("ix_registry_configuration_key", "config_key", "status"),
        # Exactly one active configuration per key. Two active rows is an ambiguous rater, and a
        # rater that cannot be named cannot have a severity estimated. Migration 0014.
        Index("uq_registry_configuration_one_active", "config_key", unique=True,
              postgresql_where=text("status = 'active'")),
    )


class LintAcknowledgment(Base):
    """One recorded answer to one advisory finding.

    The linter's advisory class means "a judgment the linter cannot make". `lint()` drops an
    advisory finding whose `rule:subject` appears here, so this table is the only thing that makes
    that class different from a warning log — the acknowledgment becomes part of the version
    record, and the next reader sees a judgment that was made rather than a check that was skipped.

    NOT the same as `NodeVersion.construct_unchanged_ack`, which answers one specific BLOCKING rule
    about a descriptor edit. One version can carry several acknowledgments here, each with its own
    author and reason, and folding them into a column would lose which was answered and by whom.

    Public reference content, no tenancy: a judgment about a node is a judgment everywhere it
    appears. Migration 0015.
    """
    __tablename__ = "registry_lint_acknowledgment"

    ack_id: Mapped[str] = mapped_column(Text, primary_key=True)
    rule: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    node_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("registry_node_version.node_version_id"))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    acknowledged_by: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()")

    __table_args__ = (
        UniqueConstraint("rule", "subject", name="uq_registry_lint_ack_finding"),
        # A reason that says nothing is the check being skipped with extra steps.
        CheckConstraint("length(btrim(reason)) >= 12", name="reason_substantive"),
        Index("ix_registry_lint_ack_version", "node_version_id"),
    )
