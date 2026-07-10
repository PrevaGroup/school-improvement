import { useState } from 'react';
import { uploadOutputTypes } from '../../data/mockData.js';

export default function UploadData() {
  const [filename, setFilename] = useState('');
  const [outputType, setOutputType] = useState(uploadOutputTypes[0].id);
  const [status, setStatus] = useState(null); // null | 'processing' | 'done'

  const pickFile = () => {
    // Mocked file picker (no actual upload)
    const mocks = [
      'student_roster_2026Q4.xlsx',
      'attendance_daily_export.csv',
      'odr_log_may2026.csv',
      'aimsweb_composite.csv',
    ];
    setFilename(mocks[Math.floor(Math.random() * mocks.length)]);
    setStatus(null);
  };

  const processFile = () => {
    setStatus('processing');
    setTimeout(() => setStatus('done'), 1400);
  };

  const selectedOutput = uploadOutputTypes.find((o) => o.id === outputType);

  return (
    <>
      <div className="view-header">
        <div>
          <h2>Upload Data · Bulk Conversion</h2>
          <div className="sub">
            Mock an upload, choose a destination format, and generate a bulk-import file
            for tools like Panorama or PowerSchool.
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-title">1 · Select source file</div>
        <div className={`upload-zone ${filename ? 'has-file' : ''}`}>
          {filename ? (
            <>
              <div style={{ fontWeight: 600, marginBottom: 4 }}>{filename}</div>
              <div style={{ fontSize: 11, color: 'var(--muted)' }}>~{(Math.random() * 1.8 + 0.2).toFixed(1)} MB · mock data</div>
            </>
          ) : (
            <>Drag &amp; drop a file here, or click to browse (mocked)</>
          )}
          <div style={{ marginTop: 12 }}>
            <button className="btn secondary" onClick={pickFile}>
              {filename ? 'Choose different file' : 'Browse files'}
            </button>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-title">2 · Choose output bulk-import format</div>
        <select
          value={outputType}
          onChange={(e) => { setOutputType(e.target.value); setStatus(null); }}
          style={{ minWidth: 360 }}
        >
          {uploadOutputTypes.map((o) => (
            <option key={o.id} value={o.id}>{o.label}</option>
          ))}
        </select>
        <div style={{ marginTop: 10, fontSize: 12, color: 'var(--muted)' }}>
          Target: <strong style={{ color: 'var(--text)' }}>{selectedOutput.label}</strong>
        </div>
      </div>

      <div className="card">
        <div className="card-title">3 · Process file</div>
        <button className="btn" disabled={!filename || status === 'processing'} onClick={processFile}>
          {status === 'processing' ? 'Processing…' : 'Process file'}
        </button>
        {status === 'done' && (
          <div style={{ marginTop: 14, padding: 12, background: '#dcfce7', border: '1px solid #86efac', borderRadius: 6, fontSize: 13 }}>
            ✓ Conversion complete · generated <code>{filename.replace(/\.[^.]+$/, '')}__{outputType}.csv</code> (mock).
            Ready to upload to {selectedOutput.label.split(' — ')[0]}.
          </div>
        )}
      </div>
    </>
  );
}
