# likeschools — "Schools Like You"

Input-matched demographic peer groups: for each school, the *k* nearest schools of the same
instructional level by **Mahalanobis distance** over standardized demographic **input** features
(never outcomes). Downstream, "how is this school doing?" is always answered *relative to its
peers*, so demographics aren't used as an excuse and improvement is measured fairly.

> **The code is the source of truth.** The three `school-classification-*.md` design docs in this
> folder capture the concept, the literature review, and the original spec — but they describe
> *dev alternatives* and have **drifted from what shipped**. Where they disagree with the code,
> the code wins. The reconciled truth is below.

## Where every component lives (component map)

**likeschools is the matching ENGINE — it has no serving surface.** It computes peer sets and
writes `mart_school_peer`; that table is its whole contract. The `/marts/like-schools` and
`/marts/peer-benchmark` endpoints and the chat tools over them belong to **`serving`** and are
listed below only so you know where they are — they are not yours to change from here. (Decided
2026-07-15: `serving` needs `fetch_peer_benchmark` for two other features, so peer serving living
here forced a cross-module import. See `docs/MODULES.md` and §4 of `ARCHITECTURE.md`.)

| Concern | File(s) today | Notes |
|---|---|---|
| **Design docs** | `backend/likeschools/*.md` (concept, lit-review, spec) | drifted — reference only |
| **Matching engine** | `backend/etl/peers/build_peers.py` | the Mahalanobis matcher (the thing you'd edit to change the algorithm) |
| **Schema / DDL** | `backend/migrations/versions/0004_peer_tables.py` | creates the 3 owned tables |
| **ORM models** | `backend/etl/peers/models.py` → `FeatMatchVector`, `MartSchoolPeer`, `ModelPartitionStats` | moved out of core 2026-07-15; registered via `migrations/env.py` + `0001` |
| **Dependency** | `backend/requirements.txt` → `scikit-learn` | used only by the matcher |
| *(not this module)* | `backend/app/marts.py`, `backend/app/chat.py` | peer serving + chat tools — owned by **`serving`**, which reads `mart_school_peer` with SQL |

Legacy, do **not** confuse: `dim_peer_group` + `dim_school.peer_group_id` (in `reference.py`) are
an **older rule/kmeans peer concept**, superseded by the Mahalanobis `mart_school_peer`. Leave
them alone unless you're deliberately removing the legacy path.

## The contract (what makes this swappable)

**Owned tables** (all PUBLIC / no-RLS — computed from the public universe, identical per tenant):
- `feat_match_vector` — standardized match vector per school
- `mart_school_peer` — the precomputed k-nearest peer lists ← **this is the seam**
- `model_partition_stats` — per-partition model provenance (means, sds, shrinkage, precision matrix)

**Reads:** `dim_school` **input** features only (`pct_sed`, `pct_el`, `pct_swd`, `enroll_total`,
`locale`, `school_level`). Hard rule (spec D1): the matcher must **never read outcome metrics** —
that's what keeps peer-relative performance honest.

**Downstream consumers** (`marts.py`, `chat.py`) read `mart_school_peer` by its column shape. So:
you can rewrite the matcher however you like — different distance, different features, a totally
different method — and nothing downstream breaks **as long as `mart_school_peer` keeps the same
columns**. That table is the module's public API.

## How the algorithm actually works (reconciled to the code)

Per instructional-level partition (`build_peers.py`, following spec §4.2 Path A):
`impute (within-level median) → z-score → Ledoit-Wolf shrinkage covariance →
NearestNeighbors(metric='mahalanobis', VI=precision_) → keep k nearest, drop self`.

**Deviations from the spec docs — the code does this, the docs don't:**
- Keyed on `dim_school.school_id` (NCES) + `school_year` (text), **not** `nces_id`/smallint.
- Match features come from `dim_school`: `pct_sed`, `pct_el`, `pct_swd`, `enroll_total` (log1p),
  `locale` (one-hot: city/suburb/town/rural).
- The economic-disadvantage feature (`f_econ_disadv`) is **CA SED**, not the federal **FRPL** the
  spec's "% economically disadvantaged (or FRPL)" wording (§3.1) implies. They are *not* the same
  population: CA SED (CDE/CALPADS) = FRPM-eligible **OR** neither parent holds a HS diploma (plus
  foster/homeless/migrant/direct-certified), a union that flags more students than FRPL's pure
  income proxy (EDFacts FS033/CCD, NSLP ≤130%/≤185% of poverty). Harmless while the universe is
  CA-only (values are z-scored within partition, so it's internally conformed). **But the moment a
  non-CA state is ingested via EDFacts/CCD FRPL, `pct_sed` and `pct_frpl` would land in the same
  `f_econ_disadv` slot while measuring different populations — cross-state peers would then match on
  an apples-to-oranges economic axis.** The honest fix for multi-state is a conformed
  economic-disadvantage definition in `core` vocab (pick one basis, or carry both and choose
  per-source), not silent pooling.
- **Race is excluded** from the match vector (spec D8 default; `dim_school` carries no per-school
  race anyway).
- A single run-year label (`--year`, default = `max(dim_school.school_year)`) covers all current
  schools, avoiding fragmentation from mixed fact-stub years.
- `MIN_PARTITION = 3` — below that a level can't form a meaningful peer set.

## How to update the algorithm (runbook)

1. Edit **`backend/etl/peers/build_peers.py`** (`FEATURES`/`CORE`, `level_bucket()`, the distance
   step, `k`, confidence percentile). This is the only file that defines the method.
2. If you add/rename an **output column**, that's a contract change — `mart_school_peer`'s shape
   is the only thing the rest of the system depends on. Update the DDL
   (`migrations/versions/0004_peer_tables.py` or a new migration), the models in
   `etl/peers/models.py`, **and** every reader (`serving` queries the table with SQL — grep
   `mart_school_peer`). Otherwise downstream is unaffected: that's the point of the seam.
3. Rebuild (from `backend/`, needs scikit-learn + DB via Auth Proxy + ADC):
   `python -m etl.peers.build_peers [--k 50] [--year 2025-26] [--conf-pctile 90] [--dry-run]`
4. Serving is then a cheap indexed lookup — no serving change needed for a pure method change.

## Reorg target

- [x] **Models out of core** (2026-07-15) — the 3 mart models moved from `app/models/reference.py`
      to `etl/peers/models.py`. This module's tables are no longer part of the frozen contract, so
      changing one is no longer a breaking change to everything.
- [ ] Pull the remaining pieces under this folder: `build/build_peers.py`, `models.py`,
      `migrations/0004_*`, `tests/` (golden peer-set fixtures); the design `.md` docs to `docs/`
      here. **No `api/`** — this module has no serving surface. Tracked in `docs/MODULES.md`.

When the models move again, update `migrations/env.py` **and**
`migrations/versions/0001_initial_schema.py` — both import `etl.peers.models` to register these
tables on `Base.metadata`, and autogenerate reads a table it can't see as **DROP TABLE**.
`backend/tests/test_schema_inventory.py` will fail if you forget.
