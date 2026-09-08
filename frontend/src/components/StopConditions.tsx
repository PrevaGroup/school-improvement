import { useEffect, useState } from "react";
import { api, ApiError } from "../api";

// Whether scores may be released to students, and on whose authority.
//
// Five results would mean the system should stop releasing scores while they are true. Each needs
// a threshold agreed IN ADVANCE, because a result without a prior commitment gets explained
// rather than acted on.
//
// WHAT THIS SCREEN REFUSES TO COLLAPSE. There are five states here and four of them are commonly
// read as the fifth:
//
//   holds         measured, within a threshold somebody agreed to. The only real pass.
//   triggered     measured, past it. Stop releasing.
//   uncommitted   measured, and nobody has agreed what the number would mean. NOT a pass —
//                 it cannot stop anything, which is a fact about the process, not the scores.
//   insufficient  there was nothing to measure. NOT a pass.
//   never run     the condition has never been evaluated. NOT a pass, and the one most likely
//                 to be invisible, because an absent row shows nothing at all.
//
// A single green tick over any of the last three would be the most consequential lie this
// interface could tell, so no state shares a colour or a word with another.

type Condition = {
  condition: string;
  verdict: "holds" | "triggered" | "uncommitted" | "insufficient";
  observed: number | null;
  threshold_value: number;
  agreed_by: string | null;
  agreed_on: string | null;
  can_gate: boolean;
  n: number;
  detail: string;
  breakdown: Record<string, unknown> | null;
  created_at: string | null;
  eval_run_id: string;
};

type Payload = {
  available: boolean;
  conditions: Condition[];
  never_run: string[];
  stop_release: boolean;
  history: { condition: string; verdict: string; observed: number | null;
             created_at: string | null }[];
};

// What each condition protects. A verdict with no statement of what it would invalidate is a
// number, and a reader cannot weigh a number they cannot interpret.
const WHAT_IT_PROTECTS: Record<string, string> = {
  cohort_invariance:
    "A paper's score must not depend on whose work was scored alongside it. Nothing shows the " +
    "scorer another student's writing, so movement here means an isolation guarantee is leaking.",
  matched_pairs:
    "Two papers differing only in spelling and grammar must score identically — conventions is " +
    "not on this scale. This is the failure that falls hardest on multilingual writers.",
  severity_uniformity:
    "If the model is harsher on one criterion than another, the class trait profile reports the " +
    "rater rather than the class. This condition specifically disqualifies that reading.",
  abstention_subgroup:
    "If one group of students gets “we could not place this” far more often, they get " +
    "less feedback from the same system, for reasons about the system.",
  teacher_acceptance:
    "If overrides are flat, probes are missed and drafts go out unedited, the human review that " +
    "licenses everything downstream is not happening.",
};

const HUMAN: Record<string, string> = {
  cohort_invariance: "Cohort invariance",
  matched_pairs: "Surface-feature matched pairs",
  severity_uniformity: "Severity uniformity across criteria",
  abstention_subgroup: "Subgroup abstention",
  teacher_acceptance: "Teacher review is informative",
};

const VERDICT_WORD: Record<string, string> = {
  holds: "Holds",
  triggered: "STOP",
  uncommitted: "No agreed threshold",
  insufficient: "Not enough data",
};

function num(v: number | null): string {
  return v == null ? "—" : (Math.round(v * 1000) / 1000).toString();
}

export function StopConditions() {
  const [d, setD] = useState<Payload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api.get<Payload>("/evals/stop-conditions")
      .then((r) => { if (live) setD(r); })
      .catch((e) => { if (live) setError(e instanceof ApiError ? e.message : String(e)); });
    return () => { live = false; };
  }, []);

  if (error) return <div className="sc"><div className="rv-err">{error}</div></div>;
  if (!d) return <div className="sc"><p className="rv-mut">Loading…</p></div>;

  const gating = d.conditions.filter((c) => c.can_gate).length;

  return (
    <div className="sc">
      <div className="sc-lede">
        <h2>May scores be released?</h2>
        <p>
          Five results would mean the system should stop releasing scores to students while they
          are true. Each needs a threshold agreed in advance — a result without a prior
          commitment gets explained rather than acted on.
        </p>
      </div>

      {/* The headline, and it is deliberately not a tick. "Nothing is currently stopping a
          release" is true and weak; "everything checks out" would be false while any condition
          is uncommitted, insufficient or unrun. */}
      <div className={`sc-banner ${d.stop_release ? "sc-stop" : ""}`}>
        {d.stop_release ? (
          <>
            <b>A stop condition is triggered.</b> Scores should not be released to students while
            this is true.
          </>
        ) : (
          <>
            <b>Nothing is currently stopping a release.</b>{" "}
            {gating === 0
              ? "No condition can stop one either — none has an agreed threshold yet, so this " +
                "is a statement about the process rather than about the scores."
              : `${gating} of 5 conditions could stop one; the rest are reporting only.`}
          </>
        )}
      </div>

      <ul className="sc-list">
        {d.conditions.map((c) => (
          <li key={c.condition} className={`sc-${c.verdict}`}>
            <div className="sc-head">
              <b>{HUMAN[c.condition] ?? c.condition}</b>
              <span className={`sc-chip sc-chip-${c.verdict}`}>{VERDICT_WORD[c.verdict]}</span>
            </div>
            <p className="sc-protects">{WHAT_IT_PROTECTS[c.condition]}</p>
            <div className="sc-nums">
              <span>observed <b>{num(c.observed)}</b></span>
              <span>threshold <b>{num(c.threshold_value)}</b></span>
              <span>{c.n} observation{c.n === 1 ? "" : "s"}</span>
              {/* The pre-commitment fact, said outright rather than implied by a colour. */}
              {c.can_gate
                ? <span className="sc-agreed">agreed by {c.agreed_by} on {c.agreed_on}</span>
                : <span className="sc-unagreed">no threshold agreed — cannot stop a release</span>}
            </div>
            <p className="sc-detail">{c.detail}</p>
            {c.breakdown && Object.keys(c.breakdown).length > 0 && (
              <details>
                <summary>The numbers under the number</summary>
                <pre>{JSON.stringify(c.breakdown, null, 1)}</pre>
              </details>
            )}
          </li>
        ))}
      </ul>

      {/* Never run is listed, not omitted. An absent row shows nothing at all, which is the one
          state a reader will mistake for a pass without noticing they did. */}
      {d.never_run.length > 0 && (
        <div className="sc-neverrun">
          <b>{d.never_run.length} condition{d.never_run.length === 1 ? " has" : "s have"} never
            been run.</b>
          <ul>
            {d.never_run.map((c) => (
              <li key={c}>
                <b>{HUMAN[c] ?? c}</b> — {WHAT_IT_PROTECTS[c]}
              </li>
            ))}
          </ul>
          <small>
            Never run is not the same as passing. Until each has been evaluated at least once,
            nothing here is evidence about the scores.
          </small>
        </div>
      )}

      {d.history.length > 0 && (
        <details className="sc-history">
          <summary>{d.history.length} recorded findings</summary>
          <table>
            <tbody>
              {d.history.map((h, i) => (
                <tr key={i}>
                  <td>{h.created_at?.slice(0, 16).replace("T", " ")}</td>
                  <td>{HUMAN[h.condition] ?? h.condition}</td>
                  <td className={`sc-chip-${h.verdict}`}>{VERDICT_WORD[h.verdict] ?? h.verdict}</td>
                  <td>{num(h.observed)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <small>
            The history is what tells a run that has held for three months apart from one nobody
            has executed since June. A single latest verdict cannot.
          </small>
        </details>
      )}
    </div>
  );
}
