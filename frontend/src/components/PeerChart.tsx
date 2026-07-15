import type { PeerDistribution } from "../types";
import { fmt1 } from "../format";

interface Props {
  dist: PeerDistribution | null;
  value: number | null;
  direction: "lower_better" | "higher_better";
}

export function PeerChart({ dist, value, direction }: Props) {
  if (!dist || value == null) return <div className="muted">No comparable peer data.</div>;

  // Fixed 0–100% scale: the dot's absolute position then reads the same as you flip schools,
  // so a 90% school looks far worse than a 20% one at a glance (not auto-rescaled per school).
  // Do NOT "improve" this to fit the data range — the comparability across schools IS the point.
  const lo = 0;
  const hi = 100;
  const W = 320;
  const x = (v: number) => ((v - lo) / (hi - lo)) * W;
  const vx = x(value);
  const vAnchor = vx > W - 22 ? "end" : vx < 22 ? "start" : "middle";
  const p25 = dist.p25 ?? 0;
  const p75 = dist.p75 ?? 0;

  return (
    <>
      <svg
        width="100%"
        viewBox={`0 0 ${W} 44`}
        style={{ overflow: "visible", maxWidth: "440px", display: "block", margin: "0 auto" }}
      >
        <line x1="0" y1="22" x2={W} y2="22" stroke="var(--line)" strokeWidth="2" />
        <rect x={x(p25)} y="14" width={Math.max(1, x(p75) - x(p25))} height="16" fill="var(--line)" rx="3">
          <title>
            Middle 50% of the {dist.n} peers (25th–75th percentile): {fmt1(dist.p25)}%–{fmt1(dist.p75)}%.
            Median {fmt1(dist.median)}%.
          </title>
        </rect>
        <line x1={x(dist.median ?? 0)} y1="12" x2={x(dist.median ?? 0)} y2="32" stroke="var(--muted)" strokeWidth="2" />
        <circle cx={x(value)} cy="22" r="5" fill="var(--red)" />
        <text x={vx} y="10" textAnchor={vAnchor} fontSize="11" fill="var(--ink)">{fmt1(value)}</text>
        <text x="0" y="44" fontSize="9" fill="var(--muted)">0%</text>
        <text x={W} y="44" textAnchor="end" fontSize="9" fill="var(--muted)">100%</text>
      </svg>
      <div className="muted" style={{ fontSize: "12px", marginTop: "4px" }}>
        {dist.n} similar schools including this one · median={fmt1(dist.median)}% 25%={fmt1(dist.p25)}%{" "}
        75%={fmt1(dist.p75)}% · red dot = this school ·{" "}
        {direction === "lower_better" ? "lower is better" : "higher is better"}
      </div>
    </>
  );
}
