import { Fragment, useState } from 'react';
import InfoIcon from '../InfoIcon.jsx';
import { transferStudents, transferTranscripts } from '../../data/mockData.js';

function transcriptStatusChip(s) {
  if (s === 'received')    return <span className="chip good">✓ received</span>;
  if (s === 'auto-linked') return <span className="chip good">↗ auto-linked</span>;
  if (s === 'pending')     return <span className="chip warn">pending</span>;
  return <span className="chip bad">missing</span>;
}

function folderStatusChip(s) {
  if (s === 'complete') return <span className="chip good">complete</span>;
  if (s === 'partial')  return <span className="chip warn">partial</span>;
  return <span className="chip bad">not received</span>;
}

function acceptedChip(a) {
  if (a === true)       return <span className="chip good">accepted</span>;
  if (a === 'pending')  return <span className="chip warn">pending</span>;
  if (a === 'review')   return <span className="chip warn">review</span>;
  return <span className="chip bad">denied</span>;
}

function TranscriptFormatInfo() {
  return (
    <InfoIcon ariaLabel="Transcript exchange formats" width={420}>
      <h4>Transcript exchange formats</h4>
      <ul className="info-list">
        <li><strong>CLR 2.0</strong> — Modern badges, post-secondary</li>
        <li><strong>PESC High School Transcript</strong> — XML courses only</li>
        <li><strong>Ed-Fi / State options</strong> — e.g., FL, IN, AL, TX</li>
      </ul>
    </InfoIcon>
  );
}

function CumulativeFolderInfo() {
  return (
    <InfoIcon ariaLabel="Cumulative folder contents" width={500} align="right">
      <h4>What's in a cumulative folder</h4>
      <p>The contents vary by district, but a typical cumulative folder contains:</p>
      <ul className="info-list">
        <li>The student's enrollment forms and emergency contact information</li>
        <li>Birth certificate copy</li>
        <li>Immunization records</li>
        <li>Year-by-year report cards</li>
        <li>Standardized test scores (state assessments, sometimes nationally normed tests)</li>
        <li>The official transcript (for high school)</li>
        <li>Attendance history summaries</li>
        <li>Discipline records — referrals, suspension notices, behavior contracts</li>
        <li>Health records and any medical notes</li>
        <li>Special education paperwork (IEPs, 504 plans, evaluations) — often kept in a separate, more tightly access-controlled file</li>
        <li>Counselor notes</li>
        <li>Awards, honors, extracurricular notes</li>
        <li>Withdrawal forms from previous schools, if the student transferred in</li>
        <li>Any correspondence with parents that the school chose to file</li>
      </ul>
    </InfoIcon>
  );
}

export default function TransferData() {
  const [selectedId, setSelectedId] = useState('TS-001');
  const selected = transferStudents.find((s) => s.id === selectedId);
  const transcript = transferTranscripts[selectedId];

  return (
    <>
      <div className="view-header">
        <div>
          <h2>Transfer Student Data</h2>
          <div className="sub">
            Incoming transfers with prior school / district / grade, transcript availability,
            and cumulative folder completeness. Select a row to inspect the transcript and the
            district's course-for-credit translation.
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-title">
          Transferring students
          <span className="hint">{transferStudents.length} students in queue</span>
        </div>
        <table>
          <thead>
            <tr>
              <th>Student</th>
              <th>From school</th>
              <th>District</th>
              <th>Grade</th>
              <th>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                  Transcript available
                  <TranscriptFormatInfo />
                </span>
              </th>
              <th>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                  Cumulative folder
                  <CumulativeFolderInfo />
                </span>
              </th>
            </tr>
          </thead>
          <tbody>
            {transferStudents.map((s) => (
              <tr
                key={s.id}
                className={`selectable ${selectedId === s.id ? 'selected' : ''}`}
                onClick={() => setSelectedId(s.id)}
              >
                <td>
                  <div style={{ fontWeight: 600 }}>{s.name}</div>
                  <div style={{ color: 'var(--muted)', fontSize: 11 }}>{s.id}</div>
                </td>
                <td>{s.fromSchool}</td>
                <td>
                  {s.fromDistrict}
                  <div style={{ color: 'var(--muted)', fontSize: 11 }}>{s.fromState}</div>
                </td>
                <td>{s.grade}</td>
                <td>
                  {transcriptStatusChip(s.transcript.status)}
                  <div style={{ color: 'var(--muted)', fontSize: 11, marginTop: 3 }}>{s.transcript.format}</div>
                </td>
                <td>
                  {folderStatusChip(s.folder.status)}
                  {s.folder.missing.length > 0 && (
                    <div style={{ color: 'var(--muted)', fontSize: 11, marginTop: 3 }}>
                      missing: {s.folder.missing.join(', ')}
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <div className="card-title">
          Transcript · {selected.name}
          <span className="hint">
            from {selected.fromSchool} ({selected.fromDistrict}, {selected.fromState})
          </span>
        </div>

        {transcript ? (
          <>
            <div style={{ display: 'flex', gap: 18, marginBottom: 14, flexWrap: 'wrap' }}>
              <div className="metric" style={{ minWidth: 140 }}>
                <div className="label">Cumulative GPA</div>
                <div className="value">{transcript.cumulativeGPA.toFixed(2)}</div>
                <div className="delta" style={{ color: 'var(--muted)' }}>unweighted</div>
              </div>
              <div className="metric" style={{ minWidth: 140 }}>
                <div className="label">Weighted GPA</div>
                <div className="value">{transcript.weightedGPA.toFixed(2)}</div>
                <div className="delta" style={{ color: 'var(--muted)' }}>honors / AP boost</div>
              </div>
              <div className="metric" style={{ minWidth: 200 }}>
                <div className="label">Transcript format</div>
                <div className="value" style={{ fontSize: 15, lineHeight: '28px' }}>
                  <span className="chip">{selected.transcript.format}</span>
                </div>
                <div className="delta" style={{ color: 'var(--muted)' }}>
                  {transcriptStatusChip(selected.transcript.status)}
                </div>
              </div>
            </div>

            {transcript.years.map((y) => (
              <Fragment key={y.year}>
                <div style={{
                  marginTop: 14, marginBottom: 6,
                  fontWeight: 600, fontSize: 13,
                  color: 'var(--accent)',
                  borderBottom: '1px solid var(--border)',
                  paddingBottom: 4,
                }}>
                  {y.year}
                </div>
                <table>
                  <colgroup>
                    <col />
                    <col style={{ width: 60 }} />
                    <col style={{ width: 50 }} />
                    <col style={{ width: 22 }} />
                    <col />
                    <col style={{ width: 50 }} />
                    <col style={{ width: 100 }} />
                    <col />
                  </colgroup>
                  <thead>
                    <tr>
                      <th>Course (source)</th>
                      <th>Grade</th>
                      <th>Cr.</th>
                      <th></th>
                      <th>Course for credit (this district)</th>
                      <th>Cr.</th>
                      <th>Status</th>
                      <th>Note</th>
                    </tr>
                  </thead>
                  <tbody>
                    {y.courses.map((c, i) => (
                      <tr key={i}>
                        <td>{c.course}</td>
                        <td style={{ fontVariantNumeric: 'tabular-nums', fontWeight: 600 }}>{c.grade}</td>
                        <td style={{ fontVariantNumeric: 'tabular-nums' }}>{c.cr.toFixed(2)}</td>
                        <td style={{ color: 'var(--muted)', textAlign: 'center' }}>→</td>
                        <td>{c.t.course}</td>
                        <td style={{ fontVariantNumeric: 'tabular-nums' }}>{c.t.cr.toFixed(2)}</td>
                        <td>{acceptedChip(c.t.accepted)}</td>
                        <td style={{ color: 'var(--muted)', fontSize: 11 }}>{c.t.note || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Fragment>
            ))}

            <div style={{ marginTop: 14 }}>
              <button className="btn">Accept all high-confidence credits</button>
              <button className="btn secondary" style={{ marginLeft: 8 }}>Send to counselor review</button>
            </div>
          </>
        ) : (
          <div style={{ padding: '24px 0', color: 'var(--muted)', fontSize: 13 }}>
            Transcript pending from {selected.fromSchool}.
            {selected.transcript.format !== '—' && (
              <> Requested via <strong>{selected.transcript.format}</strong>.</>
            )}
          </div>
        )}
      </div>
    </>
  );
}
