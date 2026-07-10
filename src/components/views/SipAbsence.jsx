import { useState } from 'react';
import SisToggle from '../SisToggle.jsx';
import { sipAbsencePatterns } from '../../data/mockData.js';

function DayStrip({ days, eventIndex, eventLabel }) {
  return (
    <div className="viz-wrap">
      <div className="day-strip">
        {days.map((d, i) => (
          <div
            key={i}
            className={`day-cell ${d.state} ${d.mark ? 'marked' : ''}`}
            title={d.mark ? `Day ${i + 1} · ${d.mark}` : `Day ${i + 1} · ${d.state}`}
          />
        ))}
        {eventIndex != null && (
          <div
            className="day-event"
            style={{ left: `calc(${(eventIndex + 0.5) / days.length * 100}% - 1px)` }}
          >
            {eventLabel && <span className="day-event-label">{eventLabel}</span>}
          </div>
        )}
      </div>
      <DayLegend />
    </div>
  );
}

function DayLegend() {
  return (
    <div className="day-legend">
      <span><span className="swatch" style={{ background: '#dcfce7' }} /> present</span>
      <span><span className="swatch" style={{ background: '#fca5a5' }} /> absent</span>
      <span><span className="swatch" style={{ background: '#fcd34d' }} /> tardy</span>
      <span style={{ marginLeft: 'auto' }}>30 most-recent school days →</span>
    </div>
  );
}

function PeriodGrid({ periods, periodLabels }) {
  const cols = periodLabels.length;
  return (
    <div className="period-grid" style={{ '--cols': cols }}>
      <div className="ph-row head">
        <span className="lbl"></span>
        {periodLabels.map((p) => (
          <span key={p} className="cell">{p}</span>
        ))}
      </div>
      {periods.map((row) => (
        <div className="ph-row" key={row.day}>
          <span className="lbl">{row.day}</span>
          {row.cells.map((c, i) => {
            const klass = c === 'a' ? 'absent' : c === 't' ? 'tardy' : '';
            return (
              <span key={i} className={`cell ${klass}`}>
                {c === 'a' ? '✕' : c === 't' ? '↺' : '✓'}
              </span>
            );
          })}
        </div>
      ))}
    </div>
  );
}

function DualDayStrips({ a, b }) {
  return (
    <div className="viz-wrap">
      <div style={{ fontSize: 11, color: 'var(--muted)', margin: '0 0 4px' }}>{a.label}</div>
      <div className="day-strip">
        {a.days.map((d, i) => (
          <div key={i} className={`day-cell ${d.state}`} title={`Day ${i + 1}`} />
        ))}
      </div>
      <div style={{ fontSize: 10, color: 'var(--muted)', margin: '2px 0 8px' }}>{a.summary}</div>
      <div style={{ fontSize: 11, color: 'var(--muted)', margin: '0 0 4px' }}>{b.label}</div>
      <div className="day-strip">
        {b.days.map((d, i) => (
          <div key={i} className={`day-cell ${d.state}`} title={`Day ${i + 1}`} />
        ))}
      </div>
      <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 2 }}>{b.summary}</div>
    </div>
  );
}

function CoAbsence({ peers }) {
  return (
    <div className="viz-wrap">
      {peers.map((p) => (
        <div className="coabsence-row" key={p.name}>
          <span className="who">{p.name}</span>
          <div className="day-strip">
            {p.days.map((d, i) => (
              <div key={i} className={`day-cell ${d.state}`} title={`Day ${i + 1}`} />
            ))}
          </div>
        </div>
      ))}
      <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 4 }}>
        Vertical alignment of red cells across rows = shared absence days.
      </div>
    </div>
  );
}

function MonthLine({ months }) {
  const W = 400, H = 110, P = { l: 24, r: 8, t: 8, b: 18 };
  const xs = (i) => P.l + (i * (W - P.l - P.r)) / (months.length - 1);
  const ys = (v) => P.t + (1 - (v - 70) / 30) * (H - P.t - P.b);
  const path = months.map((m, i) => `${i === 0 ? 'M' : 'L'} ${xs(i)} ${ys(m.v)}`).join(' ');
  return (
    <svg className="line-chart" viewBox={`0 0 ${W} ${H}`}>
      {[80, 90, 100].map((v) => (
        <g key={v}>
          <line className="grid" x1={P.l} x2={W - P.r} y1={ys(v)} y2={ys(v)} />
          <text className="axis-label" x={2} y={ys(v) + 3}>{v}%</text>
        </g>
      ))}
      <path d={path} fill="none" stroke="#4f46e5" strokeWidth="2" />
      {months.map((m, i) => (
        <g key={m.m}>
          <circle cx={xs(i)} cy={ys(m.v)} r="2.5" fill="#4f46e5" />
          <text className="axis-label" x={xs(i)} y={H - 4} textAnchor="middle">{m.m}</text>
        </g>
      ))}
    </svg>
  );
}

function Trajectory({ series, weeks, interventionWeek }) {
  const W = 400, H = 130, P = { l: 24, r: 8, t: 16, b: 18 };
  const xs = (i) => P.l + (i * (W - P.l - P.r)) / (weeks - 1);
  const ys = (v) => P.t + (1 - (v - 20) / 80) * (H - P.t - P.b);
  const eventX = xs(interventionWeek);
  return (
    <svg className="line-chart" viewBox={`0 0 ${W} ${H}`} style={{ height: 130 }}>
      {[30, 50, 70, 90].map((v) => (
        <g key={v}>
          <line className="grid" x1={P.l} x2={W - P.r} y1={ys(v)} y2={ys(v)} />
          <text className="axis-label" x={2} y={ys(v) + 3}>{v}%</text>
        </g>
      ))}
      <line className="event-line" x1={eventX} x2={eventX} y1={P.t} y2={H - P.b} />
      <text className="event-label" x={eventX + 4} y={P.t + 8}>AIP starts (wk {interventionWeek + 1})</text>
      {series.map((s) => {
        const d = s.values.map((v, i) => `${i === 0 ? 'M' : 'L'} ${xs(i)} ${ys(v)}`).join(' ');
        return (
          <g key={s.label}>
            <path d={d} fill="none" stroke={s.color} strokeWidth="2" />
          </g>
        );
      })}
      <text className="axis-label" x={P.l} y={H - 4}>wk 1</text>
      <text className="axis-label" x={W - P.r} y={H - 4} textAnchor="end">wk {weeks}</text>
      <g transform={`translate(${P.l + 6}, ${P.t})`}>
        {series.map((s, i) => (
          <g key={s.label} transform={`translate(${i * 180}, 0)`}>
            <rect x="0" y="-9" width="10" height="3" fill={s.color} />
            <text className="axis-label" x="14" y="-6" style={{ fill: 'var(--text)' }}>{s.label}</text>
          </g>
        ))}
      </g>
    </svg>
  );
}

function PatternViz(p) {
  switch (p.viz) {
    case 'days':
      return <DayStrip days={p.days} eventIndex={p.eventIndex} eventLabel={p.eventLabel} />;
    case 'period':
      return <PeriodGrid periods={p.periods} periodLabels={p.periodLabels} />;
    case 'dual_days':
      return <DualDayStrips a={p.seriesA} b={p.seriesB} />;
    case 'coabsence':
      return <CoAbsence peers={p.peers} />;
    case 'season':
      return <MonthLine months={p.months} />;
    case 'trajectory':
      return <Trajectory series={p.series} weeks={p.weeks} interventionWeek={p.interventionWeek} />;
    default:
      return null;
  }
}

export default function SipAbsence() {
  const [useSIS, setUseSIS] = useState(true);

  return (
    <>
      <div className="view-header">
        <div>
          <h2>School Attendance · SIP Absence Patterns</h2>
          <div className="sub">
            Temporal and contextual absence behaviors that aggregate-rate dashboards miss.
            Two students with the same YTD% can be completely different intervention profiles.
          </div>
        </div>
        <SisToggle value={useSIS} onChange={setUseSIS} />
      </div>

      <div className="card">
        <div className="card-title">
          Why look past the YTD% number
          <span className="hint">
            {useSIS ? 'Joined: SIS attendance + gradebook + ODR + bus roster' : 'Daily-rate file only — many patterns invisible'}
          </span>
        </div>
        <div style={{ fontSize: 13, color: 'var(--muted)', lineHeight: 1.55 }}>
          Standard tiering sums absences and triggers on % thresholds. The patterns below all
          look the same in that view, but each calls for a different intervention — from a
          bus-route fix, to test-anxiety support, to wraparound services. A VAE with
          calendar-, period-, and event-aware features separates them in latent space.
        </div>
      </div>

      <div className="grid-2">
        {sipAbsencePatterns.map((p) => (
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
              <b>What aggregate tiering misses · </b>{p.miss}
            </div>
          </div>
        ))}
      </div>
    </>
  );
}
