import React from 'react';
import PeriodPicker from './PeriodPicker';

/**
 * ColorfulKpiTile — vivid KPI card.
 *
 * Design notes for the "make it pop" version:
 *
 *   • The tile sits on a soft-to-medium GRADIENT (not flat pastel). This
 *     gives it depth without breaking the calm palette.
 *   • The icon chip is now SOLID in the tone's vivid colour, with a white
 *     icon glyph. This is the single biggest "premium look" lever — a
 *     vivid chip in the corner of every card.
 *   • A decorative blurred circle ("glow") sits behind the icon chip in
 *     the same vivid colour, adding atmosphere without noise.
 *   • The big number is rendered in the tone's deep ink — vivid, but
 *     readable.
 *   • Sparkline area-fill opacity bumped to 0.22 so the line is more
 *     present, and the line stroke is 1.8px instead of 1.4px.
 *   • Hover lift + soft shadow growth makes the tile feel "real" when
 *     it's clickable.
 *
 * Existing call sites are 100% backward compatible — the `tone` prop
 * unlocks the new look; `accent` still works for the neutral white tile.
 */

// Octoboard-inspired premium SaaS look:
//   • Every tile sits on a clean near-white surface with a subtle shadow.
//   • The big number is a VIBRANT teal-blue across every tile (the hero
//     accent). Joyful, not muted.
//   • The icon chip is fully saturated in the tone's vivid colour with a
//     white glyph — the only category cue.
//   • Sparklines pick up the tone's vivid line so the trend reads.
// Same surface everywhere so the dashboard reads as one cohesive product.
const SHARED_SURFACE = '#F5F7FB';
const SHARED_LINE    = '#DCE3EF';
// The vibrant hero accent used for every big number, regardless of tone.
// Joyful teal-blue, picks up well against the cream surface.
const HERO_INK       = '#0F172A';

const TONE_STYLE = {
  // Mockup rule: blue = normal, green = growth / healthy, red = decrease /
  // at risk, grey = zero. The chip is a LIGHT tint with a coloured glyph.
  success: { vivid: '#16A34A', glow: 'rgba(22,163,74,0.12)',   line: '#16A34A' },
  danger:  { vivid: '#E11D48', glow: 'rgba(225,29,72,0.12)',   line: '#E11D48' },
  warning: { vivid: '#E11D48', glow: 'rgba(225,29,72,0.12)',   line: '#E11D48' },
  info:    { vivid: '#2F6BFF', glow: 'rgba(47,107,255,0.12)',  line: '#2F6BFF' },
  purple:  { vivid: '#2F6BFF', glow: 'rgba(47,107,255,0.12)',  line: '#2F6BFF' },
  neutral: { vivid: '#94A3B8', glow: 'rgba(148,163,184,0.14)', line: '#94A3B8' },
};

/** Inline sparkline with bigger presence: thicker stroke + denser fill
 *  so the chart reads as part of the tile, not decoration. */
const Sparkline = ({ points = [], stroke = '#64748B', width = 100, height = 32 }) => {
  if (!Array.isArray(points) || points.length < 2) return null;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = max - min || 1;
  const stepX = width / (points.length - 1);
  const xy = points.map((p, i) => [i * stepX, height - 3 - ((p - min) / range) * (height - 6)]);
  const d = xy.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
  const area = `${d} L${width.toFixed(1)},${height.toFixed(1)} L0,${height.toFixed(1)} Z`;
  return (
    <svg
      width="100%"
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      aria-hidden="true"
      style={{ display: 'block' }}
    >
      <path d={area} fill={stroke} opacity="0.22" />
      <path d={d} fill="none" stroke={stroke} strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
};

// Delta colors are DIRECTION-based, never metric-based: a "+" delta is
// always green, a "-" delta is always red. A flat delta is muted.
const DELTA_STYLE = {
  up:   { bg: 'rgba(22,163,74,0.12)',  fg: '#15803D', dot: '#16A34A' },
  down: { bg: 'rgba(225,29,72,0.12)',  fg: '#1D4ED8', dot: '#E11D48' },
  flat: { bg: 'rgba(100,116,139,0.12)', fg: '#334155', dot: '#64748B' },
};

const DeltaPill = ({ delta }) => {
  if (!delta || typeof delta.value !== 'number') return null;
  const sign = delta.sign || (delta.value > 0 ? 'up' : delta.value < 0 ? 'down' : 'flat');
  const s = DELTA_STYLE[sign] || DELTA_STYLE.flat;
  const arrow = sign === 'up' ? '↗' : sign === 'down' ? '↘' : '→';
  const abs = Math.abs(delta.value);
  return (
    <span
      className="inline-flex items-center gap-1 text-[11px] rounded-full px-2 py-0.5"
      style={{
        color: s.fg,
        background: s.bg,
        fontWeight: 600,
        boxShadow: `inset 0 0 0 1px ${s.dot}33`,
        fontVariantNumeric: 'tabular-nums',
      }}
    >
      <span aria-hidden="true" style={{ color: s.dot }}>{arrow}</span>
      {sign === 'up' && '+'}{sign === 'down' && '-'}{abs.toFixed(abs < 10 ? 1 : 0)}%
    </span>
  );
};

const ColorfulKpiTile = ({
  icon: Icon,
  title,
  value,
  sublabel,
  delta,
  trend,
  accent = '#2F6BFF',
  tone,
  onClick,
  period,
  onPeriodChange,
  topRight,
  loading = false,
  className = '',
}) => {
  const palette     = tone ? TONE_STYLE[tone] || TONE_STYLE.neutral : null;
  const vivid       = palette ? palette.vivid : accent;
  const glow        = palette ? palette.glow  : `${accent}33`;
  const sparkLine   = palette ? palette.line  : HERO_INK;
  // Mockup "Activité" tiles: the number carries the tone — blue for a normal
  // count, green for growth, red for at-risk, grey for zero; navy otherwise.
  const numberInk   = vivid;

  const Tag = onClick ? 'button' : 'div';
  return (
    <Tag
      onClick={onClick}
      className={`relative w-full text-left rounded-2xl overflow-hidden ft-lift ${onClick ? 'cursor-pointer' : ''} ${className}`}
      style={{
        background: SHARED_SURFACE,
        color: 'var(--ink)',
        border: `1px solid ${SHARED_LINE}`,
        boxShadow: '0 1px 2px rgba(16,24,40,0.04)',
        padding: '11px 13px 9px',
        minHeight: 112,
      }}
    >
      {/* Subtle corner glow in the tone colour — only added when there's a
          tone. Adds restraint-level depth without competing with the number. */}

      {topRight && (
        <div className="absolute top-1.5 right-1.5 z-10" onClick={(e) => e.stopPropagation()}>
          {topRight}
        </div>
      )}

      <div className="relative flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <p
            className="text-[9.5px] uppercase"
            style={{
              color: 'var(--ink-mute)',
              fontWeight: 700,
              letterSpacing: '0.12em',
            }}
          >
            {title}
          </p>
          <div className="mt-1 flex items-baseline gap-1.5 flex-wrap">
            <span
              style={{
                fontSize: 26,
                lineHeight: 1,
                fontWeight: 700,
                color: numberInk,
                letterSpacing: '-0.024em',
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              {loading
                ? <span className="inline-block w-12 h-6 rounded animate-pulse" style={{ background: 'rgba(0,0,0,0.06)' }} />
                : value}
            </span>
            <DeltaPill delta={delta} />
          </div>
          {sublabel && (
            <p
              className="mt-0.5 text-[10.5px] line-clamp-2"
              style={{ color: 'var(--ink-mute)' }}
            >
              {sublabel}
            </p>
          )}
        </div>

        {/* Icon chip — SOLID vivid colour with white glyph. This is the single
            most "premium" lever; every modern dashboard uses this pattern. */}
        {Icon && (
          <div
            className="shrink-0 w-8 h-8 rounded-lg flex items-center justify-center relative"
            style={{
              background: glow,
              color: vivid,
            }}
          >
            <Icon size={16} strokeWidth={2} />
          </div>
        )}
      </div>

      {/* Sparkline along the bottom edge of the card, full width, taller than
          before so the trend reads as data not garnish. */}
      {Array.isArray(trend) && trend.length >= 2 && (
        <div className="mt-2 -mx-1 -mb-1">
          <Sparkline points={trend} stroke={sparkLine} height={24} />
        </div>
      )}

      {period && onPeriodChange && (
        <div className="relative mt-2 flex justify-start">
          <PeriodPicker
            value={period.value}
            unit={period.unit}
            onChange={onPeriodChange}
            accent={palette ? vivid : accent}
            compact
          />
        </div>
      )}
    </Tag>
  );
};

export default ColorfulKpiTile;
