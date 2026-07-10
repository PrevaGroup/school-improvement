import { useState } from 'react';
import SisToggle from '../SisToggle.jsx';
import { sipMetrics } from '../../data/mockData.js';

export default function SchoolImprovementPlan() {
  const [useSIS, setUseSIS] = useState(true);

  return (
    <>
      <div className="view-header">
        <div>
          <h2>School Improvement Plan · Process Metrics</h2>
          <div className="sub">
            MTSS/EWS pipeline process metrics that almost nobody tracks at the SIP level —
            but which determine whether the plan is actually being executed.
          </div>
        </div>
        <SisToggle value={useSIS} onChange={setUseSIS} />
      </div>

      <div className="card">
        <div className="card-title">
          Pipeline execution health
          <span className="hint">
            {useSIS ? 'Live from SIS · refreshed nightly' : 'Manual roll-up · monthly cadence'}
          </span>
        </div>
        <div className="grid-2">
          {sipMetrics.map((m) => (
            <div className="metric" key={m.label}>
              <div className="label">{m.label}</div>
              <div className="value">
                {m.value}%
                <span style={{ fontSize: 12, color: 'var(--muted)', fontWeight: 400, marginLeft: 8 }}>
                  · target {m.target}%
                </span>
              </div>
              <div className="metric-bar">
                <div
                  style={{
                    width: `${m.value}%`,
                    background: m.value >= m.target ? 'var(--good)'
                              : m.value >= m.target * 0.7 ? 'var(--warn)'
                              : 'var(--bad)',
                  }}
                />
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6 }}>
                <span className={`delta ${m.deltaGood ? 'good' : 'bad'}`}>{m.delta}</span>
                <span className="delta" style={{ color: 'var(--muted)' }}>{m.denomLabel}</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="card">
        <div className="card-title">Where AI moves the needle</div>
        <ul style={{ margin: 0, padding: '0 0 0 18px', fontSize: 13, color: 'var(--text)', lineHeight: 1.6 }}>
          <li>Auto-detect referrals that have aged past the contact SLA and re-queue them with a draft outreach.</li>
          <li>Cluster reasons-for-non-contact across the bottom-performing metrics to identify upstream friction.</li>
          <li>Surface Tier-3 plans untouched for 90+ days with a one-click "schedule review" workflow.</li>
          <li>Generate teacher-readable summaries of IEP/504 accommodations to lift the acknowledgement rate.</li>
        </ul>
      </div>
    </>
  );
}
