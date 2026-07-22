import { useEffect, useState } from "react";
import { api } from "../api";
import { fmtNum, fmtCostUSD, fmtDateTime } from "../format";
import { NO_SESSION } from "../traceSessions";
import type {
  EvalSummary, EvalTraceRow, EvalCaseRow, EvalRunRow, EvalResultRow, EvalTraceDetail, EvalTraceEvent,
  EvalGraderCatalogEntry, EvalGraderScore, EvalGraderStat, EvalCaseDetail, EvalCaseHistoryRow,
  EvalGraderDetail,
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

// Wrap each of `nums` where it appears as a standalone number in `text` (not inside a longer
// number) in a <mark>, so a grader's flagged figures light up in the answer and the tool output.
function markNumbers(text: string, nums: string[]): (string | JSX.Element)[] {
  if (!text || !nums || !nums.length) return [text];
  const esc = [...new Set(nums)].filter(Boolean).map((n) => n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  if (!esc.length) return [text];
  const re = new RegExp(esc.join("|"), "g");
  const isNumChar = (c: string | undefined) => c !== undefined && /[\d.]/.test(c);
  const out: (string | JSX.Element)[] = [];
  let last = 0, k = 0, m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    const start = m.index, end = start + m[0].length;
    if (isNumChar(text[start - 1]) || isNumChar(text[end])) continue; // part of a longer number
    if (start > last) out.push(text.slice(last, start));
    out.push(<mark className="hl" key={k++}>{m[0]}</mark>);
    last = end;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

type Highlight = { reply: string[]; tool: string[] };

// One turn, expanded: the question, each tool call with its full output, and the final answer —
// fetched from the GCS object via GET /evals/traces/{id}. Degrades to the header if it aged out.
// `highlight` marks a grader's flagged numbers in the answer + tool outputs.
function TraceDetail({ traceId, highlight }: { traceId: string; highlight?: Highlight }) {
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
        : d.events.map((e, i) => <EventRow key={i} e={e} highlight={highlight}
                                           meta={{ level: d.level, versions: d.versions }} />)}
    </div>
  );
}

// The six kinds of content in the system prompt — read the left columns as a novice ("what is
// this?"), the right column as a tuner ("what do I change, and which grader tells me it worked?").
const PROMPT_LAYERS = [
  { layer: "Identity & scope", what: "Who the assistant is, and what's off-limits", when: "static",
    tune: "edit the role / out-of-scope text → the decline cases + the usefulness judge" },
  { layer: "Guardrails", what: "Rules it must never break (honesty / legal)", when: "static",
    tune: "tighten a rule → its matching grader: numeric_provenance, plan_status_compliance, suppressed_value_handling" },
  { layer: "Operating doctrine", what: "How it should work — strong habits", when: "static",
    tune: "reword the habit → expected_tools / efficiency + the judge" },
  { layer: "Tool routing", what: "When to reach for which tool", when: "static",
    tune: "edit here or the tool catalog → expected_tools + iteration count" },
  { layer: "Output style", what: "Voice, length, format", when: "static",
    tune: "reword → the usefulness judge + output-token count" },
  { layer: "Runtime context", what: "This turn's facts: level + the on-screen charts (school: not yet)", when: "per turn",
    tune: "change what build_system assembles → resolution_correctness + fewer redundant set_school" },
];

// Click-to-open panel: what the model received with this question, categorized (for novices) and
// annotated with how to tune each layer + which grader confirms it (for tuners), then this turn's
// hashes and verbatim system prompt.
function QPanel({ level, versions, system }: {
  level: string | null; versions: Record<string, string>; system?: string | null;
}) {
  const h = (k: string) => (versions?.[k] ? versions[k].slice(0, 8) : "—");
  return (
    <div className="qpanel">
      <div className="qpanel-lead">Sent to the model with this question: the <b>system prompt</b> (six
        layers below), the <b>9-tool catalog</b>, and this session's <b>prior turns</b>.</div>
      <div className="tbl-wrap" style={{ maxHeight: "unset" }}>
        <table className="tbl ev-tbl qpanel-tbl">
          <thead><tr><th>Layer</th><th>What it is</th><th>When</th><th>Tune it → check with</th></tr></thead>
          <tbody>
            {PROMPT_LAYERS.map((l) => (
              <tr key={l.layer}>
                <td className="mono">{l.layer}</td>
                <td>{l.what}</td>
                <td className="mono d">{l.when}</td>
                <td className="muted">{l.tune}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="qpanel-hd">This turn</div>
      <div className="qpanel-meta mono">level {level || "?"} · prompt {h("prompt_hash")} · tools {h("tool_catalog_hash")}</div>
      {system
        ? <pre className="qinfo-sys">{system}</pre>
        : <div className="qpanel-note muted">Verbatim system prompt not captured for this trace — it
            pre-dates the capture feature. New turns show the exact text here.</div>}
      <div className="qpanel-note muted">Also shaping the answer, but not in the prompt: the tool
        catalog (capabilities), the conversation (this session's memory), and the model itself.</div>
    </div>
  );
}

function EventRow({ e, meta, highlight }: {
  e: EvalTraceEvent;
  meta?: { level: string | null; versions: Record<string, string> };
  highlight?: Highlight;
}) {
  const [open, setOpen] = useState(false);
  if (e.type === "turn_start") {
    return (
      <div>
        <div className="ev-ev ev-ev-q">
          <span className="ev-ev-lab">Q</span>
          <span className="ev-ev-body">
            {e.question}{" "}
            {meta ? (
              <button className="qinfo-btn" onClick={() => setOpen((v) => !v)}>
                ⓘ context {open ? "▲" : "▼"}
              </button>
            ) : null}
          </span>
        </div>
        {open && meta ? <QPanel level={meta.level} versions={meta.versions} system={e.system_prompt} /> : null}
      </div>
    );
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
        <pre className="ev-ev-out">{markNumbers(JSON.stringify(e.output, null, 2), highlight?.tool || [])}</pre>
      </div>
    );
  }
  if (e.type === "turn_end") {
    return <div className="ev-ev ev-ev-a"><span className="ev-ev-lab">A</span>
      <span className="ev-ev-body">{markNumbers(e.reply || "", highlight?.reply || [])}</span></div>;
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

function CasesTable({ rows, selected, onSelect }: {
  rows: EvalCaseRow[]; selected?: string | null; onSelect?: (id: string) => void;
}) {
  return (
    <div className="tbl-wrap" style={{ maxHeight: "unset" }}>
      <table className="tbl ev-tbl">
        <thead>
          <tr><th>Question</th><th>Level</th><th>Source</th><th>Graders</th><th>Tags</th></tr>
        </thead>
        <tbody>
          {rows.map((c) => (
            <tr key={c.eval_case_id} className={selected === c.eval_case_id ? "sel" : ""}
                style={onSelect ? { cursor: "pointer" } : undefined}
                onClick={onSelect ? () => onSelect(c.eval_case_id) : undefined}>
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
  const [sel, setSel] = useState<string | null>(null);

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
        <>
          {statuses.map((s) => (
            <div className="card" key={s}>
              <h3 className="h3-row">
                <span>{CASE_STATUS_LABEL[s] || s}</span>
                <span className="muted">{groups[s].length}</span>
              </h3>
              <CasesTable rows={groups[s]} selected={sel} onSelect={(id) => setSel(sel === id ? null : id)} />
              {s === "candidate" ? (
                <div className="muted ev-foot">
                  Mined from real failures — a human reviews, confirms graders, and promotes to
                  <span className="mono"> active</span> before these gate anything.
                </div>
              ) : null}
            </div>
          ))}
          {sel ? <CaseDetail caseId={sel} /> : null}
        </>
      )}
    </>
  );
}

// One case, expanded: its answer key (question, graders + params, source, notes) and its result
// history — every run that scored it, each drillable to the actual answer.
function CaseDetail({ caseId }: { caseId: string }) {
  const [d, setD] = useState<{ case: EvalCaseDetail; history: EvalCaseHistoryRow[] } | null>(null);
  const [err, setErr] = useState(false);
  const [selTrace, setSelTrace] = useState<string | null>(null);

  useEffect(() => {
    setD(null); setSelTrace(null); setErr(false);
    api.get<{ case: EvalCaseDetail; history: EvalCaseHistoryRow[]; available: boolean }>(`/evals/cases/${encodeURIComponent(caseId)}`)
      .then((r) => (r.available ? setD(r) : setErr(true))).catch(() => setErr(true));
  }, [caseId]);

  if (err) return <div className="card muted">Couldn’t load this case.</div>;
  if (!d) return <Loading />;
  const c = d.case;
  const minedFrom = c.source && c.source.startsWith("mined:") ? c.source.slice(6) : null;
  return (
    <>
      <div className="card ev-detail">
        <div className="ev-detail-meta mono">
          <span className={"ev-pill " + statusClass(c.status)}>{c.status || "—"}</span>
          {" · "}{c.level || "—"} · source {c.source?.startsWith("mined") ? "mined" : c.source || "—"}
        </div>
        <div className="ev-kv"><b>Question</b><div>{c.question}</div></div>
        <div className="ev-kv"><b>Graders</b><div className="mono">{c.graders.length ? c.graders.join(", ") : "(default set)"}</div></div>
        <div className="ev-kv"><b>Params</b>
          <pre className="qinfo-sys">{JSON.stringify(c.params || {}, null, 2)}</pre></div>
        {c.tags.length ? <div className="ev-kv"><b>Tags</b><div className="mono d">{c.tags.join(" ")}</div></div> : null}
        {c.notes ? <div className="ev-kv"><b>Notes</b><div className="muted">{c.notes}</div></div> : null}
        {minedFrom ? (
          <div className="ev-kv"><b>Mined from</b>
            <button className="linkbtn" onClick={() => setSelTrace(selTrace === minedFrom ? null : minedFrom)}>
              view source trace ↳</button></div>
        ) : null}
        <h3 className="h3-row" style={{ marginTop: 14 }}><span>Result history</span></h3>
        {d.history.length === 0 ? <div className="muted">Not scored in any run yet.</div> : (
          <div className="tbl-wrap" style={{ maxHeight: "unset" }}>
            <table className="tbl ev-tbl">
              <thead><tr><th>When</th><th>Set</th><th>Verdict</th><th></th></tr></thead>
              <tbody>
                {d.history.map((h) => (
                  <tr key={h.eval_run_id} className={selTrace === h.trace_id ? "sel" : ""}
                      style={h.trace_id ? { cursor: "pointer" } : undefined}
                      onClick={h.trace_id ? () => setSelTrace(selTrace === h.trace_id ? null : h.trace_id) : undefined}>
                    <td className="mono ev-when">{ago(h.ts)}</td>
                    <td className="mono d">{setLabel(h.set_name)}</td>
                    <td><span className={"ev-pill " + statusClass(h.verdict)}>{h.verdict || "—"}</span></td>
                    <td className="mono d">{h.trace_id ? "answer ↳" : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {selTrace ? <TraceDetail traceId={selTrace} /> : null}
    </>
  );
}

// --- grader breakdown + reference ----------------------------------------------------------- //

// Every grader that ran on one case, with its verdict, score, and own explanation — the "why".
function GraderBreakdown({ scores }: { scores: Record<string, EvalGraderScore> }) {
  const rows = Object.values(scores || {});
  if (!rows.length) return null;
  return (
    <div className="card">
      <h3 className="h3-row"><span>Grader breakdown</span></h3>
      <div className="tbl-wrap" style={{ maxHeight: "unset" }}>
        <table className="tbl ev-tbl">
          <thead>
            <tr><th>Tier</th><th>Grader</th><th>Verdict</th><th className="r">Score</th><th>Detail</th></tr>
          </thead>
          <tbody>
            {rows.map((s) => (
              <tr key={s.name}>
                <td className="mono d">{s.tier || "—"}</td>
                <td className="mono">{s.name || "—"}</td>
                <td><span className={"ev-pill " + statusClass(s.verdict || null)}>{s.verdict || "—"}</span></td>
                <td className="r mono">{s.score == null ? "—" : s.score}</td>
                <td className="ev-q muted">{s.detail || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// What each grader checks (GET /evals/graders — kept honest to graders.py by a test).
function GradersReference() {
  const [cat, setCat] = useState<EvalGraderCatalogEntry[] | null>(null);
  const [tiers, setTiers] = useState<Record<string, string>>({});
  const [sel, setSel] = useState<string | null>(null);
  useEffect(() => {
    api.get<{ graders: EvalGraderCatalogEntry[]; tiers: Record<string, string> }>("/evals/graders")
      .then((d) => { setCat(d.graders || []); setTiers(d.tiers || {}); }).catch(() => setCat([]));
  }, []);
  if (!cat || !cat.length) return null;
  return (
    <details className="card ev-ref">
      <summary>What these graders check <span className="muted">— click one for its track record</span></summary>
      <table className="tbl ev-tbl">
        <tbody>
          {cat.map((g) => (
            <tr key={g.name} className={sel === g.name ? "sel" : ""} style={{ cursor: "pointer" }}
                onClick={() => setSel(sel === g.name ? null : g.name)}>
              <td className="mono d">{g.tier} · {tiers[g.tier] || ""}</td>
              <td className="mono">{g.name}</td>
              <td className="ev-q muted">{g.summary}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {sel ? <GraderDetail name={sel} /> : null}
    </details>
  );
}

// One grader, expanded: what it checks + its track record (fail rate + recent failing cases,
// each drillable to the trace).
function GraderDetail({ name }: { name: string }) {
  const [d, setD] = useState<EvalGraderDetail | null>(null);
  const [err, setErr] = useState(false);
  const [selTrace, setSelTrace] = useState<string | null>(null);
  useEffect(() => {
    setD(null); setSelTrace(null); setErr(false);
    api.get<EvalGraderDetail & { available: boolean }>(`/evals/graders/${encodeURIComponent(name)}`)
      .then((r) => (r.available ? setD(r) : setErr(true))).catch(() => setErr(true));
  }, [name]);
  if (err) return <div className="card muted">Couldn’t load this grader.</div>;
  if (!d) return <Loading />;
  return (
    <>
      <div className="card ev-detail">
        <div className="ev-detail-meta mono">{d.grader.tier} · {d.grader.name}</div>
        <div className="ev-kv"><b>Checks</b><div>{d.grader.summary}</div></div>
        <div className="ev-kv"><b>Track record</b>
          <div>failed <b>{d.stats.failed}</b> of {d.stats.ran} time{d.stats.ran === 1 ? "" : "s"} it ran (recent)</div></div>
        <h3 className="h3-row" style={{ marginTop: 14 }}><span>Recent failures</span></h3>
        {d.failures.length === 0 ? <div className="muted">No recent failures.</div> : (
          <div className="tbl-wrap" style={{ maxHeight: "unset" }}>
            <table className="tbl ev-tbl">
              <thead><tr><th>When</th><th>Case</th><th>Detail</th><th></th></tr></thead>
              <tbody>
                {d.failures.map((f, i) => (
                  <tr key={i} className={selTrace === f.trace_id ? "sel" : ""}
                      style={f.trace_id ? { cursor: "pointer" } : undefined}
                      onClick={f.trace_id ? () => setSelTrace(selTrace === f.trace_id ? null : f.trace_id) : undefined}>
                    <td className="mono ev-when">{ago(f.ts)}</td>
                    <td className="ev-q">{f.question || <span className="muted">—</span>}</td>
                    <td className="ev-q muted">{f.detail || "—"}</td>
                    <td className="mono d">{f.trace_id ? "↳" : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {selTrace ? <TraceDetail traceId={selTrace} /> : null}
    </>
  );
}

// --- results (scored runs) ------------------------------------------------------------------ //

// One failing (or passing) case, told as a story: the question + verdict, WHY it scored that way
// (the grader breakdown, which now shows its work), then THE TURN — with the grader's flagged
// numbers highlighted in the answer and the tool output that should have grounded them.
function CaseNarrative({ result }: { result: EvalResultRow }) {
  const ev = result.scores?.numeric_provenance?.evidence;
  const hl: Highlight | undefined = ev ? { reply: ev.reply || [], tool: ev.tool || [] } : undefined;
  return (
    <div className="ev-story">
      <div className="ev-story-hd">
        <span className={"ev-pill " + statusClass(result.verdict)}>{result.verdict || "—"}</span>
        <span className="ev-story-q">{result.question || "—"}</span>
      </div>
      <div className="qpanel-hd">Why it scored this way</div>
      <GraderBreakdown scores={result.scores} />
      <div className="qpanel-hd">The turn</div>
      {result.trace_id
        ? <TraceDetail traceId={result.trace_id} highlight={hl} />
        : <div className="card muted">No trace recorded for this case.</div>}
    </div>
  );
}

function ResultsPanel({ runId, runs, onSelect }: {
  runId?: string; runs: EvalRunRow[]; onSelect: (m: Main) => void;
}) {
  const [results, setResults] = useState<EvalResultRow[] | null>(null);
  const [stats, setStats] = useState<EvalGraderStat[]>([]);
  const [sel, setSel] = useState<EvalResultRow | null>(null);

  useEffect(() => {
    setSel(null); setStats([]);
    if (!runId) { setResults(null); return; }
    setResults(null);
    api.get<{ results: EvalResultRow[]; grader_stats?: EvalGraderStat[] }>(`/evals/runs/${encodeURIComponent(runId)}/results`)
      .then((d) => { setResults(d.results || []); setStats(d.grader_stats || []); })
      .catch(() => setResults([]));
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
          {stats.length ? (
            <div className="card">
              <h3 className="h3-row"><span>Grader failures</span><span className="muted">this run</span></h3>
              <div className="ev-gstats">
                {stats.map((g) => (
                  <span key={g.grader} className={"ev-gstat" + (g.failed ? " bad" : "")}>
                    <span className="mono d">{g.tier}</span> {g.grader}
                    <b> {g.failed}/{g.ran}</b>
                  </span>
                ))}
              </div>
              <div className="muted ev-foot">How many cases each grader failed — the ranked fix backlog.</div>
            </div>
          ) : null}

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
                      const on = sel?.eval_case_id === r.eval_case_id;
                      return (
                        <tr key={r.eval_case_id} className={on ? "sel" : ""} style={{ cursor: "pointer" }}
                            onClick={() => setSel(on ? null : r)}>
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
            <div className="muted ev-foot">Click a row for the grader breakdown and the full turn —
              the tool outputs make a verdict like <span className="mono">numeric_provenance</span> obvious.</div>
          </div>

          {sel ? <CaseNarrative result={sel} /> : null}

          <GradersReference />
        </>
      ) : null}
    </>
  );
}
