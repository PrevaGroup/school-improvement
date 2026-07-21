import { describe, expect, it } from "vitest";

import { DEFAULT_WORKSPACE_SPEC, applyChatWorkspace, defaultSpecForLevel } from "./workspace";
import type { ChatWorkspace, SlotPayload, WorkspaceData, WorkspaceSpec } from "./types";

// applyChatWorkspace is the client half of "Claude controls a spec; the server renders
// the data": it may only MERGE payloads the server sent — never fabricate, never let a
// one-slot change disturb the other panels. These pin the merge semantics.

function slot(name: string): SlotPayload {
  return { display_name: name, target_value: 10, peer_distribution: { n: 40, median: 12, p25: 8, p75: 20 } };
}

function data(): WorkspaceData {
  return {
    school_id: "S1",
    spec: DEFAULT_WORKSPACE_SPEC,
    slots: [slot("A"), slot("B"), slot("C")],
    subgroup_slots: [null, null, null],
    spotlight: null,
    plan: { has_plan: true, plan_status: "on_file", plan_year: "2024-25", goals: [] },
  };
}

function turn(overrides: Partial<ChatWorkspace>): ChatWorkspace {
  return { spec: null, payloads: {}, spotlight: null, school: null, ...overrides };
}

describe("applyChatWorkspace — merge, never fabricate", () => {
  it("replaces exactly the slots the server sent and keeps the rest", () => {
    const next = applyChatWorkspace(data(), turn({ payloads: { slot_2: slot("NEW") } }))!;
    expect(next.slots.map((s) => s.display_name)).toEqual(["A", "NEW", "C"]);
  });

  it("fills one subgroup box without touching the indicator slots or the other boxes", () => {
    const next = applyChatWorkspace(data(), turn({ payloads: { subgroup_2: slot("EL") } }))!;
    expect(next.subgroup_slots[1]?.display_name).toBe("EL");
    expect(next.subgroup_slots[0]).toBeNull();
    expect(next.subgroup_slots[2]).toBeNull();
    expect(next.slots.map((s) => s.display_name)).toEqual(["A", "B", "C"]);
  });

  it("adopts the turn's spec so the next request describes the true screen", () => {
    const spec: typeof DEFAULT_WORKSPACE_SPEC = {
      ...DEFAULT_WORKSPACE_SPEC,
      subgroup_slots: [{ metric_id: "suspension_rate", school_year: null, student_group_id: "el" }, null, null],
    };
    const next = applyChatWorkspace(data(), turn({ spec, payloads: { subgroup_1: slot("EL") } }))!;
    expect(next.spec.subgroup_slots[0]?.student_group_id).toBe("el");
  });

  it("keeps the plan and spotlight when only a slot changed", () => {
    const prev = data();
    prev.spotlight = { plan_year: "2024-25", items: [] };
    const next = applyChatWorkspace(prev, turn({ payloads: { slot_1: slot("NEW") } }))!;
    expect(next.plan).toBe(prev.plan);
    expect(next.spotlight).toBe(prev.spotlight);
  });

  it("applies a spotlight without touching the charts", () => {
    const spot = { plan_year: "2024-25", items: [] };
    const next = applyChatWorkspace(data(), turn({ spotlight: spot }))!;
    expect(next.spotlight).toBe(spot);
    expect(next.slots.map((s) => s.display_name)).toEqual(["A", "B", "C"]);
  });

  it("is a no-op before the panels have loaded", () => {
    expect(applyChatWorkspace(null, turn({ payloads: { slot_1: slot("X") } }))).toBeNull();
  });
});

describe("DEFAULT_WORKSPACE_SPEC mirrors the backend HS default", () => {
  it("is the three-indicator HS panel, latest year, all students", () => {
    expect(DEFAULT_WORKSPACE_SPEC.slots.map((s) => s.metric_id)).toEqual([
      "chronic_absenteeism_rate", "grad_rate_acgr", "college_going_rate",
    ]);
    expect(DEFAULT_WORKSPACE_SPEC.slots.every((s) => s.school_year === null && s.student_group_id === "all")).toBe(true);
    expect(DEFAULT_WORKSPACE_SPEC.subgroup_slots).toEqual([null, null, null]);
    expect(DEFAULT_WORKSPACE_SPEC.plan_spotlight).toBeNull();
  });
});

describe("defaultSpecForLevel — level-aware, server-preferred", () => {
  it("HS leads with grad/college; ES/MS lead with CAASPP outcomes", () => {
    expect(defaultSpecForLevel("High").slots.map((s) => s.metric_id)).toEqual([
      "chronic_absenteeism_rate", "grad_rate_acgr", "college_going_rate",
    ]);
    const ms = defaultSpecForLevel("Middle").slots.map((s) => s.metric_id);
    expect(ms).toEqual(["chronic_absenteeism_rate", "ela_met_standard_pct", "math_met_standard_pct"]);
    // grad/college are HS-only — they must NOT be in the ES/MS default (that was the bug).
    expect(ms).not.toContain("grad_rate_acgr");
    expect(defaultSpecForLevel("Primary").slots.map((s) => s.metric_id)).toEqual(ms);
  });

  it("prefers the server-provided defaults when present", () => {
    const server: Record<string, WorkspaceSpec> = {
      Middle: { slots: [
        { metric_id: "suspension_rate", school_year: null, student_group_id: "all" },
        { metric_id: "stability_rate", school_year: null, student_group_id: "all" },
        { metric_id: "chronic_absenteeism_rate", school_year: null, student_group_id: "all" },
      ], subgroup_slots: [null, null, null], plan_spotlight: null },
    };
    expect(defaultSpecForLevel("Middle", server).slots[0].metric_id).toBe("suspension_rate");
    // A level the server didn't send still falls back to the client map.
    expect(defaultSpecForLevel("High", server).slots[1].metric_id).toBe("grad_rate_acgr");
  });

  it("returns an independent deep copy (a session must own its spec)", () => {
    const a = defaultSpecForLevel("High");
    a.slots[0].metric_id = "mutated";
    expect(defaultSpecForLevel("High").slots[0].metric_id).toBe("chronic_absenteeism_rate");
  });
});
