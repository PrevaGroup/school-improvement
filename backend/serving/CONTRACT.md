# serving — CONTRACT

The read surface. Owns **no tables — definitionally**: a read surface that owned tables would be
a producer, and the modules it reads could no longer be swapped independently. That invariant is
what lets the peer endpoints live here without breaking the one rule.

## Reads (SQL only, never imports)

| From | Tables | Contract relied on |
|---|---|---|
| **sip** | `plan_extraction` | column shape + the `ExtractedPlan` JSON layout of `document` |
| **likeschools** | `mart_school_peer` | column shape; `rank` 1 = nearest; `low_confidence` |
| **public_metrics** (rows) / **core** (shape) | `fact_metric`, `dim_*` | conformed grain + vocab ids; `direction` on `dim_metric`; `value_status` semantics |

## Serves — frozen by `tests/test_route_contract.py`

`/api/marts/attendance-plans`, `/api/marts/attendance-diagnostic`, `/api/marts/subgroup-metrics`,
`/api/marts/districts`, `/api/marts/like-schools`, `/api/marts/peer-benchmark` (GET) ·
`/api/marts/workspace`, `/api/chat` (POST). Deliberate changes update the test's `EXPECTED`
in the same commit. (`/api/marts/school-detail` was retired 2026-07-16 when the panel cut
over to `POST /marts/workspace`.)

## Response-shape invariants the UI and chat rely on

- **Data honesty:** a null value with `value_status='suppressed'` is UNKNOWN, never 0; a missing
  plan is `plan_missing` / `not_on_file` (a data gap), never `unmet_need` (a finding).
- **Direction-adjusted percentiles:** `peer_performance_percentile` is always
  higher-is-better-than-band, whatever the metric's direction.
- **Cohort framing:** a school is ranked within peers **+ itself**; the peer *list* excludes it.
- Chat tools never invent data — every answer grounds in these same fetch functions.
- **Workspace (docs/design/agentic-workspace-and-sessions.md):** Claude controls a *spec*
  (validated against `dim_metric`/`dim_period`/`dim_student_group`/`plan_extraction`); the
  server renders the *data*, and the same server-built payload goes to the model and the UI.
  The only model-authored text rendered in the workspace is the spotlight `reason` (truncated,
  visibly attributed). Slot metrics are the derived `unit='pct'` whitelist; the year param
  varies the data year while the peer cohort stays the latest peer set; a subgroup band's
  small `n` is captioned (`band_status`), never hidden.

## Known pressure (decide before the first trace is written)

The chat traces/evals overhaul would make this module *write* a table — i.e., a producer.
That contradicts this contract's first line. Options + recommendation:
`docs/design/chat-traces-and-evals.md`.

## Migration revisions owned

None, and it must stay that way while "owns no tables" holds.

## Tests

`tests/test_marts.py`, `tests/test_peer_math.py`, `tests/test_chat_tools.py`,
`tests/test_route_contract.py` (the surface freeze), `tests/test_spa_fallback.py`.
