"""The writing product: student work, scored against a rubric, reviewed by the teacher.

A second product on the same server as SIP, not a part of it. Everything here imports `core`
(`app.config`, `app.db`, `app.security`, `app.models`) and its own module, never a SIP module and
never another writing module — `tests/test_module_boundaries.py` holds both rules. Its tables are
in the Postgres schema `writing`, reached at runtime as `writing_app` (migrations 0041–0042).

Modules: scoring, intake, delivery, measurement, roster, registry, corpus, pooling, and serving
(the teacher console's read side). See docs/MODULES.md.
"""
