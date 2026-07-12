# School Improvement Platform

A multi-tenant data platform for California school-improvement analysis. Public state
data (attendance, behavior, academics, …) is shared; a district's own data is isolated
by PostgreSQL row-level security. Built on a dimensional (star) model with per-fact ETL
loaders, on Cloud SQL.

## Layout

| Path | What |
|---|---|
| [`docs/TARGET_SCHEMA.md`](docs/TARGET_SCHEMA.md) | The data model spec — five layers (raw / staging / star / augment / marts), tenancy + RLS, missingness, instruments |
| [`docs/DATA_CATALOG.md`](docs/DATA_CATALOG.md) | The raw CA data sources and how they were obtained |
| [`backend/`](backend/) | FastAPI + SQLAlchemy + Alembic app: RLS schema, Secret-Manager config, and the ETL loaders |
| [`backend/etl/ca/`](backend/etl/ca/) | California public-data loaders (`load_ca_<fact>.py`) + [their README](backend/etl/ca/README.md) |
| [`mvp-setup-runbook.md`](mvp-setup-runbook.md) | Cloud SQL / Cloud Run / Identity Platform setup runbook |

## Status

- Cloud SQL Postgres with the full aggregate **star schema** (17 tables) + **row-level
  security** (tenant isolation proven), credentials in **Google Secret Manager**.
- **8 public metrics loaded** (chronic absenteeism, suspension, expulsion, graduation,
  stability, college-going, homelessness, enrollment) — ~960k `fact_metric` rows.

## Backend quickstart

See [`backend/README.md`](backend/README.md) for roles/bootstrap, migrations, the RLS
smoke test, and running the loaders.

---

_Raw data is not committed (it's large and reproducible); it lives outside this repo and
is documented in `docs/DATA_CATALOG.md`._
