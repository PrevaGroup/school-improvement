import { useState } from 'react';
import SisToggle from '../SisToggle.jsx';
import { tierFramework } from '../../data/mockData.js';

export default function AdditionalTiers() {
  const [useSIS, setUseSIS] = useState(true);

  return (
    <>
      <div className="view-header">
        <div>
          <h2>Weekly Attendance · Additional Tiers (1–5)</h2>
          <div className="sub">
            Interventions stratified by tier, from universal supports through court / alternative placement.
          </div>
        </div>
        <SisToggle value={useSIS} onChange={setUseSIS} />
      </div>

      <div className="card">
        <div className="card-title">
          MTSS attendance tiers
          <span className="hint">
            {useSIS ? 'Student counts pulled from SIS' : 'Student counts entered manually'}
          </span>
        </div>
        {tierFramework.map((t) => (
          <div className="tier-card" key={t.tier}>
            <div className={`tier-label ${t.color}`}>Tier {t.tier}</div>
            <div>
              <h3>{t.title}</h3>
              <p>{t.blurb}</p>
              <ul>
                {t.items.map((it) => <li key={it}>{it}</li>)}
              </ul>
            </div>
          </div>
        ))}
      </div>
    </>
  );
}
