# Data Model — School Improvement Platform

This document specifies the transformed data model for a multi-tenant school-improvement
platform. The model serves two audiences from one substrate: **state-style benchmarking**
(annual, comparable, disaggregated by student group) and **district operational improvement**
(sub-annual progress, resource decisions, plan evaluation).

It is a **dimensional model** — a star schema of conformed dimensions and grained facts — with
a normalized companion area for document-derived data and a serving layer of purpose-built
marts. It is not a Data Vault; the star is the core, fed directly from staging.

Companion: [`DATA_CATALOG.md`](DATA_CATALOG.md) describes the raw source files. DDL is
ANSI/PostgreSQL-flavored.

---

## 1. Architecture

### 1.1 Layers

Each layer is a database schema (namespace). The schema name states the layer; table names
stay clean.

| Schema | Layer | Purpose |
|---|---|---|
| `raw` | Raw data | Source files landed verbatim. Audit fidelity; never modified. |
| `staging` | Transform | Parse, type, conform, and extract. Isolates all source-shaped mess. |
| `star` | Star schema | Conformed `dim_*` + grained `fact_*`. The comparable measurement substrate. |
| `augment` | Surrounding datasets | Normalized entities that extend the star (plans, documents, findings). |
| `marts` | Serving / semantic layer | Purpose-built answers. The query surface for applications and agents. |

```
raw ──▶ staging ──┬─▶ star ─────┐
                  │             ├──▶ marts
                  └─▶ augment ──┘
```

### 1.2 Conventions

- **`fact_` / `dim_` prefixes are used only in `star`.** `augment` tables are plain entity
  names; `marts` tables are plain or `mart_`-prefixed. The prefix signals dimensional role;
  outside the star it would mislead.
- **School identity** is `school_id` — nationally the **NCES school ID**; state-native codes
  (California CDS) are attributes (`state_school_id` / `state_district_id`) plus a crosswalk.
  *(The CA build originally loaded `school_id` from the 14-digit CDS; migration
  `0002_nces_rekey` re-keys it to the NCES Fed ID via the directory crosswalk, retaining the
  CDS as `state_school_id`.)*
- **Time** is a dimension (`dim_period`), not a column. See §4.2.
- **Tenancy**: tenant-scoped rows carry `tenant_id` + `visibility`; defaults follow
  `data_origin` (state → public, local → private). See §7.
- **Rates vs counts**: rate/percentage measures are non-additive — never summed across rows.
  Store consistently (percent 0–100).

### 1.3 Implementation status

This document is the **target** design; the body specifies the destination, not the current
database. Build status (2026-07):

| Area | Status | Notes |
|---|---|---|
| Layer schemas (`star.` / `augment.` / `marts.`) | **Planned** | All tables currently live in the default `public` schema; DDL below is namespaced for the target. |
| `fact_metric` + conformed `dim_*` (metric, student_group, period, instrument, peer_group, school) + crosswalk | **Built** | 8 public metrics loaded (~960k rows). |
| Identity on NCES `school_id` (§1.2, §4.4) | **Built** | Re-keyed CDS→NCES via `0002_nces_rekey`; CDS kept as `state_school_id` / `state_district_id`. |
| Tenancy + RLS: `dim_tenant` / `tenant_scope` / `tenant_membership`, `FORCE` RLS (§7) | **Built** | Consortium / `shared` read-cascade only partially implemented. |
| `ref_benchmark` + benchmark/derived `fact_metric` columns (§4.9) | **Planned** | Columns exist; not yet populated (benchmarking step unbuilt). |
| Operational event facts (§4.3), `dim_school_calendar`, `ref_calendar_event` | **Planned** | Student-grained facts deferred. |
| Plan core `plan` / `plan_goal` / `plan_action` (§5.1) | **Built (minimal)** | Loaded via the SIP extractor; one linked metric per goal/action. |
| Provenance & bridges: `doc_chunk`, `bridge_action_metric`, `bridge_action_program`, `plan_finding` (§5.2) | **Planned** | The SIP staging JSON captures provenance + multi-metric links; the DB tables to hold them are unbuilt. |
| `marts` layer (§6) | **Planned** | None built. |

---

## 2. Layer: `raw`

Source files as delivered (CDE tab-delimited text, CAASPP caret-delimited, SACS Access
databases, district SIS extracts, plan PDFs). Read-only; the system of record for
reprocessing. Contents cataloged in [`DATA_CATALOG.md`](DATA_CATALOG.md).

---

## 3. Layer: `staging`

Two transform types share this layer; they differ in determinism and trust.

- **Deterministic conforming (`raw → staging → star`).** Parse formats, decode suppression,
  build `school_id`, apply the student-group crosswalk, normalize units, densify the
  missingness spine (§4.10), compute benchmarks. Reproducible: same input → same output.
- **Extraction + curation (`raw docs → staging → augment`).** LLM/NLP extraction of plan
  entities from documents, with provenance. Non-deterministic: staged extractions are
  **validated (and human-reviewed for sensitive content) before promotion** to `augment`.

Staging is persisted so `star` and `augment` are fully rebuildable from `raw`.

---

## 4. Layer: `star`

### 4.1 The metric fact — `star.fact_metric` (keystone)

**Grain: one row per `school_id × period_id × metric_id × student_group_id`** (tenant-scoped).
Aggregated measurements — school-and-subgroup level, at a flexible time grain (§4.2). This
one fact serves both audiences: filter to annual periods for benchmarking, to term/month
periods for progress.

```sql
CREATE TABLE star.fact_metric (
  school_id         TEXT,
  period_id         TEXT,            -- -> dim_period (carries the time grain)
  metric_id         TEXT,            -- -> dim_metric
  student_group_id  TEXT,            -- -> dim_student_group
  -- tenancy (§7); defaults from dim_metric.data_origin
  tenant_id         TEXT NOT NULL DEFAULT 'public',
  visibility        TEXT NOT NULL DEFAULT 'public',   -- public | private | shared
  -- measurement (§4.10)
  value             NUMERIC,         -- real number (incl. 0) only when value_status='reported'
  value_status      TEXT,            -- reported|suppressed|no_students|not_applicable|not_collected|not_loaded|unknown
  n_size            INTEGER,         -- denominator (students behind the value)
  instrument_id     TEXT,            -- -> dim_instrument (which tool produced it)
  source_dataset    TEXT,            -- lineage
  -- benchmarks (computed; §4.9)
  value_state       NUMERIC,
  value_district    NUMERIC,
  value_peer_median NUMERIC,         -- within peer group
  value_prior       NUMERIC,         -- prior comparable period, same series
  value_all_group   NUMERIC,         -- 'all' students, same school/period (equity gap)
  target_value      NUMERIC,
  -- derived, signed toward "good" via dim_metric.direction
  change            NUMERIC,         -- vs value_prior; NULL across a series_break
  gap_vs_state      NUMERIC,
  gap_vs_peer       NUMERIC,
  gap_vs_all_students NUMERIC,       -- equity gap
  z_in_peer         NUMERIC,
  pctile_in_peer    NUMERIC,
  series_break      BOOLEAN,         -- instrument changed vs prior period (§4.7)
  status_level      TEXT,            -- Very Low..Very High
  change_level      TEXT,            -- Declined..Increased
  band              TEXT,            -- 5x5 status×change result (Red..Blue)
  PRIMARY KEY (school_id, period_id, metric_id, student_group_id)
);
```

`fact_metric` is **aggregated in entity** (school × group) but **flexible in time**. Sign
normalization means a rising suspension rate and a falling graduation rate both yield a
negative `change`, so all downstream scoring is uniform.

### 4.2 Time — `dim_date`, `dim_period`, `dim_school_calendar`

Time is modeled at three related grains so the platform supports annual benchmarking,
within-year progress loops, and operational calendar analysis.

**`dim_period` — the flexible time grain `fact_metric` keys on.** A period carries its own
grain, so annual and sub-annual coexist in one fact.

```sql
CREATE TABLE dim_period (
  period_id     TEXT PRIMARY KEY,
  grain         TEXT,       -- annual | term | grading_period | month | biweekly | week | window
  school_year   TEXT,       -- containing year (annual filter + rollup)
  label         TEXT,       -- '2023-24' | 'Fall' | 'Oct' | 'Winter iReady'
  start_date    DATE, end_date DATE,
  day_in_session_start INTEGER, day_in_session_end INTEGER,  -- cross-year "same point in year"
  sort_order    INTEGER, is_current BOOLEAN,
  -- tenancy: standard periods (annual, state windows) are public;
  -- a district's grading/monitoring cadence is private to that tenant.
  tenant_id     TEXT NOT NULL DEFAULT 'public',
  visibility    TEXT NOT NULL DEFAULT 'public'
);
```

`dim_period` is a **tenant-scoped dimension** (a deliberate exception — most dimensions are
fully conformed). Standard periods are `public`; each district's operational cadence is
private. A period's own tenancy therefore states whether it is comparable across tenants —
no separate role flag is needed. A `fact_metric` row references either a public period or one
of its own tenant's periods.

**`dim_date`** — one row per calendar date; universal attributes (`date_key, school_year,
month, iso_week, day_of_week, is_weekend`).

**`dim_school_calendar`** — an **enriched dimension** at `school_id × date`. The
district-specific overlay that makes operational patterns queryable as flags rather than
hardcoded date logic: `is_instructional_day, term, day_in_session, is_day_before_holiday,
is_day_after_holiday, is_state_testing_window, is_early_release`. Built by joining the
district calendar to the public `ref_calendar_event` reference (§4.9).

### 4.3 Operational event facts (atomic) — *planned, not yet built*

Progress and early-warning analysis at the **student** grain. Atomic, SIS-sourced,
`data_origin='local_sis'` → always tenant-private (FERPA). Each is at its *natural* grain:

| Fact | Grain | Purpose |
|---|---|---|
| `star.fact_attendance_event` | student × date × period | daily/period attendance; skip patterns |
| `star.fact_behavior_event` | student × incident datetime | referrals/suspensions (events) |
| `star.fact_course_mark` | student × course × grading period | course performance (the "C" in ABC) |

These roll up (via `dim_date`/`dim_period`) into the aggregated `fact_metric`. Division of
labor: **event facts answer "who to act on"; `fact_metric` answers "is the school/subgroup on
track"; annual periods answer compliance.**

### 4.4 `dim_school` (and identity)

One row per school per year. Source: the public schools directory.

Key columns: `school_id` (12-digit NCES Fed ID; from the CDS→NCES crosswalk in CA),
`state_school_id` (14-digit CA CDS) / `state_district_id`, `school_name`,
`district_id` (7-digit NCES LEAID) / `district_name`, `county_name`, `school_level`, grade span,
charter/Title I/DASS/ESSA-assistance flags, `locale`, `enroll_total`, student-composition
percentages (feed peer grouping), lat/long, `peer_group_id`. Roll-ups to `dim_district` /
`dim_county` on the identity hierarchy are *planned* (not yet built).

### 4.5 `dim_metric` — the metric registry

The registry that lets the long fact hold heterogeneous measures uniformly.

```sql
CREATE TABLE dim_metric (
  metric_id         TEXT PRIMARY KEY,
  domain            TEXT,      -- attendance|behavior|academics|climate|engagement|finance|staffing
  display_name      TEXT,
  unit              TEXT,      -- pct | rate | scale_score | dfs_points | usd | fte
  direction         TEXT,      -- higher_better | lower_better | context
  grains            TEXT,      -- cadences this metric legitimately reports at (e.g. 'annual,month')
  applies_to_levels TEXT,      -- 'ES,MS,HS' — governs the missingness spine
  applies_to_grades TEXT,      -- e.g. '3-8,11'
  is_leading_indicator BOOLEAN,
  data_origin       TEXT,      -- state | local_sis | local_survey  (drives default visibility)
  instrument_dependent BOOLEAN,-- value scale/construct depends on the tool used (§4.7)
  definition        TEXT,
  suppress_threshold SMALLINT DEFAULT 11
);
```

The registry declares each metric's legitimate **grains**, which bounds the flexible-time
model at the source: a metric appears in `fact_metric` only at grains it actually reports.
Representative metrics span state files (chronic absenteeism, suspension, CAASPP ELA/Math,
graduation), local SIS/survey measures (reclassification, course pass/D-F, interim
diagnostics, climate-survey constructs), and staffing (`teacher_fte_total`, `teacher_new_fte`
= inexperienced ≤2 yrs, `teacher_outoffield_pct`).

### 4.6 `dim_student_group` (+ crosswalk)

The disaggregation axis. Each source encodes subgroups differently, so all are conformed to
`student_group_id` via `staging.group_crosswalk` before any join.

```sql
CREATE TABLE dim_student_group (
  student_group_id TEXT PRIMARY KEY,   -- 'all','race_black','el','sed','swd','foster','homeless',...
  label            TEXT,
  dimension        TEXT,               -- total|race|gender|ses|program|eng_prof
  is_equity_focus  BOOLEAN
);
```

**Student groups are overlapping lenses, not a partition.** One student appears in every group
they belong to (a Black homeless student is counted in `race_black`, `homeless`, `sed`,
`gender_*`, and `all`); only `all` counts each student once. **Never sum groups.** The state
files provide single-axis slices only — no intersection cells (e.g. Black ∧ homeless); those
require student-level data.

### 4.7 `dim_instrument`

The tool that produced a measurement (surveys, diagnostics). The same construct can come from
different instruments across schools and years (e.g. a district switching climate-survey
vendors), with different scales and only partially overlapping meaning.

```sql
CREATE TABLE dim_instrument (
  instrument_id    TEXT PRIMARY KEY,
  vendor           TEXT,
  display_name     TEXT,
  scale_type       TEXT,       -- pct_favorable | likert_mean_1_5 | scale_score | rate
  scale_min NUMERIC, scale_max NUMERIC,
  version          TEXT,
  notes            TEXT
);
```

Rule: for `instrument_dependent` metrics, a change of `instrument_id` between periods sets
`fact_metric.series_break = TRUE`; `change`/trend is suppressed across it and the metric is
never compared across instruments. A vendor switch is not improvement.

### 4.8 `dim_peer_group`

A cluster of comparable **schools** (level × size band × composition × locale) so benchmarks
are relative to similar schools, not just the state average. `value_peer_median`,
`z_in_peer`, and `pctile_in_peer` are computed within `peer_group_id`.

### 4.9 Reference & benchmark tables

Public, conformed lookups (part of the reference tier, §7.2):

- `ref_benchmark` — authoritative state/county/district aggregate values (the rollup rows CDE
  ships alongside school rows). `fact_metric.value_state`/`value_district` are filled by join,
  matching official figures exactly — never by averaging schools.
- `ref_calendar_event` — holidays and testing windows (`date, event_type, jurisdiction`);
  third-party data that feeds `dim_school_calendar`.
- Code tables — SACS `fund`/`resource`/`function`/`object`/`goal`, and other source code sets.

### 4.10 Missingness — `value_status`

Missingness is explicit, never implicit. Three states, one contract:

| In `fact_metric`? | `value` | `value_status` | Means |
|---|---|---|---|
| row present | number (incl. 0) | `reported` | measured |
| row present | NULL | not `reported` (typed) | **expected but missing** — reason attached |
| no row | — | — | **not expected** (out of scope) |

`value_status`: `reported` (incl. a real 0) · `suppressed` (N<11 masked) · `no_students`
(n_size 0) · `not_applicable` (out of grade span/level) · `not_collected` · `not_loaded`
(source exists, not ingested) · `unknown`.

The **expected** grain is materialized (a spine of in-scope `school × period × metric × group`
per `applies_to_levels`/`grains`), then measurements are left-joined; unmatched in-scope cells
become typed rows. `not_applicable` combinations stay absent, which is what keeps absence
meaningful. Loaders **emit real zeros** (a true 0 is `reported`, never a gap), and keep
`not_loaded` distinct from `not_applicable` so the UI shows "no data" rather than "no problem."
Coverage is counted against the *expected* denominator, not the `reported` count.

### 4.11 Load & accumulation rules

1. **School rows only in facts.** State files ship school + rollup rows together; route
   rollups to `ref_benchmark`, not the fact (rollups in the fact double-count).
2. **Benchmarks from `ref_benchmark`, not averages.** State rates are enrollment-weighted.
3. **Groups are non-additive** (§4.6) — never sum; "students affected" uses per-row values or
   the `all` denominator.
4. **Idempotent loads** — upsert on the PK; re-running a period replaces, not appends.
5. **One source version per period** — some files ship `-v2/-v3` revisions.
6. **Keep suppressed rows** — masked ≠ absent.
7. **Within-grain, within-instrument comparison only** — `change`/trend never cross a period
   grain or an instrument change.

---

## 5. Layer: `augment`

Normalized entities that extend the star with what measurements cannot hold — chiefly the
improvement plans (SPSA/LCAP/CSI-TSI-ATSI), which are the primary **school-level statement of
resource use**. Entities reference the star's keys; they are not facts.

### 5.1 Plan model

```sql
CREATE TABLE augment.plan (
  plan_id TEXT PRIMARY KEY, tenant_id TEXT, visibility TEXT,
  school_id TEXT, plan_year TEXT, plan_type TEXT,   -- SPSA|LCAP|CSI|TSI|ATSI
  status TEXT, adopted_date DATE, total_budget NUMERIC, source_url TEXT
);
CREATE TABLE augment.plan_goal (
  goal_id TEXT PRIMARY KEY, plan_id TEXT, tenant_id TEXT, visibility TEXT,
  lcff_priority SMALLINT,
  linked_metric_id TEXT,        -- -> dim_metric (the join that makes plans evaluable)
  target_group_id TEXT,         -- -> dim_student_group
  baseline_value NUMERIC, baseline_year TEXT, target_value NUMERIC, target_year TEXT,
  prior_status TEXT,            -- the school's own self-rating: Met|Partially|Not Met
  narrative TEXT
);
CREATE TABLE augment.plan_action (
  action_id TEXT PRIMARY KEY, goal_id TEXT, tenant_id TEXT, visibility TEXT,
  strategy_text TEXT,
  category_id TEXT,             -- -> intervention_category (reference)
  target_metric_id TEXT,        -- derived argmax(weight) of bridge_action_metric
  target_group_id TEXT,
  budgeted_amount NUMERIC, funding_source_id TEXT,  -- -> funding_source (reference)
  fte NUMERIC, role_type TEXT,
  is_district_provided BOOLEAN, -- district resource vs site-funded (prevents overstating capacity)
  source_chunk_id TEXT          -- -> doc_chunk (provenance)
);
CREATE TABLE augment.plan_finding (           -- needs-assessment pain points / self-diagnosis
  finding_id TEXT PRIMARY KEY, plan_id TEXT, tenant_id TEXT, visibility TEXT,
  domain TEXT, target_group_id TEXT, linked_metric_id TEXT,
  finding_text TEXT, self_reported_cause TEXT, source_chunk_id TEXT
);
```

Plan baselines/targets live here, not in `fact_metric` — `linked_metric_id` resolves against
`dim_metric` (the definition), so a local metric needs only a registry entry, not a fact row.
Where a plan-asserted baseline and an authoritative value both exist, the gap is a finding.

*Built:* `plan` / `plan_goal` / `plan_action` (minimal — one linked metric per goal/action,
loaded by the SIP extractor). *Planned:* `plan_finding`, and the `source_chunk_id` /
`target_metric_id` columns that depend on the §5.2 bridge/provenance tables.

### 5.2 Provenance & bridges — *planned, not yet built*

> The SIP staging JSON (`etl/ca/sip/schema.py`) already carries page-level provenance and
> multi-metric link proposals; these DB tables to persist them are the next augment step.

- `augment.doc_chunk` — the source spans behind every extracted value (`plan_id, page,
  section, text, embedding`), for citation and retrieval.
- `augment.bridge_action_metric` (`action_id, metric_id, weight_pct`) — **source of truth for
  action→metric**; reproduces the plan budget's per-measure weighting so "$ / FTE dedicated to
  a domain" is a `SUM(budgeted_amount × weight_pct)`. Money and FTE are non-additive across
  bridge rows (weights sum to 100 per action); FTE split by weight is notional, not headcount.
- `augment.bridge_action_program` (`action_id, program_id`).

Controlled vocabularies referenced by actions — `intervention_category`, `program`,
`funding_source` — are shared lookups in the **reference tier** (public), not extracted
entities.

---

## 6. Layer: `marts` — *planned, not yet built*

The serving/semantic layer: purpose-built, opinionated tables that encode agreed definitions
once, so applications and agents read a consistent foundation instead of re-deriving from
facts. This is the primary query surface (see §7.4).

### 6.1 Facts vs rollups vs marts

- **Base fact** — atomic, independently sourced (daily attendance from SIS; annual state
  metrics loaded directly from the state).
- **Rollup** — derived by summarizing a base fact (a SIS metric's term/annual value). Provenance
  is derivation, not source. Rollups may be materialized as grain-tagged `fact_metric` rows.
- **Mart** — a derived table that adds *analysis* (scoring, ranking, comparison).

### 6.2 Core marts

| Mart | Grain | Answers |
|---|---|---|
| `mart_opportunity` | school × metric × group | Where to focus. A tunable priority score over gap size, reach, equity, improvability, trend, and leverage (leading→lagging). |
| `mart_plan_alignment` | school × plan | Does the plan target the real gaps? Coverage of top opportunities; unaddressed gaps. |
| `mart_plan_effectiveness` | goal | Did the plan move the metric? Baseline→target→actual vs a comparison group (difference-in-differences). Refuses a verdict across an instrument change. |
| `mart_resource_profile` | school × domain | Is the plan staffed or aspirational? Funded $/FTE per domain (site-funded only), flagging need-vs-resource mismatch. |
| `mart_school_profile` | school | UI summary: headline metrics, bands, top opportunities, alignment. |

### 6.3 Grain discipline

Marts target **roles, not durations**: a progress mart walks a tenant's periods in order
("latest vs prior vs target") and works at any cadence without change. Heterogeneous cadences
are aligned by **as-of** lookup ("latest value as of a reporting date"), not by materializing
every metric at every grain. Bespoke operational cadences are `local_sis` → private, so they
appear only in per-tenant marts; the public/cross-tenant surface uses the standard (annual /
shared-window) periods. Comparison is always within-grain and within-instrument.

### 6.4 Mart coverage (health metric)

Every answer is tagged with the tier that served it (`mart` | `fact` | `raw_sql` |
`reference`). **Mart-hit rate** = mart-served ÷ total. Low coverage means agents are
improvising against raw data — slower, inconsistent, and using the least-safe path. Questions
that fall through are logged and clustered; recurring patterns become new marts. The metric is
simultaneously a quality, security, and cost signal.

---

## 7. Multi-tenancy & security

Public (state) data is shared; anything a district adds about itself (survey values, local-SIS
metrics, plan extractions) is visible only to that district. Enforced at the row with
PostgreSQL row-level security (RLS), not application logic.

### 7.1 The tenant

A tenant is an **administrative boundary that owns a set of schools** — *not* a fixed hierarchy
level. It may be a district, a county office, an independent charter, a charter-management org
spanning several LEAs, an entire state operating as one district (e.g. Hawaii), a mega-system
above many sub-districts (e.g. NYC), or a single private school. So a tenant is defined by
**membership**, not a code prefix.

```sql
CREATE TABLE dim_tenant (
  tenant_id TEXT PRIMARY KEY,     -- LEA id where a clean LEA exists; synthetic id otherwise
  tenant_type TEXT,               -- state|district|coe|charter|cmo|consortium|private_school|public
  display_name TEXT, jurisdiction TEXT
);
CREATE TABLE tenant_scope (       -- which schools a tenant owns (write authority)
  tenant_id TEXT, school_id TEXT, PRIMARY KEY (tenant_id, school_id)
);
CREATE TABLE tenant_membership (  -- nesting: parent/consortium relationships
  tenant_id TEXT, parent_id TEXT, PRIMARY KEY (tenant_id, parent_id)
);
```

Tenants **nest**: a parent's scope is the union of its children's, and read access cascades
downward (a state or mega-system tenant reads its sub-tenants; a sub-district sees only its
own). This models Hawaii-as-state, NYC-above-community-districts, and CMOs-over-charters with
the same two tables.

### 7.2 The public reference tier

Cross-tenant and cross-state comparison requires shared yardsticks, so these are `public`
(platform-writable, read-all): all conformed dimensions and crosswalks (`dim_metric`,
`dim_student_group`, `dim_instrument`, `dim_school`, `dim_peer_group`, standard `dim_period`
rows), code tables, `ref_benchmark`, `ref_calendar_event`, `data_origin='state'` facts, and
scale-normalization/concordance data. Nationally this tier rests on federal datasets (NCES /
EDFacts / SEDA) as the common floor, with per-state data as depth.

### 7.3 Row-level security

Every tenant-scoped table (`fact_metric`, the event facts, `dim_period`, the `augment` entities,
and marts) runs `ENABLE` + `FORCE ROW LEVEL SECURITY` and connects as a **non-owner,
`NOBYPASSRLS`** role (owners and superusers otherwise skip policies).

```sql
-- READ: public rows for all; private rows for their tenant (or a consortium member)
CREATE POLICY p_read ON star.fact_metric FOR SELECT USING (
  visibility = 'public' OR tenant_id = current_tenant()
  OR (visibility = 'shared' AND EXISTS (SELECT 1 FROM tenant_membership m
       WHERE m.parent_id = fact_metric.tenant_id AND m.tenant_id = current_tenant())));
-- WRITE: your own rows, only about schools you own
CREATE POLICY p_write ON star.fact_metric FOR ALL
  USING (tenant_id = current_tenant())
  WITH CHECK (tenant_id = current_tenant()
    AND EXISTS (SELECT 1 FROM tenant_scope s
                WHERE s.tenant_id = current_tenant() AND s.school_id = fact_metric.school_id));
```

Write authority is the `tenant_scope` membership check — which handles every tenant shape
(a code-prefix rule would not).

### 7.4 The trust boundary

`current_tenant()` must be un-spoofable by whoever authored the query. The client never sends
its own tenant; identity is bound in trusted server code before the query runs.

- **Default — typed tools + session GUC.** Applications expose typed operations; the server
  composes SQL and sets `SET LOCAL app.tenant` (from the verified login) inside the request
  transaction. `current_tenant()` reads the GUC. Safe because callers pass parameters, not SQL.
- **Raw-SQL access — per-tenant roles.** If an agent runs arbitrary SQL, a GUC is bypassable;
  bind tenancy to the DB **role** (one read-only `NOBYPASSRLS` role per tenant,
  `current_tenant() = current_user`) and run every such query `READ ONLY`.

Keeping raw SQL off the agent and serving typed tools over marts is the default posture; it
makes the GUC binding safe and aligns with the mart-coverage goal (§6.4).

### 7.5 Deployment (Cloud SQL + Google identity)

Managed identity simplifies authentication but does not replace RLS. **IAM is resource-level;
RLS is row-level** — IAM cannot filter the public/private row mix. The backend authenticates to
Cloud SQL via the Auth Proxy (or the Cloud SQL Python Connector) as a service account using ADC,
with the DB-role passwords held in **Secret Manager** (IAM DB auth is a later hardening option);
**Identity Platform** (OIDC) yields the verified user → tenant. Because the backend
is one service account, the typed-tools + `SET LOCAL` pattern is the natural default. Cloud SQL grants no full superuser, so
run the public/state loader as the **table owner** (owners bypass RLS unless `FORCE`), not a
`BYPASSRLS` role.

---

## Appendix A — Design decisions (record)

Durable decisions, most recent first. This appendix carries rationale; the body above is the
specification.

- **Time is a flexible-grain dimension.** `fact_metric` keys on `period_id → dim_period`
  (carrying `grain`), not a `school_year` column. One fact serves annual benchmarking and
  sub-annual progress; grains are bounded by `dim_metric.grains`; comparison stays within-grain.
- **Tenant = membership, not level.** Defined by `tenant_scope` (+ `tenant_membership` nesting),
  so state-as-district (Hawaii), mega-systems (NYC), CMOs, and private schools need no special
  cases. RLS write authority uses membership, not a code prefix.
- **Identity generalizes to NCES.** `school_id` is the conformed key nationally; state codes
  (CA CDS) are attributes. The public reference tier rests on federal datasets nationally.
- **Five layers as schemas** (`raw`/`staging`/`star`/`augment`/`marts`); `fact_`/`dim_` only in
  `star`. The plan layer is normalized `augment` entities, not facts.
- **Missingness is explicit** (`value_status` + expected-grain spine); real zeros are reported;
  `not_loaded ≠ not_applicable`.
- **Instrument tracked per measurement**; a vendor/tool change is a `series_break`, never a
  trend. Student groups are overlapping, non-additive lenses.
- **Benchmarks from the state's own aggregate rows**, computed within peer groups; state values
  are never re-derived by averaging schools.
- **Plan resourcing is first-class** — `bridge_action_metric.weight_pct` and
  `is_district_provided` make "funded vs aspirational" computable; money/FTE are non-additive.
- **Marts are the semantic layer**; coverage (mart-hit rate) is tracked, and misses drive the
  mart backlog.
