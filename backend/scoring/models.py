"""The three tables the `scoring` module owns — the record the writing subsystem is built around.

Design: the SIP teacher-subsystem expansion plan (§6 the score record, §2 decisions 2/7/9) and
agentic-scoring-pipeline-design v0.06 (§3.2 states, §6.1 the score record).

`serving` reads these with SQL and owns nothing; the pipeline writes them. Nothing downstream
imports these classes, so the module can be rewritten freely as long as the table shapes hold.

Three shape decisions carry most of the weight, and each is here rather than in application code
because application code is where invariants go to die:

- **Immutable, append-only.** A score is never updated. A teacher who disagrees writes a new event
  referencing the prior one; a corrected model configuration writes new events too. `updated_at`
  is deliberately absent — there is no operation that would set it.

- **Override and supersession are two different relations.** An override references a prior EVENT
  for the same artifact and criterion: a different judgment about the same text. A supersession
  points across ARTIFACTS under one binding key: a different text. Collapsing them loses the
  distinction between "we scored this wrong" and "they wrote it again", which is exactly what the
  override stream exists to tell apart.

- **The facet stamp is wide on purpose.** Facets not logged now are unrecoverable later — the
  hidden-facet problem the construct audit found in the existing rubric data. Rubric version and
  form variant are separate columns because folding the alternate form into the version makes its
  effect unrecoverable, and a human scorer is identified individually because rater severity
  cannot be estimated from an anonymous pool.

REGISTRATION — these classes only reach `Base.metadata` if something imports this module:
    * migrations/env.py                              -> autogenerate; unseen table means DROP TABLE
    * migrations/versions/0001_initial_schema.py     -> create_all on a fresh database
    backend/tests/test_schema_inventory.py fails if a table stops being registered.

TENANCY: artifact and score_event hold identifiable student work and carry `TenantMixin`. They are
NOT yet in `PRIVATE_TABLES` — turning RLS on is a deliberate `core` move (CLAUDE.md), made when the
subsystem first holds real student writing, not a side effect of the module existing. Same posture
`evals` took, and for the same reason.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (CheckConstraint, ForeignKey, Index, Integer, Numeric, Text,
                        TIMESTAMP, UniqueConstraint)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.tenant import TenantMixin

# --------------------------------------------------------------------------- #
# The artifact state machine.
#
# Nothing in the pipeline halts. An artifact is written into a state from which no forward
# transition is currently permitted, and a human transition releases it — which is why the error
# queue is a view over states rather than a stage.
#
# Per-CRITERION outcomes (scored / abstained / no_verified_evidence / ...) are NOT states: they
# live on score_event.status, drawn from core's vocabulary. Mixing the two grains is what makes a
# state machine unenforceable.
# --------------------------------------------------------------------------- #
ARTIFACT_STATES: tuple[str, ...] = (
    "unbound",        # we hold it and cannot yet say what it is or whose
    "bound",          # binding key resolved
    "not_scorable",   # a defined non-attempt against the bound task — never a low score
    "scored",         # every criterion has an outcome, including abstentions
    "composed",       # rationale packet built (student feedback is composed after review)
    "blocked",        # output safety held the student-facing draft
    "in_review",      # with the teacher
    "released",       # terminal — teacher-only
    "withheld",       # terminal — exists, deliberately not sent
)

# Who may make each move. `machine` = the pipeline; `teacher` = a human with release authority.
# Only a teacher may reach `released`: that single constraint is the authority claim the product
# rests on, and it is enforced by the trigger in migration 0008, not by the interface.
ARTIFACT_TRANSITIONS: dict[str, dict[str, str]] = {
    "unbound":      {"bound": "teacher", "withheld": "teacher"},
    "bound":        {"scored": "machine", "not_scorable": "machine", "withheld": "teacher"},
    "not_scorable": {"bound": "teacher", "withheld": "teacher"},
    "scored":       {"composed": "machine", "withheld": "teacher"},
    "composed":     {"in_review": "machine", "blocked": "machine", "withheld": "teacher"},
    "blocked":      {"in_review": "teacher", "withheld": "teacher"},
    "in_review":    {"released": "teacher", "withheld": "teacher"},
    "released":     {},
    "withheld":     {},
}

TERMINAL_STATES = frozenset(s for s, moves in ARTIFACT_TRANSITIONS.items() if not moves)


class Artifact(Base, TenantMixin):
    """One submitted document, under one binding key, in one state.

    The binding key is (student, section, task, iteration) — the four resolutions stage A makes,
    which fail independently and cost different amounts to get wrong. `window_label` is declared
    rather than inferred: nothing in a set of scores identifies which two occasions constitute a
    growth interval, and elapsed time does not stand in for it.
    """
    __tablename__ = "artifact"

    artifact_id: Mapped[str] = mapped_column(Text, primary_key=True)
    run_id: Mapped[str] = mapped_column(Text, nullable=False)

    # --- binding key (pipeline §3.4) ---
    student_id: Mapped[str | None] = mapped_column(Text)          # null while unbound
    section_id: Mapped[str | None] = mapped_column(Text)
    task_id: Mapped[str | None] = mapped_column(Text)
    iteration: Mapped[str | None] = mapped_column(Text)           # e.g. draft | final
    window_label: Mapped[str | None] = mapped_column(Text)        # "fall 2026" — declared, not inferred

    # --- provenance ---
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    source_uri: Mapped[str | None] = mapped_column(Text)
    handed_in_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    # Per binding element: "looked_up" or "inferred". A score whose binding was inferred has a
    # different error profile from one looked up, and pooling them pools two populations. A rising
    # inferred rate is also the earliest signal an integration has broken.
    resolution_path: Mapped[dict | None] = mapped_column(JSONB)

    state: Mapped[str] = mapped_column(Text, nullable=False, server_default="unbound")
    state_reason_code: Mapped[str | None] = mapped_column(Text)

    # Supersession — a LATER ARTIFACT under the same binding key displaces this one for reporting.
    # Distinct from an override, which is a new event about this same text (see ScoreEvent).
    # Nothing is deleted: the superseded artifact keeps its scores, its reviewer and its delivery
    # record, which is what lets a growth claim over the pair be qualified honestly.
    superseded_by_artifact_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifact.artifact_id"))

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()")

    __table_args__ = (
        Index("ix_artifact_binding", "tenant_id", "section_id", "task_id", "iteration"),
        Index("ix_artifact_student", "tenant_id", "student_id"),
        Index("ix_artifact_run", "run_id"),
        Index("ix_artifact_state", "tenant_id", "state"),
        CheckConstraint(
            "state IN (" + ",".join(f"'{s}'" for s in ARTIFACT_STATES) + ")",
            name="state"),
    )


class ScoreEvent(Base, TenantMixin):
    """One immutable judgment about one criterion of one artifact.

    Never updated. An override appends a new row pointing at the one it disagrees with, so the
    pairing that makes overrides valuable — this configuration said 3, this named teacher said 2 —
    survives intact and remains a calibration observation for the configuration it was about.
    """
    __tablename__ = "score_event"

    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifact.artifact_id"), nullable=False)

    # --- binding, denormalised so the event is self-describing ---
    run_id: Mapped[str] = mapped_column(Text, nullable=False)
    student_id: Mapped[str | None] = mapped_column(Text)
    section_id: Mapped[str | None] = mapped_column(Text)
    task_id: Mapped[str | None] = mapped_column(Text)
    iteration: Mapped[str | None] = mapped_column(Text)
    window_label: Mapped[str | None] = mapped_column(Text)

    # --- the item ---
    node_id: Mapped[str] = mapped_column(Text, nullable=False)     # standard × criterion × scale × grade band
    trait_set_version: Mapped[str | None] = mapped_column(Text)
    rubric_version: Mapped[str | None] = mapped_column(Text)
    form_variant: Mapped[str | None] = mapped_column(Text)         # SEPARATE from rubric_version, deliberately

    # --- the rater ---
    # For a machine rater this resolves to model id + prompt versions + effort + span-verifier
    # normalization rules. Current models have no sampling parameters, so "decoding parameters" is
    # in practice `effort`. For a human it is that individual, never a generic "teacher".
    scoring_configuration_id: Mapped[str | None] = mapped_column(Text)
    scorer_type: Mapped[str] = mapped_column(Text, nullable=False)  # ai | teacher | expert
    scorer_id: Mapped[str | None] = mapped_column(Text)
    # Whether a human scored blind or with the model's score visible. An informed score cannot
    # serve as an independent rating in a calibration design; logging it keeps the option open.
    human_blind: Mapped[bool | None] = mapped_column()

    # --- scrutiny: escalated and unescalated scores come from different administrations ---
    scrutiny_passes: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    escalation_trigger: Mapped[str | None] = mapped_column(Text)

    # --- the outcome ---
    status: Mapped[str] = mapped_column(Text, nullable=False)       # core vocab.SCORE_STATUSES
    level: Mapped[float | None] = mapped_column(Numeric)            # null unless status = scored
    confidence: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    reason_code: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[dict | None] = mapped_column(JSONB)            # verified spans, and what was dropped

    # --- membership: record, frame and calibration are three different things ---
    is_measurement_occasion: Mapped[bool | None] = mapped_column()
    enters_calibration: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    revised_after_feedback: Mapped[bool | None] = mapped_column()

    # --- lineage ---
    # An OVERRIDE: a new judgment about the same artifact and criterion. Supersession lives on
    # artifact.superseded_by_artifact_id — a different text, not a different opinion.
    supersedes_event_id: Mapped[str | None] = mapped_column(
        ForeignKey("score_event.event_id"))
    # A set-level override is ONE judgment covering many artifacts. Recorded as one decision so it
    # is not counted as N independent human ratings, which would inflate apparent disagreement and
    # hide that a single judgment was made once.
    set_override_id: Mapped[str | None] = mapped_column(Text)

    # A resumed run must not double the observations for papers it already finished — a
    # measurement bug wearing a throughput bug's clothes.
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()")

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_score_event_idempotency"),
        CheckConstraint("scorer_type IN ('ai','teacher','expert')",
                        name="scorer_type"),
        # A level without a score, or a score without a level, is a row that means nothing.
        CheckConstraint(
            "(status = 'scored' AND level IS NOT NULL) OR "
            "(status <> 'scored' AND level IS NULL)",
            name="level_matches_status"),
        Index("ix_score_event_artifact", "artifact_id"),
        Index("ix_score_event_node", "tenant_id", "node_id"),
        Index("ix_score_event_binding", "tenant_id", "section_id", "task_id", "iteration"),
        Index("ix_score_event_calibration", "tenant_id", "enters_calibration"),
        Index("ix_score_event_config", "scoring_configuration_id"),
    )


class ArtifactStateTransition(Base, TenantMixin):
    """Every state change, with who made it. The audit half of the state machine.

    The trigger in migration 0008 rejects an illegal transition and rejects a machine actor
    reaching `released`; this table records what actually happened, so "who released this" is
    answerable from the record rather than from an application log.
    """
    __tablename__ = "artifact_state_transition"

    transition_id: Mapped[str] = mapped_column(Text, primary_key=True)
    artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifact.artifact_id"), nullable=False)
    from_state: Mapped[str | None] = mapped_column(Text)
    to_state: Mapped[str] = mapped_column(Text, nullable=False)
    actor_type: Mapped[str] = mapped_column(Text, nullable=False)   # machine | teacher
    actor_id: Mapped[str | None] = mapped_column(Text)
    reason_code: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()")

    __table_args__ = (
        Index("ix_artifact_state_transition_artifact", "artifact_id", "created_at"),
    )
