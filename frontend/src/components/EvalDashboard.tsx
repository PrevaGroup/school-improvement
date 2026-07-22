import { useEffect, useState } from "react";
import { api } from "../api";
import { fmtNum, fmtCostUSD, fmtDateTime } from "../format";
import { NO_SESSION } from "../traceSessions";
import type {
  EvalSummary, EvalTraceRow, EvalCaseRow, EvalRunRow, EvalResultRow, EvalTraceDetail, EvalTraceEvent,
} from "../types";

// The admin eval views, rendered in the main panel. The left rail (App.tsx) is the navigator —
// it picks which panel shows via `Main`; there is no internal tab strip or back button here.
// Every stage of the loop is read-only and pseudonymous (no identity stored or shown).

export type Main =
  | { kind: "workspace" }
  | { kind: "traces"; session?: string }   // session undefined = the traces overview
  | { kind: "cases" }
  | { kind: "results"; runId?: string };    // runId undefined = the runs overview

export function EvalPanel({ main, traces, runs, onSelect }: {
  main: Main;
  traces: EvalTraceRow[];
  runs: EvalRunRow[];
  onSelect: (m: Main) => void;
}) {
  return (
    <div className="ev-wrap">
      {main.kind === "traces" && main.session === undefined ? <TracesOverview traces={traces} /> : null}
      {main.kind === "traces" && main.session !== undefined ? <TracesForSession session={main.session} traces={traces} /> : null}
      {main.kind === "cases" ? <CasesPanel /> : null}
      {main.kind === "results" ? <ResultsPanel runId={main.runId} runs={runs} onSelect={onSelect} /> : null}
    </div>
  );
}

// --- shared bits ---------------------------------------------------------------------------- //

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

// The set a run executed. "golden" is the design's name for the fast PR-gating subset; we show
// it as "PR Gate" (clearer), and map legacy golden runs to the same label.
export function setLabel(s: string | null | undefined): string {
  return s === "golden" || s === "pr-gate" ? "PR Gate" : (s || "run");
}

function PanelHead({ title, sub }: { title: string; sub?: string }) {
  return (
    <div className="ev-phead">
      <h2 className="ev-title">{title}</h2>
      {sub ? <span className="ev-sub">{sub}</span> : null}
    </div>
  );
}

function Loading() { return <div className="card muted dots">loading</div>; }
function LoadError() { return <div className="card muted">Couldn’t load this view.</div>; }

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

function TracesTable({ rows, selected, onSelect }: {
  rows: EvalTraceRow[]; selected?: string | null; onSelect?: (id: string) => void;
}) {
  return (
    <div className="tbl-wrap" style={{ maxHeight: "unset" }}>
      <table className="tbl ev-tbl">
        <thead>
          <tr>
            <th>When</th><th>Question</th><th>Status</th><th>Model</th>
            <th className="r">Latency</th><th className="r">Cost</th><th className="r">Iters</th><th>Build</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((t) => (
            <tr key={t.trace_id}
                className={selected === t.trace_id ? "sel" : ""}
                style={onSelect ? { cursor: "pointer" } : undefined}
                onClick={onSelect ? () => onSelect(t.trace_id) : undefined}>
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
  );
}

// One turn, expanded: the question, each tool call with its full output, and the final answer —
// fetched from the GCS object via GET /evals/traces/{id}. Degrades to the header if it aged out.
function TraceDetail({ traceId }: { traceId: string }) {
  const [d, setD] = useState<EvalTraceDetail | null>(null);
  const [err, setErr] = useState(false);

  useEffect(() => {
    setD(null); setErr(false);
    api.get<{ trace?: EvalTraceDetail; available: boolean }>(`/evals/traces/${encodeURIComponent(traceId)}`)
      .then((r) => (r.available && r.trace ? setD(r.trace) : setErr(true)))
      .catch(() => setErr(true));
  }, [traceId]);

  if (err) return <div className="card muted">Couldn’t load this trace — the raw object may have aged out of the 90-day window.</div>;
  if (!d) return <Loading />;
  const tot = d.totals || {};
  return (
    <div className="card ev-detail">
      <div className="ev-detail-meta mono">
        {d.model || "—"} · <span className={"ev-pill " + statusClass(d.status)}>{d.status || "—"}</span>
        {" · "}{d.level || "—"} · in {fmtNum(tot.input_tokens ?? 0)} / out {fmtNum(tot.output_tokens ?? 0)}
        {" · "}{fmtCostUSD(tot.cost_usd_est ?? 0)}
        {d.versions?.git_sha ? " · git " + d.versions.git_sha.slice(0, 7) : ""}
      </div>
      {d.events.length === 0
        ? <div className="muted">No event detail — the raw trace object is unavailable.</div>
        : d.events.map((e, i) => <EventRow key={i} e={e} />)}
    </div>
  );
}

function EventRow({ e }: { e: EvalTraceEvent }) {
  if (e.type === "turn_start") {
    return <div className="ev-ev ev-ev-q"><span className="ev-ev-lab">Q</span><span className="ev-ev-body">{e.question}</span></div>;
  }
  if (e.type === "model_call") {
    return (
      <div className="ev-ev ev-ev-model mono">
        model call #{e.iteration} → {e.stop} · {e.usage?.output_tokens ?? 0} out · {e.latency_ms ?? "—"}ms
      </div>
    );
  }
  if (e.type === "tool_call") {
    return (
      <div className="ev-ev ev-ev-tool">
        <div className="ev-ev-th mono">
          <span className="ev-ev-lab">↳</span>
          <b>{e.name}</b>({JSON.stringify(e.input)})
          {e.error ? <span className="ev-pill ev-err" style={{ marginLeft: 6 }}>error</span> : null}
        </div>
        <pre className="ev-ev-out">{JSON.stringify(e.output, null, 2)}</pre>
      </div>
    );
  }
  if (e.type === "turn_end") {
    return <div className="ev-ev ev-ev-a"><span className="ev-ev-lab">A</span><span className="ev-ev-body">{e.reply}</span></div>;
  }
  return null;
}

// --- traces overview (the capture stage) ---------------------------------------------------- //

function TracesOverview({ traces }: { traces: EvalTraceRow[] }) {
  const [summary, setSummary] = useState<EvalSummary | null>(null);
  const [err, setErr] = useState(false);
  const [sel, setSel] = useState<string | null>(null);

  useEffect(() => {
    api.get<EvalSummary>("/evals/summary").then(setSummary).catch(() => setErr(true));
  }, []);

  if (err) return <LoadError />;
  if (summary === null) return <Loading />;
  const empty = summary.available === false || (summary.available && (summary.traces ?? 0) === 0);
  return (
    <>
      <PanelHead title="Traces" sub="every real turn, traced end-to-end (prod)" />
      {empty ? (
        <div className="card ev-emptycard">
          <h3>No traces ingested yet</h3>
          <p className="muted">
            Chat turns are emitted to Google Cloud Storage as they happen, and a batch job
            populates the queryable store. Once it runs, turns and their cost, latency, and status
            appear here.
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
            <h3 className="h3-row"><span>Recent traces</span></h3>
            <TracesTable rows={traces.slice(0, 50)} selected={sel}
                         onSelect={(id) => setSel(sel === id ? null : id)} />
            <div className="muted ev-foot">
              Real use only (source=prod). Pseudonymous — no identity is stored or shown. Click a
              row to read the full turn; pick a session in the rail to see just its turns.
            </div>
          </div>
          {sel ? <TraceDetail traceId={sel} /> : null}
        </>
      )}
    </>
  );
}

function TracesForSession({ session, traces }: { session: string; traces: EvalTraceRow[] }) {
  const [sel, setSel] = useState<string | null>(null);
  const rows = traces.filter((t) => (t.session_id || NO_SESSION) === session);
  const latest = rows.reduce<string | null>((m, t) => (t.ts && (!m || t.ts > m) ? t.ts : m), null);
  return (
    <>
      <PanelHead title={fmtDateTime(latest)}
                 sub={`${rows.length} turn${rows.length === 1 ? "" : "s"} · ${session}`} />
      <div className="card">
        <TracesTable rows={rows} selected={sel} onSelect={(id) => setSel(sel === id ? null : id)} />
      </div>
      {sel ? <TraceDetail traceId={sel} /> : null}
    </>
  );
}

// --- evals (curated + mined cases, grouped by status) --------------------------------------- //

const CASE_STATUS_ORDER = ["active", "candidate", "retired"];
const CASE_STATUS_LABEL: Record<string, string> = {
  active: "Active · the PR Gate set",
  candidate: "Candidate · mined, awaiting review",
  retired: "Retired",
};

function CasesTable({ rows }: { rows: EvalCaseRow[] }) {
  return (
    <div className="tbl-wrap" style={{ maxHeight: "unset" }}>
      <table className="tbl ev-tbl">
        <thead>
          <tr><th>Question</th><th>Level</th><th>Source</th><th>Graders</th><th>Tags</th></tr>
        </thead>
        <tbody>
          {rows.map((c) => (
            <tr key={c.eval_case_id}>
              <td className="ev-q">{c.question || <span className="muted">—</span>}</td>
              <td className="mono d">{c.level || "—"}</td>
              <td className="mono d">{c.source?.startsWith("mined") ? "mined" : c.source || "—"}</td>
              <td className="mono d">{c.graders.length ? c.graders.join(", ") : "—"}</td>
              <td className="mono d">{c.tags.length ? c.tags.join(" ") : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CasesPanel() {
  const [data, setData] = useState<{ cases: EvalCaseRow[]; available: boolean } | null>(null);
  const [err, setErr] = useState(false);

  useEffect(() => {
    api.get<{ cases: EvalCaseRow[]; available: boolean }>("/evals/cases")
      .then(setData).catch(() => setErr(true));
  }, []);

  if (err) return <LoadError />;
  if (data === null) return <Loading />;
  // Group by status, preserving the endpoint's order within each group.
  const groups: Record<string, EvalCaseRow[]> = {};
  for (const c of data.cases) (groups[c.status || "other"] ||= []).push(c);
  const statuses = [
    ...CASE_STATUS_ORDER.filter((s) => groups[s]),
    ...Object.keys(groups).filter((s) => !CASE_STATUS_ORDER.includes(s)),
  ];
  return (
    <>
      <PanelHead title="Evals" sub="the questions the assistant must keep getting right" />
      {data.available === false || data.cases.length === 0 ? (
        <div className="card ev-emptycard">
          <h3>No eval cases yet</h3>
          <p className="muted">
            Load the curated seed set, then mine more from real failures. Once loaded they appear
            here.
          </p>
          <p className="muted mono ev-cmd">cd backend &amp;&amp; python -m evals.load_seed_cases</p>
        </div>
      ) : (
        statuses.map((s) => (
          <div className="card" key={s}>
            <h3 className="h3-row">
              <span>{CASE_STATUS_LABEL[s] || s}</span>
              <span className="muted">{groups[s].length}</span>
            </h3>
            <CasesTable rows={groups[s]} />
            {s === "candidate" ? (
              <div className="muted ev-foot">
                Mined from real failures — a human reviews, confirms graders, and promotes to
                <span className="mono"> active</span> before these gate anything.
              </div>
            ) : null}
          </div>
        ))
      )}
    </>
  );
}

// --- results (scored runs) ------------------------------------------------------------------ //

function ResultsPanel({ runId, runs, onSelect }: {
  runId?: string; runs: EvalRunRow[]; onSelect: (m: Main) => void;
}) {
  const [results, setResults] = useState<EvalResultRow[] | null>(null);
  const [selTrace, setSelTrace] = useState<string | null>(null);

  useEffect(() => {
    setSelTrace(null);
    if (!runId) { setResults(null); return; }
    setResults(null);
    api.get<{ results: EvalResultRow[] }>(`/evals/runs/${encodeURIComponent(runId)}/results`)
      .then((d) => setResults(d.results || [])).catch(() => setResults([]));
  }, [runId]);

  if (runs.length === 0) {
    return (
      <>
        <PanelHead title="Results" sub="scored runs of the eval set" />
        <div className="card ev-emptycard">
          <h3>No eval runs yet</h3>
          <p className="muted">
            A run executes the active case set against the live agent and scores each answer. Run
            one and its pass rate, cost, and per-case results appear here.
          </p>
          <p className="muted mono ev-cmd">
            cd backend &amp;&amp; python -m evals.run_evals --set pr-gate --target-url &lt;url&gt;
          </p>
        </div>
      </>
    );
  }
  const pct = (r: number | null) => (r == null ? "—" : (r * 100).toFixed(0) + "%");
  return (
    <>
      <PanelHead title="Results" sub="scored runs of the eval set" />
      <div className="card">
        <h3 className="h3-row"><span>Eval runs</span></h3>
        <div className="tbl-wrap" style={{ maxHeight: "unset" }}>
          <table className="tbl ev-tbl">
            <thead>
              <tr>
                <th>When</th><th>Set</th><th>Target</th><th>Model</th>
                <th className="r">Pass rate</th><th className="r">Cases</th><th className="r">Cost</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.eval_run_id} className={runId === r.eval_run_id ? "sel" : ""}
                    style={{ cursor: "pointer" }}
                    onClick={() => onSelect({ kind: "results", runId: runId === r.eval_run_id ? undefined : r.eval_run_id })}>
                  <td className="mono ev-when">{ago(r.ts)}</td>
                  <td className="mono d">{setLabel(r.set_name)}</td>
                  <td className="mono d">{r.target || "—"}</td>
                  <td className="mono d">{r.model || "—"}</td>
                  <td className="r mono">{pct(r.pass_rate)}</td>
                  <td className="r mono">{r.passed ?? 0}/{r.n ?? 0}</td>
                  <td className="r mono">{fmtCostUSD(r.cost_usd ?? 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {runId ? (
        <>
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
                        <tr key={r.eval_case_id}
                            className={selTrace === r.trace_id ? "sel" : ""}
                            style={r.trace_id ? { cursor: "pointer" } : undefined}
                            onClick={r.trace_id ? () => setSelTrace(selTrace === r.trace_id ? null : r.trace_id) : undefined}>
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
            <div className="muted ev-foot">Click a row to read that case's full turn — the tool
              outputs make a verdict like <span className="mono">numeric_provenance</span> obvious.</div>
          </div>
          {selTrace ? <TraceDetail traceId={selTrace} /> : null}
        </>
      ) : null}
    </>
  );
}
