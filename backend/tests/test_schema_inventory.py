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

So this imports the same way env.py does today, and fails if the inventory changes.

If you moved a model and this went red: **do not edit EXPECTED_TABLES to match.** The table
still exists in the database — only the model's location changed, and that's the bug. Only
edit the list when you have genuinely added or dropped a table on purpose, in the same commit
as its migration.

The right fix depends on where the model went, and one of the two options is a trap:

* **Wrong:** re-export it from `app/models/__init__.py` so `app.models` reaches it again. That
  makes `core` import a module, inverting the dependency the whole reorg exists to establish
  — `core` is the thing modules depend on, never the reverse.
* **Right:** have `migrations/env.py` import the module's models directly, alongside `Base`.
  env.py is migration tooling, not `core`, so it is allowed to know every module — that's the
  same exemption `app/main.py` gets as the composition root.

Taking the second path means env.py and this test stop agreeing on one import, so update the
import here to match env.py's list in the same commit. That coupling is deliberate: these two
must be read together or the guard stops guarding.
"""
import importlib.util
import pathlib

from sqlalchemy import create_mock_engine

from app.models import Base, PRIVATE_TABLES, SCHOOL_SCOPED_TABLES

# Mirror migrations/env.py exactly: it imports each table-owning module so their models
# register on Base.metadata. `core` alone no longer knows them (that's the point of the
# carve-out), so without these two lines this file would see 14 tables, not 21 — and would
# "prove" that 7 tables had vanished. If env.py's import list changes, change it here too.
import etl.ca.sip.models  # noqa: E402,F401  — plan_extraction, plan, plan_goal, plan_action
import etl.peers.models   # noqa: E402,F401  — feat_match_vector, mart_school_peer, model_partition_stats

# table -> the module that OWNS it (writes it). As of the carve-out (2026-07-15) this map is
# REAL, not aspirational: each table's model lives in its owning module's models.py, and core
# declares only what's marked core below.
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
    # --- likeschools' tables — declared in etl/peers/models.py ---
    "feat_match_vector": "likeschools",
    "mart_school_peer": "likeschools",
    "model_partition_stats": "likeschools",
    # --- sip's tables — declared in etl/ca/sip/models.py ---
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
        "--autogenerate` would now emit DROP TABLE for them. If a model moved, make sure "
        "migrations/env.py still imports it (NOT by re-exporting from app.models — that "
        "inverts core). Do not just delete it from EXPECTED_TABLES; read this module's "
        "docstring first."
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


# Tables a revision AFTER 0001 creates with its own op.create_table().
TABLES_OWNED_BY_LATER_REVISIONS = {
    "plan_extraction": "0003_plan_extraction.py",
    "feat_match_vector": "0004_peer_tables.py",
    "mart_school_peer": "0004_peer_tables.py",
    "model_partition_stats": "0004_peer_tables.py",
}


def _revision_0001():
    path = pathlib.Path(__file__).resolve().parent.parent / "migrations/versions/0001_initial_schema.py"
    spec = importlib.util.spec_from_file_location("revision_0001", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_0001_does_not_create_tables_that_later_revisions_own():
    """Regression: `alembic upgrade head` on an EMPTY database must reach head.

    0001 builds its tables with `Base.metadata.create_all()`, i.e. from the live models.
    Unbounded, that creates every table the models currently declare — including ones a
    later revision owns. It created plan_extraction, and then 0003's
    op.create_table("plan_extraction") hit an existing table and blew up. Nobody noticed
    because it only breaks a from-scratch build, which is exactly what
    sql/20_reset_database.sql exists to do ("proving the full chain builds from nothing").

    So: whatever DDL 0001 emits must not touch a later revision's tables. This renders the
    actual CREATE TABLE statements through a mock engine — no database required.
    """
    revision = _revision_0001()
    baseline = [*revision.REFERENCE_TABLES, *revision.PRIVATE_TABLES]

    created: list[str] = []

    def record(sql, *args, **kwargs):
        text = str(sql.compile(dialect=engine.dialect))
        if "CREATE TABLE" in text:
            created.append(text.split("CREATE TABLE")[1].split("(")[0].strip())

    engine = create_mock_engine("postgresql+psycopg://", record)
    Base.metadata.create_all(engine, tables=[Base.metadata.tables[t] for t in baseline])

    collisions = {t: rev for t, rev in TABLES_OWNED_BY_LATER_REVISIONS.items() if t in created}
    assert not collisions, (
        f"0001 creates tables owned by later revisions: {collisions}. `alembic upgrade head` "
        "on an empty database will fail there with DuplicateTable. Keep 0001's create_all "
        "bounded to REFERENCE_TABLES + PRIVATE_TABLES."
    )

    missing = [t for t in baseline if t not in created]
    assert not missing, (
        f"0001 declares {missing} in its baseline but doesn't create them — the GRANT/RLS "
        "loops that follow will fail on tables that don't exist."
    )
