import { Fragment, useState } from 'react';
import {
  ScatterChart, Scatter, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, Radar,
  BarChart, Bar, Cell,
} from 'recharts';
import SisToggle from '../SisToggle.jsx';
import {
  projections, clusterPalette, latentHeatmap, decodedCentroids, bootstrapStability,
} from '../../data/mockData.js';

const VAE_MODELS = [
  { id: 'beta_vae',     label: 'β-VAE (β=4) · disentangled · 8-D latent' },
  { id: 'tcvae',        label: 'β-TCVAE · strongest disentanglement · 8-D latent' },
  { id: 'factor_vae',   label: 'FactorVAE · partial disentanglement · 8-D latent' },
  { id: 'vanilla',      label: 'Vanilla VAE · entangled baseline · 8-D latent' },
];

const PROJECTORS = [
  { id: 'umap', label: 'UMAP' },
  { id: 'tsne', label: 't-SNE' },
  { id: 'pca',  label: 'PCA (sanity check)' },
];

function colorFor(c) {
  return clusterPalette.find((p) => p.c === c).color;
}

function heatColor(v) {
  // map -2..2 to a diverging palette (blue to red through white)
  const t = Math.max(-2, Math.min(2, v)) / 2; // -1..1
  if (t >= 0) {
    const r = 255;
    const g = Math.round(255 - 165 * t);
    const b = Math.round(255 - 200 * t);
    return `rgb(${r},${g},${b})`;
  } else {
    const r = Math.round(255 + 175 * t);
    const g = Math.round(255 + 110 * t);
    const b = 255;
    return `rgb(${r},${g},${b})`;
  }
}

export default function ABCScreening() {
  const [useSIS, setUseSIS] = useState(true);
  const [model, setModel]   = useState('beta_vae');
  const [proj, setProj]     = useState('umap');

  const pts = projections[model][proj];

  // group scatter points by cluster for legend coloring
  const seriesByCluster = clusterPalette.map((p) => ({
    ...p,
    data: pts.filter((pt) => pt.cluster === p.c),
  }));

  return (
    <>
      <div className="view-header">
        <div>
          <h2>ABC Clusters · VAE Screening</h2>
          <div className="sub">
            Latent-space exploration of Attendance / Behavior / Course-performance composite features.
          </div>
        </div>
        <SisToggle value={useSIS} onChange={setUseSIS} />
      </div>

      <div className="card">
        <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap', alignItems: 'center' }}>
          <div>
            <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.4, marginBottom: 4 }}>VAE model</div>
            <select value={model} onChange={(e) => setModel(e.target.value)}>
              {VAE_MODELS.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
            </select>
          </div>
          <div>
            <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.4, marginBottom: 4 }}>Projector</div>
            <select value={proj} onChange={(e) => setProj(e.target.value)}>
              {PROJECTORS.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
            </select>
          </div>
          <div style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--muted)', maxWidth: 380 }}>
            Stronger disentanglement (β-TCVAE, β-VAE) separates clusters more cleanly;
            Vanilla VAE leaves them entangled. PCA is shown across all models as a
            linear-baseline sanity check.
          </div>
        </div>
      </div>

      <div className="grid-2">
        {/* 1 — Scatter */}
        <div className="card">
          <div className="card-title">
            1 · Latent projection ({PROJECTORS.find((p) => p.id === proj).label})
            <span className="hint">{pts.length} students · color = cluster</span>
          </div>
          <div style={{ width: '100%', height: 320 }}>
            <ResponsiveContainer>
              <ScatterChart margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis type="number" dataKey="x" name="x" tick={{ fontSize: 10 }} />
                <YAxis type="number" dataKey="y" name="y" tick={{ fontSize: 10 }} />
                <Tooltip
                  cursor={{ strokeDasharray: '3 3' }}
                  formatter={(v, n, item) => [item.payload.clusterLabel, 'Cluster']}
                />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                {seriesByCluster.map((s) => (
                  <Scatter key={s.c} name={s.label} data={s.data} fill={s.color} />
                ))}
              </ScatterChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* 2 — Latent heatmap */}
        <div className="card">
          <div className="card-title">
            2 · Per-dimension latent heatmap
            <span className="hint">Rows = clusters, columns = z<sub>i</sub>, cell = mean z</span>
          </div>
          <div className="heatmap">
            <div className="h-head"></div>
            {latentHeatmap.dims.map((d) => (
              <div className="h-head" key={d}>{d}</div>
            ))}
            {latentHeatmap.rows.map((r) => (
              <Fragment key={r.label}>
                <div className="h-label">{r.label}</div>
                {r.values.map((v, i) => (
                  <div
                    key={`${r.label}-${i}`}
                    className="h-cell"
                    style={{ background: heatColor(v), color: Math.abs(v) > 1 ? '#fff' : '#0f172a' }}
                    title={`${r.label} · ${latentHeatmap.dims[i]} = ${v.toFixed(2)}`}
                  >
                    {v.toFixed(2)}
                  </div>
                ))}
              </Fragment>
            ))}
          </div>
          <div style={{ marginTop: 12, fontSize: 11, color: 'var(--muted)' }}>
            "Active" latent dims (|z| ≳ 1) for each cluster — what the VAE thinks distinguishes the group.
          </div>
        </div>
      </div>

      {/* 3 — Decoded centroids */}
      <div className="card">
        <div className="card-title">
          3 · Decoded cluster centroids → reconstructed ABC profile
          <span className="hint">For non-ML stakeholders: what each cluster "looks like" in feature space</span>
        </div>
        <div className="grid-3">
          {decodedCentroids.map((c) => (
            <div key={c.cluster} style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 10 }}>
              <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6, color: colorFor(c.cluster) }}>
                ● {c.label}
              </div>
              <div style={{ width: '100%', height: 180 }}>
                <ResponsiveContainer>
                  <RadarChart data={c.features} outerRadius="70%">
                    <PolarGrid stroke="#e2e8f0" />
                    <PolarAngleAxis dataKey="k" tick={{ fontSize: 9 }} />
                    <PolarRadiusAxis angle={30} domain={[0, 100]} tick={false} axisLine={false} />
                    <Radar dataKey="v" stroke={colorFor(c.cluster)} fill={colorFor(c.cluster)} fillOpacity={0.35} />
                  </RadarChart>
                </ResponsiveContainer>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* 4 — Bootstrap stability */}
      <div className="card">
        <div className="card-title">
          4 · Bootstrap stability check
          <span className="hint">N=300 resamples · how often a cluster reproduces</span>
        </div>
        <div style={{ width: '100%', height: 220 }}>
          <ResponsiveContainer>
            <BarChart data={bootstrapStability} margin={{ top: 10, right: 20, left: -10, bottom: 0 }}>
              <CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" />
              <XAxis dataKey="cluster" tick={{ fontSize: 10 }} interval={0} />
              <YAxis domain={[0, 1]} tick={{ fontSize: 10 }} />
              <Tooltip formatter={(v) => `${(v * 100).toFixed(0)}%`} />
              <Bar dataKey="stability" radius={[4, 4, 0, 0]}>
                {bootstrapStability.map((row, i) => (
                  <Cell key={i} fill={colorFor(clusterPalette[i].c)} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div style={{ marginTop: 10, fontSize: 11, color: 'var(--muted)' }}>
          With N ≈ {bootstrapStability.reduce((a, b) => a + b.n, 0)} students, the "Slipping (Tier 2)"
          cluster has the weakest reproducibility (~71%) — treat its boundary as approximate.
        </div>
      </div>
    </>
  );
}
