import type { DiagnosticSchool, Peer, SlotPayload, Spotlight, WorkspaceData } from "../types";
import { fmt1, fmtNum, fmtPct, fmtUSD, nearDup } from "../format";
import { PeerChart } from "./PeerChart";
import { StepsInfo } from "./StepsInfo";

interface Props {
  s: DiagnosticSchool | null;
  peers: Peer[] | null;
  ws: WorkspaceData | null;
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

// One workspace chart. The shape NEVER varies (that's the design's fixed-shape rule —
// flipping metric/year/subgroup stays visually comparable); only the labels and the
// honesty captions (thin band, fixed cohort, missing-is-UNKNOWN) change.
function Slot({ p }: { p: SlotPayload }) {
  if (p.error) {
    // A validation miss (e.g. an HS-only metric after switching to a Middle school) is
    // rendered, not hidden — the spec is sticky across schools, so this is a real state.
    return (
      <div className="ind">
        <div className="muted" style={{ fontSize: "12px" }}>{p.error}</div>
      </div>
    );
  }
  const group = p.student_group_id && p.student_group_id !== "all" ? p.student_group_label || p.student_group_id : null;
  return (
    <div className="ind">
      <div className="ind-hd">
        <span className="ind-name">
          {p.display_name}
          {p.target_year ? <span className="d"> ({p.target_year})</span> : null}
          {group ? <span className="d"> · {group}</span> : null}
        </span>
        <span className="ind-val">{p.target_value == null ? "—" : fmt1(p.target_value) + "%"}</span>
      </div>
      <PeerChart
        dist={p.peer_distribution ?? null}
        value={p.target_value ?? null}
        direction={p.direction === "higher_better" ? "higher_better" : "lower_better"}
      />
      {/* A null value is UNKNOWN (often privacy-suppressed), never 0 — say so. */}
      {p.target_value == null && p.value_status ? (
        <div className="ind-cap">Value unavailable — may be privacy-suppressed for small enrollment (unknown, not zero).</div>
      ) : null}
      {p.band_status ? <div className="ind-cap">{p.band_status}</div> : null}
      {p.cohort_note ? <div className="ind-cap">{p.cohort_note}</div> : null}
    </div>
  );
}

// Claude-pinned plan items. Rendered entirely from the stored plan rows the server
// resolved — the only Claude-authored text on screen is the attributed `reason` line.
function SpotlightStrip({ spot }: { spot: Spotlight }) {
  if (!spot.items.length) return null;
  return (
    <div className="spot">
      <div className="spot-hd">Spotlight — pinned by Claude for what the charts show</div>
      {spot.items.map((it, i) => (
        <div className="spot-item" key={i}>
          <div className="spot-reason">→ {it.reason}</div>
          <div>
            <strong>
              {it.goal_type || "goal"} {it.goal_number || ""}
            </strong>{" "}
            — {(it.statement || "").slice(0, 140)}
            {(it.statement || "").length > 140 ? "…" : ""}
          </div>
          {it.actions.map((a, ai) => (
            <div className="act" key={ai}>
              • {a.strategy_text}
              <div className="meta">
                {a.budgeted_amount != null ? fmtUSD(a.budgeted_amount) : "no funding listed"}
                {a.funding_source_raw ? " · " + a.funding_source_raw : ""}
                {a.provenance && a.provenance.page != null ? " · p" + a.provenance.page : ""}
              </div>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

export function Diagnostic({ s, peers, ws }: Props) {
  if (!s) return <div className="muted">Select a school.</div>;
  const plan = ws ? (ws.plan ?? null) : null;

  return (
    <>
      <div className="card">
        <h3 className="h3-row">
          <span>School Indicators</span>
          <StepsInfo active="Scan indicators" />
        </h3>
        {ws === null ? (
          <div className="muted dots">loading indicators</div>
        ) : (
          <div className="inds">
            {ws.slots.map((p, i) => (
              <Slot p={p} key={i} />
            ))}
          </div>
        )}
      </div>

      <div className="card">
        <h3 className="h3-row">
          <span>Subgroup slice</span>
          <span className="info" tabIndex={0}>
            i
            <span className="tip">
              Three boxes, each the same fixed chart cut to ONE student group — the school&rsquo;s
              subgroup value against the same subgroup across its peer band. Fill several to
              compare subgroups (or years) side by side. Suppressed values are unknown, never
              zero; a thin band is captioned, not hidden.
            </span>
          </span>
        </h3>
        {ws === null ? (
          <div className="muted dots">loading</div>
        ) : (
          <div className="inds">
            {[0, 1, 2].map((i) => {
              const p = ws.subgroup_slots?.[i] ?? null;
              return p ? (
                <Slot p={p} key={i} />
              ) : (
                <div className="ind ind-empty" key={i}>
                  <div className="muted">
                    Add content to slice an indicator by a student group, e.g.{" "}
                    <i>&ldquo;show chronic absenteeism for English learners&rdquo;</i>.
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="card">
        <h3 className="h3-row">
          <span>Plan{plan && plan.plan_year ? " · " + plan.plan_year : ""}</span>
          <StepsInfo active="Plan for implementation" />
        </h3>
        {ws === null ? (
          <div className="muted dots">loading plan</div>
        ) : !plan || !plan.has_plan ? (
          <div className="muted">
            No SPSA on file for this school yet — its planning is unknown (not zero). The
            indicators and peers are unaffected.
          </div>
        ) : plan.goals && plan.goals.length ? (
          <>
            {ws.spotlight ? <SpotlightStrip spot={ws.spotlight} /> : null}
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
                        {a.provenance && a.provenance.page != null ? " · p" + a.provenance.page : ""}
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
                          : fmt1(p.chronic_absenteeism_rate) + "%"}
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
