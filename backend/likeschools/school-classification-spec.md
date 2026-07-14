# School Classification ("Schools Like You") — Implementation Specification

*School Improvement Plans prototype · MVP · July 2026*
*Companion to `school-classification-lit-review.md` — the review establishes the evidence; this spec establishes the build.*

---

## 1. Purpose and scope

This spec defines how the prototype computes and serves **demographic peer groups** — the set of "schools like you" for any given school — so that a school's indicators can be read against a fair, input-matched reference set rather than against the state as a whole.

MVP scope is deliberately narrow: a **rigorous, reproducible peer-grouping engine** over public federal data, materialized into the marts layer and exposed to the inference layer via MCP. Edge-case grade configurations are explicitly out of scope for MVP (see §3.2). Outcome/indicator comparison *within* a peer group is a serving concern, not a matching concern, and the two are kept architecturally separate.

---

## 2. Design decisions and provenance

Each locked decision traces to the direction established in the literature review. This table is the "citations regarding the direction" record.

| # | Decision | Choice for MVP | Source / rationale |
|---|----------|----------------|--------------------|
| D1 | **Match on inputs, not outcomes** | Similarity uses demographic/contextual inputs only; indicator values never enter the distance metric | IES/REL *Guide to Identifying Similar Schools*: outcome data "would not be appropriate" in the distance measure when evaluating relative performance ([IES guide](https://files.eric.ed.gov/fulltext/ED613435.pdf)) |
| D2 | **Multivariate distance, not a composite index** | Keep variables separate; compute a true multivariate distance | IES guide + Nebraska 27-variable distance model; preserves information, avoids collapsing distinct dimensions ([IES guide](https://files.eric.ed.gov/fulltext/ED613435.pdf)) |
| D3 | **Mahalanobis distance** | Distance accounts for covariance so correlated inputs (FRPL↔EL↔%minority) don't double-count | IES guide contrasts Euclidean vs. Mahalanobis; Mahalanobis "standardizes variables and removes correlation" ([IES guide](https://files.eric.ed.gov/fulltext/ED613435.pdf); [MatchIt](https://cran.r-project.org/web/packages/MatchIt/vignettes/matching-methods.html)) |
| D4 | **Standardize before distance** | z-score every feature within partition | Mandatory for distance methods; unscaled variables swamp the metric ([geographicdata.science](https://geographicdata.science/book/notebooks/10_clustering_and_regionalization.html)). *Note: Mahalanobis is scale-invariant, so this is for numerical conditioning; it is strictly required only for the Euclidean fallback.* |
| D5 | **Fixed-count nearest-neighbor, not hard clustering** | Each school gets its own centered band of *k* peers | Clustering yields wildly uneven groups (New Mexico: 9–134); Nebraska chose distance matching for equal peers ([IES guide](https://files.eric.ed.gov/fulltext/ED613435.pdf)) |
| D6 | **Coarse instructional level as a hard partition** | Primary / Middle / High / Combined-Other; match only within level | California ranked similar schools within type; England groups by phase; NCES CCD ships a derived `school_level` ([CCD](https://nces.ed.gov/ccd/pub_overview.asp)) |
| D7 | **Peer count k = 50 (locked; configurable)** | `k=50`, exposed as a parameter but fixed for MVP | Operating precedents bracket the range: Texas 40, Australia up to 60, California 100. 50 sits at the center; confirmed as the MVP default |
| D8 | **Non-outcome-derived weights** | Equal feature treatment (Mahalanobis' implicit inverse-covariance weighting only); no weights fit against results | Endogeneity caution: ICSEA/California SCI derived weights from test outcomes, leaking results into the "inputs-only" metric ([lit review §7](./school-classification-lit-review.md)) |
| D9 | **Similarity is computed on public data → it is a public artifact** | Peer groups carry no `tenant_id`; live in reference/mart tables, not private tenant tables | Matches the platform's public-vs-private seam; only the *indicator values* shown across a group are tenant-private ([ARCHITECTURE](../../ARCHITECTURE.md)) |

---

## 3. Feature model (the match vector)

### 3.1 Input variables (MVP — Tier 1)

Sourced entirely from federal supporting data, keyed on NCES school ID:

| Feature | Type | Source |
|---|---|---|
| % economically disadvantaged (or FRPL) | proportion | EDFacts FS033/FS226; CCD |
| % English learners | proportion | CCD / EDFacts |
| % students with disabilities (IEP) | proportion | CCD / EDFacts |
| % by race/ethnicity **or** combined % minority | proportion(s) | CCD |
| Total enrollment (size) | count (log-scaled) | CCD |
| NCES locale | categorical (4) | CCD locale files |

**Two modeling notes carried from the review:**

- **Race/ethnicity — match vs. display.** For MVP, default to **display-only** (shown across the peer group, excluded from the distance vector), because matching *on* race can normalize racialized outcome gaps (lit review §8). Make this a config flag (`include_race_in_match`, default `false`) so it is a deliberate, reversible choice rather than an accident of the schema.
- **Enrollment** is a raw count on a different scale from the proportions; apply `log1p` before standardizing so a 2,000-student school and a 200-student school sit at a sensible distance.
- **Locale** is categorical. For MVP, **one-hot encode** the 4 primary locale types into the vector (Mahalanobis then absorbs their correlation with the demographic features). Do *not* subdivide into 12 codes for MVP — the coarse 4 is enough and keeps the covariance matrix well-conditioned.

Deferred to v2: student mobility, ACS/Census community-poverty context (the US analogue of ICSEA's SEIFA and England's IDACI), homeless/migrant counts.

### 3.2 Partitioning (D6) — and the edge-case decision

Matching happens **only within a coarse instructional level**, taken from CCD's derived `school_level`, bucketed to:

`Primary` · `Middle` · `High` · `Combined-Other`

Per your call, MVP does **not** special-case unusual grade spans (5-9, 4-7, K-8 as its own thing). They fall into whichever coarse bucket CCD assigns (mostly `Combined-Other`) and are matched within it on demographics. They are edge cases by definition; a demographically-matched combined-school comparison is acceptable, and if a `Combined-Other` school's peer set is thin it is flagged low-confidence (§5.4) rather than engineered around. The grade-overlap gate and relaxation ladder discussed earlier are **noted as a v2 refinement**, not built now.

---

## 4. The distance computation

### 4.1 Mahalanobis in one paragraph

Between standardized feature vectors **xᵢ, xⱼ**, Mahalanobis distance is

> d(xᵢ, xⱼ) = √[ (xᵢ − xⱼ)ᵀ **S⁻¹** (xᵢ − xⱼ) ]

where **S** is the covariance matrix of the feature distribution *within the partition*. S⁻¹ down-weights directions where features vary together, so three correlated poverty-related variables count roughly once, not three times (D3).

### 4.2 Two mathematically-identical implementation paths

There is one subtlety that makes this easy to build on a Postgres stack: **Mahalanobis distance is Euclidean distance after a "whitening" transform.** If **W = S^(−1/2)** and we transform every school to **z = W·x**, then plain Euclidean distance in z-space equals Mahalanobis distance in x-space. Verified numerically for this spec — the two paths below return bit-identical neighbor distances.

**Path A — precompute (recommended for MVP).** Compute the inverse covariance once per partition and let the nearest-neighbor library use the Mahalanobis metric directly. No manual whitening needed.

```python
from sklearn.covariance import LedoitWolf
from sklearn.neighbors import NearestNeighbors

# X: standardized feature matrix for all schools in ONE level partition
lw  = LedoitWolf().fit(X)          # shrinkage → well-conditioned covariance
VI  = lw.precision_                # S^{-1} (inverse covariance)

nn  = NearestNeighbors(n_neighbors=K+1, metric='mahalanobis',
                       metric_params={'VI': VI}).fit(X)
dist, idx = nn.kneighbors(X)       # row 0 is the school itself → drop it
```

**Path B — live query via pgvector (v2 option).** Because pgvector only knows L2/cosine, push the *whitened* vectors into a `vector` column and query with L2 — which, post-whitening, *is* Mahalanobis. This buys arbitrary-k-at-query-time and "like X but also filter Y" at the cost of ANN approximation and index upkeep.

```python
import numpy as np
w, V = np.linalg.eigh(lw.covariance_)
Wmat = V @ np.diag(w**-0.5) @ V.T   # symmetric whitening S^{-1/2}
Z    = X @ Wmat.T                   # store Z rows in a pgvector column; query with <-> (L2)
```

Recommendation: **ship Path A for MVP.** It is deterministic, exactly reproducible, needs no ANN index, and at ~100k schools split across four level partitions the per-partition exact kNN is a trivial batch cost. Keep Path B in the back pocket for when the product wants live, filtered, variable-k similarity.

### 4.3 Robustness details (do these, they matter)

- **Shrinkage on the covariance.** The demographic features are collinear (poverty, EL, minority all move together), which makes a raw S⁻¹ unstable. Use **Ledoit-Wolf** shrinkage (`LedoitWolf().precision_`) rather than a naive inverse — it regularizes toward a well-conditioned estimate automatically. This is the single most important numerical safeguard.
- **Missing data.** Impute within-level median and set a `*_imputed` flag; drop schools missing more than a threshold (e.g., >2 of the core features) from being *candidates* but still give them a (flagged) peer list.
- **Standardization (D4).** z-score within partition before fitting. For the Mahalanobis path this only helps conditioning; for any Euclidean fallback it is mandatory.
- **No outcome-derived weights (D8).** Do not add feature weights fit against test results. If a future version wants to emphasize, say, economic disadvantage, use transparent policy-assigned weights and document them — never a regression on outcomes.

---

## 5. Data architecture

The engine slots into the existing star schema without disturbing it. Federal data is supporting/reference data; the indicators are the star; the peer groups are a new **public mart** derived from the reference layer; the "compare a school to its peers" logic is a serving view over both.

### 5.1 Layers

```
 reference (public federal)          star schema (indicators)         marts (public, MCP-served)
 ───────────────────────────         ─────────────────────────        ──────────────────────────
 ref_school            ┐             dim_school                        mart_school_peer      ◄─ the peer lists
 ref_school_demographic├─► FEATURE   dim_indicator                     mart_peer_benchmark   ◄─ school vs peer distribution
 ref_school_locale     ┘   BUILD ──► feat_match_vector ──► BATCH ──►   model_partition_stats ◄─ reproducibility
 (CCD / EDFacts)                     dim_date                          (whitening/shrinkage, means/sds)
                                     fact_indicator (tenant-private)
```

### 5.2 New tables (DDL sketch)

```sql
-- Derived, standardized match vector (public; one row per school per school_year)
CREATE TABLE feat_match_vector (
  nces_id        text     NOT NULL,
  school_year    smallint NOT NULL,
  level_bucket   text     NOT NULL,          -- Primary | Middle | High | Combined-Other
  f_econ_disadv  real, f_el real, f_swd real,
  f_enroll_log   real,
  f_locale_city real, f_locale_suburb real, f_locale_town real, f_locale_rural real,
  n_imputed      smallint NOT NULL DEFAULT 0,
  PRIMARY KEY (nces_id, school_year)
);

-- Precomputed peer lists (public reference mart) — the "schools like you" artifact
CREATE TABLE mart_school_peer (
  nces_id        text     NOT NULL,
  peer_nces_id   text     NOT NULL,
  rank           smallint NOT NULL,          -- 1..k, nearest first
  distance       real     NOT NULL,          -- Mahalanobis distance
  level_bucket   text     NOT NULL,
  school_year    smallint NOT NULL,
  low_confidence boolean  NOT NULL DEFAULT false,
  PRIMARY KEY (nces_id, peer_nces_id, school_year)
);
CREATE INDEX ON mart_school_peer (nces_id, school_year, rank);

-- Model provenance per partition per run (reproducibility + audit)
CREATE TABLE model_partition_stats (
  school_year   smallint NOT NULL,
  level_bucket  text     NOT NULL,
  feature_names text[]   NOT NULL,
  means         real[]   NOT NULL,
  sds           real[]   NOT NULL,
  shrinkage     real     NOT NULL,
  precision_mat real[]   NOT NULL,           -- serialized S^{-1}
  k             smallint NOT NULL,
  built_at      timestamptz NOT NULL,
  PRIMARY KEY (school_year, level_bucket)
);
```

Note on **D9 / RLS**: `feat_match_vector`, `mart_school_peer`, and `model_partition_stats` are **public reference tables** — no `tenant_id`, no row-level security. They are computed from the public federal universe and are identical for every tenant. Only `fact_indicator` (the values shown *across* a peer group) is tenant-private and behind `FORCE ROW LEVEL SECURITY`. This keeps the similarity artifact cleanly on the public side of the isolation seam described in `ARCHITECTURE.md`.

### 5.3 The batch job

A scheduled Python job (part of the ETL family; see `ARCHITECTURE.md`), run **once per CCD release / school year**:

1. Assemble `feat_match_vector` from the reference tables, per school, tagged with `level_bucket`.
2. For each of the four partitions: impute → standardize → Ledoit-Wolf covariance → `NearestNeighbors(metric='mahalanobis', VI=precision_)`.
3. Write `mart_school_peer` (drop self, keep k), set `low_confidence` per §5.4.
4. Persist `model_partition_stats` for audit and exact reproduction.

Serving is then a **cheap indexed lookup**, never a live computation — which is what makes the MCP layer fast and deterministic.

### 5.4 Low-confidence flagging

Set `low_confidence = true` when the k-th neighbor's distance exceeds a within-partition percentile threshold (the group is demographically loose), or when the school itself carries too many imputed features, or when a thin partition (`Combined-Other`) can't supply k genuinely close peers. This is the MVP substitute for edge-case engineering: don't hide a weak match, label it.

---

## 6. Serving layer (marts + MCP)

The inference layer reads the marts through MCP tools. Two are enough for MVP:

**`like_schools(nces_id, k=50, school_year=latest)`**
Returns the ordered peer list from `mart_school_peer` — peer NCES IDs, names, rank, distance, and the `low_confidence` flag. Pure lookup.

**`peer_benchmark(nces_id, indicator, school_year=latest)`**
Joins the peer list to `fact_indicator` and returns the target school's value alongside the peer-group distribution (min / p25 / median / p75 / max, and the target's **percentile rank within its peer group**). This is the "how am I doing relative to schools like me" payload — and the one place the inference layer sees indicators and peers together.

```sql
-- mart_peer_benchmark, conceptually:
SELECT p.nces_id, p.peer_nces_id, f.indicator_key, f.value
FROM   mart_school_peer p
JOIN   fact_indicator  f ON f.nces_id = p.peer_nces_id
WHERE  p.nces_id = :nces_id AND p.school_year = :yr;
-- aggregate to distribution + percentile of the target's own value
```

**Guardrail baked into serving (from lit review §8):** `peer_benchmark` should return the peer-relative percentile **and** an absolute reference (the fixed proficiency/growth bar) in the same payload, so the inference layer can never imply "good for a school like this" is the ceiling. Keep the matching service with **no read access** to `fact_indicator` — the only component that joins peers to outcomes is this serving view, which enforces D1 architecturally: outcomes physically cannot leak into the distance computation.

---

## 7. What's explicitly deferred (v2+)

- Grade-**overlap** gate + relaxation ladder for combined/odd-span schools (MVP uses coarse buckets only).
- ACS/Census **community-context** variable and student **mobility** (Tier 2 inputs).
- **pgvector / live similarity** (Path B) for arbitrary-k and filtered "like X but also Y" queries.
- Year-over-year **stability smoothing** (e.g., multi-year averaged inputs) once churn is measured.
- Empirical **k tuning** on your own data (sensitivity analysis around the 40–100 precedent range).

---

## 8. Open questions to resolve before/at build

1. **Race in the match vector** — MVP default is display-only (D8/§3.1); confirm this is the intended policy stance.
2. **Low-confidence threshold** — pick the distance percentile that trips the flag (needs one look at the real distance distributions per partition).
3. **Refresh cadence** — annual with CCD is the assumption; confirm no mid-year re-runs are needed.

*Resolved: peer count `k=50` is locked as the MVP default (D7).*

---

## Sources

Design-direction citations (verified in the companion review):

- IES / REL Central, *A Guide to Identifying Similar Schools to Support School Improvement* — https://files.eric.ed.gov/fulltext/ED613435.pdf (distance-not-geography; exclude outcomes; Euclidean vs. Mahalanobis; clustering size problem; Nebraska equal-peers)
- NCES Common Core of Data — https://nces.ed.gov/ccd/pub_overview.asp ; locale classifications — https://nces.ed.gov/programs/edge/docs/LOCALE_CLASSIFICATIONS.pdf
- US ED EDFacts file specifications SY 2024–25 (FS033, FS226) — https://www.ed.gov/data/edfacts-initiative/edfacts-resources/edfacts-file-specifications/edfacts-file-specifications-sy-2024-25
- MatchIt (Mahalanobis/covariate distance matching) — https://cran.r-project.org/web/packages/MatchIt/vignettes/matching-methods.html
- Standardization before distance/clustering — https://geographicdata.science/book/notebooks/10_clustering_and_regionalization.html
- Peer-count precedents: California API Similar Schools (100), Texas TEA (40), Australia ICSEA/SSSG (up to 60) — see companion review §4–§5

Companion documents in this project:
- `school-classification-lit-review.md` — the evidence base
- [`ARCHITECTURE.md`](../../ARCHITECTURE.md) — the platform/architecture context (public-vs-private seam, ETL, RLS)
