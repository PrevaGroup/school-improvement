import { useState } from 'react';
import SisToggle from '../SisToggle.jsx';
import { behaviorClusters } from '../../data/mockData.js';

const SEV_COLORS = { 1: '#86efac', 2: '#fbbf24', 3: '#ef4444' };

function IncidentTimeline({ incidents, weeks, eventWeek, eventLabel }) {
  const W = 380, H = 80;
  const P = { l: 22, r: 8, t: 14, b: 18 };
  const xs = (w) => P.l + ((w - 1) / Math.max(weeks - 1, 1)) * (W - P.l - P.r);
  const ys = (sev) => (H - P.b) - (sev / 3) * (H - P.b - P.t);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: H, display: 'block' }}>
      {/* severity guides */}
      {[1, 2, 3].map((s) => (
        <g key={s}>
          <line x1={P.l} x2={W - P.r} y1={ys(s)} y2={ys(s)} stroke="#e2e8f0" strokeDasharray="2 3" />
          <text x={2} y={ys(s) + 3} fontSize="8" fill="#94a3b8">{s === 1 ? 'min' : s === 2 ? 'mod' : 'maj'}</text>
        </g>
      ))}
      {eventWeek != null && (
        <g>
          <line
            x1={xs(eventWeek)} x2={xs(eventWeek)}
            y1={P.t} y2={H - P.b}
            stroke="#4f46e5" strokeWidth="1" strokeDasharray="3 3"
          />
          <text x={xs(eventWeek) + 3} y={P.t + 8} fontSize="9" fill="#4f46e5" fontWeight="600">{eventLabel}</text>
        </g>
      )}
      {incidents.map((inc, i) => {
        const cx = xs(inc.week);
        const cy = ys(inc.severity);
        const isTarget = inc.role === 'target';
        const fill = isTarget ? '#fff' : SEV_COLORS[inc.severity];
        const stroke = isTarget ? '#475569' : SEV_COLORS[inc.severity];
        return (
          <circle
            key={i} cx={cx} cy={cy} r={4.5}
            fill={fill} stroke={stroke} strokeWidth="1.5"
          >
            <title>
              {`Wk ${inc.week} · ${inc.type} · severity ${inc.severity}${inc.role ? ` · ${inc.role}` : ''}`}
            </title>
          </circle>
        );
      })}
      <text x={P.l} y={H - 4} fontSize="9" fill="var(--muted)">wk 1</text>
      <text x={W - P.r} y={H - 4} fontSize="9" fill="var(--muted)" textAnchor="end">wk {weeks}</text>
    </svg>
  );
}

function HorizontalBar({ bars }) {
  const max = Math.max(...bars.map((b) => b.value), 1);
  return (
    <div className="hbar">
      {bars.map((b, i) => (
        <div className="hbar-row" key={i}>
          <span className="hbar-label" title={b.label}>{b.label}</span>
          <div className="hbar-track">
            <div
              className="hbar-fill"
              style={{ width: `${(b.value / max) * 100}%`, background: b.color || 'var(--accent)' }}
            />
          </div>
          <span className="hbar-value">{b.value}</span>
        </div>
      ))}
    </div>
  );
}

function TimeOfDayHist({ hours }) {
  const W = 380, H = 110;
  const P = { l: 6, r: 6, t: 14, b: 24 };
  const max = Math.max(...hours.map((h) => h.n));
  const slot = (W - P.l - P.r) / hours.length;
  const bw = slot - 4;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: H, display: 'block' }}>
      {hours.map((h, i) => {
        const x = P.l + i * slot + 2;
        const bh = (h.n / max) * (H - P.t - P.b);
        return (
          <g key={h.h}>
            <rect x={x} y={H - P.b - bh} width={bw} height={bh} fill="#4f46e5" rx="2" />
            <text x={x + bw / 2} y={H - 8} fontSize="8" fill="var(--muted)" textAnchor="middle">{h.h}</text>
            <text x={x + bw / 2} y={H - P.b - bh - 3} fontSize="9" fill="var(--text)" textAnchor="middle" fontWeight="600">{h.n}</text>
          </g>
        );
      })}
    </svg>
  );
}

function DualTimeline({ students, weeks, interventionWeek, interventionLabel }) {
  return (
    <div>
      {students.map((s) => (
        <div key={s.name} style={{ marginBottom: 6 }}>
          <div style={{ fontSize: 11, color: s.tone === 'good' ? 'var(--good)' : 'var(--bad)', fontWeight: 600, margin: '2px 0' }}>
            {s.name}
          </div>
          <IncidentTimeline
            incidents={s.incidents}
            weeks={weeks}
            eventWeek={interventionWeek}
            eventLabel={interventionLabel}
          />
          <div style={{ fontSize: 10, color: 'var(--muted)' }}>{s.note}</div>
        </div>
      ))}
    </div>
  );
}

function PeerNetwork({ nodes, edges }) {
  const W = 380, H = 170, M = 28;
  const map = Object.fromEntries(nodes.map((n) => [n.id, n]));
  const xs = (n) => M + n.x * (W - 2 * M);
  const ys = (n) => M + n.y * (H - 2 * M);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: H, display: 'block' }}>
      {edges.map((e, i) => {
        const a = map[e.from], b = map[e.to];
        return (
          <line
            key={i}
            x1={xs(a)} y1={ys(a)} x2={xs(b)} y2={ys(b)}
            stroke="#94a3b8" strokeOpacity="0.55" strokeWidth={e.weight * 1.1}
          >
            <title>{`${a.label} ↔ ${b.label} · ${e.weight} shared incidents`}</title>
          </line>
        );
      })}
      {nodes.map((n) => (
        <g key={n.id}>
          <circle
            cx={xs(n)} cy={ys(n)} r={6 + n.size}
            fill="#4f46e5" fillOpacity="0.85" stroke="#fff" strokeWidth="2"
          />
          <text x={xs(n)} y={ys(n) + 3} fontSize="9" fill="#fff" fontWeight="600" textAnchor="middle">{n.label}</text>
        </g>
      ))}
    </svg>
  );
}

function DisparityCompare({ pair }) {
  return (
    <div className="disparity-grid">
      {[pair.a, pair.b].map((s, i) => (
        <div key={i} className={`disparity-card ${s.tone}`}>
          <div className="name">{s.name}</div>
          <div className="latent">{s.latent}</div>
          <div className="meta">
            {s.meta.map((m) => <div key={m}>· {m}</div>)}
          </div>
          <div className="consequence">→ {s.consequence}</div>
        </div>
      ))}
    </div>
  );
}

function IntExtPanel({ pair }) {
  const render = (p) => (
    <div className="intext-panel" key={p.name}>
      <div className="kind">{p.kind}</div>
      <div className="who">{p.name}</div>
      <div className="total">Total {p.unit}: <strong style={{ color: 'var(--text)' }}>{p.total}</strong></div>
      <HorizontalBar bars={p.breakdown.map((b) => ({ label: b.k, value: b.v }))} />
      <div className="profile">{p.profile}</div>
      {p.note && <div className="ext-note">{p.note}</div>}
    </div>
  );
  return (
    <div className="intext-grid">
      {render(pair.ext)}
      {render(pair.int)}
    </div>
  );
}

function PatternViz(p) {
  switch (p.viz) {
    case 'timeline':
      return <IncidentTimeline incidents={p.incidents} weeks={p.weeks} />;
    case 'bar':
      return <HorizontalBar bars={p.bars} />;
    case 'timeOfDay':
      return <TimeOfDayHist hours={p.hours} />;
    case 'dualTimeline':
      return (
        <DualTimeline
          students={p.students}
          weeks={p.weeks}
          interventionWeek={p.interventionWeek}
          interventionLabel={p.interventionLabel}
        />
      );
    case 'peerNetwork':
      return <PeerNetwork nodes={p.nodes} edges={p.edges} />;
    case 'disparity':
      return <DisparityCompare pair={p.pair} />;
    case 'intExt':
      return <IntExtPanel pair={p.pair} />;
    default:
      return null;
  }
}

export default function BehaviorClusters() {
  const [useSIS, setUseSIS] = useState(true);

  return (
    <>
      <div className="view-header">
        <div>
          <h2>Behavior Review · Latent Clusters</h2>
          <div className="sub">
            Behavior patterns that aggregate ODR counts collapse. Each cluster below
            triggers the same Tier-2 alert by raw numbers, but calls for a different intervention.
          </div>
        </div>
        <SisToggle value={useSIS} onChange={setUseSIS} />
      </div>

      <div className="card">
        <div className="card-title">
          What an ODR count hides
          <span className="hint">
            {useSIS
              ? 'Joined: SIS + SWIS (antecedents) + schedule + intervention events'
              : 'Aggregate ODR counts only — most clusters below are invisible'}
          </span>
        </div>
        <div style={{ fontSize: 13, color: 'var(--muted)', lineHeight: 1.55 }}>
          Two students with the same total ODR count can be opposite clinical profiles:
          a low-frequency moderate kid vs. a ramp-to-major kid; an externalizing kid vs. a
          near-invisible internalizing kid; a victim-then-response kid vs. a chronic
          aggressor. The patterns below are what a behavior-aware VAE separates in
          latent space — and what an ODR dashboard erases.
        </div>
      </div>

      <div className="grid-2">
        {behaviorClusters.map((p) => (
          <div className="pattern-card" key={p.id}>
            <h3>{p.name}</h3>
            <p className="blurb">{p.blurb}</p>

            {p.student && (
              <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 6 }}>
                <span className="chip gray">{p.student}</span>
              </div>
            )}

            {PatternViz(p)}

            {p.signal && (
              <div className="signal-line">
                <strong>Signal · </strong>{p.signal}
              </div>
            )}

            <div className="miss">
              <b>What aggregate counts miss · </b>{p.miss}
            </div>
          </div>
        ))}
      </div>
    </>
  );
}
