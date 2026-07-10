import { useState } from 'react';
import SisToggle from '../SisToggle.jsx';
import InfoIcon from '../InfoIcon.jsx';
import { odrRecords } from '../../data/mockData.js';

const ODR_FIELD_PSYCHOMETRICS = [
  {
    field: 'Student',
    rel: 'High — identity is recorded, not judged',
    relTier: 'high',
    val: 'High — direct administrative record',
    valTier: 'high',
    cite: 'Standard SIS practice; not a research question',
  },
  {
    field: 'Location',
    rel: 'High — observable, low-inference; staff agree on where things happened',
    relTier: 'high',
    val: 'High at the school-wide level for hot-spot analysis',
    valTier: 'high',
    cite: 'Irvin, Tobin, Sprague, Sugai, & Vincent (2004); Irvin, Horner, Ingram, Todd, Sugai, Sampson, & Boland (2006)',
  },
  {
    field: 'Time of day',
    rel: 'High — recorded, not inferred',
    relTier: 'high',
    val: 'High for temporal pattern analysis; used productively for school-wide decision-making',
    valTier: 'high',
    cite: 'Irvin et al. (2004, 2006); Sugai, Sprague, Horner, & Walker (2000)',
  },
  {
    field: 'Problem behavior — objective subset (fighting, theft, weapons, vandalism, tardy, skipping)',
    rel: 'High — clear behavioral criteria, two observers tend to agree',
    relTier: 'high',
    val: 'Reasonable as an index of school-wide behavioral climate; total ODR counts correlate with externalizing problem-behavior measures',
    valTier: 'high',
    cite: 'Irvin et al. (2004, 2006); Pas, Bradshaw, & Mitchell (2011); McIntosh, Campbell, Carter, & Zumbo (2009)',
  },
  {
    field: 'Problem behavior — subjective subset (defiance, disrespect, disruption, inappropriate language)',
    rel: 'Moderate to low — requires interpretation of intent and tone; agreement varies substantially by rater',
    relTier: 'mod',
    val: 'Compromised as a measure of student behavior because the referring decision is itself biased; same behavior gets coded differently depending on student race, teacher relationship, and classroom context',
    valTier: 'low',
    cite: 'Skiba, Michael, Nardo, & Peterson (2002); Skiba, Horner, Chung, Rausch, May, & Tobin (2011); Girvan, Cornell, & Cole (2017); Smolkowski, Girvan, McIntosh, Nese, & Horner (2016); Barrett, McEachin, Mills, & Valant (2021)',
  },
  {
    field: 'Perceived motivation',
    rel: 'Low — staff make a snap inference in seconds without protocol; rating-scale FBA instruments (MAS, QABF) on which the categories are loosely based show poor inter-rater agreement even with training',
    relTier: 'low',
    val: 'Weak as a measure of behavioral function; PBISApps itself describes it as a "best guess" and distinguishes it explicitly from a real Functional Behavior Assessment',
    valTier: 'low',
    cite: 'Newton & Sturmey (1991); Zarcone, Rodgers, Iwata, Rourke, & Dorsey (1991); Nicholson, Konstantinidi, & Furniss (2006); Shogren & Rojahn (2003); Hanley (2012); PBISApps Teach By Design, "Motive, Motivate, Motivation" (2018)',
  },
  {
    field: 'Others involved',
    rel: 'High when dyadic (named peer, staff member); moderate when diffuse ("peers," blank)',
    relTier: 'mod',
    val: 'Adequate for relational pattern analysis when used carefully',
    valTier: 'high',
    cite: 'Limited dedicated psychometric literature; treated as administrative metadata in most ODR research',
  },
  {
    field: 'Administrative decision (action taken)',
    rel: 'High as a record of what happened',
    relTier: 'high',
    val: 'Low as a proxy for behavior severity — heavily mediated by administrator discretion, prior ODR count, student race, gender, and disability status; same referred behavior yields different actions across student groups',
    valTier: 'low',
    cite: 'Skiba et al. (2002, 2011); Anyon et al. (2014); Barrett et al. (2021), "Equal time for equal crime?"; Lindsay & Hart (2017) on teacher-student race-match effects',
  },
];

function OdrPsychometricsInfo() {
  return (
    <InfoIcon ariaLabel="ODR field psychometrics" width={640}>
      <h4>ODR field psychometrics — reliability, validity, and citations</h4>
      <table>
        <colgroup>
          <col style={{ width: '20%' }} />
          <col style={{ width: '24%' }} />
          <col style={{ width: '28%' }} />
          <col style={{ width: '28%' }} />
        </colgroup>
        <thead>
          <tr>
            <th>Field</th>
            <th>Reliability</th>
            <th>Validity</th>
            <th>Key citations</th>
          </tr>
        </thead>
        <tbody>
          {ODR_FIELD_PSYCHOMETRICS.map((r) => (
            <tr key={r.field}>
              <td className="field-name">{r.field}</td>
              <td><span className={`tier rel-${r.relTier}`}>{r.rel}</span></td>
              <td><span className={`tier rel-${r.valTier}`}>{r.val}</span></td>
              <td className="cite">{r.cite}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </InfoIcon>
  );
}

export default function Behavior() {
  const [useSIS, setUseSIS] = useState(true);
  const [selectedId, setSelectedId] = useState(odrRecords[0].id);
  const selected = odrRecords.find((o) => o.id === selectedId);

  return (
    <>
      <div className="view-header">
        <div>
          <h2>Behavior Review · Office Discipline Referrals</h2>
          <div className="sub">Review ODRs and the assessed details for each incident.</div>
        </div>
        <SisToggle value={useSIS} onChange={setUseSIS} />
      </div>

      <div className="grid-2" style={{ gridTemplateColumns: '1.4fr 1fr' }}>
        <div className="card">
          <div className="card-title">
            ODR Queue
            <span className="hint">
              {useSIS ? 'Source: SIS · live' : 'Source: manual entry'} · {odrRecords.length} records
            </span>
          </div>
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Student</th>
                <th>Location</th>
                <th>Time</th>
                <th>Problem</th>
              </tr>
            </thead>
            <tbody>
              {odrRecords.map((o) => (
                <tr
                  key={o.id}
                  className={`selectable ${selectedId === o.id ? 'selected' : ''}`}
                  onClick={() => setSelectedId(o.id)}
                >
                  <td style={{ fontFamily: 'monospace', fontSize: 11 }}>{o.id}</td>
                  <td>{o.student}</td>
                  <td>{o.location}</td>
                  <td style={{ fontSize: 11, color: 'var(--muted)' }}>{o.time}</td>
                  <td>{o.problem}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="card">
          <div className="card-title">
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              Incident detail
              <OdrPsychometricsInfo />
            </span>
            <span className="hint">{selected.id}</span>
          </div>
          <Field k="Student"               v={selected.student} />
          <Field k="Location"              v={selected.location} />
          <Field k="Time"                  v={selected.time} />
          <Field k="Problem behavior"      v={selected.problem} />
          <Field k="Perceived motivation"  v={selected.motivation} />
          <Field k="Others involved"       v={selected.others} />
          <Field k="Administrative decision" v={<span className="chip">{selected.decision}</span>} />
        </div>
      </div>
    </>
  );
}

function Field({ k, v }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '160px 1fr', padding: '8px 0', borderBottom: '1px solid var(--border)' }}>
      <div style={{ color: 'var(--muted)', fontSize: 12 }}>{k}</div>
      <div style={{ fontSize: 13 }}>{v}</div>
    </div>
  );
}
