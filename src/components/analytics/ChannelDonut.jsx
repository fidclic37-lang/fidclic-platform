/**
 * ChannelDonut — donut chart with gradient segments + side legend.
 *
 * Used twice on the page: for acquisition channels (5 segments) and for
 * new-vs-returning (2 segments). The `data` prop controls everything;
 * pass any number of segments and they'll get distinct gradients.
 *
 * Props:
 *   data:       [{ name, value, color, gradientFrom?, gradientTo? }]
 *   centerNum:  optional headline number rendered in the middle
 *   centerLabel: optional small label below it
 *   size:       diameter in px (default 140)
 *   ariaLabel:  optional override
 */
import React from 'react';
import { ResponsiveContainer, PieChart, Pie, Cell, Tooltip } from 'recharts';

const DEFAULT_PALETTE = [
  { from: 'var(--flc-series-1, #2F6BFF)', to: 'var(--flc-series-4, #1D4ED8)' }, // blue
  { from: 'var(--flc-series-2, #93B4FF)', to: 'var(--flc-series-2, #93B4FF)' }, // light blue
  { from: 'var(--flc-series-3, #C7D7FF)', to: 'var(--flc-series-3, #C7D7FF)' }, // pale blue
  { from: 'var(--flc-series-5, #CBD5E1)', to: 'var(--flc-series-5, #CBD5E1)' }, // neutral
  { from: 'var(--flc-tone-sky, #0EA5E9)', to: 'var(--flc-tone-sky, #0EA5E9)' }, // sky
];

const TOOLTIP_STYLE = {
  background: 'var(--flc-card, #FFFFFF)',
  border: '1px solid var(--flc-line, #E7E5E4)',
  borderRadius: 10,
  color: 'var(--flc-ink, #191410)',
  fontSize: 12,
  padding: '8px 10px',
  boxShadow: '0 8px 24px -12px rgba(16,24,40,.25)',
};

const ChannelDonut = ({
  data = [],
  centerNum,
  centerLabel = 'Total',
  size = 140,
  ariaLabel,
}) => {
  const total = data.reduce((s, d) => s + (Number(d.value) || 0), 0);
  const segs = data.map((d, i) => {
    const pal = DEFAULT_PALETTE[i % DEFAULT_PALETTE.length];
    return {
      ...d,
      _from: d.gradientFrom || pal.from,
      _to:   d.gradientTo   || pal.to,
      _pct:  total > 0 ? Math.round(((Number(d.value) || 0) / total) * 100) : 0,
    };
  });

  if (!segs.length) {
    return (
      <div style={{ display: 'grid', placeItems: 'center', height: size, color: 'var(--flc-ink3, #524A40)', fontSize: 12 }}>
        Aucune donnée.
      </div>
    );
  }

  const idBase = `av2-donut-${Math.abs(JSON.stringify(segs.map(s => s.name)).split('').reduce((a, c) => a + c.charCodeAt(0), 0))}`;

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 16, minWidth: 0 }}>
      <div style={{ width: size, height: size, flexShrink: 0, position: 'relative' }} role="img" aria-label={ariaLabel || `Donut: ${segs.map(s => `${s.name} ${s._pct}%`).join(', ')}`}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <defs>
              {segs.map((s, i) => (
                <linearGradient key={i} id={`${idBase}-${i}`} x1="0" x2="1" y1="0" y2="0">
                  <stop offset="0%"   stopColor={s._from} />
                  <stop offset="100%" stopColor={s._to} />
                </linearGradient>
              ))}
            </defs>
            <Pie
              data={segs}
              dataKey="value"
              cx="50%"
              cy="50%"
              innerRadius={size * 0.34}
              outerRadius={size * 0.46}
              stroke="var(--flc-card, #FFFFFF)"
              strokeWidth={3}
              startAngle={90}
              endAngle={-270}
              isAnimationActive={false}
            >
              {segs.map((_s, i) => (
                <Cell key={i} fill={`url(#${idBase}-${i})`} />
              ))}
            </Pie>
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              formatter={(value, name, p) => [`${value} (${p?.payload?._pct ?? 0}%)`, name]}
              cursor={false}
            />
          </PieChart>
        </ResponsiveContainer>
        {/* Centre label */}
        {(centerNum !== undefined || centerLabel) && (
          <div
            aria-hidden="true"
            style={{
              position: 'absolute', inset: 0,
              display: 'flex', flexDirection: 'column',
              alignItems: 'center', justifyContent: 'center',
              pointerEvents: 'none',
            }}
          >
            {centerNum !== undefined && (
              <div className="av2-num" style={{ fontSize: 18, fontWeight: 500, color: 'var(--flc-ink, #191410)' }}>
                {centerNum}
              </div>
            )}
            {centerLabel && (
              <div style={{ fontSize: 9.5, color: 'var(--flc-ink3, #524A40)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>
                {centerLabel}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Side legend */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0 }}>
        {segs.map((s, i) => (
          <div
            key={i}
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              gap: 8, fontSize: 11, color: 'var(--flc-ink2, #3A332B)',
            }}
          >
            <span style={{ display: 'flex', alignItems: 'center', gap: 7, minWidth: 0 }}>
              <span style={{ width: 8, height: 8, borderRadius: '50%', background: s._from, flexShrink: 0 }} />
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.name}</span>
            </span>
            <span className="av2-num" style={{ color: 'var(--flc-ink3, #524A40)', flexShrink: 0 }}>
              {s._pct}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
};

export default ChannelDonut;
