# serving — the read surface (scaffold)

> **SCAFFOLD / MAP ONLY — no code has moved here yet.** This documents where the feature's code
> currently lives. Relocation is a later step (see `docs/MODULES.md`). Import from the paths below.

Everything the UI reads. Semantic read models that combine plan content with real metrics and
peer context, plus the conversational surface over them.

The flagship is the **attendance diagnostic** — for each school it pairs the attendance-related
goals + funded actions (verbatim plan text / provenance) with the school's real chronic-
absenteeism rate, framed as NEED (peer-relative) vs. RESPONSE (what the plan funds).

## Why one module, not three

This replaces the earlier `plan_marts` + `chat` scaffolds, and absorbs the peer serving that
`likeschools` was going to own (decided 2026-07-15 — see `docs/MODULES.md` and §4 of
`ARCHITECTURE.md`).

The reason is concrete: `fetch_peer_benchmark` is needed by the attendance diagnostic **and** the
school-detail panel **and** the chat tools. Split those across modules and every one of them
becomes a cross-module import — the one rule gone. Duplicating the percentile/cohort logic instead
would be worse. So the read surface is **one module** that owns no tables and reads every
producer's tables with SQL, which keeps the table as the only seam in the system.

> ⚠️ **The planned `chat.py` traces/eval overhaul will push on "owns no tables."** Retaining
> traces means this module starts *writing*, which would make `serving` a producer and undo the
> reasoning above. It's parked, not cancelled — decide the storage **before the first trace is
> written**: [`docs/design/chat-traces-and-evals.md`](../../docs/design/chat-traces-and-evals.md).

## Component map (where the code is today)

| Concern | File(s) | Notes |
|---|---|---|
| Plan-content marts | `backend/app/marts.py` → `fetch_attendance_plans`, `attendance_slice`, `fetch_attendance_diagnostic` | endpoint-composed (no tables yet; can be materialized later) |
| Peer serving | `backend/app/marts.py` → `fetch_like_schools`, `fetch_peer_benchmark`, `_pctile` | reads `mart_school_peer` + `fact_metric` |
| School detail | `backend/app/marts.py` → `fetch_indicators`, `fetch_school_plan`, `full_plan_goals` | the panel: indicator charts + full plan |
| Subgroup breakdown | `backend/app/marts.py` → `fetch_metric_by_subgroup`, `subgroup_slice` | `fact_metric` disaggregated by student group |
| Chat endpoint + tools | `backend/app/chat.py` | wraps the fetch fns above — an intra-module import, which is why it's legal |

## Contract

- **Owns:** no tables. That's definitional, not a stage — a read surface that owned tables would
  be a producer, and the modules it reads could no longer be swapped independently.
- **Reads (all via SQL, never via import):** `plan_extraction` (from **sip**), `fact_metric`
  (from **public_metrics**), `mart_school_peer` (from **likeschools**), `dim_*` (from **core**).
- **Serves:** `/marts/*`, `/chat`. Frozen by `backend/tests/test_route_contract.py` — the
  frontend is built against these exact URLs.

## Boundary

Reads other modules' **tables**, never their Python. If a view needs data that isn't in a produced
table, the fix is to have the owning module produce it — not to import across modules.
`backend/tests/test_module_boundaries.py` fails CI if you try.
