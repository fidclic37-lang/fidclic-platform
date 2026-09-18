/**
 * ScoreWidget — radial bar showing a 0-100 "loyalty score" with a
 * trend line (e.g. "+6 vs sem. dernière").
 *
 * Pure SVG (no recharts) — keeps the streaming-render footprint tiny.
 */
import React from 'react';

const ScoreWidget = ({ score = 0, max = 100, delta, denominator = '100' }) => {
  const clamped = Math.max(0, Math.min(max, Number(score) || 0));
  const pct = max > 0 ? clamped / max : 0;
  const radius = 24;
  const circumference = 2 * Math.PI * radius;
  const dashOffset = circumference * (1 - pct);

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
      <svg viewBox="0 0 64 64" width="56" height="56" aria-hidden="true">
        <defs>
          <linearGradient id="av2-score-grad" x1="0" x2="1">
            <stop offset="0%"   stopColor="var(--flc-accent, #C73E2C)" />
            <stop offset="100%" stopColor="var(--flc-accent-2, #E8703A)" />
          </linearGradient>
        </defs>
        <circle cx="32" cy="32" r={radius} fill="none" stroke="var(--flc-line, #ECE3D2)" strokeWidth="6" />
        <circle
          cx="32" cy="32" r={radius}
          fill="none"
          stroke="url(#av2-score-grad)"
          strokeWidth="6"
          strokeLinecap="round"
          strokeDasharray={`${circumference}`}
          strokeDashoffset={`${dashOffset}`}
          transform="rotate(-90 32 32)"
          style={{ transition: 'stroke-dashoffset 400ms cubic-bezier(.2,.7,.3,1)' }}
        />
        <text
          x="32" y="36"
          textAnchor="middle"
          fill="var(--flc-ink, #191410)"
          fontSize="14"
          fontWeight="500"
          fontFamily="Inter, system-ui, sans-serif"
          style={{ fontVariantNumeric: 'tabular-nums' }}
        >
          {clamped}
        </text>
      </svg>
      <div style={{ fontSize: 11, color: 'var(--flc-ink2, #3A332B)', lineHeight: 1.45 }}>
        {delta != null && isFinite(delta) ? (
          <div style={{ color: delta >= 0 ? 'var(--flc-ok, #0F8B58)' : 'var(--flc-risk, #C22F45)' }}>
            {delta >= 0 ? '+' : '−'}{Math.abs(delta)} vs sem. dernière
          </div>
        ) : <div style={{ color: 'var(--flc-ink3, #524A40)' }}>—</div>}
        <div style={{ color: 'var(--flc-ink3, #524A40)' }} className="av2-num">{clamped} / {denominator}</div>
      </div>
    </div>
  );
};

export default ScoreWidget;
