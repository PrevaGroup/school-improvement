import { useState } from 'react';
import SisToggle from '../SisToggle.jsx';
import { attendanceStudents, clusterDimensions } from '../../data/mockData.js';

function severityChip(s) {
  const cls = s === 'High' ? 'bad' : s === 'Moderate' ? 'warn' : 'good';
  return <span className={`chip ${cls}`}>{s}</span>;
}

export default function CategorizeAttendance() {
  const [useSIS, setUseSIS] = useState(true);
  const [selectedId, setSelectedId] = useState(attendanceStudents[0].id);
  const selected = attendanceStudents.find((s) => s.id === selectedId);

  return (
    <>
      <div className="view-header">
        <div>
          <h2>Daily Attendance · Categorize Unexplained Absences</h2>
          <div className="sub">
            Guardian conversations rated across the five Kearney &amp; Graczyk (2020) MTSS clusters.
          </div>
        </div>
        <SisToggle value={useSIS} onChange={setUseSIS} />
      </div>

      <div className="card">
        <div className="card-title">
          Students with unexplained absences
          <span className="hint">
            {useSIS ? 'Source: SIS · live nightly sync' : 'Source: manual upload only'}
          </span>
        </div>
        <table>
          <thead>
            <tr>
              <th>Student</th>
              <th>School / Grade</th>
              <th>Unexplained days</th>
              <th>YTD absence rate</th>
              <th>Last contact</th>
              <th>Severity</th>
            </tr>
          </thead>
          <tbody>
            {attendanceStudents.map((s) => (
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
                <td>{s.unexplainedDays}</td>
                <td>{(s.ytdAbsenceRate * 100).toFixed(0)}%</td>
                <td>{s.lastContact}</td>
                <td>{severityChip(s.severity)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid-2">
        <div className="card">
          <div className="card-title">
            Guardian ↔ Attendance Agent
            <span className="hint">{selected.name} · {selected.id}</span>
          </div>
          <div className="chat">
            {selected.conversation.map((m, i) => (
              <div key={i} className={`bubble ${m.from}`}>
                {m.text}
                <span className="meta">{m.from === 'agent' ? 'Attendance Agent' : 'Guardian'} · {m.t}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="card">
          <div className="card-title">
            Conversation rated across 5 clusters
            <span className="hint">Kearney &amp; Graczyk (2020)</span>
          </div>
          {clusterDimensions.map((dim) => {
            const score = selected.clusters[dim.key];
            return (
              <div className="cluster-row" key={dim.key}>
                <div>
                  <div className="name">{dim.name}</div>
                  <div className="desc">{dim.desc}</div>
                </div>
                <div>
                  <div className="bar"><div style={{ width: `${score.value * 100}%` }} /></div>
                  <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>
                    {score.label}
                  </div>
                </div>
                <div style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums', fontWeight: 600 }}>
                  {(score.value * 100).toFixed(0)}
                </div>
              </div>
            );
          })}
          <div style={{ marginTop: 14, fontSize: 11, color: 'var(--muted)' }}>
            Scores are model-assigned likelihoods across the five MTSS dimensions:
            typology, function, developmental band, ecological level, and severity.
          </div>
        </div>
      </div>
    </>
  );
}
