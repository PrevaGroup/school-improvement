import { useState } from 'react';
import SisToggle from '../SisToggle.jsx';
import { enrollmentQueue, enrollmentDetail } from '../../data/mockData.js';

function docStatusChip(status) {
  if (status === 'ok')      return <span className="chip good">✓ received</span>;
  if (status === 'missing') return <span className="chip bad">✕ missing</span>;
  return <span className="chip gray">n/a</span>;
}

function docColor(pct) {
  if (pct >= 0.85) return 'var(--good)';
  if (pct >= 0.70) return 'var(--warn)';
  return 'var(--bad)';
}

export default function EnrollStudents() {
  const [useSIS, setUseSIS] = useState(true);
  const [selectedId, setSelectedId] = useState('EN-205');
  const selected = enrollmentQueue.find((e) => e.id === selectedId);
  const detail = enrollmentDetail[selectedId];

  return (
    <>
      <div className="view-header">
        <div>
          <h2>Enroll Students</h2>
          <div className="sub">
            Intake queue with AI document checks, residency verification, and grade-placement recommendations.
          </div>
        </div>
        <SisToggle value={useSIS} onChange={setUseSIS} />
      </div>

      <div className="grid-2" style={{ gridTemplateColumns: '1.3fr 1fr' }}>
        <div className="card">
          <div className="card-title">
            Intake queue
            <span className="hint">{useSIS ? 'Prior-record lookup enabled' : 'Blind intake'}</span>
          </div>
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Student</th>
                <th>Grade</th>
                <th>Docs</th>
                <th>Residency</th>
                <th>Prior</th>
              </tr>
            </thead>
            <tbody>
              {enrollmentQueue.map((e) => (
                <tr
                  key={e.id}
                  className={`selectable ${selectedId === e.id ? 'selected' : ''}`}
                  onClick={() => setSelectedId(e.id)}
                >
                  <td style={{ fontFamily: 'monospace', fontSize: 11 }}>{e.id}</td>
                  <td>{e.name}</td>
                  <td>{e.grade}</td>
                  <td style={{ minWidth: 100 }}>
                    <div className="bar" style={{ height: 6 }}>
                      <div style={{ width: `${e.docsComplete * 100}%`, background: docColor(e.docsComplete), height: '100%' }} />
                    </div>
                    <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 2 }}>{(e.docsComplete * 100).toFixed(0)}%</div>
                  </td>
                  <td>
                    <span className={`chip ${e.residency === 'verified' ? 'good' : 'warn'}`}>{e.residency}</span>
                  </td>
                  <td style={{ fontSize: 11 }}>{e.prior}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="card">
          <div className="card-title">
            Enrollment detail
            <span className="hint">{selected.id}</span>
          </div>
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 16, fontWeight: 600 }}>{selected.name}</div>
            <div style={{ fontSize: 12, color: 'var(--muted)' }}>Gr {selected.grade} · {selected.prior}</div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 14 }}>
            <div className="metric">
              <div className="label">AI grade recommendation</div>
              <div className="value">{selected.aiGrade}</div>
              <div className="delta" style={{ color: 'var(--muted)' }}>
                confidence {(selected.confidence * 100).toFixed(0)}%
              </div>
            </div>
            <div className="metric">
              <div className="label">Residency</div>
              <div className="value" style={{ fontSize: 16, lineHeight: '28px' }}>
                <span className={`chip ${selected.residency === 'verified' ? 'good' : 'warn'}`}>{selected.residency}</span>
              </div>
              <div className="delta" style={{ color: 'var(--muted)' }}>
                {selected.flags.length ? `${selected.flags.length} flag(s)` : 'no flags'}
              </div>
            </div>
          </div>

          {detail && (
            <>
              <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.4, marginBottom: 6 }}>
                Required documents
              </div>
              <div className="list-divide">
                {detail.docs.map((d) => (
                  <div key={d.name} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
                    <span>{d.name}</span>
                    {docStatusChip(d.status)}
                  </div>
                ))}
              </div>

              <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.4, margin: '14px 0 6px' }}>
                AI-suggested next actions
              </div>
              {detail.aiActions.map((a, i) => (
                <div
                  key={i}
                  style={{
                    padding: 8,
                    borderRadius: 4,
                    marginBottom: 4,
                    background: a.tone === 'warn' ? '#fffbeb' : '#f0fdf4',
                    fontSize: 12,
                  }}
                >
                  → {a.label}
                </div>
              ))}
            </>
          )}

          <div style={{ marginTop: 12, fontSize: 11, color: 'var(--muted)' }}>{selected.notes}</div>

          <div style={{ marginTop: 14 }}>
            <button className="btn">Approve enrollment</button>
            <button className="btn secondary" style={{ marginLeft: 8 }}>Send guardian checklist</button>
          </div>
        </div>
      </div>
    </>
  );
}
