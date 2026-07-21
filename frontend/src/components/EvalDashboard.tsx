import { useEffect, useState } from "react";
import { api } from "../api";
import { fmtNum, fmtCostUSD } from "../format";
import type { EvalSummary, EvalTraceRow } from "../types";

// Read-only admin view over the eval trace store (GET /api/evals/*). Shows what real use
// looks like — recent turns, their cost/latency/status — the "capture" stage of the eval
// loop made visible. No writes, no identity (the store is pseudonymous, server-side).

function statusClass(s: string | null): string {
  if (s === "ok") return "ev-ok";
  if (s === "error") return "ev-err";
  if (s === "refusal" || s === "max_iters") return "ev-warn";
  return "ev-mut";
}

function ago(iso: string | null): string {
  if (!iso) return "—";
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.round(s / 60)}m`;
  if (s < 86400) return `${Math.round(s / 3600)}h`;
  return `${Math.round(s / 86400)}d`;
}

export function EvalDashboard({ onBack }: { onBack: () => void }) {
  const [summary, setSummary] = useState<EvalSummary | null>(null);
  const [traces, setTraces] = useState<EvalTraceRow[] | null>(null);
  const [err, setErr] = useState(false);

  useEffect(() => {
    api.get<EvalSummary>("/evals/summary").then(setSummary).catch(() => setErr(true));
    api.get<{ traces: EvalTraceRow[] }>("/evals/traces?limit=50")
      .then((d) => setTraces(d.traces || []))
      .catch(() => setErr(true));
  }, []);

  const empty = summary?.available === false || (summary?.available && summary.traces === 0);

  return (
    <div className="ev-wrap">
      <div className="ev-head">
        <button className="ev-back" onClick={onBack}>← Workspace</button>
        <h2 className="ev-title">Evaluation · traces</h2>
        <span className="ev-sub">
          the “capture” stage of the loop — every real turn, traced end-to-end
        </span>
      </div>

      {err ? (
        <div className="card muted">Couldn’t load the trace store.</div>
      ) : summary === null ? (
        <div className="card muted dots">loading</div>
      ) : empty ? (
        <div className="card ev-emptycard">
          <h3>No traces ingested yet</h3>
          <p className="muted">
            Chat turns are emitted to Google Cloud Storage as they happen, but the queryable
            store is populated by a batch job. Once it runs, recent turns and their cost, latency,
            and status appear here.
          </p>
          <p className="muted mono ev-cmd">cd backend &amp;&amp; python -m evals.ingest_traces</p>
        </div>
      ) : (
        <>
          <div className="ev-tiles">
            <Tile label="traces" value={fmtNum(summary.traces ?? 0)} sub={`last ${summary.window}`} />
            <Tile label="ok rate" value={summary.ok_rate == null ? "—" : summary.ok_rate + "%"} />
            <Tile label="cost (est.)" value={fmtCostUSD(summary.cost_usd ?? 0)} />
            <Tile label="p50 latency" value={summary.latency_p50_ms == null ? "—" : (summary.latency_p50_ms / 1000).toFixed(1) + "s"}
                  sub={summary.latency_max_ms ? "max " + (summary.latency_max_ms / 1000).toFixed(1) + "s" : undefined} />
            <Tile label="tokens" value={fmtNum(summary.tokens ?? 0)} />
          </div>

          <div className="ev-breakdowns">
            <Breakdown title="status" counts={summary.by_status} statusColor />
            <Breakdown title="source" counts={summary.by_source} />
            <Breakdown title="model" counts={summary.by_model} />
          </div>

          <div className="card">
            <h3 className="h3-row"><span>Recent turns</span></h3>
            <div className="tbl-wrap" style={{ maxHeight: "unset" }}>
              <table className="tbl ev-tbl">
                <thead>
                  <tr>
                    <th>When</th><th>Question</th><th>Status</th><th>Model</th>
                    <th className="r">Latency</th><th className="r">Cost</th><th className="r">Iters</th><th>Build</th>
                  </tr>
                </thead>
                <tbody>
                  {(traces ?? []).map((t) => (
                    <tr key={t.trace_id}>
                      <td className="mono ev-when">{ago(t.ts)}</td>
                      <td className="ev-q">{t.question || <span className="muted">—</span>}</td>
                      <td><span className={"ev-pill " + statusClass(t.status)}>{t.status || "—"}</span></td>
                      <td className="mono d">{t.model || "—"}</td>
                      <td className="r mono">{t.latency_ms == null ? "—" : (t.latency_ms / 1000).toFixed(1) + "s"}</td>
                      <td className="r mono">{t.cost_usd_est == null ? "—" : fmtCostUSD(t.cost_usd_est)}</td>
                      <td className="r mono">{t.iterations ?? "—"}</td>
                      <td className="mono d">{t.git_sha ? t.git_sha.slice(0, 7) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="muted ev-foot">
              Pseudonymous — no identity is stored or shown. This is the raw capture; mined eval
              cases and scored runs are the next stages of the loop.
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="ev-tile">
      <div className="ev-tl">{label}</div>
      <div className="ev-tv">{value}</div>
      {sub ? <div className="ev-ts">{sub}</div> : null}
    </div>
  );
}

function Breakdown({ title, counts, statusColor }: { title: string; counts?: Record<string, number>; statusColor?: boolean }) {
  const entries = Object.entries(counts || {}).sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((s, [, n]) => s + n, 0) || 1;
  return (
    <div className="card ev-bd">
      <div className="ev-bdl">{title}</div>
      {entries.length === 0 ? <div className="muted" style={{ fontSize: "12px" }}>—</div> : entries.map(([k, n]) => (
        <div className="ev-bdrow" key={k}>
          <span className={"ev-bdk" + (statusColor ? " " + statusClass(k) : "")}>{k}</span>
          <span className="ev-bdbar"><i style={{ width: (100 * n / total).toFixed(1) + "%" }} /></span>
          <span className="ev-bdn mono">{n}</span>
        </div>
      ))}
    </div>
  );
}
