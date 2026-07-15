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

export interface Indicator {
  display_name: string;
  target_value: number | null;
  target_year: string | null;
  direction: "lower_better" | "higher_better";
  peer_distribution: PeerDistribution | null;
}

export interface Provenance { page: number | null; quote: string | null }

export interface PlanAction {
  strategy_text: string;
  budgeted_amount: number | null;
  funding_source_raw: string | null;
  provenance: Provenance | null;
}

export interface PlanGoal {
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

export interface SchoolDetail { indicators: Indicator[]; plan: SchoolPlan }

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

export interface District { district_id: string; district_name: string }
export type Level = "High" | "Middle" | "Primary";
export interface ChatTurn { role: "user" | "assistant"; content: string }
