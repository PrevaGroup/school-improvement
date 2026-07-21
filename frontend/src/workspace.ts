// Pure workspace state logic (no fetch, no React) — unit-tested in workspace.test.ts.
//
// The workspace is Claude-controlled: chat tool calls return server-built chart payloads,
// and the chat response's `workspace` field carries them here. This module only MERGES
// what the server sent — it never fabricates a payload, which is the client half of the
// "Claude controls a spec; the server renders the data" invariant
// (docs/design/agentic-workspace-and-sessions.md).

import type { ChatWorkspace, Level, SlotSpec, WorkspaceData, WorkspaceSpec } from "./types";

// CLIENT FALLBACK for the level-aware default. The SERVER owns the source of truth
// (GET /marts/workspace-defaults, keyed on backend/app/marts.py DEFAULT_INDICATORS_BY_LEVEL);
// App fetches it at boot and passes it to defaultSpecForLevel. This map only covers the
// pre-fetch window / offline, so it must stay in step with the backend — server always wins.
// ES/MS lead with CAASPP outcomes because grad/college are HS-only (would render as errors).
const FALLBACK_INDICATORS_BY_LEVEL: Record<Level, string[]> = {
  High: ["chronic_absenteeism_rate", "grad_rate_acgr", "college_going_rate"],
  Middle: ["chronic_absenteeism_rate", "ela_met_standard_pct", "math_met_standard_pct"],
  Primary: ["chronic_absenteeism_rate", "ela_met_standard_pct", "math_met_standard_pct"],
};

function specOf(ids: string[]): WorkspaceSpec {
  return {
    slots: ids.map((m) => ({ metric_id: m, school_year: null, student_group_id: "all" })) as [SlotSpec, SlotSpec, SlotSpec],
    subgroup_slots: [null, null, null],
    plan_spotlight: null,
  };
}

// The seed workspace for a school at this level. Prefers the server-fetched defaults; falls
// back to the client map when they haven't loaded yet. Returns a fresh (deep) copy each call
// so a session owns its spec.
export function defaultSpecForLevel(level: Level, server?: Record<string, WorkspaceSpec> | null): WorkspaceSpec {
  const fromServer = server?.[level];
  if (fromServer) return JSON.parse(JSON.stringify(fromServer)) as WorkspaceSpec;
  return specOf(FALLBACK_INDICATORS_BY_LEVEL[level] ?? FALLBACK_INDICATORS_BY_LEVEL.High);
}

// Back-compat: the High (HS) default is the historical three-indicator panel. Prefer
// defaultSpecForLevel(level) — this constant is the HS fallback for callers without a level.
export const DEFAULT_WORKSPACE_SPEC: WorkspaceSpec = specOf(FALLBACK_INDICATORS_BY_LEVEL.High);

// Merge a chat turn's workspace mutations into the loaded panel data. Only the payloads
// the server actually sent replace anything; untouched slots, the slice, the spotlight,
// and the plan all survive. (The set_school path is handled BEFORE this in App — a school
// switch re-fetches wholesale rather than merging across schools.)
export function applyChatWorkspace(prev: WorkspaceData | null, w: ChatWorkspace): WorkspaceData | null {
  if (!prev) return prev; // panels not loaded yet — the selection effect will fetch fresh
  const slots = prev.slots.slice();
  for (let i = 0; i < 3; i++) {
    const p = w.payloads[`slot_${i + 1}`];
    if (p) slots[i] = p;
  }
  const subgroup_slots = (prev.subgroup_slots ?? [null, null, null]).slice();
  for (let i = 0; i < 3; i++) {
    const p = w.payloads[`subgroup_${i + 1}`];
    if (p) subgroup_slots[i] = p;
  }
  return {
    ...prev,
    spec: w.spec ?? prev.spec,
    slots,
    subgroup_slots,
    spotlight: w.spotlight ?? prev.spotlight,
  };
}
