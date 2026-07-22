// Formatting helpers, ported verbatim from the no-build UI.
//
// Every one of these renders null as an em dash, never as 0 or "". That is deliberate: a
// missing metric is UNKNOWN (often privacy-suppressed for small enrollment), and showing it as
// zero would be a false claim about a real school. Keep the null branch.

export const fmtUSD = (n: number | null | undefined) =>
  n == null ? "—" : "$" + Math.round(n).toLocaleString();

// Absolute date+time for trace/session labels, e.g. "Jul 22, 1:10 PM". Locale-aware; null → em dash.
export const fmtDateTime = (iso: string | null | undefined) =>
  iso == null ? "—" : new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  });

// Small-money variant for AI-usage costs, which are fractions of a dollar per turn. fmtUSD
// rounds to whole dollars (right for school budgets, its origin), which collapses a real
// $0.02 turn cost to "$0". Show 2–4 decimals so a sub-dollar cost reads honestly.
export const fmtCostUSD = (n: number | null | undefined) =>
  n == null ? "—"
    : "$" + n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 });
export const fmtPct = (n: number | null | undefined) => (n == null ? "—" : Math.round(n) + "%");
export const fmtNum = (n: number | null | undefined) => (n == null ? "—" : Number(n).toLocaleString());
export const fmt1 = (n: number | null | undefined) => (n == null ? "—" : Number(n).toFixed(1));

// The extractor often copies plan text near-verbatim into strategy_text, so the provenance
// quote then renders as the same sentence twice. Show the quote only when it adds something
// (e.g. the action is a real summary and the quote is the actual source wording).
const norm = (t: string | null | undefined) =>
  (t || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();

export function nearDup(a: string | null | undefined, b: string | null | undefined): boolean {
  const x = norm(a);
  const y = norm(b);
  if (!x || !y) return false;
  return y.startsWith(x.slice(0, 60)) || x.startsWith(y.slice(0, 60));
}
