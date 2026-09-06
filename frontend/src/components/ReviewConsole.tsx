import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api";

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
  };
};

type QueueRow = {
  artifact_id: string;
  state: string;
  state_reason_code: string | null;
  student_id: string | null;
  task_id: string | null;
  iteration: string | null;
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

type Transition = {
  from_state: string | null;
  to_state: string;
  actor_type: string;
  actor_id: string | null;
  created_at: string | null;
};

type Detail = {
  artifact_id: string;
  state: string;
  state_reason_code: string | null;
  packet: Packet;
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

function shortId(id: string | null): string {
  if (!id) return "—";
  return id.replace(/^demo-(art-|stu-)?/, "");
}

export function ReviewConsole() {
  const [queue, setQueue] = useState<QueueRow[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [available, setAvailable] = useState<boolean | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadQueue = useCallback(async () => {
    try {
      const r = await api.get<{ available: boolean; queue: QueueRow[]; counts: Record<string, number> }>(
        "/review/queue");
      setAvailable(r.available);
      setQueue(r.queue);
      setCounts(r.counts);
      if (r.queue.length && !selected) setSelected(r.queue[0].artifact_id);
    } catch (e) {
      setAvailable(false);
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }, [selected]);

  useEffect(() => { void loadQueue(); }, [loadQueue]);

  useEffect(() => {
    if (!selected) { setDetail(null); return; }
    let live = true;
    setError(null);
    api.get<Detail>(`/review/artifact/${encodeURIComponent(selected)}`)
      .then((d) => { if (live) setDetail(d); })
      .catch((e) => { if (live) { setDetail(null); setError(e instanceof ApiError ? e.message : String(e)); } });
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

  return (
    <div className="rv">
      <aside className="rv-queue">
        <div className="rv-counts">
          {Object.entries(counts).map(([state, n]) => (
            <span key={state} className={`rv-chip rv-${state}`}>{n} {STATE_LABEL[state] ?? state}</span>
          ))}
        </div>
        <ul>
          {queue.map((r) => (
            <li key={r.artifact_id}
                className={r.artifact_id === selected ? "rv-sel" : ""}
                onClick={() => setSelected(r.artifact_id)}>
              <b>{shortId(r.student_id)}</b>
              <span className={`rv-state rv-${r.state}`}>{STATE_LABEL[r.state] ?? r.state}</span>
              <small>
                {r.criteria ?? 0} criteria
                {(r.needs_human ?? 0) > 0 && <em> · {r.needs_human} need you</em>}
                {(r.holds ?? 0) > 0 && <em> · {r.holds} held</em>}
              </small>
            </li>
          ))}
        </ul>
        {!queue.length && <p className="rv-mut">Nothing waiting.</p>}
      </aside>

      <section className="rv-paper">
        {error && <div className="rv-err">{error}</div>}
        {!detail && <p className="rv-mut">Select a paper.</p>}
        {detail && <Paper d={detail} busy={busy} onMove={move} onOverride={override} />}
      </section>
    </div>
  );
}

function Paper({ d, busy, onMove, onOverride }: {
  d: Detail; busy: boolean;
  onMove: (s: string) => void;
  onOverride: (ev: ScoreEvent, level: number | null, status: string, reason: string) => void;
}) {
  const p = d.packet;
  const holds = p.feedback?.holds ?? [];
  const current = new Map(d.events.filter((e) => e.current).map((e) => [e.node_id, e]));

  return (
    <>
      <header className="rv-head">
        <div>
          <h2>{shortId(p.student_id)}</h2>
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

      {p.feedback?.message && (
        <section className="rv-feedback">
          <h3>Drafted for the student</h3>
          <pre>{p.feedback.message}</pre>
          <small>
            Composer {p.feedback.composer_version} ·{" "}
            {p.feedback.quotations.length} quotation{p.feedback.quotations.length === 1 ? "" : "s"},
            each verified against this student's own writing
          </small>
        </section>
      )}

      <section className="rv-criteria">
        <h3>Scores</h3>
        {p.criteria.map((c) => (
          <CriterionRow key={c.node_id} c={c} ev={current.get(c.node_id) ?? null}
                        busy={busy} onOverride={onOverride} />
        ))}
      </section>

      {p.text && (
        <section className="rv-text">
          <h3>What they wrote</h3>
          <pre>{p.text}</pre>
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

function CriterionRow({ c, ev, busy, onOverride }: {
  c: Criterion; ev: ScoreEvent | null; busy: boolean;
  onOverride: (ev: ScoreEvent, level: number | null, status: string, reason: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
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
        <ul className="rv-ev">
          {c.evidence.map((s, i) => <li key={i}>“{s}”</li>)}
        </ul>
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
        </div>
      )}
    </div>
  );
}
