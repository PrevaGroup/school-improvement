import { useEffect, useState } from "react";
import { api } from "../api";
import { fmtNum, fmtCostUSD } from "../format";
import type {
  EvalSummary, EvalTraceRow, EvalCaseRow, EvalRunRow, EvalResultRow, EvalTraceDetail, EvalTraceEvent,
  EvalGraderCatalogEntry, EvalGraderScore, EvalGraderStat, EvalCaseDetail, EvalCaseHistoryRow,
  EvalGraderDetail,
} from "../types";

// The admin eval workbench: a master-detail (list | detail) view per section, chosen by the
// section nav in App.tsx. Every stage is read-only and pseudonymous (no identity stored or shown).

export type EvalSection = "traces" | "evals" | "results" | "graders";

export function EvalWorkbench({ section }: { section: EvalSection }) {
  if (section === "traces") return <TracesWB />;
  if (section === "evals") return <EvalsWB />;
  if (section === "results") return <ResultsWB />;
  return <GradersWB />;
}

// The set a run executed. "golden" is the design's name for the fast PR-gating subset; we show it
// as "PR Gate" (clearer) and map legacy golden runs to the same label.
export function setLabel(s: string | null | undefined): string {
  return s === "golden" || s === "pr-gate" ? "PR Gate" : (s || "run");
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

function Loading() { return <div className="card muted dots">loading</div>; }
function LoadError() { return <div className="card muted">Couldn’t load this view.</div>; }
function Placeholder({ msg }: { msg: string }) { return <div className="wb-empty muted">{msg}</div>; }
function EmptyList({ msg, cmd }: { msg: string; cmd?: string }) {
  return (
    <div className="wb-empty muted">
      <div>{msg}</div>
      {cmd ? <div className="mono ev-cmd" style={{ marginTop: 10 }}>{cmd}</div> : null}
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

// --- the turn (trace detail) + its "ⓘ context" panel ---------------------------------------- //

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

// The six kinds of content in the system prompt — novice reads the left columns, tuner the right.
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

// --- grader breakdown + the case-failure narrative ------------------------------------------ //

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

// One case×run result, told as a story: verdict + question → WHY (grader breakdown, showing its
// work) → THE TURN, with the grader's flagged numbers highlighted in the answer + tool output.
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

// --- Traces: list of turns │ the turn (or a summary when nothing's selected) ----------------- //

function TracesSummary() {
  const [s, setS] = useState<EvalSummary | null>(null);
  const [err, setErr] = useState(false);
  useEffect(() => { api.get<EvalSummary>("/evals/summary").then(setS).catch(() => setErr(true)); }, []);
  if (err) return <LoadError />;
  if (s === null) return <Loading />;
  if (s.available === false || (s.traces ?? 0) === 0) {
    return <Placeholder msg="Select a trace to read the full turn." />;
  }
  return (
    <>
      <div className="ev-tiles">
        <Tile label="traces" value={fmtNum(s.traces ?? 0)} sub={`last ${s.window}`} />
        <Tile label="ok rate" value={s.ok_rate == null ? "—" : s.ok_rate + "%"} />
        <Tile label="cost (est.)" value={fmtCostUSD(s.cost_usd ?? 0)} />
        <Tile label="p50 latency" value={s.latency_p50_ms == null ? "—" : (s.latency_p50_ms / 1000).toFixed(1) + "s"}
              sub={s.latency_max_ms ? "max " + (s.latency_max_ms / 1000).toFixed(1) + "s" : undefined} />
        <Tile label="tokens" value={fmtNum(s.tokens ?? 0)} />
      </div>
      <div className="ev-breakdowns">
        <Breakdown title="status" counts={s.by_status} statusColor />
        <Breakdown title="source" counts={s.by_source} />
        <Breakdown title="model" counts={s.by_model} />
      </div>
      <div className="muted ev-foot">Real use only (source=prod). Pick a turn on the left to read it.</div>
    </>
  );
}

function TracesWB() {
  const [rows, setRows] = useState<EvalTraceRow[] | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  useEffect(() => {
    api.get<{ traces: EvalTraceRow[] }>("/evals/traces?limit=200")
      .then((d) => setRows(d.traces || [])).catch(() => setRows([]));
  }, []);
  return (
    <div className="wb">
      <div className="wb-list">
        <div className="wb-hd"><span>Traces</span><span className="muted">{rows?.length ?? ""}</span></div>
        {rows === null ? <Loading />
          : rows.length === 0 ? <EmptyList msg="No traces ingested yet." cmd="python -m evals.ingest_traces" />
            : rows.map((t) => (
              <div key={t.trace_id} className={"wb-row" + (sel === t.trace_id ? " on" : "")}
                   onClick={() => setSel(t.trace_id)}>
                <div className="wb-row-t">{t.question || <span className="muted">— (no question)</span>}</div>
                <div className="wb-row-m">
                  <span className={"ev-pill " + statusClass(t.status)}>{t.status || "—"}</span>
                  {" · "}{ago(t.ts)} · {t.model || "—"}
                </div>
              </div>
            ))}
      </div>
      <div className="wb-detail">
        {sel ? <TraceDetail traceId={sel} /> : <TracesSummary />}
      </div>
    </div>
  );
}

// --- Evals: cases (grouped by status), expand → run history │ config or a result narrative ---- //

const CASE_STATUS_ORDER = ["active", "candidate", "retired"];
const CASE_STATUS_LABEL: Record<string, string> = {
  active: "Active · the PR Gate set",
  candidate: "Candidate · mined, awaiting review",
  retired: "Retired",
};

function CaseConfig({ c }: { c: EvalCaseDetail }) {
  return (
    <div className="card ev-detail">
      <div className="ev-detail-meta mono">
        <span className={"ev-pill " + statusClass(c.status)}>{c.status || "—"}</span>
        {" · "}{c.level || "—"} · source {c.source?.startsWith("mined") ? "mined" : c.source || "—"}
      </div>
      <div className="ev-kv"><b>Question</b><div>{c.question}</div></div>
      <div className="ev-kv"><b>Graders</b><div className="mono">{c.graders.length ? c.graders.join(", ") : "(default set)"}</div></div>
      <div className="ev-kv"><b>Params</b><pre className="qinfo-sys">{JSON.stringify(c.params || {}, null, 2)}</pre></div>
      {c.tags.length ? <div className="ev-kv"><b>Tags</b><div className="mono d">{c.tags.join(" ")}</div></div> : null}
      {c.notes ? <div className="ev-kv"><b>Notes</b><div className="muted">{c.notes}</div></div> : null}
      <div className="muted ev-foot">Pick a run on the left to see how it scored.</div>
    </div>
  );
}

function EvalsWB() {
  const [cases, setCases] = useState<EvalCaseRow[] | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [hist, setHist] = useState<Record<string, EvalCaseHistoryRow[]>>({});
  const [info, setInfo] = useState<Record<string, EvalCaseDetail>>({});
  const [sel, setSel] = useState<EvalResultRow | null>(null);

  useEffect(() => {
    api.get<{ cases: EvalCaseRow[] }>("/evals/cases").then((d) => setCases(d.cases || [])).catch(() => setCases([]));
  }, []);

  const toggle = (id: string) => {
    setSel(null);
    if (expanded === id) { setExpanded(null); return; }
    setExpanded(id);
    if (!(id in hist)) {
      api.get<{ case: EvalCaseDetail; history: EvalCaseHistoryRow[] }>(`/evals/cases/${encodeURIComponent(id)}`)
        .then((d) => { setHist((p) => ({ ...p, [id]: d.history || [] })); setInfo((p) => ({ ...p, [id]: d.case })); })
        .catch(() => setHist((p) => ({ ...p, [id]: [] })));
    }
  };
  const pick = (c: EvalCaseRow, hRow: EvalCaseHistoryRow) => setSel({
    eval_case_id: c.eval_case_id, question: c.question, verdict: hRow.verdict,
    scores: hRow.scores || {}, judge_rationale: null, trace_id: hRow.trace_id,
  });

  const groups: Record<string, EvalCaseRow[]> = {};
  for (const c of cases || []) (groups[c.status || "other"] ||= []).push(c);
  const statuses = [
    ...CASE_STATUS_ORDER.filter((s) => groups[s]),
    ...Object.keys(groups).filter((s) => !CASE_STATUS_ORDER.includes(s)),
  ];

  return (
    <div className="wb">
      <div className="wb-list">
        <div className="wb-hd"><span>Evals</span><span className="muted">{cases?.length ?? ""}</span></div>
        {cases === null ? <Loading />
          : cases.length === 0 ? <EmptyList msg="No eval cases yet." cmd="python -m evals.load_seed_cases" />
            : statuses.map((st) => (
              <div key={st}>
                <div className="wb-group">{CASE_STATUS_LABEL[st] || st} · {groups[st].length}</div>
                {groups[st].map((c) => (
                  <div key={c.eval_case_id}>
                    <div className={"wb-row" + (expanded === c.eval_case_id ? " open" : "")}
                         onClick={() => toggle(c.eval_case_id)}>
                      <div className="wb-row-t">{c.question || "—"}
                        <span className="wb-caret"> {expanded === c.eval_case_id ? "▾" : "▸"}</span></div>
                      <div className="wb-row-m">{c.level || "—"} · {c.source?.startsWith("mined") ? "mined" : c.source || "—"}</div>
                    </div>
                    {expanded === c.eval_case_id ? (
                      <div className="wb-sub">
                        {!(c.eval_case_id in hist) ? <div className="muted wb-subrow">loading…</div>
                          : (hist[c.eval_case_id] || []).length === 0 ? <div className="muted wb-subrow">not scored in any run yet</div>
                            : (hist[c.eval_case_id] || []).map((h, i) => (
                              <div key={i} className={"wb-subrow" + (sel?.eval_case_id === c.eval_case_id && sel?.trace_id === h.trace_id ? " on" : "")}
                                   onClick={() => pick(c, h)}>
                                <span className={"ev-pill " + statusClass(h.verdict)}>{h.verdict || "—"}</span>
                                <span className="wb-subrow-t">{setLabel(h.set_name)} · {ago(h.ts)}</span>
                              </div>
                            ))}
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
            ))}
      </div>
      <div className="wb-detail">
        {sel ? <CaseNarrative result={sel} />
          : expanded && info[expanded] ? <CaseConfig c={info[expanded]} />
            : <Placeholder msg="Expand a case, then pick a run to see how it scored." />}
      </div>
    </div>
  );
}

// --- Results: runs, expand → per-case results │ a result narrative --------------------------- //

function ResultsWB() {
  const [runs, setRuns] = useState<EvalRunRow[] | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, EvalResultRow[]>>({});
  const [stats, setStats] = useState<Record<string, EvalGraderStat[]>>({});
  const [sel, setSel] = useState<EvalResultRow | null>(null);

  useEffect(() => {
    api.get<{ runs: EvalRunRow[] }>("/evals/runs").then((d) => setRuns(d.runs || [])).catch(() => setRuns([]));
  }, []);

  const toggle = (id: string) => {
    setSel(null);
    if (expanded === id) { setExpanded(null); return; }
    setExpanded(id);
    if (!(id in results)) {
      api.get<{ results: EvalResultRow[]; grader_stats?: EvalGraderStat[] }>(`/evals/runs/${encodeURIComponent(id)}/results`)
        .then((d) => { setResults((p) => ({ ...p, [id]: d.results || [] })); setStats((p) => ({ ...p, [id]: d.grader_stats || [] })); })
        .catch(() => setResults((p) => ({ ...p, [id]: [] })));
    }
  };
  const pct = (r: number | null) => (r == null ? "—" : (r * 100).toFixed(0) + "%");

  return (
    <div className="wb">
      <div className="wb-list">
        <div className="wb-hd"><span>Results</span><span className="muted">runs</span></div>
        {runs === null ? <Loading />
          : runs.length === 0 ? <EmptyList msg="No eval runs yet." cmd="python -m evals.run_evals --set pr-gate --target-url <url>" />
            : runs.map((r) => (
              <div key={r.eval_run_id}>
                <div className={"wb-row" + (expanded === r.eval_run_id ? " open" : "")}
                     onClick={() => toggle(r.eval_run_id)}>
                  <div className="wb-row-t">{setLabel(r.set_name)} · {pct(r.pass_rate)}
                    <span className="wb-caret"> {expanded === r.eval_run_id ? "▾" : "▸"}</span></div>
                  <div className="wb-row-m">{ago(r.ts)} · {r.passed ?? 0}/{r.n ?? 0} · {fmtCostUSD(r.cost_usd ?? 0)}</div>
                </div>
                {expanded === r.eval_run_id ? (
                  <div className="wb-sub">
                    {stats[r.eval_run_id]?.length ? (
                      <div className="ev-gstats" style={{ margin: "2px 0 6px" }}>
                        {stats[r.eval_run_id].filter((g) => g.failed).map((g) => (
                          <span key={g.grader} className="ev-gstat bad">{g.grader} <b>{g.failed}/{g.ran}</b></span>
                        ))}
                      </div>
                    ) : null}
                    {!(r.eval_run_id in results) ? <div className="muted wb-subrow">loading…</div>
                      : (results[r.eval_run_id] || []).map((res) => (
                        <div key={res.eval_case_id} className={"wb-subrow" + (sel === res ? " on" : "")}
                             onClick={() => setSel(res)}>
                          <span className={"ev-pill " + statusClass(res.verdict)}>{res.verdict || "—"}</span>
                          <span className="wb-subrow-t">{res.question || "—"}</span>
                        </div>
                      ))}
                  </div>
                ) : null}
              </div>
            ))}
      </div>
      <div className="wb-detail">
        {sel ? <CaseNarrative result={sel} /> : <Placeholder msg="Expand a run, then pick a case to see why it scored." />}
      </div>
    </div>
  );
}

// --- Graders: the catalog │ what it checks + track record + recent failures ------------------ //

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

function GradersWB() {
  const [cat, setCat] = useState<EvalGraderCatalogEntry[] | null>(null);
  const [tiers, setTiers] = useState<Record<string, string>>({});
  const [sel, setSel] = useState<string | null>(null);
  useEffect(() => {
    api.get<{ graders: EvalGraderCatalogEntry[]; tiers: Record<string, string> }>("/evals/graders")
      .then((d) => { setCat(d.graders || []); setTiers(d.tiers || {}); }).catch(() => setCat([]));
  }, []);
  return (
    <div className="wb">
      <div className="wb-list">
        <div className="wb-hd"><span>Graders</span><span className="muted">{cat?.length ?? ""}</span></div>
        {cat === null ? <Loading />
          : cat.map((g) => (
            <div key={g.name} className={"wb-row" + (sel === g.name ? " on" : "")} onClick={() => setSel(g.name)}>
              <div className="wb-row-t mono">{g.name}</div>
              <div className="wb-row-m">{g.tier} · {tiers[g.tier] || ""} — {g.summary}</div>
            </div>
          ))}
      </div>
      <div className="wb-detail">
        {sel ? <GraderDetail name={sel} /> : <Placeholder msg="Select a grader for what it checks and its track record." />}
      </div>
    </div>
  );
}
