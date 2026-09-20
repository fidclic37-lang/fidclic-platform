/**
 * VisitsBarLineChart — Recharts ComposedChart with purple bars (total visits)
 * + a cyan line for unique customers. Dark theme.
 *
 * Props:
 *   data:       Array<{ label, visits, uniques }>
 *   height:     px (default 200)
 *   ariaLabel:  string (defaults to a generated summary)
 */
import React, { useMemo } from 'react';
import {
  ResponsiveContainer, ComposedChart, Bar, Line,
  CartesianGrid, XAxis, YAxis, Tooltip,
} from 'recharts';

const TOOLTIP_STYLE = {
  background: 'var(--flc-card, #FFFFFF)',
  border: '1px solid var(--flc-line, #E7E5E4)',
  borderRadius: 10,
  color: 'var(--flc-ink, #191410)',
  fontSize: 12,
  padding: '8px 10px',
  boxShadow: '0 8px 24px -12px rgba(16,24,40,.25)',
};

const LegendDot = ({ color, label }) => (
  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: 'var(--flc-ink2, #3A332B)', fontSize: 11 }}>
    <span style={{ width: 8, height: 8, borderRadius: '50%', background: color }} />
    {label}
  </span>
);

const VisitsBarLineChart = ({ data = [], height = 200, ariaLabel }) => {
  const summary = useMemo(() => {
    const totalV = data.reduce((s, d) => s + (Number(d.visits) || 0), 0);
    const totalU = data.reduce((s, d) => s + (Number(d.uniques) || 0), 0);
    return `Visites: ${totalV}, clients uniques: ${totalU} sur ${data.length} jours`;
  }, [data]);

  if (!data.length) {
    return (
      <div style={{ height, display: 'grid', placeItems: 'center', color: 'var(--flc-ink3, #524A40)', fontSize: 12 }}>
        Aucune visite à afficher pour cette période.
      </div>
    );
  }

  return (
    <>
      <div style={{ display: 'flex', gap: 14, marginBottom: 4 }}>
        <LegendDot color="var(--flc-accent, #C73E2C)" label="Visites totales" />
        <LegendDot color="#8FB0FF" label="Clients uniques" />
      </div>
      <div role="img" aria-label={ariaLabel || summary} style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: -22 }}>
            <defs>
              <linearGradient id="av2-vis-bar" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%"   stopColor="#2F6BFF" />
                <stop offset="100%" stopColor="#5B8DEF" />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="var(--flc-line, #ECE3D2)" vertical={false} strokeDasharray="2 4" />
            <XAxis
              dataKey="label"
              tick={{ fill: 'var(--flc-ink3, #524A40)', fontSize: 10 }}
              tickLine={false}
              axisLine={false}
              interval="preserveStartEnd"
              minTickGap={28}
            />
            <YAxis
              tick={{ fill: 'var(--flc-ink3, #524A40)', fontSize: 10 }}
              tickLine={false}
              axisLine={false}
              width={32}
            />
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              labelStyle={{ color: 'var(--flc-ink3, #524A40)', fontSize: 11 }}
              cursor={{ fill: 'color-mix(in srgb, var(--flc-ink, #191410) 6%, transparent)' }}
            />
            <Bar
              dataKey="visits"
              fill="url(#av2-vis-bar)"
              radius={[4, 4, 0, 0]}
              maxBarSize={16}
              name="Visites"
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="uniques"
              stroke="#8FB0FF"
              strokeWidth={2}
              dot={{ r: 2.5, fill: 'hsl(208 55% 40%)', stroke: 'var(--flc-card, #FFFFFF)', strokeWidth: 1 }}
              activeDot={{ r: 4 }}
              name="Uniques"
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </>
  );
};

export default VisitsBarLineChart;
