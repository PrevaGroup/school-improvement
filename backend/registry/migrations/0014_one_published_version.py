"""registry — exactly one published node version, exactly one active configuration

Found while building the scoring driver, not while designing the registry, and that is the useful
part of the story. The driver joins `registry_node_version` on `status = 'published'` to assemble a
trait set. Nothing stopped a node from having two published versions at once, and with two the join
silently returns the node twice: the artifact gets scored on it twice, `rubric_version` differs
between the two events, and the trait set the artifact was scored against no longer matches the one
recorded. Every downstream number is then built on an item that appears twice with two wordings.

Nothing would have raised. The linter checks authoring quality, not this; the models declare no
constraint; every existing test passes. It only became visible by writing the query that depends
on it.

Same shape for `registry_scoring_configuration`: the driver reads the active configuration for a
key, and two active rows makes the rater ambiguous. A rater that cannot be named cannot have a
severity estimated, which is most of why the configuration is a versioned object at all.

Partial unique indexes rather than triggers: the rule is decidable from the rows themselves, and a
constraint that the planner can also use is better than a function nobody reads. Superseded,
withdrawn and draft rows are unaffected — a node keeps its whole history, and only the count of
CURRENT ones is bounded.

Revision ID: 0014
Revises: 0013
"""
from __future__ import annotations

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE UNIQUE INDEX uq_registry_node_one_published
        ON registry_node_version (node_id)
     WHERE status = 'published';

    CREATE UNIQUE INDEX uq_registry_configuration_one_active
        ON registry_scoring_configuration (config_key)
     WHERE status = 'active';
    """)


def downgrade() -> None:
    op.execute("""
    DROP INDEX IF EXISTS uq_registry_configuration_one_active;
    DROP INDEX IF EXISTS uq_registry_node_one_published;
    """)
