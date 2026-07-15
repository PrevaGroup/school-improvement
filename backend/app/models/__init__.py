"""`core`'s schema: the star dims, the conformed fact, and tenancy. Nothing module-owned.

Module tables (likeschools' `feat_match_vector` / `mart_school_peer` /
`model_partition_stats`; sip's `plan_extraction` / `plan` / `plan_goal` / `plan_action`)
moved OUT of here 2026-07-15 and live with the module that writes them.

Do NOT re-export them from this file to "fix" a table missing from `Base.metadata`. That
makes `core` import a module and inverts the one dependency this structure rests on —
`core` is what modules depend on, never the reverse. Registration belongs in the two
places that genuinely need the full metadata, both of which are migration tooling and are
therefore allowed to know every module:

    migrations/env.py                            (autogenerate)
    migrations/versions/0001_initial_schema.py   (create_all on a fresh database)

backend/tests/test_schema_inventory.py fails if a table stops being registered — because
autogenerate reads a missing table as DROP TABLE.
"""
from .base import Base, PRIVATE_TABLES, SCHOOL_SCOPED_TABLES
from .reference import (
    DimTenant, TenantScope, TenantMembership,
    DimSchool, DimDate, DimStudentGroup, GroupCrosswalk,
    DimMetric, DimInstrument, DimPeerGroup, DimMetricRelationship,
    RefBenchmark,
)
from .tenant import DimPeriod, FactMetric, TenantMixin

__all__ = [
    "Base", "PRIVATE_TABLES", "SCHOOL_SCOPED_TABLES",
    # reference / conformed dimensions
    "DimTenant", "TenantScope", "TenantMembership",
    "DimSchool", "DimDate", "DimStudentGroup", "GroupCrosswalk",
    "DimMetric", "DimInstrument", "DimPeerGroup", "DimMetricRelationship",
    "RefBenchmark",
    # private / tenant-scoped
    "DimPeriod", "FactMetric",
    # the trust boundary a module applies to its own private tables
    "TenantMixin",
]
