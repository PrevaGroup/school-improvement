import { describe, expect, it } from "vitest";

import { DEFAULT_WORKSPACE_SPEC, applyChatWorkspace } from "./workspace";
import type { ChatWorkspace, SlotPayload, WorkspaceData } from "./types";

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
    subgroup_slice: null,
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

  it("fills the subgroup slice without touching the indicator slots", () => {
    const next = applyChatWorkspace(data(), turn({ payloads: { subgroup_slice: slot("EL") } }))!;
    expect(next.subgroup_slice?.display_name).toBe("EL");
    expect(next.slots.map((s) => s.display_name)).toEqual(["A", "B", "C"]);
  });

  it("adopts the turn's spec so the next request describes the true screen", () => {
    const spec = {
      ...DEFAULT_WORKSPACE_SPEC,
      subgroup_slice: { metric_id: "suspension_rate", school_year: null, student_group_id: "el" },
    };
    const next = applyChatWorkspace(data(), turn({ spec, payloads: { subgroup_slice: slot("EL") } }))!;
    expect(next.spec.subgroup_slice?.student_group_id).toBe("el");
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

describe("DEFAULT_WORKSPACE_SPEC mirrors the backend default", () => {
  it("is the old fixed three-indicator panel, latest year, all students", () => {
    expect(DEFAULT_WORKSPACE_SPEC.slots.map((s) => s.metric_id)).toEqual([
      "chronic_absenteeism_rate", "grad_rate_acgr", "college_going_rate",
    ]);
    expect(DEFAULT_WORKSPACE_SPEC.slots.every((s) => s.school_year === null && s.student_group_id === "all")).toBe(true);
    expect(DEFAULT_WORKSPACE_SPEC.subgroup_slice).toBeNull();
    expect(DEFAULT_WORKSPACE_SPEC.plan_spotlight).toBeNull();
  });
});
