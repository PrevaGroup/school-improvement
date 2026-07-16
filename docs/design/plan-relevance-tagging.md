# Design note: make SIP → Mart robust with extraction-time relevance tagging

**Status:** proposed · **Scope:** `serving`, `sip`, `core` (phased) · **Supersedes:** ad-hoc `attendance_slice` regex tuning

## The problem (verified against the current tree)

The plan-relevance layer decides *"which of a plan's goals/actions are about attendance?"* — a
**meaning** judgment. Today it answers that with a **keyword regex at serving time**, in
[`app/marts.py`](../../backend/app/marts.py):

```python
ATT_RE = re.compile(r"absent|attendance|chronic|truan", re.I)   # marts.py:24
def _link_is_attendance(ml): return ml.get("proposed_metric_id") == ATT_METRIC or _hit(...)  # :32
...
if g_att or a_att:            # marts.py:45 — goal-level OR sweeps ALL child actions
    actions_out.append(...)
```

Two concrete precision leaks:

1. **`marts.py:32`** trusts a bare `proposed_metric_id` with no text corroboration.
2. **`marts.py:45`** — once a *goal* is tagged attendance-relevant, **every action under it is
   included**, regardless of the action's own content.

### The case that exposed it (Wilson HS)

Wilson's "Culture/Climate" goal is a **bundled, multi-metric goal**: it carries belonging
(PULSE) targets, suspension targets, *and* a real attendance target ("increase attendance rate
to 92.2%"), served by one shared set of climate/PD strategies. The mart flagged the goal on the
genuine attendance text, then swept in all six shared climate actions (Courageous Conversations,
affinity clubs, "look-fors" — none individually about attendance, all "no funding listed"). Result:
Wilson reads as **"7 actions · $49,888 · responsive"** when its only attendance-specific funded
line is a shared ~$50K office aide. The verdict inflates from the truthful *thin response* toward
*responsive*.

**The stored JSON is faithful** — this is a categorization error in the mart, not bad extraction.

### Why it's brittle (not just buggy)

Semantic classification via keyword regex at serving time fails three structural ways, and CA
scale (1,000+ districts, each formatting SPSAs differently) makes each one chronic:

- **Lexical:** misses synonyms (`ADA`, `re-engagement`, `tardies`, `days present`, `on-track`);
  false hits (`chronic behavior`, `absent teacher`).
- **Structural:** assumes a goal maps to one metric. Bundled goals (common) break it.
- **Format:** `subject` / `accountability_measure` / `strategic_5yr` goal types are
  Long-Beach-specific; the next district won't use them.

Three iterations on one school without converging is the tell: the rules aren't generalizing.

## Root cause

The semantics are computed at the **wrong layer** (serving) with the **wrong tool** (regex). The
meaning judgment should happen **once, upstream, where the LLM has full document context**;
serving should be a **deterministic filter over structured tags**. Determinism is what has to be
robust; the intelligence belongs at extraction, where it already is.

## Target architecture

### 1. Structured tags on goals/actions, produced at extraction (or a re-tag pass)

Add three fields, filled by the model against the conformed vocabulary:

| Field | Meaning | Notes |
|---|---|---|
| `domain` | `attendance \| behavior \| academics \| climate \| engagement \| …` | **always set**, even when no state metric exists — this is what makes local constructs (belonging) *visible* |
| `metric_id` | one of `dim_metric.metric_id`, else **null** | closed set; null when nothing state-benchmarkable applies |
| `relation` | `strategy_for \| shared \| target_only` (per action↔metric) | this is what fixes bundled goals |
| `confidence` | 0–1 | low-confidence tags get flagged, not silently trusted |

Model **action↔metric as many-to-many**: a shared climate action legitimately links to
`climate/belonging` *and* `attendance`. Bundled goals then decompose naturally instead of being an
edge case coded around. Wilson becomes: `{climate → belonging, no metric}`, `{behavior →
suspension_rate}`, `{attendance → chronic_absenteeism_rate, target_only}` — and **no action is
`strategy_for` attendance**, which is the truthful "thin response."

### 2. Serving becomes deterministic

`attendance_slice` collapses to a structured filter — no regex, no goal-vs-action heuristic:

```
domain == 'attendance' AND relation IN ('strategy_for','shared')     # counts toward the verdict
domain == 'attendance' AND relation == 'target_only'                 # shown as the target (92.2%)
```

The keyword regex survives only as a **fallback for untagged legacy docs**, not the primary path.
The verdict (`responsive` vs `unmet_need`) keys off **attendance-specific funded actions
(`strategy_for`/`shared`)** only.

### 3. The vocabulary is tenant-scoped (this is why we're multi-tenant)

State accountability is a narrow lens; the belonging/SEL/climate work districts increasingly fund
is measured **locally** and is structurally absent from CDE data (every current `METRICS` entry is
`data_origin="state"`, [`app/vocab.py`](../../backend/app/vocab.py)). Hand the extractor the
**global catalog + the tenant's own metrics**, so a district's "Sense of Belonging" maps to *their*
`belonging_pulse` instead of `none`. Benchmarking must honor `data_origin` + `instrument_dependent`
(compare only same-instrument, opted-in tenants — `dim_instrument` already models the scales).

## The `core` decision (must be ratified separately — do not fold into feature work)

`dim_metric.metric_id` is the **sole PK** ([`reference.py:177`](../../backend/app/models/reference.py))
— a global catalog — while `fact_metric` is tenant-scoped. "Upload your own metrics" splits in two:

- **Shared local instruments** (PULSE, Panorama — many districts): add to the **global catalog**
  as `data_origin='local_survey'`, `instrument_dependent=true`. No schema change; values stay
  private via `fact_metric` RLS.
- **Bespoke, district-invented metrics:** need **tenant-scoped definitions** — either `tenant_id`
  on `dim_metric` (composite/namespaced ids, re-keys FKs) or a **`tenant_metric` extension table**
  under the existing RLS pattern.

**Recommendation:** keep `dim_metric` as the curated global/shared catalog; add a `tenant_metric`
extension for bespoke defs (mirrors RLS, avoids re-keying the global catalog and its FKs). This is
a **breaking `core` migration** — its own reviewed branch per `CLAUDE.md`, not folded into `sip`
or `serving` work.

## Phasing (one module per branch)

| Phase | Module | Change | Cost |
|---|---|---|---|
| **0** (optional stopgap) | `serving` | Tighten `attendance_slice` to **action-level** (`a_att` only; require text to corroborate a bare `metric_id`). Honest-for-the-demo; **no `core` change**. Explicitly a stopgap. | small |
| **1** | `sip` | Add `domain`/`metric_id?`/`relation`/`confidence` to the extraction schema ([`schema.py`](../../backend/etl/ca/sip/schema.py)) + `emit_plan` prompt (inject `dim_metric` vocab). Add a **re-tag pass** over existing `plan_extraction` docs — feeds goals/actions + vocab to the model, emits tags, **no PDF re-extraction** (raw stays immutable). | medium |
| **2** | `serving` | Rewrite `attendance_slice` to filter on structured tags; regex kept only as legacy fallback. Materialize at load-time later (the code already flags "endpoint-composed MVP; can be materialized"). | medium |
| **3** | `core` (reviewed) | Tenant-scoped vocabulary (`tenant_metric`) + benchmarking that honors `data_origin`/`instrument_dependent`. Gated on the decision above. | large |

## What this fixes

- **Precision** — belonging PD is no longer counted as attendance; shown as context; the 92.2%
  target still surfaces. Wilson reads truthfully.
- **Missingness** — the model states *"no `strategy_for` attendance"* explicitly, instead of the
  mart inferring it from a missing keyword.
- **Generalization** — no district-specific `goal_type` or keyword assumptions; works across CA.
- **Local constructs** — belonging gets a home via `domain`, benchmarkable per tenant once they
  bring their instrument. The multi-tenant design is what makes this land.
