/**
 * RevenueAreaChart — headline number + dark area chart.
 *
 * Props:
 *   total:    number — headline (formatted by parent)
 *   unit:     "€" by default
 *   delta:    +/- percentage (optional)
 *   data:     [{ x, value }] — area series
 *   height:   px (default 80)
 *   label:    section label (default "REVENU MENSUEL")
 */
import React from 'react';
import { ResponsiveContainer, AreaChart, Area, Tooltip } from 'recharts';

const TOOLTIP_STYLE = {
  background: 'var(--flc-card, #FFFFFF)',
  border: '1px solid var(--flc-line, #E7E5E4)',
  borderRadius: 10,
  color: 'var(--flc-ink, #191410)',
  fontSize: 12,
  padding: '6px 10px',
  boxShadow: '0 8px 24px -12px rgba(16,24,40,.25)',
};

const RevenueAreaChart = ({ total, unit = '€', delta, data = [], height = 80, label = 'Revenu mensuel' }) => {
  const up = (delta ?? 0) >= 0;
  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 4 }}>
        <div>
          <div style={{ fontSize: 10, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--flc-ink3, #524A40)', fontWeight: 500 }}>
            {label}
          </div>
          <div className="av2-num" style={{ fontSize: 26, fontWeight: 500, color: 'var(--flc-ink, #191410)', lineHeight: 1.05, marginTop: 2 }}>
            {total ?? '—'}
            {unit ? <span style={{ fontSize: 14, color: 'var(--flc-ink3, #524A40)', marginLeft: 4 }}>{unit}</span> : null}
          </div>
        </div>
        {delta != null && isFinite(delta) ? (
          <span
            style={{
              fontSize: 10, fontWeight: 500, padding: '3px 8px', borderRadius: 99,
              color: up ? 'var(--flc-ok, #0F8B58)' : 'var(--flc-risk, #C22F45)',
              background: up ? 'color-mix(in srgb, var(--flc-ok, #0F8B58) 12%, transparent)' : 'color-mix(in srgb, var(--flc-risk, #C22F45) 12%, transparent)',
              fontVariantNumeric: 'tabular-nums',
            }}
          >
            {up ? '+' : '−'}{Math.abs(delta).toFixed(1)}%
          </span>
        ) : null}
      </div>
      <div role="img" aria-label={`Tendance du revenu, ${data.length} points`} style={{ height }}>
        {data.length >= 2 ? (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data} margin={{ top: 0, right: 0, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id="av2-rev-grad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%"   stopColor="var(--flc-accent, #C73E2C)" stopOpacity={0.5} />
                  <stop offset="100%" stopColor="var(--flc-accent, #C73E2C)" stopOpacity={0} />
                </linearGradient>
              </defs>
              <Area
                type="monotone"
                dataKey="value"
                stroke="var(--flc-accent-2, #E8703A)"
                strokeWidth={2}
                fill="url(#av2-rev-grad)"
                isAnimationActive={false}
                dot={false}
              />
              <Tooltip
                contentStyle={TOOLTIP_STYLE}
                labelStyle={{ color: 'var(--flc-ink3, #524A40)', fontSize: 11 }}
                cursor={{ stroke: 'color-mix(in srgb, var(--flc-accent-2, #E8703A) 30%, transparent)', strokeWidth: 1 }}
              />
            </AreaChart>
          </ResponsiveContainer>
        ) : (
          <div style={{ display: 'grid', placeItems: 'center', height: '100%', fontSize: 11, color: 'var(--flc-ink3, #524A40)' }}>
            Pas assez de données pour tracer la tendance.
          </div>
        )}
      </div>
    </>
  );
};

export default RevenueAreaChart;
