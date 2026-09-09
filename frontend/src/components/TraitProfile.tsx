import { useEffect, useState } from "react";
import { api, ApiError } from "../api";

// Which trait this class is weakest on — the page a teacher reads before planning a lesson.
//
// The assignment home answers "is 5B's op-ed done". It cannot answer "what should I teach next",
// because that is a property of the TRAITS and the pipeline bar has no notion of one.
//
// WHAT THIS SCREEN REFUSES TO SHOW, and why the refusals are the design:
//
//  * No per-student number, and no number that spans traits for one student. That figure would
//    rank students, and this page would become a leaderboard with a lesson-planning label on it.
//    `/review/home` keeps the same restraint and says so.
//  * No comparison of raw means across traits. The holistic trait runs 1-6 and the elements run
//    1-3, so a mean of 2.4 is near the bottom on one and near the top on the other. The bar shows
//    each trait's standing WITHIN ITS OWN SCALE, and the distribution sits beside it because the
//    distribution is the honest object.
//  * No level vanishes at zero. Nobody reaching the top of a scale is the finding, and it is
//    invisible if empty levels are dropped — the same argument as the manifest gate.
//  * "Could not judge" is never folded into the middle. A trait where a third of the class
//    abstained is not a trait the class is average at.

export type TraitRow = {
  node_id: string;
  label: string;
  categories: number[];
  levels: Record<string, number>;
  scored: number;
  unjudged: number;
  unjudged_reasons: Record<string, number>;
  mean: number | null;
  position: number | null;
  at_lowest: number;
  at_highest: number;
};

type Payload = {
  available: boolean;
  section_id: string;
  task_id: string;
  iteration: string;
  traits: TraitRow[];
  reason?: string;
};

// The absences a teacher can act on read differently from the ones an engineer can.
const WHY: Record<string, string> = {
  element_not_present: "not in the writing",
  no_spans_proposed: "no evidence found",
  no_verified_evidence: "no evidence confirmed",
  model_abstained: "scorer declined",
  off_scale: "scorer returned an off-scale level",
  not_this_task: "not an attempt at this task",
};

function why(code: string): string {
  return WHY[code] ?? code.replace(/_/g, " ");
}

export function TraitProfile({ sectionId, taskId, iteration, title }: {
  sectionId: string; taskId: string; iteration: string; title?: string;
}) {
  const [data, setData] = useState<Payload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setData(null);
    setError(null);
    api.get<Payload>(`/review/traits?section_id=${encodeURIComponent(sectionId)}`
      + `&task_id=${encodeURIComponent(taskId)}&iteration=${encodeURIComponent(iteration)}`)
      .then((d: Payload) => { if (live) setData(d); })
      .catch((e: ApiError) => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [sectionId, taskId, iteration]);

  if (error) return <p className="muted">Could not read the trait profile: {error}</p>;
  if (!data) return <p className="muted">Reading the trait profile…</p>;
  if (!data.available) {
    return <p className="muted">Not available yet{data.reason ? ` — ${data.reason}` : ""}.</p>;
  }
  if (!data.traits.length) {
    return <p className="muted">Nothing has been scored for this assignment yet.</p>;
  }

  return (
    <section className="trait-profile">
      <h3>{title ?? "How the class did, trait by trait"}</h3>
      <p className="muted small">
        Weakest first. Each bar shows where the class sits within that trait&rsquo;s own scale, so
        traits on different scales can be read side by side. Nothing here is a score for a student.
      </p>

      <ol className="traits">
        {data.traits.map((t) => (
          <li key={t.node_id} className="trait">
            <div className="trait-head">
              <span className="trait-name">{t.label}</span>
              <span className="trait-scale muted small">
                {t.mean === null
                  ? "not judged"
                  : `mean ${t.mean.toFixed(2)} of ${t.categories[0]}–${t.categories[t.categories.length - 1]}`}
              </span>
            </div>

            {t.position !== null && (
              <div className="bar" role="img"
                   aria-label={`${t.label}: ${Math.round(t.position * 100)}% of its own scale`}>
                <div className="bar-fill" style={{ width: `${Math.max(2, t.position * 100)}%` }} />
              </div>
            )}

            <div className="levels">
              {t.categories.map((c) => {
                const n = t.levels[String(c)] ?? 0;
                const end = c === t.categories[0] || c === t.categories[t.categories.length - 1];
                return (
                  <span key={c} className={`level${n === 0 ? " empty" : ""}${end ? " end" : ""}`}>
                    <b>{c}</b>
                    <span>{n}</span>
                  </span>
                );
              })}
            </div>

            {t.unjudged > 0 && (
              <p className="unjudged small">
                {t.unjudged} not judged
                {" — "}
                {Object.entries(t.unjudged_reasons)
                  .sort((a, b) => b[1] - a[1])
                  .map(([code, n]) => `${n} ${why(code)}`)
                  .join(", ")}
              </p>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}
