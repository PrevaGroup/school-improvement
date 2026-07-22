import { describe, expect, it } from "vitest";

import { NO_SESSION, groupBySession } from "./traceSessions";
import type { EvalTraceRow } from "./types";

function row(over: Partial<EvalTraceRow>): EvalTraceRow {
  return {
    trace_id: "t", session_id: null, ts: null, question: null, status: "ok",
    latency_ms: null, model: null, cost_usd_est: null, iterations: null, git_sha: null,
    ...over,
  };
}

describe("groupBySession", () => {
  it("buckets by session_id and counts turns", () => {
    const g = groupBySession([
      row({ session_id: "s1", ts: "2026-07-22T10:00:00Z", question: "q1" }),
      row({ session_id: "s1", ts: "2026-07-22T10:05:00Z", question: "q2" }),
      row({ session_id: "s2", ts: "2026-07-22T09:00:00Z", question: "q3" }),
    ]);
    expect(g.map((x) => x.session)).toEqual(["s1", "s2"]); // s1 newer → first
    expect(g[0].count).toBe(2);
    expect(g[1].count).toBe(1);
  });

  it("labels a session with its most recent question, regardless of input order", () => {
    const g = groupBySession([
      row({ session_id: "s1", ts: "2026-07-22T10:00:00Z", question: "older" }),
      row({ session_id: "s1", ts: "2026-07-22T12:00:00Z", question: "newest" }),
      row({ session_id: "s1", ts: "2026-07-22T11:00:00Z", question: "middle" }),
    ]);
    expect(g[0].label).toBe("newest");
    expect(g[0].latestTs).toBe("2026-07-22T12:00:00Z");
  });

  it("puts null-session turns in one NO_SESSION bucket", () => {
    const g = groupBySession([
      row({ session_id: null, ts: "2026-07-22T10:00:00Z", question: "a" }),
      row({ session_id: null, ts: "2026-07-22T11:00:00Z", question: "b" }),
    ]);
    expect(g).toHaveLength(1);
    expect(g[0].session).toBe(NO_SESSION);
    expect(g[0].count).toBe(2);
  });

  it("sorts sessions newest-first by latest ts", () => {
    const g = groupBySession([
      row({ session_id: "old", ts: "2026-07-20T10:00:00Z", question: "x" }),
      row({ session_id: "new", ts: "2026-07-22T10:00:00Z", question: "y" }),
    ]);
    expect(g.map((x) => x.session)).toEqual(["new", "old"]);
  });

  it("is empty for no traces", () => {
    expect(groupBySession([])).toEqual([]);
  });
});
