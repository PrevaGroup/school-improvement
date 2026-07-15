import type { DiagnosticSchool, Peer, SchoolDetail } from "../types";
import { fmt1, fmtNum, fmtPct, fmtUSD, nearDup } from "../format";
import { PeerChart } from "./PeerChart";
import { StepsInfo } from "./StepsInfo";

interface Props {
  s: DiagnosticSchool | null;
  peers: Peer[] | null;
  detail: SchoolDetail | null;
}

// `plan_missing` is the one that matters: "not extracted yet" is UNKNOWN, not "has no plan".
// Saying a real school funds no attendance response when its SPSA merely hasn't been loaded is
// false and defamatory. Keep those two cases worded distinctly.
function bannerText(s: DiagnosticSchool): string | undefined {
  const perf = s.peer_performance_percentile;
  const worseThan = perf == null ? null : Math.round(100 - perf);
  const byAlignment: Record<string, string> = {
    unmet_need: `Unmet need — worse than ${worseThan}% of similar schools on chronic absenteeism, with little or no funded attendance response.`,
    no_response: `Thin response — the plan funds little or no attendance action.`,
    responsive: `Responsive — a real need met with funded attendance strategies.`,
    ok: `On track relative to peers.`,
    plan_missing:
      worseThan == null
        ? `No attendance plan extracted for this school yet — showing metrics and peers.`
        : `Worse than ${worseThan}% of similar schools on chronic absenteeism — attendance plan not yet extracted, so the response isn't assessed.`,
    unknown: `Not enough data to assess.`,
  };
  return byAlignment[s.alignment];
}

export function Diagnostic({ s, peers, detail }: Props) {
  if (!s) return <div className="muted">Select a school.</div>;
  const inds = detail ? detail.indicators : null;
  const plan = detail ? detail.plan : null;

  return (
    <>
      <div className="card">
        <h3 className="h3-row">
          <span>Indicators</span>
          <StepsInfo active="Scan indicators" />
        </h3>
        {inds === null ? (
          <div className="muted dots">loading indicators</div>
        ) : (
          <div className="inds">
            {inds.map((ind, i) => (
              <div className="ind" key={i}>
                <div className="ind-hd">
                  <span className="ind-name">
                    {ind.display_name}
                    {ind.target_year ? <span className="d"> ({ind.target_year})</span> : null}
                  </span>
                  <span className="ind-val">
                    {ind.target_value == null ? "—" : fmt1(ind.target_value) + "%"}
                  </span>
                </div>
                <PeerChart
                  dist={ind.peer_distribution}
                  value={ind.target_value}
                  direction={ind.direction}
                />
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="card">
        <h3 className="h3-row">
          <span>Plan{plan && plan.plan_year ? " · " + plan.plan_year : ""}</span>
          <StepsInfo active="Plan for implementation" />
        </h3>
        {plan === null ? (
          <div className="muted dots">loading plan</div>
        ) : !plan.has_plan ? (
          <div className="muted">
            No SPSA on file for this school yet — its planning is unknown (not zero). The
            indicators and peers are unaffected.
          </div>
        ) : plan.goals && plan.goals.length ? (
          <>
            <div className="plan-sum">
              {plan.goals.length} goals ·{" "}
              {fmtUSD(
                plan.goals.reduce(
                  (t, g) => t + (g.actions || []).reduce((sum, a) => sum + (a.budgeted_amount || 0), 0),
                  0,
                ),
              )}{" "}
              funded · click a goal for detail, or ask Claude →
            </div>
            {plan.goals.map((g, gi) => {
              const acts = g.actions || [];
              const bud = acts.reduce((sum, a) => sum + (a.budgeted_amount || 0), 0);
              const st = g.statement || "";
              return (
                <details className="goal" key={gi}>
                  <summary>
                    <strong>
                      {g.goal_type || "goal"} {g.goal_number || ""}
                    </strong>{" "}
                    — {st.slice(0, 100)}
                    {st.length > 100 ? "…" : ""}
                    <span className="gmeta">
                      {acts.length} {acts.length === 1 ? "action" : "actions"}
                      {bud > 0 ? " · " + fmtUSD(bud) : ""}
                    </span>
                  </summary>
                  {acts.map((a, ai) => (
                    <div className="act" key={ai}>
                      • {a.strategy_text}
                      <div className="meta">
                        {a.budgeted_amount != null ? fmtUSD(a.budgeted_amount) : "no funding listed"}
                        {a.funding_source_raw ? " · " + a.funding_source_raw : ""}
                        {a.provenance ? " · p" + a.provenance.page : ""}
                      </div>
                      {a.provenance &&
                      a.provenance.quote &&
                      !nearDup(a.strategy_text, a.provenance.quote) ? (
                        <div className="quote">&ldquo;{a.provenance.quote}&rdquo;</div>
                      ) : null}
                    </div>
                  ))}
                </details>
              );
            })}
          </>
        ) : (
          <div className="muted">The SPSA is on file but has no extracted goals.</div>
        )}
      </div>

      <div className="card">
        <h3 className="h3-row">
          <span>Schools like this one</span>
          <span className="info" tabIndex={0}>
            i
            <span className="tip">
              Peers are the statewide schools most similar to this one on <b>inputs</b> —
              enrollment, econ-disadvantaged %, EL %, students-with-disabilities %, and locale —
              using Mahalanobis (covariance-adjusted) distance, computed within the same
              instructional level. Outcomes are never used to match, so &ldquo;similar&rdquo;
              means similar <b>students</b>, not similar results. The nearest ~50 form the
              comparison band.
            </span>
          </span>
        </h3>
        {peers === null ? (
          <div className="muted dots">loading peers</div>
        ) : peers.length ? (
          <>
            <div className="tbl-wrap">
              <table className="tbl">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>School</th>
                    <th className="r">Enroll</th>
                    <th className="r">Econ-dis</th>
                    <th className="r">EL</th>
                    <th className="r">SWD</th>
                    <th>Locale</th>
                    <th className="r">Chronic abs</th>
                  </tr>
                </thead>
                <tbody>
                  {peers.map((p, i) => (
                    <tr key={i}>
                      <td>{p.rank}</td>
                      <td>
                        {p.school_name}
                        {p.has_plan ? (
                          <span className="sip-dot" title="SPSA on file">
                            ●
                          </span>
                        ) : null}
                        <div className="d">{p.district_name}</div>
                      </td>
                      <td className="r">{fmtNum(p.enroll_total)}</td>
                      <td className="r">{fmtPct(p.pct_sed)}</td>
                      <td className="r">{fmtPct(p.pct_el)}</td>
                      <td className="r">{fmtPct(p.pct_swd)}</td>
                      <td>{p.locale ?? "—"}</td>
                      <td className="r">
                        {p.chronic_absenteeism_rate == null
                          ? "—"
                          : p.chronic_absenteeism_rate + "%"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="muted" style={{ fontSize: "11px", marginTop: "6px" }}>
              Ranked by demographic similarity (enrollment · econ-disadv · EL · SWD · locale).
              Chronic abs = each peer&rsquo;s latest chronic-absenteeism rate.{" "}
              <span className="sip-dot">●</span> = SPSA on file.
            </div>
          </>
        ) : (
          <div className="muted">No peer set for this school.</div>
        )}
      </div>

      <div className="card takeaway">
        <h3>Takeaway</h3>
        <div className={"banner b-" + s.alignment}>{bannerText(s)}</div>
      </div>
    </>
  );
}
