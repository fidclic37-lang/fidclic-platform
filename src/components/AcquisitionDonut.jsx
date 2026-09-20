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
        // The endpoint answers { sources: [{source,label,count,percentage}], total, period_days }.
        // (Iterating the whole object used to turn "total" and "period_days"
        // into fake sources.) Colours are assigned by rank — biggest slice
        // gets the primary blue, then lighter blues, then grey — like every
        // other chart on the page.
        const LADDER = ['#2F6BFF', '#5B8DEF', '#8FB0FF', '#C7D7FF', '#DCE3EF', '#E6EAF2'];
        const list = Array.isArray(r?.data?.sources) ? r.data.sources
          : Object.entries(r?.data?.breakdown || {}).map(([source, count]) => ({ source, count }));
        const entries = list
          .map((row) => ({ key: row.source, name: (SOURCE_LABELS[row.source] || {}).label || String(row.label || row.source).replace(/_/g, ' '), value: Number(row.count) || 0 }))
          .filter((e) => e.value > 0)
          .sort((a, b) => b.value - a.value)
          .map((e, i) => ({ ...e, color: LADDER[Math.min(i, LADDER.length - 1)] }));
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
