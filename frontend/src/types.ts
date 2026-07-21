// Shapes the backend actually returns (backend/app/marts.py, backend/app/chat.py).
//
// `| null` is load-bearing throughout. Education data is full of gaps, and a metric that is
// absent is UNKNOWN — often privacy-suppressed for small enrollment — never zero. Typing these
// as `number` and defaulting to 0 would silently invent facts about real schools; the backend
// goes to real trouble to keep missingness explicit (plan_status, value_status), so the UI must
// not throw that away at the type boundary.

export type Alignment =
  | "unmet_need" | "no_response" | "responsive" | "ok" | "plan_missing" | "unknown";

export interface PeerDistribution {
  n: number;
  median: number | null;
  p25: number | null;
  p75: number | null;
}

// --- Claude-controlled workspace (backend/app/marts.py WorkspaceSpec et al.) ---------- //
// Claude controls the SPEC; the server renders the DATA. The spec is what the client
// stores and sends; every payload below was built server-side from DB rows.

export interface SlotSpec {
  metric_id: string;
  school_year: string | null; // null = latest available
  student_group_id: string; // "all" on slots 1-3; a real subgroup on the slice
}

export interface SpotlightItemSpec {
  goal_index: number; // position in the served plan goals — canonical ref
  action_indices: number[] | null;
  reason: string;
}

export interface SpotlightSpec {
  plan_year: string | null; // server-stamped; a mismatch on restore drops the spotlight
  items: SpotlightItemSpec[];
}

export interface WorkspaceSpec {
  slots: [SlotSpec, SlotSpec, SlotSpec];
  // Three parallel subgroup-slice boxes (like the indicator slots), each null until filled.
  subgroup_slots: [SlotSpec | null, SlotSpec | null, SlotSpec | null];
  plan_spotlight: SpotlightSpec | null;
}

// One chart-ready slot as the server built it (fetch_slot). `error` is a validation
// message (e.g. an HS-only metric after switching to a Middle school) — rendered, not
// hidden. The honesty fields ride along: value_status (missing = UNKNOWN, never 0),
// band_status (thin subgroup band), cohort_note (fixed cohort, varied data year).
export interface SlotPayload {
  error?: string;
  slot_spec?: SlotSpec;
  display_name?: string;
  metric_id?: string;
  direction?: "lower_better" | "higher_better" | null;
  student_group_id?: string;
  student_group_label?: string | null;
  target_value?: number | null;
  target_year?: string | null;
  peer_distribution?: PeerDistribution | null;
  peer_performance_percentile?: number | null;
  band_status?: string | null;
  cohort_note?: string;
  value_status?: string;
}

export interface SpotlightItem {
  goal_index: number;
  goal_number: string | null;
  goal_type: string | null;
  statement: string | null;
  actions: PlanAction[];
  reason: string; // the ONE Claude-authored line — rendered visibly attributed
}

export interface Spotlight {
  plan_year: string | null;
  items: SpotlightItem[];
  note?: string;
}

// POST /marts/workspace response — everything the panel renders for one school.
export interface WorkspaceData {
  school_id: string;
  spec: WorkspaceSpec;
  slots: SlotPayload[];
  subgroup_slots: (SlotPayload | null)[];
  spotlight: Spotlight | null;
  plan?: SchoolPlan;
}

// The `workspace` field on a chat response: the turn's accumulated mutations, carrying
// the SAME server-built payloads the model saw (applied directly — no refetch).
export interface ChatWorkspace {
  spec: WorkspaceSpec | null;
  payloads: Record<string, SlotPayload>;
  spotlight: Spotlight | null;
  school: { school_id: string; school_name: string; district_id: string } | null;
  session_title?: string | null; // rename_session — applied to the active rail entry
}

export interface Provenance { page: number | null; quote: string | null }

export interface PlanAction {
  action_index?: number; // canonical spotlight ref (positions — numbers can be null)
  strategy_text: string;
  budgeted_amount: number | null;
  funding_source_raw: string | null;
  provenance: Provenance | null;
}

export interface PlanGoal {
  goal_index?: number; // canonical spotlight ref
  goal_type: string | null;
  goal_number: string | null;
  statement: string | null;
  actions: PlanAction[];
}

export interface SchoolPlan {
  has_plan: boolean;
  plan_status: string;
  plan_year: string | null;
  goals: PlanGoal[];
}

export interface DiagnosticSchool {
  school_id: string;
  school_name: string;
  alignment: Alignment;
  peer_performance_percentile: number | null;
}

export interface Peer {
  rank: number;
  school_name: string;
  district_name: string | null;
  enroll_total: number | null;
  pct_sed: number | null;
  pct_el: number | null;
  pct_swd: number | null;
  locale: string | null;
  chronic_absenteeism_rate: number | null;
  has_plan: boolean;
}

// Admin eval dashboard (GET /api/evals/*, admin-gated). `available:false` = the trace store
// isn't populated yet (migration / ingest not run) — the UI shows an honest empty state.
export interface EvalSummary {
  available: boolean;
  window?: number;
  traces?: number;
  ok_rate?: number | null;
  by_status?: Record<string, number>;
  by_source?: Record<string, number>;
  by_model?: Record<string, number>;
  cost_usd?: number;
  tokens?: number;
  latency_p50_ms?: number | null;
  latency_max_ms?: number | null;
}
export interface EvalTraceRow {
  trace_id: string;
  ts: string | null;
  question: string | null;
  status: string | null;
  latency_ms: number | null;
  model: string | null;
  cost_usd_est: number | null;
  iterations: number | null;
  git_sha: string | null;
}

export interface District { district_id: string; district_name: string }
export type Level = "High" | "Middle" | "Primary";
export interface ChatTurn { role: "user" | "assistant"; content: string }
