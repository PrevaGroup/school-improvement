# Design note: chat traces + an eval system, without breaking the serving seam

**Status:** parked (the overhaul is later) · **Scope:** `serving`, possibly a new producer ·
**Raises:** the first real pressure on the "serving owns no tables" invariant

The plan is to overhaul `app/chat.py` to **retain traces** and use them to **fuel an eval
system** — the long-term goal being that evals, not humans, catch regressions. The overhaul is
deferred. This note exists so the one non-obvious consequence is on the record **before**
someone starts building, because it collides with a decision made the same week.

## The collision: traces make `serving` a producer

The producer/consumer seam ([`MODULES.md`](../MODULES.md), decided 2026-07-15) rests on one
invariant:

> **`serving` owns no tables.** It reads every producer's tables with SQL and imports none of
> them, so the table stays the only seam.

That invariant is what pays for `likeschools` giving up its serving surface, and
`tests/test_module_boundaries.py` now enforces the map in CI.

**Retaining traces means chat starts writing.** A trace row — messages, tool calls, tool
results, model, tokens, latency, trace id — makes `serving` **own a table**. That is a
producer, and it contradicts the invariant one day after it was settled. Not fatal; just a
decision that should be made deliberately rather than discovered halfway through a diff.

## Three ways out

1. **Traces outside Postgres — Cloud Logging or GCS/JSONL.** *(recommended)* Serving stays
   table-free, so the seam is untouched. Traces are an **append-only event stream**, which is a
   poor fit for a relational table and a natural fit for a log; evals read them in batch, and
   neither evals nor traces want to sit in the transactional path of a chat request. Cost: a
   second storage story, and joins against the star schema get manual.
2. **A separate producer module** (`traces/`, `evals/`) that `serving` writes through. Keeps
   the rule intact and keeps traces queryable in SQL next to `fact_metric`. Cost: a module
   boundary on the request hot path, and `serving` gains a write dependency it doesn't have
   today.
3. **An explicit exception for `serving`.** Cheapest to build. Cost: it is the first crack in a
   rule whose entire value is that it has none — and the boundary test would need a carve-out,
   which is exactly the shape of `KNOWN_VIOLATIONS` ("that list may only shrink").

## Keep the two layers separate

`chat` has a deterministic half and a probabilistic half, and they need different instruments.
Conflating them is how an eval suite becomes both slow and untrustworthy.

| Layer | What it is | Instrument | Exists today? |
|---|---|---|---|
| **Tool layer** — `_run_tool` dispatch, args, the honesty fields | Deterministic. No model call. | **Unit tests** | ✅ [`tests/test_chat_tools.py`](../../backend/tests/test_chat_tools.py) — 28 tests |
| **Model layer** — did the answer ground itself, obey `plan_status`, stay honest | Non-deterministic. Needs a model call. | **Evals** | ❌ this is the work |

`_run_tool` is also the natural **trace seam**: every tool call already funnels through one
function with a name, an input dict, and a returned payload. That is a trace record with no
restructuring — which is part of why the tool layer is worth keeping deterministic and
separately tested.

## The highest-value eval target already exists

Start the eval suite on the **honesty layer**, not on answer quality.

`chat` bolts `plan_status` / `coverage` / `value_status` / `meaning` onto mart output
specifically so the model can never read *"no rows"* as *"no plan exists"*. The system prompt
says it outright: absence of data is not absence of the thing, and reporting a school as having
"no attendance plan" when its SPSA merely hasn't been loaded is **false and defamatory about a
real school**.

That makes it the rare eval target where:

- **failure is unambiguous** — the school either has a loaded plan or doesn't; no judgment call,
  no rubric, no LLM-as-judge needed to score it;
- **the ground truth is already in the database** — `plan_status` is computed, not opinion;
- **the cost of being wrong is real**, not cosmetic. Everything else ("was the answer useful?")
  is taste by comparison.

The three tri-state cases (`not_on_file`, `no_attendance_section`, `has_attendance_plan`) are
already pinned deterministically in `test_chat_tools.py`. The eval question is the next one up:
*given* correct tool output, does the model's prose actually respect it? A trace stream makes
that measurable after the fact, across real questions, instead of guessed at.

## Open

- Which storage (above). **Decide before writing the first trace**, not after.
- Traces of *public-data* chat carry no tenant data today — but a trace contains **user
  questions**, which is the first user-generated content this system would retain. It is not
  FERPA-covered, and it is also not nothing: it needs a retention answer, and if chat ever
  serves private tenant data, the trace store inherits the tenancy problem wholesale.
- Whether evals run in CI (cost, flakiness, model spend) or on a schedule against a fixed
  question set. CI is not obviously right for a non-deterministic, paid, slow suite.
