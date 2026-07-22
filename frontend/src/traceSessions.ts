import type { EvalTraceRow } from "./types";

// Group the recent-traces feed by session for the admin rail's "traces by session" list.
// Traces are pseudonymous and server-side; a session is one conversation (a client-generated
// session_id, or "eval-<case>" for eval runs). Grouping is client-side over the fetched feed —
// no dedicated endpoint — which is plenty at current volume.

export const NO_SESSION = "(no session)";

export interface TraceSessionGroup {
  session: string; // the session_id, or NO_SESSION for null-session turns
  label: string; // the most-recent non-empty question in the session
  count: number; // turns in the session
  latestTs: string | null; // newest turn's ts (ISO) — the sort key
}

// Rows arrive newest-first (the endpoint orders by ts desc), but we don't rely on that: we take
// the max ts per group and sort groups by it, so a session's label is its latest question.
export function groupBySession(traces: EvalTraceRow[]): TraceSessionGroup[] {
  const groups = new Map<string, TraceSessionGroup>();
  for (const t of traces) {
    const key = t.session_id || NO_SESSION;
    const g = groups.get(key);
    const ts = t.ts;
    const q = (t.question || "").trim();
    if (!g) {
      groups.set(key, { session: key, label: q, count: 1, latestTs: ts });
    } else {
      g.count += 1;
      // Adopt this turn's question/ts as the label when it's newer than what we have.
      if (ts && (!g.latestTs || ts > g.latestTs)) {
        g.latestTs = ts;
        if (q) g.label = q;
      } else if (!g.label && q) {
        g.label = q;
      }
    }
  }
  return [...groups.values()].sort((a, b) => (b.latestTs || "").localeCompare(a.latestTs || ""));
}
