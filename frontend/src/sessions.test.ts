import { describe, expect, it } from "vitest";

import {
  MAX_SESSIONS,
  byRecency,
  createSession,
  forkSession,
  latestForSchool,
  titleFor,
  upsert,
} from "./sessions";
import type { Session } from "./sessions";

const SCHOOL = { school_id: "S1", school_name: "Wilson High", district_id: "0622500", level: "High" as const };

function sess(overrides: Partial<Session>): Session {
  return { ...createSession(SCHOOL), ...overrides };
}

describe("session creation and forking", () => {
  it("a new session opens on the default workspace with an empty transcript", () => {
    const s = createSession(SCHOOL);
    expect(s.workspace.slots.map((x) => x.metric_id)).toEqual([
      "chronic_absenteeism_rate", "grad_rate_acgr", "college_going_rate",
    ]);
    expect(s.workspace.subgroup_slice).toBeNull();
    expect(s.messages).toEqual([]);
    expect(s.school_id).toBe("S1");
  });

  it("each session owns its spec — mutating one never leaks into another", () => {
    const a = createSession(SCHOOL);
    const b = createSession(SCHOOL);
    a.workspace.slots[0].metric_id = "suspension_rate";
    expect(b.workspace.slots[0].metric_id).toBe("chronic_absenteeism_rate");
  });

  it("forking copies the transcript forward but resets the workspace", () => {
    const from = sess({ messages: [{ role: "user", content: "why is attendance low?" }] });
    from.workspace.subgroup_slice = { metric_id: "suspension_rate", school_year: null, student_group_id: "el" };
    const fork = forkSession(from, { ...SCHOOL, school_id: "S2", school_name: "Jordan High" });
    expect(fork.messages).toEqual(from.messages); // one continuous conversation...
    expect(fork.messages).not.toBe(from.messages); // ...but an independent copy
    expect(fork.workspace.subgroup_slice).toBeNull(); // fresh lens on the new school
    expect(fork.school_id).toBe("S2");
  });
});

describe("titles and lookup", () => {
  it("titles from the first user question, truncated", () => {
    const s = sess({
      messages: [
        { role: "user", content: "x".repeat(80) },
        { role: "assistant", content: "..." },
      ],
    });
    const t = titleFor(s);
    expect(t.startsWith("Wilson High — ")).toBe(true);
    expect(t.endsWith("…")).toBe(true);
  });

  it("falls back to the school name before any question is asked", () => {
    expect(titleFor(sess({}))).toBe("Wilson High");
  });

  it("latestForSchool picks the most recently touched session for that school only", () => {
    const old = sess({ id: "a", updated_at: 1 });
    const newer = sess({ id: "b", updated_at: 2 });
    const other = sess({ id: "c", school_id: "S2", updated_at: 3 });
    expect(latestForSchool([old, newer, other], "S1")?.id).toBe("b");
    expect(latestForSchool([old, newer, other], "S9")).toBeNull();
  });
});

describe("upsert — bounded, active-safe", () => {
  it("replaces by id and sorts by recency", () => {
    const a = sess({ id: "a", updated_at: 1 });
    const b = sess({ id: "b", updated_at: 2 });
    const a2 = { ...a, updated_at: 3 };
    expect(upsert([a, b], a2, null).map((s) => s.id)).toEqual(["a", "b"]);
  });

  it("prunes past the cap by recency", () => {
    const many = Array.from({ length: MAX_SESSIONS }, (_, i) => sess({ id: `s${i}`, updated_at: i + 10 }));
    const next = upsert(many, sess({ id: "new", updated_at: 999 }), null);
    expect(next.length).toBe(MAX_SESSIONS);
    expect(next[0].id).toBe("new");
    expect(next.some((s) => s.id === "s0")).toBe(false); // the oldest fell off
  });

  it("never prunes the active session", () => {
    const many = Array.from({ length: MAX_SESSIONS }, (_, i) => sess({ id: `s${i}`, updated_at: i + 10 }));
    const active = sess({ id: "active", updated_at: 1 }); // oldest of all
    const next = upsert([...many.slice(0, MAX_SESSIONS - 1), active], sess({ id: "new", updated_at: 999 }), "active");
    expect(next.some((s) => s.id === "active")).toBe(true);
  });

  it("byRecency does not mutate its input", () => {
    const a = sess({ id: "a", updated_at: 1 });
    const b = sess({ id: "b", updated_at: 2 });
    const arr = [a, b];
    byRecency(arr);
    expect(arr[0].id).toBe("a");
  });
});
