"""Pin every table registered on `Base.metadata` — the guard for the core carve-out.

## The failure this exists to catch

`migrations/env.py` does exactly one thing to discover the schema:

    from app.models import Base
    target_metadata = Base.metadata

A model class only lands in `Base.metadata` if importing `app.models` imports it. The next
step of the reorg (docs/MODULES.md) moves module-owned tables OUT of `core` — likeschools'
`feat_match_vector` / `mart_school_peer` / `model_partition_stats`, sip's `plan_extraction`
and `plan` / `plan_goal` / `plan_action`. The moment one of those moves somewhere
`app/models/__init__.py` no longer imports, it silently vanishes from `target_metadata` —
and `alembic revision --autogenerate` reads "table not in the model" as **DROP TABLE**.

That is a data-loss bug reviews miss, because the diff that causes it (a model moving to a
new file) looks entirely harmless, and the DROP appears later, in a *generated* migration
nobody hand-wrote.

So this imports the same way env.py does, and fails if the inventory changes. If you moved a
model and this went red, do NOT edit EXPECTED_TABLES to match — re-export the model so
`app.models` still reaches it. Only edit the list when you have genuinely added or dropped a
table on purpose, in the same commit as its migration.
"""
from app.models import Base, PRIVATE_TABLES, SCHOOL_SCOPED_TABLES

# table -> the module that OWNS it (writes it). Ownership is aspirational for the ones marked
# "in core today": that mismatch IS the remaining reorg work — core currently owns module
# tables, which is why "core is a frozen contract" isn't true yet.
EXPECTED_TABLES: dict[str, str] = {
    # --- genuinely core: the star schema spine + tenancy ---
    "dim_date": "core",
    "dim_instrument": "core",
    "dim_metric": "core",
    "dim_metric_relationship": "core",
    "dim_peer_group": "core",
    "dim_period": "core",
    "dim_school": "core",
    "dim_student_group": "core",
    "dim_tenant": "core",
    "group_crosswalk": "core",
    "ref_benchmark": "core",
    "tenant_membership": "core",
    "tenant_scope": "core",
    # --- public_metrics writes it; core defines it (conformed fact — stays in core) ---
    "fact_metric": "public_metrics",
    # --- likeschools' tables (in core/reference.py today; move with the carve-out) ---
    "feat_match_vector": "likeschools",
    "mart_school_peer": "likeschools",
    "model_partition_stats": "likeschools",
    # --- sip's tables (in core reference.py / tenant.py today; move with the carve-out) ---
    "plan_extraction": "sip",
    "plan": "sip",
    "plan_goal": "sip",
    "plan_action": "sip",
}


def test_no_table_silently_leaves_the_metadata():
    """The DROP TABLE guard. Read this test's docstring before touching EXPECTED_TABLES."""
    registered = set(Base.metadata.tables)
    expected = set(EXPECTED_TABLES)
    missing = sorted(expected - registered)
    added = sorted(registered - expected)
    assert not missing, (
        f"{missing} are no longer registered on Base.metadata. `alembic revision "
        "--autogenerate` would now emit DROP TABLE for them. If a model moved, re-export it "
        "so `from app.models import Base` still imports it — do NOT just delete it from "
        "EXPECTED_TABLES."
    )
    assert not added, (
        f"New tables on Base.metadata: {added}. Add them to EXPECTED_TABLES with their owning "
        "module, in the same commit as their migration."
    )


def test_rls_table_sets_are_unchanged():
    """PRIVATE_TABLES drives RLS policy generation — a silent change here is a tenancy leak.

    These are the tables the trust boundary depends on (CLAUDE.md / ARCHITECTURE.md), so they
    get pinned separately from the inventory above: a table could stay registered while quietly
    dropping out of the private set, which the inventory test would not notice.
    """
    assert set(PRIVATE_TABLES) == {"dim_period", "fact_metric", "plan", "plan_action", "plan_goal"}
    assert set(SCHOOL_SCOPED_TABLES) == {"fact_metric"}


def test_private_tables_are_actually_registered():
    """A name in PRIVATE_TABLES that matches no real table would generate RLS for nothing."""
    unknown = sorted(set(PRIVATE_TABLES) - set(Base.metadata.tables))
    assert not unknown, f"PRIVATE_TABLES names tables that don't exist: {unknown}"
