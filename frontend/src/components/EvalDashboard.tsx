import { useEffect, useState } from "react";
import { api } from "../api";
import { fmtNum, fmtCostUSD } from "../format";
import type {
  EvalSummary, EvalTraceRow, EvalCaseRow, EvalRunRow, EvalResultRow,
} from "../types";

// Read-only admin view over the eval loop (GET /api/evals/*). Three tabs = the three stages of
// the loop: capture (traces) → cases mined/curated from them → scored runs of those cases.
// No writes, no identity (the store is pseudonymous, server-side).

type Tab = "traces" | "cases" | "results";

function statusClass(s: string | null): string {
  if (s === "ok" || s === "pass" || s === "active") return "ev-ok";
  if (s === "error" || s === "fail") return "ev-err";
  if (s === "refusal" || s === "max_iters" || s === "candidate") return "ev-warn";
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
  const [tab, setTab] = useState<Tab>("traces");
  return (
    <div className="ev-wrap">
      <div className="ev-head">
        <button className="ev-back" onClick={onBack}>← Workspace</button>
        <h2 className="ev-title">Evaluation</h2>
        <div className="seg" role="tablist">
          <button className={tab === "traces" ? "on" : ""} onClick={() => setTab("traces")}>
            Recent traces
          </button>
          <button className={tab === "cases" ? "on" : ""} onClick={() => setTab("cases")}>
            Evals
          </button>
          <button className={tab === "results" ? "on" : ""} onClick={() => setTab("results")}>
            Results
          </button>
        </div>
      </div>
      {tab === "traces" ? <TracesTab /> : tab === "cases" ? <CasesTab /> : <ResultsTab />}
    </div>
  );
}

// --- shared bits ---------------------------------------------------------------------------- //

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="ev-tile">
      <div className="ev-tl">{label}</div>
      <div className="ev-tv">{value}</div>
      {sub ? <div className="ev-ts">{sub}</div> : null}
    </div>
  );
}

function Breakdown({ title, counts, statusColor }:
  { title: string; counts?: Record<string, number>; statusColor?: boolean }) {
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

function Loading() { return <div className="card muted dots">loading</div>; }
function LoadError() { return <div className="card muted">Couldn’t load this view.</div>; }

// --- traces tab (the capture stage) --------------------------------------------------------- //

function TracesTab() {
  const [summary, setSummary] = useState<EvalSummary | null>(null);
  const [traces, setTraces] = useState<EvalTraceRow[] | null>(null);
  const [err, setErr] = useState(false);

  useEffect(() => {
    api.get<EvalSummary>("/evals/summary").then(setSummary).catch(() => setErr(true));
    api.get<{ traces: EvalTraceRow[] }>("/evals/traces?limit=50")
      .then((d) => setTraces(d.traces || [])).catch(() => setErr(true));
  }, []);

  const empty = summary?.available === false || (summary?.available && summary.traces === 0);
  if (err) return <LoadError />;
  if (summary === null) return <Loading />;
  if (empty) {
    return (
      <div className="card ev-emptycard">
        <h3>No traces ingested yet</h3>
        <p className="muted">
          Chat turns are emitted to Google Cloud Storage as they happen, but the queryable store is
          populated by a batch job. Once it runs, recent turns and their cost, latency, and status
          appear here.
        </p>
        <p className="muted mono ev-cmd">cd backend &amp;&amp; python -m evals.ingest_traces</p>
      </div>
    );
  }
  return (
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
        <h3 className="h3-row"><span>Recent traces</span></h3>
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
          Real use only (source=prod). Pseudonymous — no identity is stored or shown.
        </div>
      </div>
    </>
  );
}

// --- evals tab (the curated + mined cases) -------------------------------------------------- //

function CasesTab() {
  const [data, setData] = useState<{ cases: EvalCaseRow[]; by_status?: Record<string, number>; available: boolean } | null>(null);
  const [err, setErr] = useState(false);

  useEffect(() => {
    api.get<{ cases: EvalCaseRow[]; by_status?: Record<string, number>; available: boolean }>("/evals/cases")
      .then(setData).catch(() => setErr(true));
  }, []);

  if (err) return <LoadError />;
  if (data === null) return <Loading />;
  if (data.available === false || data.cases.length === 0) {
    return (
      <div className="card ev-emptycard">
        <h3>No eval cases yet</h3>
        <p className="muted">
          Cases are the questions the assistant must keep getting right. Load the curated seed set,
          then mine more from real failures. Once loaded they appear here.
        </p>
        <p className="muted mono ev-cmd">cd backend &amp;&amp; python -m evals.load_seed_cases</p>
      </div>
    );
  }
  return (
    <>
      <div className="ev-breakdowns">
        <Breakdown title="cases by status" counts={data.by_status} statusColor />
      </div>
      <div className="card">
        <h3 className="h3-row"><span>Eval cases</span></h3>
        <div className="tbl-wrap" style={{ maxHeight: "unset" }}>
          <table className="tbl ev-tbl">
            <thead>
              <tr><th>Question</th><th>Level</th><th>Status</th><th>Source</th><th>Graders</th><th>Tags</th></tr>
            </thead>
            <tbody>
              {data.cases.map((c) => (
                <tr key={c.eval_case_id}>
                  <td className="ev-q">{c.question || <span className="muted">—</span>}</td>
                  <td className="mono d">{c.level || "—"}</td>
                  <td><span className={"ev-pill " + statusClass(c.status)}>{c.status || "—"}</span></td>
                  <td className="mono d">{c.source?.startsWith("mined") ? "mined" : c.source || "—"}</td>
                  <td className="mono d">{c.graders.length ? c.graders.join(", ") : "—"}</td>
                  <td className="mono d">{c.tags.length ? c.tags.join(" ") : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="muted ev-foot">
          Mined cases land as <span className="mono">candidate</span> — a human reviews and promotes
          to <span className="mono">active</span> before they gate anything.
        </div>
      </div>
    </>
  );
}

// --- results tab (the scored runs) ---------------------------------------------------------- //

function ResultsTab() {
  const [runs, setRuns] = useState<EvalRunRow[] | null>(null);
  const [err, setErr] = useState(false);
  const [sel, setSel] = useState<string | null>(null);
  const [results, setResults] = useState<EvalResultRow[] | null>(null);

  useEffect(() => {
    api.get<{ runs: EvalRunRow[]; available: boolean }>("/evals/runs")
      .then((d) => setRuns(d.runs || [])).catch(() => setErr(true));
  }, []);

  useEffect(() => {
    if (!sel) { setResults(null); return; }
    setResults(null);
    api.get<{ results: EvalResultRow[] }>(`/evals/runs/${encodeURIComponent(sel)}/results`)
      .then((d) => setResults(d.results || [])).catch(() => setResults([]));
  }, [sel]);

  if (err) return <LoadError />;
  if (runs === null) return <Loading />;
  if (runs.length === 0) {
    return (
      <div className="card ev-emptycard">
        <h3>No eval runs yet</h3>
        <p className="muted">
          A run executes the active case set against the live agent and scores each answer. Run one,
          and its pass rate, cost, and per-case results appear here.
        </p>
        <p className="muted mono ev-cmd">
          cd backend &amp;&amp; python -m evals.run_evals --set golden --target-url &lt;url&gt;
        </p>
      </div>
    );
  }
  const pct = (r: number | null) => (r == null ? "—" : (r * 100).toFixed(0) + "%");
  return (
    <>
      <div className="card">
        <h3 className="h3-row"><span>Eval runs</span></h3>
        <div className="tbl-wrap" style={{ maxHeight: "unset" }}>
          <table className="tbl ev-tbl">
            <thead>
              <tr>
                <th>When</th><th>Set</th><th>Target</th><th>Model</th>
                <th className="r">Pass rate</th><th className="r">Cases</th><th className="r">Cost</th><th></th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.eval_run_id} className={sel === r.eval_run_id ? "sel" : ""}
                    style={{ cursor: "pointer" }}
                    onClick={() => setSel(sel === r.eval_run_id ? null : r.eval_run_id)}>
                  <td className="mono ev-when">{ago(r.ts)}</td>
                  <td className="mono d">{r.set_name || "—"}</td>
                  <td className="mono d">{r.target || "—"}</td>
                  <td className="mono d">{r.model || "—"}</td>
                  <td className="r mono">{pct(r.pass_rate)}</td>
                  <td className="r mono">{r.passed ?? 0}/{r.n ?? 0}</td>
                  <td className="r mono">{fmtCostUSD(r.cost_usd ?? 0)}</td>
                  <td className="mono d">{sel === r.eval_run_id ? "▾" : "▸"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {sel ? (
        <div className="card">
          <h3 className="h3-row"><span>Results · failures first</span></h3>
          {results === null ? <Loading /> : (
            <div className="tbl-wrap" style={{ maxHeight: "unset" }}>
              <table className="tbl ev-tbl">
                <thead>
                  <tr><th>Verdict</th><th>Question</th><th>Failed graders</th><th>Judge</th></tr>
                </thead>
                <tbody>
                  {results.map((r) => {
                    const failed = Object.values(r.scores || {})
                      .filter((s) => s.verdict === "fail").map((s) => s.name).filter(Boolean);
                    return (
                      <tr key={r.eval_case_id}>
                        <td><span className={"ev-pill " + statusClass(r.verdict)}>{r.verdict || "—"}</span></td>
                        <td className="ev-q">{r.question || <span className="muted">—</span>}</td>
                        <td className="mono d">{failed.length ? failed.join(", ") : "—"}</td>
                        <td className="ev-q muted">{r.judge_rationale || "—"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ) : null}
    </>
  );
}
