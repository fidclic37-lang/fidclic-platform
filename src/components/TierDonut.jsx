import React, { useEffect, useState } from 'react';
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from 'recharts';
import { ownerAPI } from '../lib/api';
import { useBranch } from '../contexts/BranchContext';

/**
 * TierDonut — "Répartition par tier" panel.
 *
 * Shows how customers split across Bronze / Silver / Gold / VIP. Reads from
 * /owner/analytics/summary which already returns `tier_distribution`.
 * Same visual treatment as AcquisitionDonut — donut on the left, legend
 * with %, count and swatch on the right, total in the centre.
 *
 * The tier label and colour for each segment are configurable on the
 * Settings page (tier definitions), but for the donut we use the canonical
 * Bronze/Silver/Gold/VIP palette so the chart reads consistently across
 * tenants.
 */
const TIER_META = {
  bronze: { label: 'Bronze', color: '#C7D7FF' },
  silver: { label: 'Silver', color: '#CBD5E1' },
  gold:   { label: 'Gold',   color: '#93B4FF' },
  vip:    { label: 'VIP',    color: '#1D4ED8' },
};

export default function TierDonut() {
  const { branchId } = useBranch();
  const [data, setData] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    ownerAPI.getAnalyticsSummary?.({ ...(branchId ? { branch_id: branchId } : {}) })
      .then((r) => {
        if (!alive) return;
        const dist = r?.data?.tier_distribution || {};
        const entries = ['bronze', 'silver', 'gold', 'vip']
          .map((key) => ({
            key,
            name: TIER_META[key].label,
            color: TIER_META[key].color,
            value: Number(dist[key] || 0),
          }))
          .filter((e) => e.value > 0);
        const sum = entries.reduce((s, e) => s + e.value, 0);
        setData(entries);
        setTotal(sum);
      })
      .catch(() => { /* silent */ })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [branchId]);

  return (
    <div className="ft-card" style={{ padding: 16 }}>
      <div className="flex items-baseline justify-between mb-3">
        <p className="text-[10.5px] uppercase" style={{ letterSpacing: '0.16em', color: 'var(--ink-mute)', fontWeight: 600 }}>
          Répartition par tier
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
          Aucun palier atteint pour l'instant.
        </div>
      ) : (
        <div className="flex items-center gap-4">
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

          <div className="flex-1 min-w-0 space-y-1.5">
            {data.map((d) => {
              const pct = total > 0 ? (d.value / total) * 100 : 0;
              return (
                <div key={d.key} className="flex items-center justify-between gap-2 text-[12px]">
                  <div className="flex items-center gap-1.5 min-w-0">
                    <span className="w-2 h-2 rounded-sm shrink-0" style={{ background: d.color }} />
                    <span className="truncate" style={{ color: 'var(--ink)', fontWeight: 500 }}>{d.name}</span>
                  </div>
                  <div className="flex items-baseline gap-1.5 shrink-0">
                    <span style={{ color: 'var(--ink-mute)', fontSize: 11 }}>{d.value} clients</span>
                    <span style={{ color: 'var(--ink)', fontWeight: 500, fontSize: 11.5 }}>{pct.toFixed(0)}%</span>
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
