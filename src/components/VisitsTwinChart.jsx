import React, { useEffect, useMemo, useState } from 'react';
import {
  ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts';
import { chartAnimation } from '../lib/chartAnimation';
import { useBranch } from '../contexts/BranchContext';
import { ownerAPI } from '../lib/api';

/**
 * VisitsTwinChart — compact twin-series chart for the Analytics page.
 *
 * What it shows: terracotta bars for total visits per day/week/month, plus
 * a navy line with dot markers showing the count of unique customers in
 * the same buckets. The two together tell you "are visits growing because
 * existing customers come more often, or because we're acquiring more
 * customers?" — the most important question in retention analytics.
 *
 * Pulls bucketed data from two existing endpoints:
 *   /api/owner/analytics/metric?metric=total_visits&series=true
 *   /api/owner/analytics/metric?metric=new_customers&series=true  (proxy for uniques)
 *
 * The chart is intentionally lean — no axes shouting, calm grid, custom
 * tooltip in the brand colours, period pill on the right of the header.
 */
const PERIOD_OPTS = [
  { label: '7 derniers jours',    days: 7 },
  { label: '30 derniers jours',   days: 30 },
  { label: '90 derniers jours',   days: 90 },
  { label: 'Cette année',         days: 365 },
];

export default function VisitsTwinChart({ controlledDays = null } = {}) {
  const { branchId } = useBranch();
  const [opt, setOpt] = useState(PERIOD_OPTS[1]);
  // When the parent passes a controlledDays (the shared filter on the
  // Analytics page), it overrides the local picker.
  const effectiveDays = controlledDays != null && Number.isFinite(controlledDays) ? Math.max(1, Math.round(controlledDays)) : opt.days;
  const [visits, setVisits] = useState([]);
  const [uniques, setUniques] = useState([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    Promise.all([
      ownerAPI.getAnalyticsMetric({ metric: 'total_visits',   days: effectiveDays, series: true, ...(branchId ? { branch_id: branchId } : {}) }),
      ownerAPI.getAnalyticsMetric({ metric: 'new_customers',  days: effectiveDays, series: true, ...(branchId ? { branch_id: branchId } : {}) }),
    ]).then(([a, b]) => {
      if (!alive) return;
      setVisits(Array.isArray(a?.data?.series) ? a.data.series : []);
      setUniques(Array.isArray(b?.data?.series) ? b.data.series : []);
    }).catch(() => { /* silent */ })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [effectiveDays, branchId]);

  const data = useMemo(() => {
    const n = Math.max(visits.length, uniques.length, 0);
    return Array.from({ length: n }, (_, i) => ({
      idx: i + 1,
      visits:  visits[i]  ?? 0,
      uniques: uniques[i] ?? 0,
    }));
  }, [visits, uniques]);

  return (
    <div className="ft-card" style={{ padding: 16 }}>
      <div className="flex items-baseline justify-between mb-3">
        <p className="text-[10.5px] uppercase" style={{ letterSpacing: '0.16em', color: 'var(--ink-mute)', fontWeight: 600 }}>
          Visites dans le temps
        </p>
        {controlledDays != null ? (
          // Shared filter controls this chart — show effective window as text
          <span className="text-[11px] font-medium" style={{ color: 'var(--ink-soft)' }}>
            {effectiveDays} derniers jours
          </span>
        ) : (
          <div className="relative">
            <button
              type="button"
              onClick={() => setOpen((v) => !v)}
              className="inline-flex items-center gap-1.5 px-3 py-1 rounded-md text-[12px]"
              style={{ background: 'var(--surface-card)', border: '1px solid var(--hairline)', color: 'var(--ink-soft)' }}
            >
              {opt.label}
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="6 9 12 15 18 9"/></svg>
            </button>
            {open && (
              <div
                className="absolute right-0 top-full mt-1 rounded-md overflow-hidden z-20"
                style={{ background: 'var(--surface-card)', border: '1px solid var(--hairline)', boxShadow: 'var(--shadow-md)' }}
              >
                {PERIOD_OPTS.map((o) => (
                  <button
                    key={o.days}
                    type="button"
                    onClick={() => { setOpt(o); setOpen(false); }}
                    className="block w-full text-left px-3 py-1.5 text-[12px] hover:bg-[#FAFAF8]"
                    style={{ color: o.days === opt.days ? 'var(--brand-deep)' : 'var(--ink)' }}
                  >
                    {o.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Legend — two coloured dots, calm spacing */}
      <div className="flex items-center gap-4 mb-2 text-[11.5px]" style={{ color: 'var(--ink-soft)' }}>
        <span className="inline-flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-sm" style={{ background: '#B85C38' }} />
          Visites totales
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-full" style={{ background: '#5B7AB7' }} />
          Clients uniques
        </span>
      </div>

      <div style={{ width: '100%', height: 200 }}>
        {loading ? (
          <div className="w-full h-full ft-skeleton" style={{ borderRadius: 8 }} />
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 4, left: -10 }}>
              <CartesianGrid stroke="var(--flc-line, #EFEDE9)" strokeDasharray="3 3" vertical={false} />
              <XAxis
                dataKey="idx" tickLine={false} axisLine={false}
                tick={{ fontSize: 10, fill: 'var(--flc-ink3, #9C9590)' }}
                interval="preserveStartEnd"
              />
              <YAxis
                tickLine={false} axisLine={false}
                tick={{ fontSize: 10, fill: 'var(--flc-ink3, #9C9590)' }}
                width={32}
              />
              <Tooltip
                cursor={{ fill: 'rgba(184,92,56,0.06)' }}
                contentStyle={{
                  background: 'var(--flc-card, #FFFFFF)', border: '1px solid var(--flc-line, #EFEDE9)',
                  borderRadius: 8, padding: '6px 10px',
                  fontSize: 12, color: 'var(--flc-ink, #171412)',
                  boxShadow: '0 4px 14px rgba(0,0,0,0.08)',
                }}
                labelStyle={{ color: 'var(--flc-ink3, #8D857D)', fontSize: 10, marginBottom: 2 }}
                formatter={(v, name) => [v, name === 'visits' ? 'Visites totales' : 'Clients uniques']}
                labelFormatter={(l) => `Période ${l}`}
              />
              <defs>
                <linearGradient id="vtc-bar" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--flc-accent-2, #E8703A)" />
                  <stop offset="100%" stopColor="var(--flc-accent-deep, #A82843)" />
                </linearGradient>
              </defs>
              <Bar isAnimationActive={chartAnimation()} dataKey="visits" fill="url(#vtc-bar)" radius={[3, 3, 0, 0]} maxBarSize={18} />
              <Line isAnimationActive={chartAnimation()}
                type="monotone" dataKey="uniques"
                stroke="#5B7AB7" strokeWidth={1.8}
                dot={{ r: 2.5, fill: '#5B7AB7', stroke: 'var(--flc-card, #FFFFFF)', strokeWidth: 1 }}
                activeDot={{ r: 3.5 }}
              />
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}
