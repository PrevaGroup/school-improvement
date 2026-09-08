import { useEffect, useState } from "react";
import { api, ApiError } from "../api";

// Where every set stands — the page a teacher opens before they open a paper.
//
// The queue answers "what is waiting for me". It cannot answer "is 5B's op-ed done", because
// that is a property of a SET and the queue has no notion of one. A teacher does not carry
// twenty-eight papers in mind; they carry one assignment and want to know whether it is
// finished. That question had no screen until this one.
//
// WHAT THIS SCREEN REFUSES TO SHOW, on the same terms as the paper view:
//
//  * No average, no completion percentage, no per-class score. Every number is a count of
//    PAPERS in a state. A mean over criterion levels is a number nobody assigned.
//  * No segment disappears at zero. A count that vanishes when it is empty is how a teacher
//    stops noticing that nothing has been handed back — the same argument as the manifest
//    gate showing all five counts including the zeros.
//  * Stuck papers are NAMED, not counted. "Two are stuck" is not something anyone can act on,
//    and both reasons a paper stops before scoring are fixed by opening it.

export type PipelineStage = { key: string; label: string; n: number };

export type AssignmentRow = {
  section_id: string | null;
  task_id: string | null;
  iteration: string | null;
  window_label: string | null;
  section_name: string | null;
  task_name: string | null;
  module_key: string | null;
  ordinal: number | null;
  total: number;
  working: number;
  stuck: number;
  ready: number;
  reviewed: number;
  delivered: number;
  failing: number;
};

export type StuckRow = {
  artifact_id: string;
  state: string;
  state_reason_code: string | null;
  section_id: string | null;
  task_id: string | null;
  section_name: string | null;
  task_name: string | null;
  file_name: string | null;
  display_name: string | null;
};

type Home = {
  available: boolean;
  pipeline: PipelineStage[];
  assignments: AssignmentRow[];
  stuck: StuckRow[];
};

export type Scope = {
  section_id: string | null;
  task_id: string | null;
  iteration: string | null;
  window_label: string | null;
};

// Why each segment is where it is, in the words a teacher would use. A colour alone says a
// segment is different from its neighbour, not what it means.
const STAGE_NOTE: Record<string, string> = {
  working: "Handed in, being scored. Nothing for you to do yet.",
  stuck: "We need something from you before this can be scored — usually whose paper it is.",
  ready: "Scored and waiting on you. This is the only segment that is a request.",
  reviewed: "You decided. The feedback has not gone to the student yet.",
  delivered: "The student has it.",
};

// The two things a paper can be stopped by, said plainly. The reason code is a machine's word.
const STUCK_WHY: Record<string, string> = {
  unbound: "We don't know whose paper this is",
  blocked: "Scored, but the feedback needs your eyes before it goes out",
  not_scorable: "Nothing was handed in to score",
};

function label(a: AssignmentRow): string {
  return a.task_name || a.task_id || "Assignment not declared";
}

function classOf(a: AssignmentRow): string {
  return a.section_name || a.section_id || "Class not declared";
}

// A set is finished when nothing is working, nothing is stuck, and nothing is waiting on a
// person. Delivered-or-not is deliberately NOT part of it: a teacher can decide not to send
// feedback, and that is a finished paper, not an unfinished one.
function outstanding(a: AssignmentRow): number {
  return a.working + a.stuck + a.ready;
}

export function AssignmentHome({ onOpenSet, onOpenPaper }: {
  onOpenSet: (scope: Scope, title: string) => void;
  onOpenPaper: (artifact_id: string) => void;
}) {
  const [home, setHome] = useState<Home | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api.get<Home>("/review/home")
      .then((h) => { if (live) setHome(h); })
      .catch((e) => { if (live) setError(e instanceof ApiError ? e.message : String(e)); });
    return () => { live = false; };
  }, []);

  if (error) return <div className="ah"><div className="rv-err">{error}</div></div>;
  if (!home) return <div className="ah"><p className="rv-mut">Loading…</p></div>;
  if (!home.available) {
    return (
      <div className="ah">
        <p className="rv-mut">
          Nothing has been read yet. Confirm a folder in <b>Folders</b> and the sets will
          appear here.
        </p>
      </div>
    );
  }

  const total = home.pipeline.reduce((n, s) => n + s.n, 0);
  // Group by unit the way the ladder does, so lessons from one module sit together. A set whose
  // task was never declared has no module and lands in its own group rather than vanishing.
  const modules = [...new Set(home.assignments.map((a) => a.module_key ?? ""))];

  return (
    <div className="ah">
      <div className="ah-lede">
        <h2>What is waiting for you</h2>
        <p>
          Work sits with the assignment it came from. Nothing here expires and nothing is
          required — a paper you never send feedback on is finished as far as we are concerned.
        </p>
      </div>

      {total === 0 ? (
        <p className="rv-mut">
          No papers yet. A confirmed folder is what puts them here.
        </p>
      ) : (
        <div className="ah-pipe">
          <div className="ah-bar" role="img"
               aria-label={home.pipeline.map((s) => `${s.n} ${s.label}`).join(", ")}>
            {home.pipeline.map((s) => (
              s.n > 0 ? (
                <span key={s.key} className={`ah-seg ah-${s.key}`}
                      style={{ width: `${(s.n / total * 100).toFixed(2)}%` }}
                      title={`${s.label}: ${s.n}`} />
              ) : null
            ))}
          </div>
          {/* Every stage in the key, including the empty ones — a segment that disappears at
              zero is how "nothing has been handed back" stops being noticeable. */}
          <ul className="ah-key">
            {home.pipeline.map((s) => (
              <li key={s.key} className={s.n === 0 ? "ah-zero" : ""}>
                <i className={`ah-${s.key}`} />
                <b>{s.n}</b> {s.label}
                <small>{STAGE_NOTE[s.key]}</small>
              </li>
            ))}
          </ul>
          <p className="ah-total">{total} papers across your classes.</p>
        </div>
      )}

      <h3 className="ah-head">Missing information</h3>
      {home.stuck.length === 0 ? (
        <p className="rv-mut">
          Nothing is missing. Everything that arrived has a name and an assignment on it.
        </p>
      ) : (
        <ul className="ah-stuck">
          {home.stuck.map((s) => (
            <li key={s.artifact_id}>
              <button className="ah-linkish" onClick={() => onOpenPaper(s.artifact_id)}>
                {s.file_name || s.display_name || s.artifact_id}
              </button>
              <span className="ah-why">{STUCK_WHY[s.state] ?? s.state}</span>
              <small>
                {[s.section_name || s.section_id, s.task_name || s.task_id]
                  .filter(Boolean).join(" · ") || "no class or assignment declared"}
                {s.state_reason_code ? ` · ${s.state_reason_code}` : ""}
              </small>
            </li>
          ))}
        </ul>
      )}

      <h3 className="ah-head">Assignments</h3>
      {home.assignments.length === 0 && (
        <p className="rv-mut">No sets yet.</p>
      )}
      {modules.map((m) => {
        const rows = home.assignments.filter((a) => (a.module_key ?? "") === m);
        return (
          <div className="ah-unit" key={m || "_none"}>
            {m ? <h4>{m}</h4> : rows.length ? <h4 className="ah-undeclared">Not in a unit</h4> : null}
            <ul className="ah-sets">
              {rows.map((a) => {
                const out = outstanding(a);
                const key = [a.section_id, a.task_id, a.iteration, a.window_label].join("|");
                const title = `${classOf(a)} — ${label(a)}`;
                return (
                  <li key={key} className={a.ready ? "ah-needs" : ""}>
                    <div className="ah-set-main">
                      <div className="ah-set-title">
                        <button className="ah-linkish"
                                onClick={() => onOpenSet({
                                  section_id: a.section_id, task_id: a.task_id,
                                  iteration: a.iteration, window_label: a.window_label,
                                }, title)}>
                          {label(a)}
                        </button>
                        {a.iteration && <span className="ah-iter">{a.iteration}</span>}
                        {a.window_label && <span className="ah-win">{a.window_label}</span>}
                      </div>
                      <div className="ah-set-cls">{classOf(a)}</div>
                      <div className="ah-set-state">
                        {/* Counts in the order the work happens, and the ones that are a
                            request to a person are bold. The rest are description. */}
                        {a.ready > 0 && <b>{a.ready} require your review. </b>}
                        {a.stuck > 0 && <b>{a.stuck} missing information. </b>}
                        {a.working > 0 && <span>{a.working} still scoring · </span>}
                        <span>{a.reviewed + a.delivered} of {a.total} reviewed</span>
                        <span> · {a.delivered} of {a.total} with feedback on the doc</span>
                        {a.reviewed > 0 && <span> · <b>{a.reviewed} approved, not handed back</b></span>}
                        {a.failing > 0 && <span> · <b className="ah-bad">{a.failing} did not send</b></span>}
                      </div>
                    </div>
                    <div className="ah-set-act">
                      {out === 0
                        ? <span className="ah-done">Nothing outstanding</span>
                        : <span className="ah-out">{out} outstanding</span>}
                      <button className={a.ready ? "ah-btn ah-primary" : "ah-btn"}
                              onClick={() => onOpenSet({
                                section_id: a.section_id, task_id: a.task_id,
                                iteration: a.iteration, window_label: a.window_label,
                              }, title)}>
                        Review
                      </button>
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
    </div>
  );
}
