/**
 * Sparkline — tiny gradient area + line, no axes, no grid, no tooltip.
 *
 * Wraps Recharts AreaChart inside a ResponsiveContainer so the parent
 * controls the height (Card sets it to 28-32px). Each accent gets a unique
 * <linearGradient> id so multiple sparklines on the same page don't share
 * defs by accident.
 *
 * Accents: purple | pink | cyan | emerald | orange | amber
 */
import React, { useMemo, useId } from 'react';
import { AreaChart, Area, ResponsiveContainer } from 'recharts';

// hsl(...) strings sourced from the .fdt-analytics-v2 token table so each
// sparkline reads as part of the same family as its parent card's icon chip.
const ACCENT = {
  purple:  { stroke: 'var(--flc-tone-blue, #2F6BFF)', fill: 'var(--flc-tone-blue, #2F6BFF)' },
  pink:    { stroke: 'var(--flc-tone-blue, #2F6BFF)', fill: 'var(--flc-tone-blue, #2F6BFF)' },
  cyan:    { stroke: 'var(--flc-tone-blue, #2F6BFF)', fill: 'var(--flc-tone-blue, #2F6BFF)' },
  emerald: { stroke: 'var(--flc-tone-blue, #2F6BFF)', fill: 'var(--flc-tone-blue, #2F6BFF)' },
  orange:  { stroke: 'var(--flc-tone-blue, #2F6BFF)', fill: 'var(--flc-tone-blue, #2F6BFF)' },
  amber:   { stroke: 'var(--flc-tone-blue, #2F6BFF)', fill: 'var(--flc-tone-blue, #2F6BFF)' },
};

const Sparkline = ({ data, accent = 'purple', height = 32, ariaLabel }) => {
  const id = useId();
  const gradientId = `av2-spark-${accent}-${id.replace(/:/g, '')}`;
  const { stroke, fill } = ACCENT[accent] || ACCENT.purple;

  // Normalize input. Accept either [number, number, ...] or [{ value: n }, ...].
  const series = useMemo(() => {
    if (!Array.isArray(data) || data.length === 0) return [];
    return data.map((d, i) =>
      typeof d === 'number'
        ? { x: i, value: d }
        : { x: i, value: Number(d?.value ?? d?.v ?? 0) || 0 }
    );
  }, [data]);

  if (series.length < 2) {
    // Single point or no data — render a flat placeholder so the card's
    // bottom-flush gradient still bleeds to the edge rather than collapsing.
    return (
      <div
        style={{ height, width: '100%' }}
        role="img"
        aria-label={ariaLabel || 'Sparkline (insufficient data)'}
      />
    );
  }

  return (
    <div style={{ height, width: '100%' }}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart
          data={series}
          margin={{ top: 0, right: 0, bottom: 0, left: 0 }}
          role="img"
          aria-label={ariaLabel || `Sparkline of ${series.length} points`}
        >
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={fill} stopOpacity={0.55} />
              <stop offset="100%" stopColor={fill} stopOpacity={0} />
            </linearGradient>
          </defs>
          <Area
            type="monotone"
            dataKey="value"
            stroke={stroke}
            strokeWidth={1.6}
            strokeLinejoin="round"
            strokeLinecap="round"
            fill={`url(#${gradientId})`}
            isAnimationActive={false}
            dot={false}
            activeDot={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
};

export default Sparkline;
