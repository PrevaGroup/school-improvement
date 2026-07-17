// Pure workspace state logic (no fetch, no React) — unit-tested in workspace.test.ts.
//
// The workspace is Claude-controlled: chat tool calls return server-built chart payloads,
// and the chat response's `workspace` field carries them here. This module only MERGES
// what the server sent — it never fabricates a payload, which is the client half of the
// "Claude controls a spec; the server renders the data" invariant
// (docs/design/agentic-workspace-and-sessions.md).

import type { ChatWorkspace, WorkspaceData, WorkspaceSpec } from "./types";

// Mirrors backend DEFAULT_WORKSPACE_SPEC (backend/app/marts.py): the first paint —
// and every new school before Claude acts — is exactly the old fixed three-indicator panel.
export const DEFAULT_WORKSPACE_SPEC: WorkspaceSpec = {
  slots: [
    { metric_id: "chronic_absenteeism_rate", school_year: null, student_group_id: "all" },
    { metric_id: "grad_rate_acgr", school_year: null, student_group_id: "all" },
    { metric_id: "college_going_rate", school_year: null, student_group_id: "all" },
  ],
  subgroup_slice: null,
  plan_spotlight: null,
};

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
  return {
    ...prev,
    spec: w.spec ?? prev.spec,
    slots,
    subgroup_slice: w.payloads["subgroup_slice"] ?? prev.subgroup_slice,
    spotlight: w.spotlight ?? prev.spotlight,
  };
}
