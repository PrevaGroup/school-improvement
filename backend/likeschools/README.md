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

This feature currently spans **7 concerns across the old layout**. To change the algorithm you
touch these; the reorg (see `docs/MODULES.md`) will pull the swappable ones under this folder.

| Concern | File(s) today | Notes |
|---|---|---|
| **Design docs** | `backend/likeschools/*.md` (concept, lit-review, spec) | drifted — reference only |
| **Matching engine** | `backend/etl/peers/build_peers.py` | the Mahalanobis matcher (the thing you'd edit to change the algorithm) |
| **Schema / DDL** | `backend/migrations/versions/0004_peer_tables.py` | creates the 3 owned tables |
| **ORM models** | `backend/app/models/reference.py` → `FeatMatchVector`, `MartSchoolPeer`, `ModelPartitionStats` | **buried in core `reference.py`; should move here** |
| **Serving API** | `backend/app/marts.py` → `fetch_like_schools`, `fetch_peer_benchmark`, `/like-schools`, `/peer-benchmark` | reads the tables + `fact_metric` |
| **Chat tools** | `backend/app/chat.py` → `find_similar_schools`, `compare_to_peers` | wrap the serving fns |
| **Dependency** | `backend/requirements.txt` → `scikit-learn` | used only by the matcher |

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
- **Race is excluded** from the match vector (spec D8 default; `dim_school` carries no per-school
  race anyway).
- A single run-year label (`--year`, default = `max(dim_school.school_year)`) covers all current
  schools, avoiding fragmentation from mixed fact-stub years.
- `MIN_PARTITION = 3` — below that a level can't form a meaningful peer set.

## How to update the algorithm (runbook)

1. Edit **`backend/etl/peers/build_peers.py`** (`FEATURES`/`CORE`, `level_bucket()`, the distance
   step, `k`, confidence percentile). This is the only file that defines the method.
2. If you add/rename an **output column**, that's a contract change: update the DDL
   (`migrations/versions/0004_peer_tables.py` or a new migration), the ORM models in
   `reference.py`, **and** every downstream reader (`marts.py`, `chat.py`). Otherwise downstream
   is unaffected.
3. Rebuild (from `backend/`, needs scikit-learn + DB via Auth Proxy + ADC):
   `python -m etl.peers.build_peers [--k 50] [--year 2025-26] [--conf-pctile 90] [--dry-run]`
4. Serving is then a cheap indexed lookup — no serving change needed for a pure method change.

## Reorg target

Pull the swappable pieces under this folder: `build/build_peers.py`, `models.py` (the 3 mart
models moved out of core `reference.py`), `api/` (the peer endpoints from `marts.py`),
`migrations/0004_*`, `tests/` (golden peer-set fixtures). The design `.md` docs move to
`docs/` here. Tracked in `docs/MODULES.md`. **First safe step: move the 3 mart models out of
`reference.py`** — grep confirms only `build_peers.py` imports them, so it's a 2-file change that
decouples this module's private tables from the shared contract.
