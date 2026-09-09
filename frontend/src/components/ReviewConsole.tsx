import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api";
import { AssignmentHome, Scope } from "./AssignmentHome";
import { TraitProfile } from "./TraitProfile";

// The teacher's review screen: the queue on the left, one paper on the right.
//
// WHAT THIS SCREEN REFUSES TO SHOW, which is as much of the design as what it shows:
//
//  * No total, no average, no percentage. The scale is criterion-referenced — a level says the
//    writing meets that descriptor, not that it ranks anywhere — so a mean across criteria is a
//    number nobody assigned. The only counts here are counts of PAPERS in a state.
//  * A criterion the scoring could not reach shows NO number at all, not a zero and not a blank
//    cell that reads like one. "We could not tell" and "this is weak" are different findings and
//    the whole record is built to keep them apart.
//  * Evidence is only ever the student's own words, verified as an exact substring of what they
//    wrote. Spans the model proposed and could not verify are reported as a count, never as text.
//  * Prior levels from a different scoring configuration are labelled, because raw levels from two
//    raters are not directly comparable and two numbers side by side invite a trend.

type Criterion = {
  node_id: string;
  criterion_label: string | null;
  standard_code: string | null;
  scale_categories: number[] | null;
  status: string;
  level: number | null;
  confidence: string | null;
  reason: string | null;
  reason_code: string | null;
  needs_human: boolean;
  evidence: string[];
  // WHERE each verified span sits in the normalised text. The verifier returned these offsets
  // so a reader could highlight without searching again; until now they were discarded and the
  // console listed quotations beside the paper instead of showing them in it.
  spans?: { at: number; len: number; span: string | null }[];
  evidence_dropped: number;
  rubric_version: string | null;
  prior: PriorObservation[];
};

type PriorObservation = {
  task_id: string | null;
  iteration: string | null;
  window_label: string | null;
  level: number | null;
  scoring_configuration_id: string | null;
  same_rater: boolean;
  when: string | null;
};

type Packet = {
  composer_version: string;
  student_id: string | null;
  section_id: string | null;
  task_id: string | null;
  iteration: string | null;
  window_label: string | null;
  text?: string;
  // The string the offsets are into, and the string the scorer was actually shown. Highlighting
  // over `text` instead would be off by however much whitespace and typography the normaliser
  // folded — silently, and by a different amount on every paper.
  text_normalized?: string;
  normalization_version?: string;
  stamp: Record<string, string | number | null>;
  criteria: Criterion[];
  needs_human: string[];
  prior_rater_mismatch: boolean;
  prior_note: string | null;
  feedback?: {
    message: string;
    quotations: string[];
    composer_version: string;
    holds: { code: string; detail: string }[];
    // Set once a teacher has edited. The machine's original is kept beside it — "what the model
    // drafted" and "what the teacher sent" are two different facts, and only one of them tells you
    // how much editing the drafts actually need.
    edited_by?: string;
    machine_draft?: string;
    holds_are_advisory?: boolean;
  };
};

type QueueRow = {
  artifact_id: string;
  state: string;
  state_reason_code: string | null;
  student_id: string | null;
  section_id: string | null;
  task_id: string | null;
  iteration: string | null;
  window_label: string | null;
  display_name: string | null;
  needs_human: number | null;
  holds: number | null;
  criteria: number | null;
  prior_rater_mismatch: boolean | null;
};

type ScoreEvent = {
  event_id: string;
  node_id: string;
  status: string;
  level: number | null;
  reason: string | null;
  scorer_type: string;
  scorer_id: string | null;
  supersedes_event_id: string | null;
  current: boolean;
  created_at: string | null;
};

type Attempt = {
  delivery_id: string;
  composition_id: string;
  channel: string;
  target_ref: string | null;
  status: string;
  detail: string | null;
  message_hash: string | null;
  attempted_at: string | null;
  delivered_at: string | null;
  attempted_by: string | null;
};

type Delivery = {
  available: boolean;
  attempts: Attempt[];
  delivered: Attempt | null;
  last_attempt: Attempt | null;
};

type Transition = {
  from_state: string | null;
  to_state: string;
  actor_type: string;
  actor_id: string | null;
  created_at: string | null;
};

type IntakeFile = {
  name: string;
  status: string;
  reason_code: string | null;
  candidates: { student_id: string; display_name: string | null; score: number }[] | null;
  word_count: number | null;
  text: string | null;
  folder: string | null;
  read_at: string | null;
};

type RosterEntry = { student_id: string; display_name: string | null };

type Detail = {
  artifact_id: string;
  composition_id: string;
  state: string;
  state_reason_code: string | null;
  student_id: string | null;
  intake: IntakeFile | null;
  roster: RosterEntry[];
  packet: Packet | null;
  events: ScoreEvent[];
  transitions: Transition[];
  needs_human: number;
  prior_rater_mismatch: boolean;
};

const STATE_LABEL: Record<string, string> = {
  in_review: "Ready for you",
  blocked: "Held — the draft did not clear its checks",
  released: "Released",
  withheld: "Not sent",
  not_scorable: "No attempt",
  unbound: "Could not tell whose",
};

// A criterion outcome that carries no number, said in words rather than left as an empty cell.
const NO_NUMBER: Record<string, string> = {
  abstained: "Could not place it — needs you",
  no_verified_evidence: "No verified evidence — needs you",
  not_scorable: "No attempt on this criterion",
  withheld: "Withheld",
  unbound: "Not bound",
};

// A name when the roster has one, the identifier when it does not. Deliberately no prettifying
// regex: a key tidied up to look like a name is worse than a key, because it hides that nobody
// knows who this is. `unbound` is a real state and it should look like one.
function who(name: string | null | undefined, id: string | null): string {
  return (name && name.trim()) || id || "—";
}

// A set is a binding key, and a paper is in it when every declared part matches. `null` in the
// scope means "not declared", which is a value a paper can genuinely have — so this compares
// rather than skipping, and a set of undeclared papers is a real set you can open.
// The papers a set-level decision would touch, named. The endpoint takes an explicit list
// rather than a binding key, and this is why: a scope expands quietly when a late paper arrives,
// and a judgment that silently grew to cover work the teacher never saw is not the judgment they
// made. So the console sends what it showed.
export type SetPaper = { artifact_id: string; name: string };

function inScope(r: QueueRow, sc: Scope): boolean {
  return r.section_id === sc.section_id && r.task_id === sc.task_id
      && r.iteration === sc.iteration && r.window_label === sc.window_label;
}

export function ReviewConsole() {
  // The console opens on the sets, not on a paper. "What is waiting for me" is a question the
  // teacher asks second; "is 5B's op-ed done" is the one they arrive with.
  const [scope, setScope] = useState<Scope | null>(null);
  const [scopeTitle, setScopeTitle] = useState<string>("");
  const [atHome, setAtHome] = useState(true);
  const [queue, setQueue] = useState<QueueRow[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [available, setAvailable] = useState<boolean | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [delivery, setDelivery] = useState<Delivery | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadQueue = useCallback(async () => {
    try {
      const r = await api.get<{ available: boolean; queue: QueueRow[]; counts: Record<string, number> }>(
        "/review/queue");
      setAvailable(r.available);
      setQueue(r.queue);
      setCounts(r.counts);
      if (r.queue.length && !selected && !atHome) setSelected(r.queue[0].artifact_id);
    } catch (e) {
      setAvailable(false);
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }, [selected, atHome]);

  useEffect(() => { void loadQueue(); }, [loadQueue]);

  function openSet(sc: Scope, title: string) {
    setScope(sc);
    setScopeTitle(title);
    setAtHome(false);
    const first = queue.find((r) => inScope(r, sc));
    setSelected(first ? first.artifact_id : null);
  }

  // A stuck paper is opened from the home page directly, with no set around it — that is the
  // point of naming them there rather than counting them.
  function openPaper(artifact_id: string) {
    setScope(null);
    setScopeTitle("");
    setAtHome(false);
    setSelected(artifact_id);
  }

  function goHome() {
    setAtHome(true);
    setScope(null);
    setSelected(null);
    setDetail(null);
  }

  useEffect(() => {
    if (!selected) { setDetail(null); return; }
    let live = true;
    setError(null);
    api.get<Detail>(`/review/artifact/${encodeURIComponent(selected)}`)
      .then((d) => { if (live) setDetail(d); })
      .catch((e) => { if (live) { setDetail(null); setError(e instanceof ApiError ? e.message : String(e)); } });
    // Separate call: a paper with no hand-back yet is the normal case, and a 404 or an empty
    // result here must not stop the review packet rendering.
    api.get<Delivery>(`/delivery/${encodeURIComponent(selected)}`)
      .then((d) => { if (live) setDelivery(d); })
      .catch(() => { if (live) setDelivery(null); });
    return () => { live = false; };
  }, [selected]);

  async function move(state: string) {
    if (!detail) return;
    setBusy(true);
    setError(null);
    try {
      await api.post(`/review/${encodeURIComponent(detail.artifact_id)}/state`, { state });
      const d = await api.get<Detail>(`/review/artifact/${encodeURIComponent(detail.artifact_id)}`);
      setDetail(d);
      await loadQueue();
    } catch (e) {
      // The database's refusal, passed through. It names the states and says what was wrong with
      // the move, which is more useful than anything this layer could reconstruct.
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  // One judgment about one criterion, across the papers on screen. The single-paper override
  // is deliberately NOT looped: the same decision written N times reads as N raters concurring.
  async function setOverride(node_id: string, level: number | null, status: string,
                             reason: string, artifact_ids: string[]) {
    setBusy(true);
    setError(null);
    try {
      const r = await api.post<{ applied: unknown[]; not_scored_on_this_criterion: string[] }>(
        "/review/set-override", { node_id, level, status, reason, artifact_ids });
      // Named, not counted: a paper the decision did not reach still carries the machine's score,
      // and it is the one thing the teacher has to act on afterwards.
      if (r.not_scored_on_this_criterion.length) {
        setError(`Applied to ${r.applied.length}. Not applied to `
          + `${r.not_scored_on_this_criterion.length} — those papers have no standing score on `
          + `this criterion, so they still carry whatever the scoring said.`);
      }
      if (selected) {
        const d = await api.get<Detail>(`/review/artifact/${encodeURIComponent(selected)}`);
        setDetail(d);
      }
      await loadQueue();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function resolveTo(student_id: string) {
    if (!detail) return;
    setBusy(true);
    setError(null);
    try {
      await api.post(`/review/${encodeURIComponent(detail.artifact_id)}/resolve`, { student_id });
      const d = await api.get<Detail>(`/review/artifact/${encodeURIComponent(detail.artifact_id)}`);
      setDetail(d);
      await loadQueue();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function saveFeedback(message: string) {
    if (!detail) return;
    setBusy(true);
    setError(null);
    try {
      await api.post(`/review/${encodeURIComponent(detail.artifact_id)}/feedback`, { message });
      const d = await api.get<Detail>(`/review/artifact/${encodeURIComponent(detail.artifact_id)}`);
      setDetail(d);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function override(ev: ScoreEvent, level: number | null, status: string, reason: string) {
    if (!detail) return;
    setBusy(true);
    setError(null);
    try {
      await api.post(`/review/${encodeURIComponent(detail.artifact_id)}/override`, {
        supersedes_event_id: ev.event_id, level, status, reason,
      });
      const d = await api.get<Detail>(`/review/artifact/${encodeURIComponent(detail.artifact_id)}`);
      setDetail(d);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (available === false) {
    return (
      <div className="rv-empty">
        <h2>No papers yet</h2>
        <p>
          Nothing has been scored and composed into a review packet. This screen fills once the
          pipeline has run — it is not an error.
        </p>
        {error && <p className="rv-err">{error}</p>}
      </div>
    );
  }

  if (atHome) return <AssignmentHome onOpenSet={openSet} onOpenPaper={openPaper} />;

  const shown = scope ? queue.filter((r) => inScope(r, scope)) : queue;

  return (
    <div className="rv">
      <aside className="rv-queue">
        <div className="rv-back">
          <button onClick={goHome}>&larr; All assignments</button>
          {scopeTitle && <div className="rv-scope">{scopeTitle}</div>}
        </div>
        <div className="rv-counts">
          {Object.entries(scope
            ? shown.reduce<Record<string, number>>(
                (acc, r) => ({ ...acc, [r.state]: (acc[r.state] ?? 0) + 1 }), {})
            : counts).map(([state, n]) => (
            <span key={state} className={`rv-chip rv-${state}`}>{n} {STATE_LABEL[state] ?? state}</span>
          ))}
        </div>
        {/* Only inside a set. A profile across every assignment in the school would average
            classes that share nothing — different tasks, different rubrics, different weeks. */}
        {scope?.section_id && scope?.task_id && scope?.iteration && (
          <TraitProfile sectionId={scope.section_id} taskId={scope.task_id}
                        iteration={scope.iteration} />
        )}
        <ul>
          {shown.map((r) => (
            <li key={r.artifact_id}
                className={r.artifact_id === selected ? "rv-sel" : ""}
                onClick={() => setSelected(r.artifact_id)}>
              <b>{who(r.display_name, r.student_id)}</b>
              <span className={`rv-state rv-${r.state}`}>{STATE_LABEL[r.state] ?? r.state}</span>
              <small>
                {r.criteria ?? 0} criteria
                {(r.needs_human ?? 0) > 0 && <em> · {r.needs_human} need you</em>}
                {(r.holds ?? 0) > 0 && <em> · {r.holds} held</em>}
              </small>
            </li>
          ))}
        </ul>
        {!shown.length && (
          <p className="rv-mut">
            {scope ? "Nothing in this set is waiting on you." : "Nothing waiting."}
          </p>
        )}
      </aside>

      <section className="rv-paper">
        {error && <div className="rv-err">{error}</div>}
        {!detail && <p className="rv-mut">Select a paper.</p>}
        {detail && detail.state === "unbound"
          ? <Stuck d={detail} busy={busy} onResolve={resolveTo} />
          : detail && <Paper d={detail} delivery={delivery} busy={busy} onMove={move}
                             onOverride={override} onSaveFeedback={saveFeedback}
                             setPapers={scope
                               ? shown.map((r) => ({ artifact_id: r.artifact_id,
                                                     name: who(r.display_name, r.student_id) }))
                               : null}
                             setTitle={scopeTitle}
                             onSetOverride={setOverride} />}
      </section>
    </div>
  );
}

// A paper that exists in a folder and belongs to nobody yet. It became an artifact rather than
// being dropped — a file that exists in a folder and nowhere in the system is the failure the
// intake statuses exist to prevent — and this is where a person answers the question the matching
// could not.
//
// The candidate list may be EMPTY, and that is a real answer rather than a missing one: nothing in
// this file says whose it is. Showing three low-scoring names instead would be worse than showing
// none, because a rushed teacher accepts one and the paper is filed under a student who did not
// write it.
function Stuck({ d, busy, onResolve }: {
  d: Detail; busy: boolean; onResolve: (student_id: string) => void;
}) {
  const [picked, setPicked] = useState("");
  const f = d.intake;
  const candidates = f?.candidates ?? [];
  const named = new Set(candidates.map((c) => c.student_id));

  return (
    <>
      <header className="rv-head">
        <div>
          <h2>{f?.name ?? d.artifact_id}</h2>
          <small>
            {f?.word_count != null ? `${f.word_count} words` : "—"}
            {f?.folder && <> · from {f.folder}</>}
          </small>
        </div>
        <span className="rv-state rv-unbound">{STATE_LABEL.unbound}</span>
      </header>

      <div className="rv-holds">
        <b>We don't know whose paper this is.</b>
        <p>
          Nothing in the file said whose it is, so it is waiting rather than guessed at. Nobody
          is scored until you say.
        </p>
        {f?.reason_code && <small><code>{f.reason_code}</code></small>}
      </div>

      <section className="rv-criteria">
        <h3>Whose is it?</h3>
        {candidates.length > 0 ? (
          <>
            <p className="rv-mut">Closest matches on the filename:</p>
            <div className="rv-editbar">
              {candidates.map((c) => (
                <button key={c.student_id} className="rv-primary" disabled={busy}
                        onClick={() => onResolve(c.student_id)}>
                  {c.display_name ?? c.student_id}
                </button>
              ))}
            </div>
          </>
        ) : (
          <p className="rv-mut">
            Nothing in the filename points at anyone on this roster, so there is no shortlist to
            offer — pick from the class below.
          </p>
        )}

        <div className="rv-editbar" style={{ marginTop: 14 }}>
          <select value={picked} disabled={busy}
                  onChange={(e) => setPicked(e.target.value)}>
            <option value="">{candidates.length ? "Someone else…" : "Choose a student…"}</option>
            {d.roster.filter((r) => !named.has(r.student_id)).map((r) => (
              <option key={r.student_id} value={r.student_id}>
                {r.display_name ?? r.student_id}
              </option>
            ))}
          </select>
          <button disabled={busy || !picked} onClick={() => onResolve(picked)}>
            Save name
          </button>
          <small>
            Once saved this cannot be changed — a paper that already carries scores and
            feedback describes one student's writing.
          </small>
        </div>
      </section>

      {f?.text && (
        <section className="rv-text">
          <h3>What it says</h3>
          <pre>{f.text}</pre>
        </section>
      )}
    </>
  );
}

function Paper({ d, delivery, busy, onMove, onOverride, onSaveFeedback,
                setPapers, setTitle, onSetOverride }: {
  d: Detail; delivery: Delivery | null; busy: boolean;
  setPapers: SetPaper[] | null; setTitle: string;
  onSetOverride: (node_id: string, level: number | null, status: string, reason: string,
                  artifact_ids: string[]) => void;
  onMove: (s: string) => void;
  onOverride: (ev: ScoreEvent, level: number | null, status: string, reason: string) => void;
  onSaveFeedback: (message: string) => void;
}) {
  const p = d.packet;
  // One criterion at a time. Highlighting every criterion's evidence at once would colour most
  // of the paper and say nothing — the question a teacher has is "why did THIS get a 2", and the
  // answer is the handful of sentences that criterion was judged on.
  const [focus, setFocus] = useState<Criterion | null>(null);
  if (!p) return <p className="rv-mut">This paper has not been scored yet.</p>;
  const holds = p.feedback?.holds ?? [];
  const current = new Map(d.events.filter((e) => e.current).map((e) => [e.node_id, e]));

  return (
    <>
      <header className="rv-head">
        <div>
          <h2>{who(null, p.student_id)}</h2>
          <small>{p.task_id} · {p.iteration} · {p.window_label}</small>
        </div>
        <div className="rv-actions">
          <span className={`rv-state rv-${d.state}`}>{STATE_LABEL[d.state] ?? d.state}</span>
          {d.state === "in_review" && (
            <>
              <button disabled={busy} className="rv-primary" onClick={() => onMove("released")}>
                Release
              </button>
              <button disabled={busy} onClick={() => onMove("withheld")}>Do not send</button>
            </>
          )}
          {d.state === "blocked" && (
            <button disabled={busy} onClick={() => onMove("in_review")}>
              Take it anyway
            </button>
          )}
        </div>
      </header>

      {holds.length > 0 && (
        <div className="rv-holds">
          <b>The drafted message was held.</b>
          <ul>{holds.map((h, i) => <li key={i}><code>{h.code}</code> {h.detail}</li>)}</ul>
          <small>
            Nothing has gone to the student. Holding costs a click; a message that goes out wrong
            cannot be clicked back.
          </small>
        </div>
      )}

      {p.prior_note && <div className="rv-note">{p.prior_note}</div>}

      {delivery?.available && delivery.attempts.length > 0 && (
        <HandBack delivery={delivery}
                  currentComposition={d.composition_id} />
      )}

      {p.feedback?.message && (
        <FeedbackPanel key={d.composition_id} fb={p.feedback} busy={busy}
                       onSave={onSaveFeedback} />
      )}

      <section className="rv-criteria">
        <h3>Scores</h3>
        {p.criteria.map((c) => (
          <CriterionRow key={c.node_id} c={c} ev={current.get(c.node_id) ?? null}
                        busy={busy} onOverride={onOverride}
                        setPapers={setPapers} setTitle={setTitle}
                        onSetOverride={onSetOverride}
                        focused={focus?.node_id === c.node_id}
                        onFocus={() => setFocus(focus?.node_id === c.node_id ? null : c)} />
        ))}
      </section>

      {p.text && (
        <section className="rv-text">
          <h3>What they wrote</h3>
          {focus && <PaperWithSpans p={p} c={focus} onClear={() => setFocus(null)} />}
          {!focus && <pre>{p.text}</pre>}
        </section>
      )}

      <section className="rv-stamp">
        <h3>How this was scored</h3>
        <dl>
          {Object.entries(p.stamp).map(([k, v]) => (
            <div key={k}><dt>{k.replace(/_/g, " ")}</dt><dd>{v == null ? "—" : String(v)}</dd></div>
          ))}
        </dl>
        <h3>What happened to it</h3>
        <ol className="rv-trail">
          {d.transitions.map((t, i) => (
            <li key={i}>
              {t.from_state ?? "—"} → <b>{t.to_state}</b>{" "}
              <span className={t.actor_type === "teacher" ? "rv-teacher" : "rv-machine"}>
                {t.actor_type}
              </span>
              {t.actor_id && <small> {t.actor_id}</small>}
            </li>
          ))}
        </ol>
      </section>
    </>
  );
}

function CriterionRow({ c, ev, busy, onOverride, setPapers, setTitle, onSetOverride,
                       focused, onFocus }: {
  c: Criterion; ev: ScoreEvent | null; busy: boolean;
  focused: boolean; onFocus: () => void;
  setPapers: SetPaper[] | null; setTitle: string;
  onSetOverride: (node_id: string, level: number | null, status: string, reason: string,
                  artifact_ids: string[]) => void;
  onOverride: (ev: ScoreEvent, level: number | null, status: string, reason: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [applyToSet, setApplyToSet] = useState(false);
  // The level the RECORD currently holds, which is the override's if a teacher made one — not the
  // packet's copy. The packet is what was in front of the teacher when they decided; showing it
  // after an override would show someone their own change had not happened.
  const level = ev ? ev.level : c.level;
  const status = ev ? ev.status : c.status;
  const overridden = !!ev && ev.scorer_type !== "ai";

  return (
    <div className={`rv-crit ${c.needs_human ? "rv-needs" : ""}`}>
      <div className="rv-crit-head">
        <div>
          <b>{c.criterion_label ?? c.node_id}</b>
          {c.standard_code && <small> {c.standard_code}</small>}
        </div>
        <div className="rv-level">
          {status === "scored" && level != null
            ? <span className="rv-num">{level}<i>/{c.scale_categories?.slice(-1)[0] ?? "—"}</i></span>
            : <span className="rv-nonum">{NO_NUMBER[status] ?? status}</span>}
          {overridden && <span className="rv-badge">changed by you</span>}
        </div>
      </div>

      {c.reason && <p className="rv-reason">{ev?.reason ?? c.reason}</p>}

      {c.evidence.length > 0 && (
        <>
          <ul className="rv-ev">
            {c.evidence.map((s, i) => <li key={i}>“{s}”</li>)}
          </ul>
          {(c.spans?.length ?? 0) > 0 && (
            <button className={"rv-showin" + (focused ? " on" : "")} onClick={onFocus}>
              {focused ? "Stop showing these in the paper" : "Show these in the paper"}
            </button>
          )}
        </>
      )}
      {c.evidence_dropped > 0 && (
        <small className="rv-mut">
          {c.evidence_dropped} proposed span{c.evidence_dropped === 1 ? "" : "s"} did not appear in
          this paper and {c.evidence_dropped === 1 ? "was" : "were"} discarded before scoring.
        </small>
      )}

      {c.prior.length > 0 && (
        <div className="rv-prior">
          <small>Earlier on this same criterion:</small>
          {c.prior.map((p, i) => (
            <span key={i} className={p.same_rater ? "" : "rv-otherrater"}>
              {p.task_id}: {p.level}
              {!p.same_rater && <i> different scorer</i>}
            </span>
          ))}
        </div>
      )}

      {ev && (
        <div className="rv-override">
          {!open && <button disabled={busy} onClick={() => setOpen(true)}>Change this</button>}
          {open && (
            <div className="rv-override-form">
              {(c.scale_categories ?? []).map((n) => (
                <button key={n} disabled={busy}
                        onClick={() => { onOverride(ev, n, "scored", reason); setOpen(false); }}>
                  {n}
                </button>
              ))}
              <button disabled={busy}
                      onClick={() => { onOverride(ev, null, "abstained", reason); setOpen(false); }}>
                Can't tell
              </button>
              <input value={reason} placeholder="why (optional)"
                     onChange={(e) => setReason(e.target.value)} />
              <button disabled={busy} onClick={() => setOpen(false)}>Cancel</button>
              <small>
                Your change is added to the record beside the original, which stays. Nothing is
                overwritten.
              </small>
            </div>
          )}
          {/* A judgment about the class, made once. Only offered inside a set — outside one there
              is no set to apply it to, and a button that silently meant "every paper you can see"
              would be a different decision from the one it looks like. */}
          {!open && !applyToSet && setPapers && setPapers.length > 1 && (
            <button className="rv-setbtn" disabled={busy} onClick={() => setApplyToSet(true)}>
              Change for all {setPapers.length} in this set
            </button>
          )}
          {applyToSet && setPapers && (
            <SetOverridePanel c={c} papers={setPapers} title={setTitle} busy={busy}
                              onApply={(lvl, st, reason_) => {
                                onSetOverride(c.node_id, lvl, st, reason_,
                                              setPapers.map((x) => x.artifact_id));
                                setApplyToSet(false);
                              }}
                              onCancel={() => setApplyToSet(false)} />
          )}
        </div>
      )}
    </div>
  );
}

// The confirmation, and most of the design is in what it refuses to skip.
//
// It NAMES every paper the decision will touch, because "all 28" is a number and a teacher who
// approves a number has not seen the set. It REQUIRES a reason, because this is the only record
// of what the decision was about and it is read by people who were not in the room. And it says
// plainly that this is one judgment rather than N, because that is the fact the record keeps and
// the interface is where somebody would otherwise form the opposite impression.
// The paper with one criterion's verified evidence marked in it.
//
// The offsets come from the verifier and are into the NORMALISED text, so that is what is
// rendered — and it is labelled, because it is not character-for-character what the student
// typed. Showing the raw text with these offsets would misplace every highlight on any paper
// whose typography was folded, which is most papers out of Google Docs; searching the raw text
// for the span instead would re-implement the match in a second place with different rules.
//
// Overlaps are merged rather than nested. Two spans that overlap are one piece of evidence as
// far as a reader is concerned, and nested <mark>s render as a darker patch that reads like a
// third, stronger thing.
function PaperWithSpans({ p, c, onClear }: {
  p: Packet; c: Criterion; onClear: () => void;
}) {
  const body = p.text_normalized;
  if (!body) {
    // Scored before the offsets were kept. Say so rather than silently showing an unhighlighted
    // paper, which would read as "this criterion has no evidence in the text".
    return (
      <>
        <p className="rv-mut">
          This paper was scored before span positions were recorded, so its evidence can only be
          listed, not shown in place.
        </p>
        <pre>{p.text}</pre>
      </>
    );
  }

  const marks = [...(c.spans ?? [])]
    .filter((s) => s.at >= 0 && s.len > 0 && s.at + s.len <= body.length)
    .sort((a, b) => a.at - b.at)
    .reduce<{ at: number; end: number }[]>((acc, s) => {
      const last = acc[acc.length - 1];
      if (last && s.at <= last.end) last.end = Math.max(last.end, s.at + s.len);
      else acc.push({ at: s.at, end: s.at + s.len });
      return acc;
    }, []);

  const parts: JSX.Element[] = [];
  let cursor = 0;
  marks.forEach((m, i) => {
    if (m.at > cursor) parts.push(<span key={`t${i}`}>{body.slice(cursor, m.at)}</span>);
    parts.push(<mark key={`m${i}`}>{body.slice(m.at, m.end)}</mark>);
    cursor = m.end;
  });
  if (cursor < body.length) parts.push(<span key="tail">{body.slice(cursor)}</span>);

  return (
    <>
      <div className="rv-spanbar">
        <b>{c.criterion_label ?? c.node_id}</b>
        <span className="rv-mut">
          {marks.length} passage{marks.length === 1 ? "" : "s"} this criterion was judged on
        </span>
        <button onClick={onClear}>Show the paper as written</button>
      </div>
      <pre className="rv-marked">{parts}</pre>
      <small className="rv-mut">
        Shown with typography normalised{p.normalization_version
          ? ` (${p.normalization_version})` : ""} — quotation marks, dashes and spacing folded.
        That is the text the scoring read, and the only text these positions are exact in.
      </small>
    </>
  );
}

function SetOverridePanel({ c, papers, title, busy, onApply, onCancel }: {
  c: Criterion; papers: SetPaper[]; title: string; busy: boolean;
  onApply: (level: number | null, status: string, reason: string) => void;
  onCancel: () => void;
}) {
  const [why, setWhy] = useState("");
  const ready = why.trim().length > 0;

  return (
    <div className="rv-setpanel">
      <b>{c.criterion_label ?? c.node_id} — for the whole set</b>
      {title && <div className="rv-mut">{title}</div>}
      <p>
        This is recorded as <b>one judgment</b> applied to {papers.length} papers, not as{" "}
        {papers.length} separate ratings. That distinction is kept in the record: the same
        decision counted {papers.length} times would look like {papers.length} raters agreeing.
      </p>
      <details>
        <summary>{papers.length} papers this will change</summary>
        <ul className="rv-setlist">
          {papers.map((p) => <li key={p.artifact_id}>{p.name}</li>)}
        </ul>
      </details>
      <input value={why} placeholder="why this applies to the whole set (required)"
             onChange={(e) => setWhy(e.target.value)} />
      <div className="rv-setacts">
        {(c.scale_categories ?? []).map((n) => (
          <button key={n} disabled={busy || !ready}
                  onClick={() => onApply(n, "scored", why)}>{n}</button>
        ))}
        <button disabled={busy || !ready}
                onClick={() => onApply(null, "abstained", why)}>Can't tell</button>
        <button disabled={busy} onClick={onCancel}>Cancel</button>
      </div>
      {!ready && <small className="rv-mut">Say why before applying it.</small>}
      <small className="rv-mut">
        Papers with no standing score on this criterion are left alone, and named afterwards.
      </small>
    </div>
  );
}


// The message a student will read. Editable, because a teacher edits it every time — and the edit
// APPENDS: a new composition row pointing at the one it replaces, so the machine's draft survives
// beside the version that went out.
//
// The safety checks re-run on an edit and are shown, but they do not block. The gate exists to stop
// a machine's draft reaching a person unexamined, and by the time somebody is typing here it has
// already done that. A teacher who has read the paper and written their own sentence is the
// authority; holding it would be the tool overruling them.
function FeedbackPanel({ fb, busy, onSave }: {
  fb: NonNullable<Packet["feedback"]>; busy: boolean; onSave: (m: string) => void;
}) {
  const [draft, setDraft] = useState(fb.message);
  const [editing, setEditing] = useState(false);
  const dirty = draft.trim() !== fb.message.trim();

  return (
    <section className="rv-feedback">
      <h3>
        {fb.edited_by ? "Your message to the student" : "Drafted for the student"}
        {fb.edited_by && <span className="rv-badge">edited by you</span>}
      </h3>

      {editing ? (
        <>
          <textarea className="rv-edit" value={draft} rows={12}
                    onChange={(e) => setDraft(e.target.value)} />
          <div className="rv-editbar">
            <button className="rv-primary" disabled={busy || !dirty}
                    onClick={() => { onSave(draft); setEditing(false); }}>
              Save the message
            </button>
            <button disabled={busy}
                    onClick={() => { setDraft(fb.message); setEditing(false); }}>
              Cancel
            </button>
            <small>
              Saving keeps the original beside your version. Nothing is overwritten.
            </small>
          </div>
        </>
      ) : (
        <>
          <pre>{fb.message}</pre>
          <div className="rv-editbar">
            <button disabled={busy} onClick={() => setEditing(true)}>Edit the message</button>
            <small>
              Composer {fb.composer_version} ·{" "}
              {fb.quotations.length} quotation{fb.quotations.length === 1 ? "" : "s"}, each
              verified against this student's own writing
            </small>
          </div>
        </>
      )}

      {fb.holds_are_advisory && fb.holds.length > 0 && (
        <div className="rv-note">
          <b>Worth a look, not a block.</b>
          <ul>{fb.holds.map((h, i) => <li key={i}><code>{h.code}</code> {h.detail}</li>)}</ul>
          <small>Your words, your call — this is recorded, not enforced.</small>
        </div>
      )}

      {fb.machine_draft && fb.machine_draft !== fb.message && (
        <details className="rv-original">
          <summary>What the model drafted</summary>
          <pre>{fb.machine_draft}</pre>
        </details>
      )}
    </section>
  );
}


// What happened after Release. Read only: the file channel writes where the folder is, and the API
// cannot reach it — the batch job sends until Drive makes the channel reachable from here.
//
// Three things this has to keep straight, and each of them is a different sentence on screen:
//   * what the student is HOLDING, which is the last successful send
//   * what happened LAST, which may be a failure after a success — and does not mean they have
//     nothing
//   * whether the message has been edited SINCE, in which case they are holding an older one
function HandBack({ delivery, currentComposition }: {
  delivery: Delivery; currentComposition: string;
}) {
  const { delivered, last_attempt: last, attempts } = delivery;
  const stale = !!delivered && delivered.composition_id !== currentComposition;
  const failingNow = last?.status === "failed";

  return (
    <section className="rv-criteria">
      <h3>Handed back</h3>

      {delivered ? (
        <p className={stale ? "rv-nonum" : ""}>
          {stale
            ? "The student is holding an EARLIER version of this message — it was edited after it went out."
            : "Delivered."}{" "}
          <span className="rv-mut">
            {new Date(delivered.delivered_at!).toLocaleString()} · {delivered.channel}
          </span>
        </p>
      ) : (
        <p className="rv-nonum">Nothing has reached this student yet.</p>
      )}

      {failingNow && (
        <div className="rv-holds">
          <b>The last attempt did not go.</b>
          <p>{last?.detail}</p>
          <small>
            {delivered
              ? "They still have the earlier message — this failure did not take anything away."
              : "Nothing has reached them. It will be retried."}
          </small>
        </div>
      )}

      <ol className="rv-trail">
        {attempts.map((a) => (
          <li key={a.delivery_id}>
            <b className={a.status === "sent" ? "rv-teacher" : "rv-machine"}>{a.status}</b>{" "}
            {a.attempted_at && new Date(a.attempted_at).toLocaleTimeString()}
            {a.target_ref && <> → {a.target_ref}</>}
            {a.detail && <> — {a.detail}</>}
            {/* The hash is how "which version did they read" is answerable at all. */}
            {a.message_hash && <small> · {a.message_hash.slice(0, 8)}</small>}
          </li>
        ))}
      </ol>
    </section>
  );
}
