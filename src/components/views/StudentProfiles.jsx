import { useState } from 'react';
import SisToggle from '../SisToggle.jsx';
import { studentProfileRoster, studentProfileAiSuggestions } from '../../data/mockData.js';

function completenessColor(v) {
  if (v >= 85) return 'var(--good)';
  if (v >= 70) return 'var(--warn)';
  return 'var(--bad)';
}

export default function StudentProfiles() {
  const [useSIS, setUseSIS] = useState(true);
  const [selectedId, setSelectedId] = useState('S-10487');
  const selected = studentProfileRoster.find((s) => s.id === selectedId);
  const ai = studentProfileAiSuggestions[selectedId];

  return (
    <>
      <div className="view-header">
        <div>
          <h2>Set Up Student Profiles</h2>
          <div className="sub">
            Profile completeness, AI-suggested field fills, and likely-duplicate detection.
          </div>
        </div>
        <SisToggle value={useSIS} onChange={setUseSIS} />
      </div>

      <div className="card">
        <div className="card-title">
          Roster · profile health
          <span className="hint">{useSIS ? 'Cross-checked against SIS' : 'Local file only — duplicates likely undetected'}</span>
        </div>
        <table>
          <thead>
            <tr>
              <th>Student</th>
              <th>Grade / school</th>
              <th>Completeness</th>
              <th>Missing fields</th>
              <th>Duplicate candidates</th>
            </tr>
          </thead>
          <tbody>
            {studentProfileRoster.map((s) => (
              <tr
                key={s.id}
                className={`selectable ${selectedId === s.id ? 'selected' : ''}`}
                onClick={() => setSelectedId(s.id)}
              >
                <td>
                  <div style={{ fontWeight: 600 }}>{s.name}</div>
                  <div style={{ color: 'var(--muted)', fontSize: 11 }}>{s.id}</div>
                </td>
                <td>{s.school} · Gr {s.grade}</td>
                <td style={{ minWidth: 120 }}>
                  <div className="bar" style={{ height: 6 }}>
                    <div style={{ width: `${s.completeness}%`, background: completenessColor(s.completeness), height: '100%' }} />
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>{s.completeness}%</div>
                </td>
                <td style={{ fontSize: 12 }}>
                  {s.missing.length ? s.missing.join(', ') : <span style={{ color: 'var(--muted)' }}>—</span>}
                </td>
                <td>
                  {s.duplicates
                    ? <span className="chip warn">{s.duplicates}</span>
                    : <span style={{ color: 'var(--muted)' }}>0</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid-2">
        <div className="card">
          <div className="card-title">
            AI-suggested field fills
            <span className="hint">{selected.name}</span>
          </div>
          {ai ? (
            <table>
              <thead>
                <tr>
                  <th>Field</th>
                  <th>Suggested value</th>
                  <th>Confidence</th>
                  <th>Source</th>
                </tr>
              </thead>
              <tbody>
                {ai.fillIns.map((f) => (
                  <tr key={f.field}>
                    <td>{f.field}</td>
                    <td><strong>{f.suggested}</strong></td>
                    <td><span className="chip">{(f.confidence * 100).toFixed(0)}%</span></td>
                    <td style={{ color: 'var(--muted)', fontSize: 11 }}>{f.source}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div style={{ color: 'var(--muted)', fontSize: 12 }}>No AI fill-in suggestions for this student.</div>
          )}
          {ai && (
            <div style={{ marginTop: 12 }}>
              <button className="btn">Accept all high-confidence (≥ 85%)</button>
              <button className="btn secondary" style={{ marginLeft: 8 }}>Review individually</button>
            </div>
          )}
        </div>

        <div className="card">
          <div className="card-title">
            Likely-duplicate candidates
            <span className="hint">{selected.name}</span>
          </div>
          {ai && ai.duplicates.length > 0 ? ai.duplicates.map((d) => (
            <div
              key={d.id}
              style={{ padding: 10, border: '1px solid #fef3c7', background: '#fffbeb', borderRadius: 6, marginBottom: 8 }}
            >
              <div style={{ fontWeight: 600 }}>
                {d.name}
                <span style={{ color: 'var(--muted)', fontWeight: 400, marginLeft: 6 }}>· {d.id}</span>
              </div>
              <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
                Similarity {(d.similarity * 100).toFixed(0)}% · {d.reason}
              </div>
              <div style={{ marginTop: 8 }}>
                <button className="btn" style={{ marginRight: 6 }}>Merge</button>
                <button className="btn secondary">Keep separate</button>
              </div>
            </div>
          )) : (
            <div style={{ color: 'var(--muted)', fontSize: 12 }}>None detected.</div>
          )}

          {ai && (
            <>
              <div style={{ marginTop: 14, fontSize: 11, textTransform: 'uppercase', letterSpacing: 0.4, color: 'var(--muted)' }}>
                AI tag suggestions
              </div>
              <div style={{ marginTop: 6 }}>
                {ai.tagSuggestions.map((t) => (
                  <span key={t} className="chip" style={{ marginRight: 4, marginBottom: 4, display: 'inline-block' }}>
                    + {t}
                  </span>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </>
  );
}
