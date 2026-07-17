# Design note: Claude-controlled workspace (indicator slots, subgroup slice, plan spotlight) + client-side sessions

**Status:** implemented (phases 1–4, 2026-07-16) · **Scope:** `serving`, `frontend` (no `core` change) ·
**Relates to:** [plan-relevance-tagging.md](plan-relevance-tagging.md) (the spotlight is its
read-time complement), [eval-trace-system.md](eval-trace-system.md) (§2 session continuity)

> **As-built deltas** (code is the source of truth; these are the deliberate departures):
> the spotlight spec is a `SpotlightSpec {plan_year, items}` wrapper so the server-stamped
> `plan_year` travels with the stored spec; slot payloads carry `student_group_label` for
> the slice header; `rename_session` shipped (phase 4) with a `custom_title` flag so the
> derived title never clobbers a Claude-authored one; sessions guard the active session
> from cap-pruning; `set_school` to the already-selected school forks a fresh session
> in place (no selection change fires, so the client applies the default payloads directly).

## What this is

Replace the fixed "Indicators" panel with a **Claude-controlled workspace**: three indicator
slots plus a fourth "Subgroup slice" slot, each holding a chart of a fixed, unchanging shape
(the existing `PeerChart`), where **Claude decides via chat tools what each slot shows** —
which metric, which school year, which student subgroup. The plan panel gains a
Claude-curated **spotlight**: plan items Claude pins as relevant to what's on screen. And the
frontend gains **sessions**: a left rail of recent lines of inquiry, persisted in
localStorage, each pinning a school + workspace + chat transcript.

Control is **Claude-only** (decided): no manual slot dropdowns. The default workspace renders
without any chat, so the app still works when chat is down or spend-capped.

## The invariant that makes this safe

> **Claude controls a *spec*; the server renders the *data*.**

The tool input is a small declarative spec, validated against `dim_metric` / `dim_period` /
`dim_student_group` / `plan_extraction`. The server fetches real rows and builds the chart
payload; the model and the frontend both receive that same server-built payload. Claude
cannot put a number, a plan sentence, or a chart on screen that didn't come from the
database. The only Claude-authored text rendered in the workspace is the spotlight's
one-line `reason`, visibly attributed.

This extends the DATA HONESTY contract already enforced in `chat.py` / `types.ts`: null is
UNKNOWN (often privacy suppression), never 0; `plan_status: not_on_file` is never "has no
plan". Every new payload carries the same `value_status` / `plan_status` fields through.

## Workspace spec

```ts
interface SlotSpec {
  metric_id: string;           // validated against dim_metric (see whitelist below)
  school_year: string | null;  // null = latest available; else validated against dim_period
  student_group_id: string;    // "all" for slots 1–3; any dim_student_group id for the slice
}

interface WorkspaceSpec {
  slots: [SlotSpec, SlotSpec, SlotSpec];
  subgroup_slice: SlotSpec | null;               // null = the slice renders its empty state
  plan_spotlight: SpotlightItem[] | null;        // see "Plan spotlight" below
}
```

**Metric whitelist is derived, not hand-listed:** `unit = 'pct' AND direction != 'context'`
from `dim_metric`. The fixed 0–100 chart scale (`PeerChart`'s deliberate, comment-guarded
comparability property) only makes sense for percent metrics; `enrollment` and
`homeless_enrollment` (`unit='count'`) are excluded by the same rule. This also admits the
CAASPP ELA/math metrics as slot options with zero extra work. Validation additionally checks
`applies_to_levels` against the school's level, so `grad_rate_acgr` is rejected for a Middle
school with a corrective error rather than an empty chart.

**Default spec** (what renders before Claude ever acts, and what a new session starts with):
today's three indicators — chronic absenteeism, graduation rate, college-going rate — latest
year, `all` students; empty slice; no spotlight. First paint of the new app is pixel-identical
to the current one. `INDICATOR_METRICS` in `marts.py` becomes this default spec.

## Chat tools (serving)

Three new tools join the catalog in `chat.py` (the computed `TOOL_CATALOG_HASH` versions this
change into traces automatically):

| Tool | Input | Effect |
|---|---|---|
| `set_workspace_slot` | `{slot: 1\|2\|3\|"subgroup_slice", metric_id, school_year?, student_group_id?}` | Validates the spec, fetches the benchmark, returns the chart-ready payload. |
| `spotlight_plan_items` | `{items: [{goal_index, action_indices?, reason}]}` | Validates references against the school's `plan_extraction` row; returns the resolved items. |
| `set_school` | `{school_name}` | Resolves via `_resolve_school`; returns the school row + its default workspace payloads. Client-side effect: activate/create a session (below). |

Tool handlers return errors for invalid specs (unknown metric, year with no data, wrong
level, out-of-range goal index) so the model self-corrects inside the existing tool loop —
same pattern as the current `{"error": ...}` returns. `MAX_TOOL_ITERS = 5` is enough for a
"set two slots and answer" turn; revisit only if traces show `max_iters` exits.

### The wire contract (request and response both grow one field)

**Request** — the frontend sends the active workspace and session on every `/chat` call:

```jsonc
{ "messages": [...], "level": "High",
  "session_id": "<session uuid>",          // already in ChatRequest; now always sent
  "workspace": { /* WorkspaceSpec */ } }   // NEW: what is currently on screen
```

`build_system` renders the workspace into the system prompt ("Slot 1 shows Chronic
absenteeism, 2023-24, All Students…"). This is what grounds the existing "don't regurgitate
the screen" instruction in actual screen state, and what stops Claude from clobbering slots
it just set. It also means slot state lands in the traced system hash.

**Response** — alongside `reply`, the accumulated workspace mutations of the turn:

```jsonc
{ "reply": "...", "tools_used": [...],
  "workspace": {                            // NEW, present only if a workspace tool ran
    "spec": { /* full WorkspaceSpec after this turn */ },
    "payloads": { "slot_1": {...}, "subgroup_slice": {...} },  // only slots that changed
    "spotlight": [ /* resolved items */ ],
    "school": { /* only if set_school ran */ }
  } }
```

The chat handler accumulates this during the tool loop (tool results currently go only to the
model; this is the seam that forwards them to the UI). **The frontend never refetches after a
tool call** — one round trip, and the model and the screen are guaranteed to be looking at
the same numbers.

## Benchmark generalization (`fetch_peer_benchmark`)

Two parameters, both already half-present in the signature:

1. **`school_year`** — currently the query takes latest-value-per-school; a requested year
   adds `AND p.school_year = :y`. **The cohort stays fixed**: always the latest
   `mart_school_peer` set, only the data year varies. Same school vs. same band across years
   is the apples-to-apples comparison, and it avoids per-year peer builds. The payload says
   so explicitly (`"cohort": "latest peer set; data year <y>"`).
2. **`student_group_id`** — replaces the hardcoded `student_group_id = 'all'` filter. The
   band becomes *peers' same-subgroup values*. Expect shrinkage: subgroup values are
   frequently suppressed for small n, so the band's `n` drops. That is honest and already
   displayed; below a soft floor (`n < 10`) the payload carries a `band_status` note and the
   UI captions the band as thin rather than hiding it. A suppressed target value renders the
   existing "UNKNOWN, not 0" treatment.

A new endpoint exposes the same fetch for session restore (specs are stored, data is not):

```
POST /marts/workspace   { school_id, spec: WorkspaceSpec }
  → { slots: [...], subgroup_slice, spotlight: [resolved], plan: {...} }
```

One call restores a whole session's panels. `/marts/school-detail` stays until the frontend
cuts over (MODULES.md: a module change can't rename a URL out from under the frontend), then
retires.

## Plan spotlight

**Why Claude curates instead of the mart filtering:** the extractor's `goal_type` and the
serving-time keyword regex are both untrusted labels — that's the documented Wilson failure
in [plan-relevance-tagging.md](plan-relevance-tagging.md). But Claude reads the full plan
text through `query_school_plan` and can match semantically at read time. The spotlight
fixes categorization *per conversation* without re-extraction, and is complementary to
extraction-time tagging: when phase-1 tags land, they make Claude's pins better-informed;
nothing here depends on them.

**Reference format:** `goal_number`/`action_number` can be null in extractions, so the
canonical reference is the **index path** into the served `full_plan_goals` array —
`{goal_index, action_indices?}` — which `query_school_plan` now includes in its output so
Claude pins exactly what it read. The server validates indices against the school's current
`plan_extraction` row and renders the pinned items from DB rows: statement, budget, funding
source, provenance quote + page. Claude contributes selection and the `reason` line only.

**Staleness:** the resolved payload carries `plan_year`; if a stored spotlight's `plan_year`
no longer matches the school's latest extraction on restore, the spotlight is dropped
silently (the full goal list below it never lies). The full collapsed goal list stays as the
always-rendered base; the spotlight is a strip above it, styled as Claude-attributed.

## Sessions (frontend only — zero backend state)

A session pins **one school** and carries everything the user was looking at. Switching
school never mutates a session; it activates or creates one.

```ts
interface Session {
  v: 1;                        // schema version — unparseable sessions are dropped on load
  id: string;                  // uuid; sent as session_id on every /chat call
  school_id: string;           // pinned
  school_name: string;         // denormalized for rail display without a fetch
  district_id: string;
  level: Level;
  title: string;               // "<school> — <first user question, truncated>"
  created_at: number;
  updated_at: number;          // rail sort key
  workspace: WorkspaceSpec;    // specs only — never cached chart data
  messages: ChatTurn[];        // reply text only — never tool payloads
}
```

- **Storage:** one localStorage key `si.sessions.v1` → `{v, active_id, sessions[]}`. Capped
  at 20 sessions, pruned by `updated_at`; writes debounced. Text-only transcripts keep this
  far under quota.
- **Specs, not data:** on activation, panels refetch via `POST /marts/workspace`. Cached
  chart data goes stale, bloats storage, and would reintroduce "the screen shows numbers the
  server didn't just produce". The existing loading-dots pattern covers the gap.
- **Header school picker** → most recent session for that school if one exists, else a new
  default-spec session. **New-session button** on the rail for a fresh look at the same
  school (otherwise old chat context contaminates a new inquiry).
- **`set_school` mid-conversation** forks: the transcript **copies forward** into the new
  session, the workspace resets to defaults. The user experiences one continuous
  conversation; the rail keeps two honest snapshots of "what was I looking at".
- **Traces join for free:** the session uuid is exactly the client-generated `session_id`
  that `ChatRequest` already carries for eval-trace continuity (eval-trace-system.md §2).
  Sessions make it always-populated and meaningful.
- **State architecture:** the active `Session` is the single source of truth; `App`'s current
  `sel`/`detail`/`peers` state becomes a view of it. All mutations — header picks, Claude
  tool effects, chat turns — flow through one reducer, which is also the one place the
  debounced persist hangs off.

## Non-goals (deliberate)

- **No server-side session store.** localStorage keeps the backend stateless and
  public-data-only — which is what lets `chat.py` skip tenancy entirely. Accounts and
  cross-device sync would drag auth/RLS into a module that deliberately has none. Revisit
  only alongside the GO_LIVE identity work, as its own decision.
- **No free-form chart configs, no arbitrary SQL, no new chart shapes.** The fixed spec and
  the fixed `PeerChart` shape are the honesty and security boundary — and the steady shape
  is what keeps flipping metrics/years/subgroups visually comparable.
- **No root-cause claim.** Subgroup × year × metric flipping localizes problems better than
  three static charts, but it is still summative indicators and problem ranking. The UI copy
  should not oversell it.

## Phasing (one module per branch, per CLAUDE.md)

| Phase | Module | Change | Cost |
|---|---|---|---|
| **1** | `serving` | Generalize `fetch_peer_benchmark` (year, subgroup, fixed-cohort note, `band_status`); derived metric whitelist; `POST /marts/workspace`; the three tools + request/response `workspace` field; index paths in `query_school_plan` output; system-prompt rendering of screen state. All unit-testable DB-patched, per house style. | medium |
| **2** | `frontend` | Workspace state + apply-payload path (single implicit session, no rail yet): slots render from specs, chat response mutates them, slice + spotlight render. Cut `/school-detail` over to `/marts/workspace`. | medium |
| **3** | `frontend` | Sessions: reducer + localStorage persistence + left rail + new-session + school-picker semantics + `set_school` fork behavior. | medium |
| **4** (polish) | `serving`+`frontend` | `rename_session` tool (Claude titles the session after the first exchange); `band_status` captioning refinements; retire `/school-detail`. | small |

Phase 1 ships value alone (chat answers improve because tools can slice by year/subgroup even
before the UI applies payloads). Phases 2 and 3 are where the showpiece lands.
