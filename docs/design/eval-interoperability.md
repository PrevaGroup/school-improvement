# Design: eval interoperability — closing the gap with Learning Commons

**Status:** PROPOSED · decisions **OPEN** (routed to the human, §5) · **Scope:** the `evals`
module (grader interface, registry), `serving`'s tool catalog, the trace export path ·
**Relationship:** builds on [`eval-trace-system.md`](eval-trace-system.md) (the decided loop);
this doc does **not** change any decision there — it proposes how to make that loop's graders and
grounding *interoperable* with the wider field, prompted by a review of
[Learning Commons](https://docs.learningcommons.org/evaluators/understanding-evaluators/introduction).

## 0. The gap in one sentence

Our eval system is interoperable on the **plumbing** axis (OTel-shaped traces, a vendor-agnostic
provider seam) but its **graders and domain grounding are entirely bespoke and unpublished** —
whereas Learning Commons is interoperable on exactly that **content/standards** axis (a shared
grader envelope, versioned evaluators, published ground-truth datasets, and a standards knowledge
graph other tools consume). This doc proposes closing the second axis without diluting the first.

## 1. Two different things (the framing that keeps this honest)

Learning Commons and our eval system are **complementary, not competing**, and every
recommendation below depends on not confusing them:

| | **Learning Commons** | **Ours** (`eval-trace-system.md`) |
|---|---|---|
| What it is | A library of reusable, calibrated **graders** + a domain **knowledge graph** | A closed-loop **improvement harness** for one agent |
| Unit evaluated | A content **artifact** (a passage, a piece of feedback) | An agent **turn / trajectory** (honesty, grounding, tool choice) |
| Graders | Productized, versioned, expert-calibrated, shared | Bespoke, internal, specific to our tools/marts (T0–T4) |
| Ground truth | Published, downloadable, **CC BY 4.0** benchmark | Private DB + curated `eval_case` rows, unpublished |
| Output shape | Standard envelope: `result.score` · `result.answer.label` · `result.explanation.summary` | Bespoke JSONB per grader in `eval_result.scores` |
| Versioning | **SemVer** per evaluator; past versions documented | Git SHA / prompt / rubric **hashes** on runs |
| Interop axis | **domain/content** — shared graders, standards, crosswalks | **plumbing** — OTel traces, provider-agnostic runner seam |
| The mine→gate loop | not its job | the whole point |

The load-bearing consequence: **an LC evaluator can sit *inside* our harness as one grader; our
loop has no LC equivalent.** So the play is *consume LC where it is a better grader/ground-truth
than what we would build, keep our loop, and standardize our grader interface so LC plugs in* —
not "adopt LC" or "rebuild LC."

## 2. What "interoperable" concretely buys LC (and what we already have)

**LC's five interop features** (verified from their docs):

1. A **standard output envelope** shared across every evaluator — `score`, `answer.label`,
   `explanation.summary` — regardless of dimension/rubric.
   ([SDK overview](https://docs.learningcommons.org/evaluators/sdk-api-reference/overview.md))
2. **Versioned evaluators** (SemVer, past versions documented) → a score is reproducible/pinnable.
3. **Published, downloadable ground-truth datasets** — explicitly *"a replicable and transparent
   benchmark for edtech developers across the field,"* CC BY 4.0.
   ([dataset overview](https://docs.learningcommons.org/evaluators/dataset/introduction.md))
4. A **shared semantic backbone** — the Knowledge Graph: academic standards, **cross-state
   crosswalks**, learning components, progressions — via GraphQL / REST / OpenAPI / an **MCP
   server** / a **Claude connector**, with controlled vocabularies.
   ([docs index](https://docs.learningcommons.org/llms.txt))
5. **Neutral interface, vendor-specific inside** — the SDK envelope is uniform, but the
   grade-level evaluator runs on Gemini-2.5-pro at temp 0.25. Interop lives at the *interface*.

**What we already have on the other axis** (and LC does not): the trace schema follows the
**OpenTelemetry GenAI semantic conventions** (exportable to Langfuse/Phoenix/Braintrust), and the
**`AgentRunner` seam** normalizes any provider into one neutral vocabulary — both enforced
invariants. These are real interop assets; the proposals below extend the *content* axis to match.

## 3. Proposals

Prioritized. Each names its tradeoff; none is a default — see §5 for the open decisions. Sequenced
against `eval-trace-system.md`'s phasing (graders land in phases 3–4).

### P1 (keystone) — a normalized grader-result envelope, LC-shaped

Today each grader writes ad-hoc JSONB into `eval_result.scores`. Give **every** grader one uniform
result — `{grader_id, grader_version, score, label, explanation, ...}` — deliberately mirroring
LC's `score` / `answer.label` / `explanation.summary`. This is the precondition for everything
below and formalizes the `judge_rubric_version` instinct already in the design. Low risk, high
leverage; pure convention over the existing JSONB column (no migration).

### P2 — a grader registry + `GraderAdapter` seam (the same move as `AgentRunner`)

Register graders — ours **and** third-party — by `id` + SemVer, referenced from
`eval_case.expected.graders[]` (which already carries "graders to run + params"). Then dropping in
an LC evaluator as a T2 content grader becomes *an adapter + a config line*, exactly how the
provider seam makes a new model an adapter.

- **Boundary:** a `GraderAdapter` calling LC's SDK is an external call — fine, the same posture as
  the runner being an HTTP client — but it must **not** import `serving` (the boundary test still
  applies), and graders still read our ground truth via SQL.
- **Tradeoff to decide (§5):** an external grader takes a live dependency into the loop — network,
  a Google API key, LC's own versioning, Gemini-backed under the hood. That is acceptable for a
  *content-quality* grader we could not calibrate ourselves; it would be wrong for a T1 honesty
  check (§4). Name it per grader, don't adopt wholesale.

### P3 — wire LC's Knowledge Graph into the chat tool catalog (highest-leverage domain interop)

LC ships an **MCP server and a Claude connector**, so adding standards / cross-state crosswalks /
learning progressions to our neutral `ToolCatalog` is near-zero-friction and CC BY 4.0. This
grounds the assistant in a *shared* standards vocabulary instead of a bespoke table, matches the
loop's "ground in a curated semantic layer" thesis, and — since the repo is CA-only today — LC's
crosswalks are the ready bridge if the platform ever goes multi-state. **This is the most concrete
"be more interoperable" step**, and it is additive (a new tool + span type — no schema break).

- **Tradeoff:** a new external tool dependency in the hot path. It is a *read* tool, cache-friendly,
  and fire-tolerant, but it is another vendor surface to key and monitor.

### P4 — consume LC evaluators only where the product generates/assesses content

Today's assistant answers data/planning questions over marts, so most LC evaluators (grade-level
appropriateness, feedback quality) **do not apply yet** — the unit they grade (a content artifact)
isn't what we produce. The moment the product drafts SPSA language, feedback, or standards-aligned
material, prefer an LC evaluator (calibrated, benchmarked) over a hand-rolled judge. This is a
*"when,"* not a *"now"* — flagged so it's a deliberate trigger, not a missed option.

### P5 — prove the OTel trace export (cheap credibility on the axis we already lead)

Our trace schema follows OTel GenAI conventions but that is latent. Actually export to one backend
(Phoenix/Langfuse) and keep it working. LC has no equivalent; this is our interop *strength* — make
it real rather than asserted.

### P6 (lower priority) — adopt LC's dataset/calibration discipline

Version our `eval_case` ground truth as a documented benchmark, and align T2 metric names to LC's
(exact-match accuracy, expert-agreement rate, reasoning-quality). Keeps open the option to compare
against — or one day contribute to — a field benchmark. No commitment to publish; just don't
foreclose it.

## 4. Non-goal: what stays bespoke, on purpose

Our **T1 honesty/grounding graders** — `plan_status` compliance (the defamation guard), numeric
provenance, suppressed-value handling, wrong-school resolution — are correctly bespoke. They test
*our* tools against *our* DB; LC has nothing for them and shouldn't. The interoperability gap is
real **only on the content/standards axis**. Converging the honesty graders toward any external
library would trade away the highest-value, most product-specific checks we have. Explicitly out of
scope.

## 5. ⚖️ Decisions routed to the human

> **Resolved 2026-07-23.** P1 **accepted + shipped** and P2 **accepted + shipped** (this landed as
> a *refactor*, not greenfield: the grader layer — `evals/graders.py`, a `GRADERS` registry,
> `run_graders`, the T1/T3 graders and the injected-callable T2 judge — already existed, so §1's
> "graders are bespoke" holds but "don't exist yet" was stale by the time this note merged).
> P3 **held** until a real need (same reasoning as P4): the CA-only, plan-focused assistant
> doesn't exercise standards lookup today. When picked up, the choice is inline REST tools (fits
> the current inline-tool chat) vs adding an MCP client; both need LC API credentials.
> P4 **declined for now** (correct: LC's current evaluators grade *content artifacts*, which this
> assistant doesn't produce). P5 **accepted + shipped** — `evals/otel_export.py` converts a trace
> to OTLP/JSON (a collector accepts it), documented in `evals/README.md` § OpenTelemetry export.
> P6 **accepted + shipped** — a versioned ground-truth benchmark (`BENCHMARK_VERSION`, stamped on
> every `eval_run`) and an LC-aligned calibration vocabulary (`evals/calibration.py`:
> `exact_match` · `expert_agreement_rate` · `reasoning_quality`).
> What P1/P2 shipped as: a `version` on every `GraderResult` (stamped by `run_graders` from
> `GRADER_VERSIONS`), and an `EXTERNAL_GRADERS` adapter registry whose graders take an injected
> `client` — the seam a Learning Commons evaluator plugs into — with a reference adapter that
> normalizes the neutral `{score, label, explanation}` envelope, unit-tested with a fake client
> (no live LC call, per P4).

The original decisions, for the record:

1. **Grader envelope (P1)** — adopt the normalized `{grader_id, grader_version, score, label,
   explanation}` shape now, as convention over the existing `eval_result.scores` JSONB? (Cheap,
   reversible, unblocks the rest.)
2. **Grader registry + external graders (P2)** — do we want third-party graders pluggable at all,
   given the live-dependency tradeoff? If yes, registry-by-SemVer with a `GraderAdapter`; if no,
   the envelope (P1) still stands for our own graders.
3. **Knowledge Graph as a tool (P3)** — add LC's MCP/Claude-connector standards graph to the tool
   catalog? Highest domain-interop leverage, but a new external hot-path dependency and a
   multi-state question we may not have yet.
4. **OTel export (P5)** — worth the small effort to make the latent export real now, or defer until
   an external observability backend is actually wanted?
5. **Benchmark discipline (P6)** — treat `eval_case` ground truth as a versioned benchmark now, or
   revisit at volume?

No code changes accompany this doc; it is analysis + proposals. On a yes, each proposal is its own
scoped PR against the phase it belongs to in `eval-trace-system.md`.
