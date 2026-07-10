import { useState } from 'react';
import SisToggle from '../SisToggle.jsx';
import { placementRoster, placementEquityFlag } from '../../data/mockData.js';

function deltaChip(d) {
  switch (d) {
    case 'up':   return <span className="chip good">↑ promote</span>;
    case 'down': return <span className="chip bad">↓ adjust</span>;
    case 'same': return <span className="chip gray">= confirm</span>;
    case 'add':  return <span className="chip warn">+ add support</span>;
    default:     return null;
  }
}

export default function PlanCourses() {
  const [useSIS, setUseSIS] = useState(true);
  const [selectedId, setSelectedId] = useState(placementRoster[0].id);
  const selected = placementRoster.find((p) => p.id === selectedId);

  return (
    <>
      <div className="view-header">
        <div>
          <h2>Plan Course Placement</h2>
          <div className="sub">
            AI-recommended math, ELA, and intervention placements with supporting signals
            and a latent-space equity check.
          </div>
        </div>
        <SisToggle value={useSIS} onChange={setUseSIS} />
      </div>

      <div className="card">
        <div className="card-title">
          Placement recommendations
          <span className="hint">
            {useSIS
              ? 'Signals: SIS + assessments + teacher recs'
              : 'Teacher recs only — assessment signals unavailable'}
          </span>
        </div>
        <table>
          <thead>
            <tr>
              <th>Student</th>
              <th>Grade</th>
              <th>Current placement</th>
              <th>AI placement</th>
              <th>Action</th>
              <th>Confidence</th>
            </tr>
          </thead>
          <tbody>
            {placementRoster.map((p) => (
              <tr
                key={p.id}
                className={`selectable ${selectedId === p.id ? 'selected' : ''}`}
                onClick={() => setSelectedId(p.id)}
              >
                <td>{p.student}</td>
                <td>{p.grade}</td>
                <td>{p.current}</td>
                <td><strong>{p.aiPlacement}</strong></td>
                <td>{deltaChip(p.delta)}</td>
                <td style={{ minWidth: 110 }}>
                  <div className="bar" style={{ height: 6 }}>
                    <div style={{ width: `${p.confidence * 100}%`, background: 'var(--accent)', height: '100%' }} />
                  </div>
                  <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 2 }}>{(p.confidence * 100).toFixed(0)}%</div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid-2">
        <div className="card">
          <div className="card-title">
            Supporting signals
            <span className="hint">{selected.student}</span>
          </div>
          <div style={{ marginBottom: 12 }}>
            <span className="chip gray">Current · {selected.current}</span>
            <span style={{ margin: '0 8px', color: 'var(--muted)' }}>→</span>
            <span className="chip good">AI · {selected.aiPlacement}</span>
          </div>
          <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.4, marginBottom: 6 }}>
            Signals that drove the recommendation
          </div>
          <ul style={{ margin: 0, padding: '0 0 0 18px', fontSize: 12, lineHeight: 1.6 }}>
            {selected.signals.map((s) => <li key={s}>{s}</li>)}
          </ul>
          <div style={{ marginTop: 14 }}>
            <button className="btn">Accept recommendation</button>
            <button className="btn secondary" style={{ marginLeft: 8 }}>Override</button>
          </div>
        </div>

        <div className="card">
          <div className="card-title">
            Equity check
            <span className="hint">latent-space twin comparison</span>
          </div>
          <div className="disparity-grid">
            {placementEquityFlag.pair.map((s, i) => (
              <div key={i} className={`disparity-card ${s.tone}`}>
                <div className="name">{s.name}</div>
                <div className="latent">{s.latent}</div>
                <div className="meta">
                  {s.meta.map((m) => <div key={m}>· {m}</div>)}
                </div>
                <div className="consequence">→ {s.placement}</div>
              </div>
            ))}
          </div>
          <div style={{ marginTop: 10, fontSize: 11, color: 'var(--muted)' }}>
            {placementEquityFlag.note}
          </div>
        </div>
      </div>
    </>
  );
}
