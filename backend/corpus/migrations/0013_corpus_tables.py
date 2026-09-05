"""corpus tables — the papers calibration is anchored on

Public reference content, no tenancy: identical for every district, which is what lets two
districts sit on one metric without a cross-tenant query.

No trigger here and none needed. The corpus is loaded by bulk ETL and read; it has no state machine
and no authority claim attached to it. What the schema does carry is the two facts the downloaded
files established and that a later reader would otherwise have to rediscover:

  * `corpus_score.rater_id` exists and is NULL for every row in this release. The column is present
    so that a corpus which DOES ship rater identity can be loaded without a migration — and so the
    absence is visible rather than inferred from a missing column. Severity is not estimable from
    an anonymous pool.
  * `corpus_source.overlaps_source_id` records non-independence between sources. ASAP2 shares
    12,725 essays with PERSUADE byte-identical at identical scores; a calibrate-on-one /
    validate-on-the-other split across them would be circular.

Revision ID: 0013
Revises: 0012
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "corpus_source",
        sa.Column("source_id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("snapshot", sa.Date()),
        sa.Column("licence", sa.Text()),
        sa.Column("url", sa.Text()),
        sa.Column("paper_count", sa.Integer()),
        sa.Column("overlaps_source_id", sa.Text(), sa.ForeignKey("corpus_source.source_id")),
        sa.Column("overlap_note", sa.Text()),
        sa.Column("loaded_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "corpus_paper",
        sa.Column("paper_id", sa.Text(), primary_key=True),
        sa.Column("source_id", sa.Text(), sa.ForeignKey("corpus_source.source_id"),
                  nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_hash", sa.Text(), nullable=False),
        sa.Column("prompt_name", sa.Text()),
        sa.Column("task_type", sa.Text()),
        sa.Column("grade_level", sa.Text()),
        sa.Column("word_count", sa.Integer()),
        sa.Column("gender", sa.Text()),
        sa.Column("ell_status", sa.Text()),
        sa.Column("race_ethnicity", sa.Text()),
        sa.Column("economically_disadvantaged", sa.Text()),
        sa.Column("disability_status", sa.Text()),
        sa.Column("partition", sa.Text(), nullable=False, server_default="unassigned"),
        sa.UniqueConstraint("source_id", "external_id", name="uq_corpus_paper_external_id"),
        sa.CheckConstraint("partition IN ('calibration','validation','unassigned')",
                           name="partition"),
    )
    op.create_index("ix_corpus_paper_hash", "corpus_paper", ["text_hash"])
    op.create_index("ix_corpus_paper_partition", "corpus_paper", ["source_id", "partition"])
    op.create_index("ix_corpus_paper_prompt", "corpus_paper", ["source_id", "prompt_name"])
    # The fairness queries — DIF and subgroup abstention run against these constantly.
    op.create_index("ix_corpus_paper_ell", "corpus_paper", ["source_id", "ell_status"])
    op.create_index("ix_corpus_paper_race", "corpus_paper", ["source_id", "race_ethnicity"])

    op.create_table(
        "corpus_score",
        sa.Column("corpus_score_id", sa.Text(), primary_key=True),
        sa.Column("paper_id", sa.Text(), sa.ForeignKey("corpus_paper.paper_id"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("label", sa.Text()),
        sa.Column("value", sa.Numeric(), nullable=False),
        sa.Column("scale_min", sa.Numeric()),
        sa.Column("scale_max", sa.Numeric()),
        sa.Column("rater_id", sa.Text()),
    )
    op.create_index("ix_corpus_score_paper", "corpus_score", ["paper_id", "kind"])

    op.create_table(
        "corpus_discourse_span",
        sa.Column("span_id", sa.Text(), primary_key=True),
        sa.Column("paper_id", sa.Text(), sa.ForeignKey("corpus_paper.paper_id"), nullable=False),
        sa.Column("discourse_type", sa.Text(), nullable=False),
        sa.Column("start_char", sa.Integer()),
        sa.Column("end_char", sa.Integer()),
        sa.Column("text", sa.Text()),
        sa.Column("effectiveness", sa.Text()),
    )
    op.create_index("ix_corpus_span_paper", "corpus_discourse_span", ["paper_id"])
    op.create_index("ix_corpus_span_type", "corpus_discourse_span", ["discourse_type"])


def downgrade() -> None:
    op.drop_table("corpus_discourse_span")
    op.drop_table("corpus_score")
    op.drop_table("corpus_paper")
    op.drop_table("corpus_source")
