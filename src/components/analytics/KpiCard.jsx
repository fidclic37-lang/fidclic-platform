/**
 * KpiCard — metric tile for the dark Analytics page.
 *
 *   [icon chip]                            [delta pill]
 *   LABEL (uppercase, muted)
 *   BIG NUMBER  (tabular-nums, -0.02em)
 *   vs 14 Avr — 13 Mai
 *   ────────── sparkline bleeds to edges ──────────
 *
 * Renders as a <button> when onClick is provided so keyboard users can
 * activate it. Otherwise renders as a plain <div>.
 *
 * Accents: purple | pink | cyan | emerald | orange | amber. Each accent
 * tints the icon chip background, the delta pill (for positive deltas),
 * and the sparkline gradient.
 */
import React from 'react';
import Sparkline from './Sparkline';

// Chip colors are full CSS colors (not hue fragments) so the brand accent
// can ride the --flc-* vars and flip with the theme.
const chip = (tone) => ({
  chipBg: `color-mix(in srgb, ${tone} 12%, transparent)`,
  chipFg: tone,
});
// Cobalt mockup: every KPI chip is the same light-blue square with a blue
// glyph — the tone prop is kept for the sparkline and for other skins.
const ACCENT = {
  purple:  chip('var(--flc-tone-blue, #2F6BFF)'),
  cyan:    chip('var(--flc-tone-blue, #2F6BFF)'),
  emerald: chip('var(--flc-tone-blue, #2F6BFF)'),
  pink:    chip('var(--flc-tone-blue, #2F6BFF)'),
  orange:  chip('var(--flc-tone-blue, #2F6BFF)'),
  amber:   chip('var(--flc-tone-blue, #2F6BFF)'),
};

const DeltaPill = ({ delta }) => {
  if (delta == null || !isFinite(delta)) return null;
  const up = delta >= 0;
  const fmt = `${up ? '+' : '−'}${Math.abs(delta).toFixed(Math.abs(delta) < 10 ? 1 : 0)}%`;
  const tone = up
    ? { fg: 'var(--flc-ok, #0F8B58)', bg: 'color-mix(in srgb, var(--flc-ok, #0F8B58) 12%, transparent)' }
    : { fg: 'var(--flc-risk, #C22F45)', bg: 'color-mix(in srgb, var(--flc-risk, #C22F45) 12%, transparent)' };
  return (
    <span
      style={{
        fontSize: 10, fontWeight: 500, padding: '2px 7px', borderRadius: 99,
        color: tone.fg, background: tone.bg, fontVariantNumeric: 'tabular-nums',
        letterSpacing: '0.01em',
      }}
    >
      {fmt}
    </span>
  );
};

const KpiCard = ({
  icon: Icon,
  label,
  value,
  unit,
  delta,
  sublabel = 'vs 14 Avr — 13 Mai',
  accent = 'purple',
  sparklineData,
  onClick,
  loading = false,
  ariaLabel,
}) => {
  const palette = ACCENT[accent] || ACCENT.purple;
  const Tag = onClick ? 'button' : 'div';

  return (
    <Tag
      type={onClick ? 'button' : undefined}
      onClick={onClick}
      aria-label={ariaLabel || `${label}: ${value}${unit || ''}`}
      style={{
        position: 'relative',
        overflow: 'hidden',
        textAlign: 'left',
        cursor: onClick ? 'pointer' : 'default',
        background: 'var(--flc-card, #FFFFFF)',
        border: '1px solid var(--flc-line, #ECE3D2)',
        borderRadius: 18,
        padding: '14px 14px 0',
        boxShadow: '0 1px 2px rgba(16,24,40,.04), 0 1px 3px rgba(16,24,40,.03)',
        color: 'var(--flc-ink, #191410)',
        font: 'inherit',
        transition: 'transform 180ms cubic-bezier(.2,.7,.3,1), border-color 180ms ease',
      }}
      onMouseEnter={(e) => {
        if (onClick) {
          e.currentTarget.style.transform = 'translateY(-1px)';
          e.currentTarget.style.borderColor = 'var(--flc-line-hi, #D9D3CA)';
        }
      }}
      onMouseLeave={(e) => {
        if (onClick) {
          e.currentTarget.style.transform = '';
          e.currentTarget.style.borderColor = 'var(--flc-line, #ECE3D2)';
        }
      }}
    >
      {/* Top row: icon chip + delta pill */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 }}>
        {Icon ? (
          <div
            aria-hidden="true"
            style={{
              width: 30, height: 30, borderRadius: 9,
              background: palette.chipBg,
              display: 'grid', placeItems: 'center',
              color: palette.chipFg,
            }}
          >
            <Icon size={15} strokeWidth={2} />
          </div>
        ) : <span />}
        <DeltaPill delta={delta} />
      </div>

      {/* Label */}
      <div
        style={{
          fontSize: 10, letterSpacing: '0.12em', textTransform: 'uppercase',
          color: 'var(--flc-ink3, #524A40)', fontWeight: 500,
        }}
      >
        {label}
      </div>

      {/* Big number */}
      <div
        className="av2-num"
        style={{
          fontSize: 24, fontWeight: 500, lineHeight: 1.1, marginTop: 4,
          color: 'var(--flc-ink, #191410)',
        }}
      >
        {loading ? (
          <span
            aria-busy="true"
            style={{
              display: 'inline-block', width: 64, height: 22, borderRadius: 6,
              background: 'var(--flc-paper2, #F4F1EC)', verticalAlign: 'middle',
            }}
          />
        ) : (
          <>
            {value}
            {unit ? <span style={{ fontSize: 14, color: 'var(--flc-ink3, #524A40)', marginLeft: 2 }}>{unit}</span> : null}
          </>
        )}
      </div>

      {/* Subline (period) */}
      <div style={{ fontSize: 10, color: 'var(--flc-ink3, #524A40)', marginTop: 4, marginBottom: 8 }}>
        {sublabel}
      </div>

      {/* Sparkline — flush to bottom edge by negative-margin trick */}
      <div style={{ margin: '0 -14px' }}>
        <Sparkline data={sparklineData} accent={accent} height={32} ariaLabel={`Tendance — ${label}`} />
      </div>
    </Tag>
  );
};

export default KpiCard;
