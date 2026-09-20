import React, { useEffect, useState } from 'react';
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from 'recharts';
import { ownerAPI } from '../lib/api';
import { useBranch } from '../contexts/BranchContext';

/**
 * AcquisitionDonut — "Top sources d'acquisition" panel.
 *
 * Shows how customers arrived: QR-in-store, Instagram, Facebook, TikTok,
 * Website. Donut chart on the left, legend list on the right with %,
 * client count, and a swatch. Centre of the donut holds the network total.
 *
 * Pulls /owner/analytics/acquisition-sources which returns the lifetime
 * breakdown. We sort descending so the largest source is always on top.
 */
const SOURCE_LABELS = {
  qr_store:   { label: 'QR in-store',  color: '#2F6BFF' },
  instagram:  { label: 'Instagram',    color: '#8FB0FF' },
  facebook:   { label: 'Facebook',     color: '#5B8DEF' },
  tiktok:     { label: 'TikTok',       color: '#0F172A' },
  website:    { label: 'Website',      color: '#64748B' },
  manual:     { label: 'Saisie staff', color: '#C7D7FF' },
};

export default function AcquisitionDonut() {
  const { branchId } = useBranch();
  const [data, setData] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    ownerAPI.getAcquisitionSources?.({ ...(branchId ? { branch_id: branchId } : {}) })
      .then((r) => {
        if (!alive) return;
        const raw = r?.data?.breakdown || r?.data?.acquisition_breakdown || r?.data || {};
        // Normalise into [{ key, label, color, value }]
        const entries = Object.entries(raw)
          .filter(([k, v]) => typeof v === 'number' && v >= 0)
          .map(([k, v]) => {
            const meta = SOURCE_LABELS[k] || { label: k.replace(/_/g, ' '), color: '#94A3B8' };
            return { key: k, name: meta.label, color: meta.color, value: v };
          })
          .sort((a, b) => b.value - a.value);
        const sum = entries.reduce((s, e) => s + e.value, 0);
        setData(entries);
        setTotal(sum);
      })
      .catch(() => { /* silent — empty state below */ })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [branchId]);

  return (
    <div className="ft-card" style={{ padding: 16 }}>
      <div className="flex items-baseline justify-between mb-3">
        <p className="text-[10.5px] uppercase" style={{ letterSpacing: '0.16em', color: 'var(--ink-mute)', fontWeight: 600 }}>
          Top sources d'acquisition
        </p>
        <span
          className="text-[10px] px-2 py-0.5 rounded"
          style={{ background: 'var(--surface-sunken)', color: 'var(--ink-mute)', letterSpacing: '0.04em' }}
        >
          À vie
        </span>
      </div>

      {loading ? (
        <div style={{ height: 130 }} className="ft-skeleton" />
      ) : total === 0 ? (
        <div className="text-center py-8" style={{ color: 'var(--ink-mute)', fontSize: 12.5 }}>
          Aucune source enregistrée pour l'instant.
        </div>
      ) : (
        <div className="flex items-center gap-4">
          {/* Donut */}
          <div className="relative shrink-0" style={{ width: 110, height: 110 }}>
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={data}
                  dataKey="value"
                  innerRadius={36}
                  outerRadius={52}
                  startAngle={90}
                  endAngle={-270}
                  paddingAngle={1.5}
                  stroke={"var(--flc-card, #FFFFFF)"}
                  strokeWidth={2}
                  isAnimationActive={false}
                >
                  {data.map((d) => <Cell key={d.key} fill={d.color} />)}
                </Pie>
                <Tooltip
                  contentStyle={{
                    background: 'var(--flc-card, #FFFFFF)', border: '1px solid var(--flc-line, #E6EAF2)',
                    borderRadius: 8, padding: '4px 8px', fontSize: 11,
                    boxShadow: '0 4px 14px rgba(0,0,0,0.08)',
                  }}
                  formatter={(v, n) => [`${v} clients`, n]}
                />
              </PieChart>
            </ResponsiveContainer>
            <div
              className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none"
              style={{ color: 'var(--ink)' }}
            >
              <p style={{ fontSize: 19, fontWeight: 500, letterSpacing: '-0.022em', lineHeight: 1 }}>{total}</p>
              <p className="text-[9px] mt-0.5" style={{ color: 'var(--ink-mute)', textTransform: 'uppercase', letterSpacing: '0.12em' }}>
                Total clients
              </p>
            </div>
          </div>

          {/* Legend */}
          <div className="flex-1 min-w-0 space-y-1.5">
            {data.slice(0, 5).map((d) => {
              const pct = total > 0 ? (d.value / total) * 100 : 0;
              return (
                <div key={d.key} className="flex items-center justify-between gap-2 text-[12px]">
                  <div className="flex items-center gap-1.5 min-w-0">
                    <span className="w-2 h-2 rounded-sm shrink-0" style={{ background: d.color }} />
                    <span className="truncate" style={{ color: 'var(--ink)', fontWeight: 500 }}>{d.name}</span>
                  </div>
                  <div className="flex items-baseline gap-1.5 shrink-0">
                    <span style={{ color: 'var(--ink-mute)', fontSize: 11 }}>{d.value} clients</span>
                    <span style={{ color: 'var(--ink)', fontWeight: 500, fontSize: 11.5 }}>{pct.toFixed(1)}%</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
