"""The four tables the `corpus` module owns — the papers calibration is anchored on.

Design: the SIP teacher-subsystem expansion plan §10 ("One anchor corpus, and what it actually
contains"), MFRM_Formative_Value_Requirements V8.27 §6.1-6.2, and the LDC PM console user design
§2.2 (the corpus exception).

Public reference content: no tenancy. These papers are identical for every district, which is what
lets two districts sit on one metric without a cross-tenant query — the same property SIP gets from
computing peer sets over the public universe.

A SEPARATE MODULE FROM `registry`, and the split is the write path. The registry is authored: a
person defines what may be scored, on a release cadence, and the linter reads it. This is bulk ETL:
a corpus arrives with its scores already attached, needing conforming rather than reading, and the
loader follows `public_metrics/load_ca_*` — a thin spec plus a shared runner, printing its loaded,
skipped and excluded counts. Different write paths that share a module eventually acquire a
conditional at the top of every function.

WHAT THE CORPUS DOES AND DOES NOT SUPPLY. Verified against the downloaded files: essay text, ONE
holistic score, demographics, and discourse-element spans. It does NOT supply trait scores, element
effectiveness ratings, or any rater identity — there is no rater column, no second rating, nothing
separating one scorer from another. So it anchors task and person parameters and cannot anchor rater
severity, which is the anonymous-pool problem the design says severity cannot be estimated from. The
human side of the connected rating design is work to schedule, not data to acquire.

The consequence for linking: an analytic node is anchored by scoring these papers on YOUR OWN nodes.
Linkage across sources runs through papers, not through declaring a foreign corpus's traits
equivalent to yours.

THE HELD-OUT SPLIT IS WITHIN THE CORPUS, BY PAPER. An earlier draft of the plan proposed calibrating
on one anchor set and validating on another; the files show ASAP2 shares 12,725 essays with PERSUADE
at identical scores, so that split would have been half-circular. `partition` is assigned at load
time by a deterministic hash of the paper's identity, so the holdout is reproducible and genuinely
disjoint — scoring a model against the papers that defined its anchor is not validation.

REGISTRATION — these classes only reach `Base.metadata` if something imports this module:
    * migrations/env.py                          -> autogenerate; unseen table means DROP TABLE
    * backend/tests/test_schema_inventory.py     -> mirrors that import list
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (CheckConstraint, ForeignKey, Index, Integer, Numeric, Text, TIMESTAMP,
                        UniqueConstraint)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# Calibration anchors the parameters; validation is held out to check the model against human
# judgment. `unassigned` exists so a paper can be loaded before the split policy is settled rather
# than forcing a guess at load time.
PARTITIONS: tuple[str, ...] = ("calibration", "validation", "unassigned")

# PERSUADE's discourse elements. Segmentation only in the downloaded release — where a counterclaim
# IS, not how good it is. That still gives the diagnostic channel ground truth for PRESENCE of the
# constructs the crosswalk found taught everywhere and scored nowhere.
DISCOURSE_TYPES: tuple[str, ...] = (
    "Lead", "Position", "Claim", "Counterclaim", "Rebuttal", "Evidence",
    "Concluding Statement", "Unannotated",
)


class CorpusSource(Base):
    """One corpus, at one snapshot.

    Snapshot is a column rather than documentation because it is load-bearing: a figure computed
    over the November snapshot is a different figure.

    THERE IS NO LICENCE COLUMN, and its absence is deliberate. This system had one, it named a
    permissive licence for PERSUADE, and that was this project asserting somebody else's terms
    from memory. The fix is not a better-sourced licence field — it is that licensing is not a fact
    this system is entitled to hold. Terms are negotiated, they change without the data changing,
    and a copy here is a second record that goes stale silently while looking authoritative.
    Licensing lives in the contracts system. `url` points at the publisher; what may be done with
    what they publish is answered there, not here.

    `overlaps_source_id` records the ASAP2/PERSUADE finding so a
    later reader does not repeat the mistake of treating them as independent.
    """
    __tablename__ = "corpus_source"

    source_id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot: Mapped[date | None] = mapped_column()
    url: Mapped[str | None] = mapped_column(Text)
    paper_count: Mapped[int | None] = mapped_column(Integer)
    # Non-independence, recorded. ASAP2 shares 12,725 essays with PERSUADE at identical scores and
    # every one of its prompts is a PERSUADE prompt — a calibrate/validate split across the two
    # would be half-circular.
    # A DECLARATION, not a reference: the corpus it names may not be loaded here, and the fact
    # that two corpora overlap is most needed BEFORE the second one is loaded and treated as
    # independent. Migration 0031 dropped the foreign key that made load order decide whether the
    # fact could be recorded at all.
    overlaps_source_id: Mapped[str | None] = mapped_column(Text)
    overlap_note: Mapped[str | None] = mapped_column(Text)
    loaded_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()")


class CorpusPaper(Base):
    """One essay, with the demographics that make the fairness work possible before a real student.

    Subgroup labels on a public corpus are what let differential item functioning and subgroup
    abstention be tested during the POC rather than after it — two of the five stop conditions move
    inside the no-real-student-data scope because of these columns.

    They are columns rather than a JSONB blob because they are filtered on constantly and a
    fairness query should not depend on remembering a key name.
    """
    __tablename__ = "corpus_paper"

    paper_id: Mapped[str] = mapped_column(Text, primary_key=True)
    source_id: Mapped[str] = mapped_column(
        ForeignKey("corpus_source.source_id"), nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_hash: Mapped[str] = mapped_column(Text, nullable=False)   # cross-source overlap detection

    prompt_name: Mapped[str | None] = mapped_column(Text)
    task_type: Mapped[str | None] = mapped_column(Text)        # Independent | Text dependent
    grade_level: Mapped[str | None] = mapped_column(Text)
    word_count: Mapped[int | None] = mapped_column(Integer)

    # --- demographics, as shipped. Blank is preserved as NULL: absence of a label is not a label.
    gender: Mapped[str | None] = mapped_column(Text)
    ell_status: Mapped[str | None] = mapped_column(Text)
    race_ethnicity: Mapped[str | None] = mapped_column(Text)
    economically_disadvantaged: Mapped[str | None] = mapped_column(Text)
    disability_status: Mapped[str | None] = mapped_column(Text)
    # The task the student was answering. Feeds the fit gate, which without it does not run —
    # so a corpus paper skipped a stage that student work goes through, and the rater the anchor
    # set characterises was not quite the rater in production.
    assignment: Mapped[str | None] = mapped_column(Text)
    # The reading supplied with a text-dependent prompt. The evidence trait for that form is
    # defined as evidence "taken from the source text(s)", which cannot be judged by anything that
    # has not read the source.
    source_text: Mapped[str | None] = mapped_column(Text)

    partition: Mapped[str] = mapped_column(Text, nullable=False, server_default="unassigned")

    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_corpus_paper_external_id"),
        CheckConstraint(
            "partition IN (" + ",".join(f"'{p}'" for p in PARTITIONS) + ")", name="partition"),
        Index("ix_corpus_paper_hash", "text_hash"),
        Index("ix_corpus_paper_partition", "source_id", "partition"),
        Index("ix_corpus_paper_prompt", "source_id", "prompt_name"),
        # The fairness queries. Named so it is obvious why they exist.
        Index("ix_corpus_paper_ell", "source_id", "ell_status"),
        Index("ix_corpus_paper_race", "source_id", "race_ethnicity"),
    )


class CorpusScore(Base):
    """A score the corpus itself shipped — not one this system produced.

    Kept apart from `score_event` deliberately. These are one anonymous human judgment on a scale
    that is not ours, and folding them into the score record would put observations with no rater
    identity into a table whose whole purpose is that every observation has one.
    """
    __tablename__ = "corpus_score"

    corpus_score_id: Mapped[str] = mapped_column(Text, primary_key=True)
    paper_id: Mapped[str] = mapped_column(
        ForeignKey("corpus_paper.paper_id"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)     # holistic | element_effectiveness
    label: Mapped[str | None] = mapped_column(Text)             # which trait, where there is one
    value: Mapped[float] = mapped_column(Numeric, nullable=False)
    scale_min: Mapped[float | None] = mapped_column(Numeric)
    scale_max: Mapped[float | None] = mapped_column(Numeric)
    # Null for every row in the downloaded release. Present so that a corpus which DOES ship rater
    # identity can be loaded without a migration — and so its absence is visible rather than
    # inferred from a missing column.
    rater_id: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_corpus_score_paper", "paper_id", "kind"),
    )


class CorpusDiscourseSpan(Base):
    """Where an argumentative element sits in a paper.

    Segmentation without effectiveness in the downloaded release: you know where the counterclaim
    is, not how good it is. That is still enough to give the diagnostic channel ground truth for
    presence — 9,534 counterclaims and 7,217 rebuttals, the constructs taught in three places and
    scored in none.
    """
    __tablename__ = "corpus_discourse_span"

    span_id: Mapped[str] = mapped_column(Text, primary_key=True)
    paper_id: Mapped[str] = mapped_column(
        ForeignKey("corpus_paper.paper_id"), nullable=False)
    discourse_type: Mapped[str] = mapped_column(Text, nullable=False)
    start_char: Mapped[int | None] = mapped_column(Integer)
    end_char: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str | None] = mapped_column(Text)
    effectiveness: Mapped[str | None] = mapped_column(Text)   # absent in the current release

    __table_args__ = (
        Index("ix_corpus_span_paper", "paper_id"),
        Index("ix_corpus_span_type", "discourse_type"),
    )
