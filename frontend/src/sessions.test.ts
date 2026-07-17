import { describe, expect, it } from "vitest";

import {
  MAX_SESSIONS,
  byRecency,
  createSession,
  forkSession,
  isEmptySession,
  latestForSchool,
  reconcileSchoolChange,
  titleFor,
  upsert,
} from "./sessions";
import type { Session, SessionMeta } from "./sessions";

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

describe("reconcileSchoolChange — no orphans, no confusion", () => {
  const B: SessionMeta = { school_id: "S2", school_name: "Jordan High", district_id: "0622500", level: "High" };

  it("repoints an EMPTY active session in place instead of spawning a second one", () => {
    // The reported bug: new (empty) session, change school -> should reuse, not create.
    const empty = sess({ id: "a", school_id: "S1", school_name: "Wilson High" });
    const r = reconcileSchoolChange([empty], "a", B);
    expect(r.sessions).toHaveLength(1); // NOT two
    expect(r.activeId).toBe("a"); // same session, repointed
    expect(r.sessions[0].school_id).toBe("S2");
    expect(r.sessions[0].school_name).toBe("Jordan High");
    expect(r.sessions[0].workspace.slots[0].metric_id).toBe("chronic_absenteeism_rate"); // reset
  });

  it("keeps a session that has a real conversation, creating a fresh one for the new school", () => {
    const chatted = sess({ id: "a", school_id: "S1", messages: [{ role: "user", content: "hi" }] });
    const r = reconcileSchoolChange([chatted], "a", B);
    expect(r.sessions).toHaveLength(2); // the conversation is preserved
    expect(r.sessions.some((s) => s.id === "a")).toBe(true);
    expect(r.activeId).not.toBe("a");
    expect(r.sessions.find((s) => s.id === r.activeId)!.school_id).toBe("S2");
  });

  it("adopts an existing session for the target school and discards the empty scratch left behind", () => {
    const empty = sess({ id: "a", school_id: "S1", updated_at: 5 });
    const existingB = sess({ id: "b", school_id: "S2", school_name: "Jordan High", updated_at: 1,
      messages: [{ role: "user", content: "old q" }] });
    const r = reconcileSchoolChange([empty, existingB], "a", B);
    expect(r.activeId).toBe("b"); // adopt the real B session
    expect(r.sessions.some((s) => s.id === "a")).toBe(false); // empty scratch dropped
    expect(r.sessions).toHaveLength(1);
  });

  it("does NOT discard a non-empty session when adopting an existing target", () => {
    const chatted = sess({ id: "a", school_id: "S1", messages: [{ role: "user", content: "keep me" }] });
    const existingB = sess({ id: "b", school_id: "S2", messages: [{ role: "user", content: "b" }] });
    const r = reconcileSchoolChange([chatted, existingB], "a", B);
    expect(r.activeId).toBe("b");
    expect(r.sessions.some((s) => s.id === "a")).toBe(true); // conversation preserved
  });

  it("is a no-op when the active session is already on the target school", () => {
    const onB = sess({ id: "a", school_id: "S2" });
    const r = reconcileSchoolChange([onB], "a", B);
    expect(r.sessions).toHaveLength(1);
    expect(r.activeId).toBe("a");
  });

  it("a fork (chat set_school) copies the transcript forward into a new session", () => {
    const src = sess({ id: "a", school_id: "S1", messages: [{ role: "user", content: "look at Jordan" }] });
    const r = reconcileSchoolChange([src], "a", B, src);
    expect(r.activeId).not.toBe("a");
    const forked = r.sessions.find((s) => s.id === r.activeId)!;
    expect(forked.school_id).toBe("S2");
    expect(forked.messages).toEqual(src.messages); // continuous conversation
    expect(r.sessions.some((s) => s.id === "a")).toBe(true); // source stays
  });
});

describe("isEmptySession", () => {
  it("is empty with no messages, non-empty once a turn lands", () => {
    expect(isEmptySession(sess({}))).toBe(true);
    expect(isEmptySession(sess({ messages: [{ role: "user", content: "x" }] }))).toBe(false);
  });
});
