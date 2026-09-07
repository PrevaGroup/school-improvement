"""registry — the rubric is a thing with an identifier, and so is a trait

The registry could hold exactly one rubric, and only by accident. A trait carried the rubric it
came from as a PROSE STRING repeated on every row —

    "LDC Student Work Rubric - Argumentation Task, Grades 11-12, exported from CoreTools 09/23/2024"

— which cannot be joined, cannot be counted, and cannot be a second value without someone typing it
identically. That is the hidden-facet shape this schema was built to avoid, sitting in the middle
of the registry itself. The SCALE argumentative rubric is not the only rubric; the system has to
hold many.

## The shape

    standard  ->  skill  ->  rubric  ->  trait  ->  criteria

A SKILL IS A SUB-STANDARD, in one of two ways, and the difference between them is recorded rather
than flattened. Either the standard already carries lettered parts (X.1a, X.1b, X.1c) and the skill
is one of them — a fact about the standards document — or the standard is one compound sentence
carrying several demands and somebody SPLIT it into clauses, which is a judgment. Two readers split
a compound standard differently, so `derivation` says which kind it is and who is answerable for
it. A schema that stored both as "sub-standard" would lose the distinction between what a document
says and what a person decided it meant.

A skill with no rubric is not an error — it is a taught thing that is not scored, which the review
console already says in as many words: "This lesson carries no scoring guide, so nothing here is
measured." `rubric_id` is therefore nullable, and the unscored case is representable rather than a
gap somebody has to explain.

`registry_node` IS the trait — the thing with a scale, whose descriptors ARE its criteria — and it
needs no change beyond an identifier that looks like one. What was missing is its parent.

## Rubric-to-trait is MANY-TO-MANY, and that is the load-bearing decision

A trait is not owned by a rubric. The same trait identifier appearing in two rubrics is precisely
how commonality gets DECLARED: a product manager issues one identifier and uses it in both, and
that assertion is what makes the two rubrics comparable. It is also the mechanism the whole
measurement design depends on — a trait shared between rubrics is the anchor that places both on
one metric. Own a trait to one rubric and every rubric floats on its own scale, with no arithmetic
that can ever bring them together.

Because it is an assertion, the data can refute it. That is a standing check, not a release gate.

## Why the identifiers are UUIDs, and why the column is still text

A trait identifier is issued once and never recycled; every historical score is stamped with it. A
value someone can type by hand is a value someone can type twice, and `ci` is a value someone can
type by hand. A CHECK now requires the canonical UUID form.

The column stays `text` rather than becoming `uuid`. `score_event.node_id` is text and holds
millions of stamps eventually; a type change there is a rewrite of the record for a guarantee that
belongs where identifiers are AUTHORED, not where they are recorded. The CHECK sits on the registry
side, which is the only place a new identifier is minted.

Publisher identifiers do not disappear — `external_ref` carries CoreTools' own id, or PERSUADE's,
without letting it become the identity. Two systems' identifiers for one thing is exactly the
situation an identity column must not be asked to hold.

## Order of operations

This migration adds a CHECK that existing demo rows violate (`demo-ci` is not a UUID). Purge the
demo BEFORE upgrading:

    python -m scoring.seed_demo --purge && python -m registry.seed_demo --purge

Revision ID: 0019
Revises: 0018
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

UUID_RE = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"


def upgrade() -> None:
    op.create_table(
        "registry_skill",
        sa.Column("skill_id", sa.Text(), primary_key=True),
        # The parent standard, e.g. RH.11-12.6 — and the sub-code within it, e.g. 'a' or '2'.
        sa.Column("standard_code", sa.Text(), nullable=False),
        sa.Column("sub_code", sa.Text()),
        sa.Column("statement", sa.Text(), nullable=False),
        # `lettered` — the standards document itself carries X.1a; a fact.
        # `clause`   — a compound standard was split by a person; a judgment, and two readers
        #              split differently, so it is recorded as one.
        # `whole`    — the standard is not compound and the skill IS the standard.
        sa.Column("derivation", sa.Text(), nullable=False),
        sa.Column("derived_by", sa.Text()),      # who is answerable for a `clause` split
        sa.Column("grade_band", sa.Text()),
        # Nullable ON PURPOSE: a skill with no rubric is taught and not scored, which the review
        # console states outright. An unscored skill must be representable.
        sa.Column("rubric_id", sa.Text()),
        sa.Column("source", sa.Text()),
        sa.Column("external_ref", sa.Text()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(f"skill_id ~ '{UUID_RE}'", name="skill_id_is_a_uuid"),
        sa.CheckConstraint("derivation IN ('lettered','clause','whole')", name="derivation"),
        # A split somebody made is a split somebody has to own.
        sa.CheckConstraint("derivation <> 'clause' OR derived_by IS NOT NULL",
                           name="a_clause_split_is_attributed"),
    )
    op.create_index("ix_registry_skill_standard", "registry_skill",
                    ["standard_code", "grade_band"])

    op.create_table(
        "registry_rubric",
        sa.Column("rubric_id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        # Who authored it. Two rubrics with the same name from different publishers are two
        # rubrics, and the only thing that reliably tells them apart is this.
        sa.Column("publisher", sa.Text()),
        sa.Column("source", sa.Text()),          # the export, the paper, the URL
        sa.Column("grade_band", sa.Text()),
        # The publisher's own identifier, kept so it never has to become the identity.
        sa.Column("external_ref", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("retired_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(f"rubric_id ~ '{UUID_RE}'", name="rubric_id_is_a_uuid"),
        sa.CheckConstraint("status IN ('draft','published','superseded','withdrawn')",
                           name="status"),
    )
    op.create_index("ix_registry_rubric_publisher", "registry_rubric",
                    ["publisher", "grade_band"])
    # Added after registry_rubric exists, because a skill points at one.
    op.create_foreign_key("fk_registry_skill_rubric_id_registry_rubric", "registry_skill",
                          "registry_rubric", ["rubric_id"], ["rubric_id"])
    op.create_index("ix_registry_skill_rubric", "registry_skill", ["rubric_id"])

    # MANY-to-many. A trait in two rubrics is one trait used twice, which is how commonality is
    # declared and how two rubrics come to share a metric.
    op.create_table(
        "registry_rubric_trait",
        sa.Column("rubric_id", sa.Text(), sa.ForeignKey("registry_rubric.rubric_id"),
                  primary_key=True),
        sa.Column("node_id", sa.Text(), sa.ForeignKey("registry_node.node_id"),
                  primary_key=True),
        sa.Column("ordinal", sa.Integer()),
    )
    op.create_index("ix_registry_rubric_trait_node", "registry_rubric_trait", ["node_id"])

    op.add_column("registry_node", sa.Column("external_ref", sa.Text()))
    op.create_check_constraint("node_id_is_a_uuid", "registry_node", f"node_id ~ '{UUID_RE}'")

    # Which rubric an occasion is scored on. `registry_scoring_site_node` stays as the FROZEN
    # resolved trait set: a rubric edited later must not retroactively change what was scored.
    op.add_column("registry_scoring_site",
                  sa.Column("rubric_id", sa.Text(), sa.ForeignKey("registry_rubric.rubric_id")))
    op.create_index("ix_registry_scoring_site_rubric", "registry_scoring_site", ["rubric_id"])


def downgrade() -> None:
    op.drop_index("ix_registry_scoring_site_rubric", "registry_scoring_site")
    op.drop_column("registry_scoring_site", "rubric_id")
    op.drop_constraint("ck_registry_node_node_id_is_a_uuid", "registry_node")
    op.drop_column("registry_node", "external_ref")
    op.drop_table("registry_rubric_trait")
    op.drop_table("registry_skill")
    op.drop_table("registry_rubric")
