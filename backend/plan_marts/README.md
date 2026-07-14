# plan_marts — plan-content read models (scaffold)

> **SCAFFOLD / MAP ONLY — no code has moved here yet.** This documents where the feature's code
> currently lives. Relocation is a later step (see `docs/MODULES.md`). Import from the paths below.

The query surface for the UI: semantic read models that combine plan content with real metrics.
The flagship is the **attendance diagnostic** — for each school it pairs the attendance-related
goals + funded actions (verbatim plan text / provenance) with the school's real chronic-
absenteeism rate, framed as NEED (peer-relative) vs. RESPONSE (what the plan funds).

## Component map (where the code is today)

| Concern | File(s) | Notes |
|---|---|---|
| Marts endpoints | `backend/app/marts.py` → `fetch_attendance_plans`, `attendance_slice`, `/marts/*` | endpoint-composed (no tables yet; can be materialized later) |

> **Coupling to know:** `backend/app/marts.py` currently also contains the **likeschools** serving
> functions (`fetch_like_schools`, `fetch_peer_benchmark`, `/like-schools`, `/peer-benchmark`).
> Two modules share one file today. When the reorg splits them, the peer-serving code goes to
> **likeschools** and only the plan-content marts stay here. The attendance diagnostic *consumes*
> likeschools via `fetch_peer_benchmark` / the `mart_school_peer` table — that's a legitimate
> cross-module read through the table contract, not an import to preserve.

## Contract

- **Owns:** no tables yet (MVP composes queries at request time).
- **Reads:** `plan_extraction` (from **sip**), `fact_metric` (from **public_metrics** / core),
  `mart_school_peer` (from **likeschools**).
- **Serves:** `/marts/*`.

## Boundary

Reads other modules' **tables**, never their Python. If a mart needs data that isn't in a produced
table, the fix is to have the owning module produce it — not to import across modules.
