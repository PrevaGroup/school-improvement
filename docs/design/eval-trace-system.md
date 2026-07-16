# Design: the eval trace system — a continuous improvement loop for marts & tools

**Status:** proposed (decisions marked ⚖️ route to the human) · **Scope:** `serving` (emission),
a **new producer module `evals`** (store + loop), GCS (raw traces) ·
**Supersedes:** [`chat-traces-and-evals.md`](chat-traces-and-evals.md) — its analysis of the
seam collision and the honesty-first eval target carries forward unchanged; this doc makes the
storage call it parked and designs the whole loop.

## 0. What this is for

The product goal is **useful responses for school planning** — and "useful" is not something a
unit test can assert. The loop that gets there:

```
   traces of real use ──▶ mined into eval cases ──▶ scored eval runs ──▶ ranked backlog
        ▲                                                                    │
        └──────────────── improved marts / tools / prompts ◀─────────────────┘
```

Every mart, tool, and prompt change should be motivated by trace evidence and gated by an eval
that previously failed. Humans set the rubric; **evals, not humans, catch regressions** (that is
already this repo's working rule for code — this extends it to model behavior).

This is the same shape the frontier labs run internally on their own data agents —
[Anthropic's self-service analytics](https://claude.com/blog/how-anthropic-enables-self-service-data-analytics-with-claude)
and [OpenAI's in-house data agent](https://openai.com/index/inside-our-in-house-data-agent/)
(both already cited in [`PRIVACY.md`](../PRIVACY.md) as the model for studying our own usage),
and the pattern behind Gemini's BigQuery data agents and Microsoft's Copilot-over-semantic-model
products. The common denominator across all four:

1. **The agent grounds in a curated semantic layer** (our marts + the tool catalog), never raw
   tables — so improving the semantic layer is the highest-leverage change, and the loop's
   primary output is a *marts & tools backlog*, not just prompt tweaks.
2. **Every interaction is traced end-to-end** — question, every model call, every tool
   call/result, final answer, cost.
3. **Traces are mined into evals**; graders are layered (deterministic → rubric/LLM-judge →
   human feedback); regressions gate changes.
4. **The loop is provider-agnostic** — the semantic layer and the traces outlive any one
   model/vendor choice.

Point 4 is a design constraint here, not a nicety: the trace schema and eval harness must not
bake in Anthropic's wire format, so the same loop can score an OpenAI/Azure ("Copilot"-stack) or
Gemini agent loop the day one is plugged in. §5 is the seam that makes that true.

## 1. Architecture: three planes

The parked note's collision — *traces make `serving` a producer* — is resolved by splitting
emission from storage. `serving` **emits events to a log stream** (GCS, not a table); a new
**producer module `evals`** ingests them and owns every table. Serving stays table-free; the
seam survives untouched.

```
┌─ HOT PATH (serving) ────────────────┐   ┌─ STORE (evals module) ──────────────┐
│ chat request                        │   │                                     │
│  TraceRecorder buffers events       │   │  ingest job (batch, Cloud Shell/    │
│  in-memory during the turn          │   │  Cloud Run job):                    │
│  ──▶ response returns to user       │   │   GCS ──▶ trace (envelope rows)     │
│  ──▶ BackgroundTask flushes ONE     │──▶│                                     │
│      JSONL object per trace to GCS  │   │  owns: trace · eval_case ·          │
│      (fire-and-forget, never raises)│   │  eval_run · eval_result · feedback  │
└─────────────────────────────────────┘   └──────────────────┬──────────────────┘
                                                             │ SQL (the normal seam)
┌─ THE LOOP (offline, evals module) ─────────────────────────▼──────────────────┐
│ run_evals: drives /api/chat as an HTTP CLIENT (no import) ──▶ graders ──▶     │
│ eval_result rows ──▶ report + deltas vs baseline                              │
│ mine_traces: failures/feedback/clusters ──▶ candidate eval_case rows          │
└───────────────────────────────────────────────────────────────────────────────┘
```

### Why this storage split (the ⚖️ decision the old note parked)

| Option (from the parked note) | Verdict |
|---|---|
| 1. Logs/GCS only | Right for **emission**, but the improvement loop needs SQL: joins against `fact_metric` ("which questions failed on schools with suppressed values?"), aggregates per tool, run-over-run deltas. Grepping JSONL doesn't scale to a loop you run weekly forever. |
| 2. A producer module serving writes *through* | A module boundary on the request hot path, and a synchronous write dependency chat doesn't need. |
| 3. Exception to "serving owns no tables" | First crack in a rule whose value is having none. |
| **Hybrid (this design): GCS emission + `evals` producer ingesting in batch** | Serving stays table-free; hot path gains one background GCS write; everything queryable lands in Postgres via the same batch-ETL pattern every other producer already uses. |

**Why not core-owned, like `usage_chat_daily`?** That table was explicitly the "dry run for
traces storage" (GO_LIVE_PLAN §3.4), and the answer from the dry run is: core ownership fits a
**tiny, stable counter** whose schema will basically never change. Traces are the opposite — an
**evolving event stream** whose schema will change every time the agent loop grows a capability
(sub-agents, code execution, new providers). Putting that in `core` makes every eval-system
iteration a breaking migration to the frozen contract. It gets its own module.

**GCS is the source of truth; Postgres holds the envelope.** Full payloads (tool results can be
an entire SPSA; Cloud Logging caps entries at 256 KB) live in
`gs://<bucket>/traces/v1/dt=YYYY-MM-DD/<trace_id>.jsonl`. The `trace` table holds the envelope +
GCS URI. Graders that need full payloads fetch the object. A one-line structured log to Cloud
Logging (trace_id, latency, tokens, tools, status) covers ops/debugging without a DB round-trip.

### Emission rules (hot path)

- **Fire-and-forget**: a failed trace write logs a warning and never raises. Chat must work
  when tracing is down; tracing must never add a failure mode or user-visible latency
  (flush happens in a FastAPI `BackgroundTask`, after the response is sent).
- **No sampling.** At prototype volume, keep 100% of turns; sampling is a knob to add later,
  never a default that silently hides the failures the loop exists to find.
- Eval-generated traffic is stamped `source: "eval"` (vs `"prod"`) so mining never feeds eval
  output back into eval cases.

## 2. Trace schema (v1)

One JSONL object per **turn** (one user message → one reply). Field names follow the
**OpenTelemetry GenAI semantic conventions** where one exists (`gen_ai.provider.name`,
`gen_ai.request.model`, `gen_ai.usage.input_tokens`, tool-span attributes). We are not adopting
an OTel SDK — the JSONL is ours — but naming discipline means these traces can be exported to
any OTel-compatible eval/observability backend (Langfuse, Phoenix, Braintrust) without rework,
and any provider's loop maps onto them.

**Envelope** (also the `trace` table row):

| Field | Notes |
|---|---|
| `trace_id` | UUIDv7 (time-ordered) |
| `session_id` | client-generated, optional — the stateless API can't infer conversation continuity |
| `ts`, `latency_ms`, `status` | `ok · refusal · error · max_iters` |
| `tenant_id` | `'public'` today — **present from day one** (§6) |
| `principal_hash` | salted hash of the verified `sub`; raw identity stays in `usage_chat_daily`, not here |
| `source` | `prod · eval` |
| `ui` | `{level, selected_school}` — the server-side scope that shaped the answer |
| `gen_ai.provider.name`, `gen_ai.request.model` | per turn; per-call values live in events (multi-model turns are legal) |
| `versions` | `{git_sha, prompt_hash, tool_catalog_hash, judge_rubric_version?}` — **without these the loop cannot attribute a delta to a change**; hashes are computed, not hand-bumped |
| `totals` | tokens by kind (input/output/cache_read/cache_write), `cost_usd_est` (via `estimate_cost_usd`), iterations |
| `gcs_uri` | the full-payload object |

**Events** (the JSONL body; `{trace_id, span_id, parent_span_id, seq, ts, type, ...}`):

| type | payload |
|---|---|
| `turn_start` | question, prior-message count, system-prompt hash |
| `model_call` | iteration, request params, normalized `stop` (§5), normalized usage, latency_ms, content digest |
| `tool_call` | name, input args, **full output**, error?, latency_ms |
| `turn_end` | final reply text, tools_used, totals |

`parent_span_id` + an **open** `type` vocabulary are what keep this schema ahead of the agent
loop: planner/executor steps, sub-agents, or a future code-execution/SQL-sandbox tool become new
span types nested under the turn — no schema break. `_run_tool` remains the single dispatch
point, so the tool layer is instrumented in one place (the parked note's "natural trace seam").

## 3. The `evals` module (new producer)

`backend/evals/` — a producer like `sip`/`likeschools`: owns its tables + migrations
(`version_locations`), its own ingest surface, depends only on `core`. Added to `SOURCE_TREES`,
`MODULE_OF_PREFIX`, and `pytest.ini testpaths` **in the scaffold commit** (both have
known silent-failure modes when omitted).

**Tables** (all carry `tenant_id`, RLS-ready):

| Table | Grain | Notes |
|---|---|---|
| `trace` | one turn | the envelope above; ingested from GCS in batch |
| `eval_case` | one curated question | question, ui context, expected behavior (graders to run + params, ground-truth SQL/fixture ref), `source` (`seed` \| `mined:<trace_id>`), `status` (`candidate → active → retired`), tags (`honesty`, `tool:<name>`, `equity`, …) |
| `eval_run` | one execution of a set | ts, versions (git_sha/prompt_hash/model/provider), target (which deployment), aggregate scores, cost_usd |
| `eval_result` | run × case | per-grader scores, pass/fail verdict, judge rationale, `trace_id` of the eval trace (every eval answer is itself a trace) |
| `feedback` | one rating | trace_id, 👍/👎, optional comment — ingested via `POST /api/feedback` (owned by this module, mounted in `main.py` like `sip`'s ingest routes) |

**Jobs** (batch, same Cloud Shell / Cloud Run-job pattern as every other producer):

- `python -m evals.ingest_traces` — new GCS objects → `trace` rows (idempotent on trace_id).
- `python -m evals.run_evals --set golden|full` — §4.
- `python -m evals.mine_traces` — §4, flywheel step 1.

**The no-import rule holds without exception.** The runner exercises chat **as an HTTP client**
against a deployed revision — the same way the frontend is a client. Nothing in `evals` imports
`serving`; graders read producers' tables with SQL (the sanctioned seam) for ground truth.

⚖️ **Runner target:** recommend a **tagged, no-traffic Cloud Run revision** for gating runs
(exact candidate code, zero user exposure — revision tags give it a stable URL) and the **live
service** for the nightly monitoring run (catches drift the gate can't: data loads, model-side
changes). Alternative — local uvicorn against Cloud SQL — saves a deploy but tests a
not-quite-prod stack.

**Spend safety for free:** the runner authenticates as its own service principal, so
`usage_chat_daily` + the per-user/global caps already meter and bound eval spend. Give the eval
principal its own cap generous enough for a full run, and the loop can never eat the API budget.

## 4. Graders and the flywheel

### Grader tiers — deterministic before judged, judged before human

| Tier | What | Instrument | Cost |
|---|---|---|---|
| **T0** | tool layer: dispatch, args, honesty fields | unit tests (exists: `test_chat_tools.py`) | CI, free |
| **T1** | **honesty/grounding** — the highest-value target (per the parked note: unambiguous failure, ground truth already in the DB, real-world cost of being wrong) | programmatic checks on the trace + a narrow yes/no judge where prose must be read | ~free |
| **T2** | **usefulness** — grounded, direct, non-regurgitating, actionable for a school planner | LLM-as-judge, versioned rubric, calibrated against a human-labeled subset (report agreement %) | paid, per run |
| **T3** | **trajectory & efficiency** — right tool, no redundant calls, iterations/tokens/latency/cost | programmatic on the trace | free |
| **T4** | **production signal** — 👍/👎 + comments, error rates in prod traces | `feedback` + `trace` aggregates | free |

T1 concretely, on this codebase:

- **`plan_status` compliance** — if any tool result in the trace said `not_on_file` for school X,
  the reply must not assert X *has no plan/goals/strategies* (the defamation guard). The trace
  makes this checkable per-turn, mechanically, over *real* questions — the step up from
  `test_chat_tools.py`, which pins tool output but can't see prose.
- **Numeric provenance** — every number in the reply must appear in some tool output in the
  trace (with formatting tolerance). Catches invented budgets/rates outright.
- **Suppressed-value handling** — a `value_status: suppressed` in tool output must never
  surface as `0` or "none" in the reply.
- **Resolution correctness** — the school the reply talks about is the school `_resolve_school`
  returned (catches wrong-school answers from partial-name matches, e.g. "Wilson").

T2's judge is itself versioned (`judge_rubric_version` in the envelope) and calibrated:
periodically a human labels a sample; judge/human agreement is reported with every run so rubric
drift is visible. Judge model: the strongest available (currently Opus-class), *not* the chat
model — the judge must out-read the system under test.

### The flywheel (the actual continuous-improvement loop)

1. **Mine** (weekly, `mine_traces`): tool errors, `_resolve_school` misses, refusals,
   `max_iters` exits, zero-tool answers to data questions, 👎 feedback, T1 failures on prod
   traces, plus clustering of questions to spot **unmet question classes**.
2. **Curate**: mined items land as `eval_case(status='candidate')` with the source trace
   attached. A human promotes to `active` (and strips anything personal — §6). Humans write
   rubrics and promote cases; they do not eyeball every answer.
3. **Aggregate → backlog**: per-tool error/miss/usefulness rates and per-question-class failure
   rates rank what to fix. This is where **marts & tools** improve, not just prompts — e.g.
   repeated resolution misses ⇒ better school-name search; a question class failing on data the
   marts don't expose ⇒ a mart gap, filed against the mart's module.
4. **Change + gate**: the fix ships **with the eval case(s) that motivated it** (red → green in
   the same PR), and the golden run guards everything else. Then the loop repeats on new traces.

### Cadence

| Run | Set | When | ~Cost |
|---|---|---|---|
| **Golden** | ~30–50 active cases (all T1 + representative T2/T3) | on demand + **on PRs touching `serving/` prompts/tools/marts** | ~$2 (Haiku answers + Opus judge) |
| **Full** | all active cases | nightly or weekly, against live | a few $ |
| T0 | unit tests | every PR (CI, exists) | free |

Model-layer evals **do not run in default CI** (paid, minutes-slow, non-deterministic); the PR
gate is a separately-triggered check (label or workflow_dispatch) whose pass/fail lands as a
required status on `serving`-touching PRs. That keeps "evals are the gate" true without making
every docs PR spend tokens. **Deltas over absolutes:** a run reports against the baseline run of
`main`, so a judge's absolute-score drift doesn't page anyone — regressions do.

**Seed set (before any mining exists):** the three `plan_status` tri-states × named/unnamed
school, one question per tool (5 tools), suppressed-subgroup cases, wrong-level and
ambiguous-name resolutions, an out-of-scope question (should decline), a "don't regurgitate the
screen" case — ~30 cases covering every honesty rule in the system prompt.

## 5. The provider seam (Anthropic · OpenAI/"Copilot" · Gemini)

What actually varies across providers is small and enumerable; everything else in this design is
already neutral. The planned `chat.py` overhaul introduces one seam:

```
neutral ToolCatalog (name, description, JSON Schema)   ← already exactly TOOLS' shape
        │
AgentRunner protocol: run(system, catalog, messages, recorder) → reply, totals
        │
        ├─ AnthropicRunner   tools / tool_use / tool_result        (exists — today's loop)
        ├─ OpenAIRunner      tools[function] / tool_calls / role:"tool"   (covers Azure OpenAI —
        │                    the "Copilot" stack — same wire format)
        └─ GeminiRunner      functionDeclarations / functionCall / functionResponse
```

Each runner owns its wire format and normalizes into the trace vocabulary:

| Normalized | Anthropic | OpenAI | Gemini |
|---|---|---|---|
| `stop: tool_use` | `stop_reason: tool_use` | `finish_reason: tool_calls` | parts contain `functionCall` |
| `stop: end` | `end_turn` | `stop` | `STOP` |
| `stop: max_tokens` | `max_tokens` | `length` | `MAX_TOKENS` |
| `stop: refusal` | `refusal` | `content_filter` | `SAFETY` |
| usage | `input/output/cache_*` | `prompt/completion/cached` | `promptTokenCount/candidatesTokenCount` |

`_run_tool` (dispatch) and the `TraceRecorder` sit **below** the runner, shared by all. The eval
harness needs **zero changes** to score a new provider: same HTTP surface, same trace schema,
same graders — `eval_run` rows differ only in `provider/model`, which makes cross-provider
comparison a query, not a project. That is the concrete meaning of "supports state-of-the-art
agentic logic from all four": the loop measures whichever loop is plugged in, and A/B-ing
providers on the golden set becomes routine.

⚖️ **Build order:** the seam should land **with the chat overhaul** (it's a refactor of the same
loop being touched anyway) — but **thin**: neutral catalog + `AnthropicRunner` only.
`OpenAIRunner`/`GeminiRunner` are written when there's a real reason to run one, not
speculatively. (Microsoft's Copilot Studio / GitHub Copilot are platforms, not raw model APIs —
the Azure OpenAI adapter is the practical "Copilot-stack" entry point.)

Future SOTA patterns this schema already accommodates (and the marts-first tool design matches):
planner/executor decomposition, sub-agents (nested spans), a sandboxed SQL/code-execution tool
over the marts (a new tool + span type — the biggest capability step the labs' internal agents
all took), and multi-model routing (cheap model drafts, strong model verifies — per-call
`model` in events).

## 6. Privacy, retention, tenancy

Traces retain **user questions** — the first user-generated content this system keeps.

- [`PRIVACY.md`](../PRIVACY.md) already discloses studying usage data to improve the prototype;
  extend it with one plain-English line: chat interactions are retained for a fixed window and
  reviewed to improve the assistant.
- **Retention:** raw GCS traces 90 days (bucket lifecycle rule, set at bucket creation);
  `trace` envelope rows kept indefinitely (no message text beyond the question — ⚖️ or drop the
  question too and keep it only in GCS); **promoted eval cases** kept indefinitely but pass
  through human review at promotion, where anything personal is stripped.
- **Identity:** traces carry `principal_hash`, never email. The join to a person exists only
  via the salt, held like other secrets.
- **Tenancy:** every table and event carries `tenant_id` from day one. Today everything is
  `'public'`. The moment chat serves private plan data, traces of those turns are
  tenant-scoped rows and the `evals` tables get the same RLS policies as `plan_*` — the schema
  is ready, only policies + the emission field flip.

## 7. Phasing (each phase = one module, one PR)

| Phase | What lands | Module |
|---|---|---|
| **0** | this doc; storage decision confirmed | docs |
| **1** | `TraceRecorder` + GCS flush + ops log line; `session_id` in `ChatRequest`; version hashes | `serving` (no tables) |
| **2** | `evals` scaffold: migration (5 tables), `ingest_traces`, `POST /api/feedback` + UI thumbs | `evals` (+ 2-line `main.py` mount) |
| **3** | seed golden set (~30), T1+T3 graders, `run_evals` + baseline report | `evals` |
| **4** | T2 judge + calibration, PR-gate wiring, `mine_traces` | `evals` |
| **5** | `AgentRunner` seam (thin: Anthropic only) — with the chat overhaul | `serving` |

Phase 1 produces value alone (traces to look at); each later phase compounds. Nothing here
blocks go-live; conversely go-live's §3.6 doesn't block phases 1–4 (traces work behind the IAM
gate — better to have the loop running **before** strangers arrive).

## 8. Decisions routed to the human (⚖️ recap)

1. **Storage:** hybrid — GCS emission + `evals` producer module (recommended above; resolves
   the parked note's question, keeps "serving owns no tables" with zero exceptions).
2. **Runner target:** tagged no-traffic revision for gates + live for nightly (recommended).
3. **Envelope retention:** keep the question text in the `trace` row indefinitely, or only in
   the 90-day GCS object?
4. **Provider seam timing:** with the chat overhaul, thin (recommended), vs. now, vs. later.
5. **Feedback thumbs in v1:** recommended yes (cheapest real usefulness signal; phase 2).
