# School Improvement Platform

The objective of this project was to develop a working prototype that implements current
state of the art agentic data analytics. This project will likely be out of date tomorrow.
All code was developed using Claude.

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
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Architecture: request/trust flow, data-model layers, ingest pipelines, repo index, remaining tasks |
| [`CLAUDE.md`](CLAUDE.md) | How to work in this repo — module boundaries, `core` as a frozen contract |
| [`docs/MODULES.md`](docs/MODULES.md) | Module registry — what each module owns and reads, and reorg status |
| [`docs/design/`](docs/design/) | Design notes, e.g. extraction-time relevance tagging for SIP → mart |

## Status

- **Live on Cloud Run** — an IAM-gated **school diagnostic workspace**: three peer-benchmarked
  indicators (chronic absenteeism, graduation rate, college-going), the school's full SPSA, its
  demographically-matched peers, and a **grounded chat** with five tools over all of it.
- Cloud SQL Postgres with the full aggregate **star schema** (17 tables) + **row-level
  security** (tenant isolation proven), credentials in **Google Secret Manager**.
- **8 public metrics loaded** (chronic absenteeism, suspension, expulsion, graduation,
  stability, college-going, homelessness, enrollment) — ~960k `fact_metric` rows.
- **SIP extraction run**: 74 of 77 Long Beach SPSAs (plus Ventura) extracted PDF → JSON →
  `plan_extraction`, via the batch path (`batch_extract` → GCS → `load_plan_extractions`).
- **"Schools like you" peer engine** (Mahalanobis kNN on *inputs* — poverty, EL, disability,
  size, locale — never outcomes) and the **marts layer** are built and serving.

> **⚠️ The deployed service is a temporary demo, not the production architecture.** It is gated
> by **Cloud Run IAM** (not GCIP), serves a **no-build React UI from the app itself** (no
> Vite/Cloudflare), and reads the **public `plan_extraction`** marts rather than the private
> tenant `/plans` path this repo also specifies.

**Planned:** GCIP sign-in + user provisioning · the private-tenant `/plans` serving path · a
real React + Vite frontend · extraction-time metric tagging to replace the keyword relevance
filter ([design note](docs/design/plan-relevance-tagging.md)).

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the full picture and remaining tasks.

## Backend quickstart

See [`backend/README.md`](backend/README.md) for roles/bootstrap, migrations, the RLS
smoke test, and running the loaders.

---

_Raw data is not committed (it's large and reproducible); it lives outside this repo and
is documented in `docs/DATA_CATALOG.md`._
