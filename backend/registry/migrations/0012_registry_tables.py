"""registry tables — nodes, tasks, scoring sites, and the scoring configuration

Configuration in the pipeline design's sense: authored before any run, applying to every artifact
in scope, reviewed on a release cadence. It fails silently and at scale, which is why the shapes
here lean on constraints and why the linter exists beside them.

Two things are enforced by the schema rather than by the linter, because they are decidable without
judgment:

  * a node's scale is immutable — `scale_categories` sits on the node, not the version, so a
    different category count cannot be a new version. It has to be a new node, which is the correct
    answer: a difference in category count is evidence the rubrics drew the construct differently.
  * a published node version is frozen — a trigger rejects an edit to its descriptors, because a
    score already stamped with v2 has to keep meaning what it meant.

Revision ID: 0012
Revises: 0011
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "registry_node",
        sa.Column("node_id", sa.Text(), primary_key=True),
        sa.Column("standard_code", sa.Text(), nullable=False),
        sa.Column("criterion_label", sa.Text(), nullable=False),
        sa.Column("grade_band", sa.Text(), nullable=False),
        sa.Column("scale_categories", postgresql.JSONB(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False, server_default="module_local"),
        sa.Column("source", sa.Text()),
        sa.Column("retired_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("kind IN ('anchor','module_local','diagnostic_only')",
                           name="ck_registry_node_kind"),
        sa.CheckConstraint("jsonb_array_length(scale_categories) >= 2",
                           name="ck_registry_node_scale_fittable"),
    )
    op.create_index("ix_registry_node_standard", "registry_node",
                    ["standard_code", "grade_band"])
    op.create_index("ix_registry_node_kind", "registry_node", ["kind"])

    op.create_table(
        "registry_node_version",
        sa.Column("node_version_id", sa.Text(), primary_key=True),
        sa.Column("node_id", sa.Text(), sa.ForeignKey("registry_node.node_id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("descriptors", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("change_note", sa.Text()),
        sa.Column("construct_unchanged_ack", sa.Text()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("node_id", "version", name="uq_registry_node_version"),
        sa.CheckConstraint("status IN ('draft','published','superseded','withdrawn')",
                           name="ck_registry_node_version_status"),
    )
    op.create_index("ix_registry_node_version_node", "registry_node_version",
                    ["node_id", "status"])

    op.create_table(
        "registry_task",
        sa.Column("task_id", sa.Text(), primary_key=True),
        sa.Column("module_key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer()),
        sa.Column("grade_band", sa.Text()),
        sa.Column("standards", postgresql.JSONB()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_registry_task_module", "registry_task", ["module_key", "ordinal"])

    op.create_table(
        "registry_scoring_site",
        sa.Column("site_id", sa.Text(), primary_key=True),
        sa.Column("task_id", sa.Text(), sa.ForeignKey("registry_task.task_id"), nullable=False),
        sa.Column("iteration", sa.Text(), nullable=False),
        sa.Column("is_measurement_occasion", sa.Boolean(), nullable=False,
                  server_default="false"),
        sa.Column("note", sa.Text()),
        sa.UniqueConstraint("task_id", "iteration", name="uq_registry_scoring_site_iteration"),
    )
    op.create_index("ix_registry_scoring_site_task", "registry_scoring_site", ["task_id"])

    op.create_table(
        "registry_scoring_site_node",
        sa.Column("site_id", sa.Text(), sa.ForeignKey("registry_scoring_site.site_id"),
                  primary_key=True),
        sa.Column("node_id", sa.Text(), sa.ForeignKey("registry_node.node_id"),
                  primary_key=True),
        sa.Column("ordinal", sa.Integer()),
    )
    op.create_index("ix_registry_site_node_node", "registry_scoring_site_node", ["node_id"])

    op.create_table(
        "registry_scoring_configuration",
        sa.Column("config_id", sa.Text(), primary_key=True),
        sa.Column("config_key", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("effort", sa.Text()),
        sa.Column("prompt_versions", postgresql.JSONB(), nullable=False),
        sa.Column("normalization_version", sa.Text(), nullable=False),
        sa.Column("definition_hash", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("supersedes_config_id", sa.Text(),
                  sa.ForeignKey("registry_scoring_configuration.config_id")),
        sa.Column("promoted_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("promoted_by", sa.Text()),
        sa.Column("second_approver", sa.Text()),
        sa.Column("rationale", sa.Text()),
        sa.Column("replay_run_id", sa.Text()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("config_key", "version", name="uq_registry_configuration_version"),
        sa.CheckConstraint("status IN ('draft','active','superseded','withdrawn')",
                           name="ck_registry_configuration_status"),
        # A promotion without a recorded reason is a change nobody can explain later.
        sa.CheckConstraint(
            "status <> 'active' OR (promoted_by IS NOT NULL AND rationale IS NOT NULL)",
            name="ck_registry_configuration_promotion_recorded"),
    )
    op.create_index("ix_registry_configuration_key", "registry_scoring_configuration",
                    ["config_key", "status"])

    op.execute("""
    -- A published node version is frozen. A score stamped with v2 has to keep meaning what it
    -- meant, so a wording change is a new version and a construct change is a new node.
    CREATE FUNCTION registry_freeze_published_version() RETURNS trigger AS $$
    BEGIN
        IF OLD.status IN ('published', 'superseded', 'withdrawn')
           AND NEW.descriptors IS DISTINCT FROM OLD.descriptors THEN
            RAISE EXCEPTION
              'registry_node_version % is % — descriptors are frozen. Create a new version.',
              OLD.node_version_id, OLD.status
              USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    CREATE TRIGGER trg_registry_node_version_freeze
        BEFORE UPDATE ON registry_node_version
        FOR EACH ROW EXECUTE FUNCTION registry_freeze_published_version();

    -- A node's scale is its identity. Changing the category count means a different construct was
    -- drawn, which is a different node — not a mutation of this one.
    CREATE FUNCTION registry_freeze_node_scale() RETURNS trigger AS $$
    BEGIN
        IF NEW.scale_categories IS DISTINCT FROM OLD.scale_categories
           OR NEW.standard_code IS DISTINCT FROM OLD.standard_code
           OR NEW.grade_band IS DISTINCT FROM OLD.grade_band THEN
            RAISE EXCEPTION
              'registry_node % — standard, grade band and scale are the identity and cannot '
              'change. Issue a new node identifier.', OLD.node_id
              USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    CREATE TRIGGER trg_registry_node_freeze
        BEFORE UPDATE ON registry_node
        FOR EACH ROW EXECUTE FUNCTION registry_freeze_node_scale();
    """)


def downgrade() -> None:
    op.execute("""
    DROP TRIGGER IF EXISTS trg_registry_node_freeze ON registry_node;
    DROP FUNCTION IF EXISTS registry_freeze_node_scale();
    DROP TRIGGER IF EXISTS trg_registry_node_version_freeze ON registry_node_version;
    DROP FUNCTION IF EXISTS registry_freeze_published_version();
    """)
    op.drop_table("registry_scoring_configuration")
    op.drop_table("registry_scoring_site_node")
    op.drop_table("registry_scoring_site")
    op.drop_table("registry_task")
    op.drop_table("registry_node_version")
    op.drop_table("registry_node")
