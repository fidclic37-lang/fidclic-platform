/**
 * TopProductsList — ranked list of products with gradient progress bars.
 *
 * Props:
 *   items: [{ name, revenue, pct }]
 *     - pct is 0..1 (proportion of the top item's revenue)
 */
import React from 'react';

const GRADIENTS = [
  ['var(--flc-series-1, #2F6BFF)', 'var(--flc-series-4, #1D4ED8)'],
  ['var(--flc-series-1, #2F6BFF)', 'var(--flc-series-2, #93B4FF)'],
  ['var(--flc-series-2, #93B4FF)', 'var(--flc-series-2, #93B4FF)'],
  ['var(--flc-series-2, #93B4FF)', 'var(--flc-series-3, #C7D7FF)'],
  ['var(--flc-series-3, #C7D7FF)', 'var(--flc-series-3, #C7D7FF)'],
];

const fmtEUR = (n) =>
  Number(n || 0).toLocaleString('fr-FR', { maximumFractionDigits: 0 }) + ' €';

const TopProductsList = ({ items = [] }) => {
  if (!items.length) {
    return (
      <div style={{ display: 'grid', placeItems: 'center', height: 120, color: 'var(--flc-ink3, #524A40)', fontSize: 12 }}>
        Aucun produit suivi pour l'instant.
      </div>
    );
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {items.map((it, i) => {
        const [from, to] = GRADIENTS[i % GRADIENTS.length];
        const pctClamped = Math.max(0.03, Math.min(1, Number(it.pct) || 0));
        return (
          <div key={`${it.name}-${i}`}>
            <div
              style={{
                display: 'flex', justifyContent: 'space-between',
                fontSize: 12, marginBottom: 4, color: 'var(--flc-ink2, #3A332B)',
              }}
            >
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0, marginRight: 12 }}>
                {it.name}
              </span>
              <span className="av2-num" style={{ color: 'var(--flc-ink3, #524A40)', flexShrink: 0 }}>
                {fmtEUR(it.revenue)}
              </span>
            </div>
            <div
              style={{
                height: 4, background: 'var(--flc-line, #ECE3D2)',
                borderRadius: 99, overflow: 'hidden',
              }}
            >
              <div
                style={{
                  width: `${(pctClamped * 100).toFixed(1)}%`,
                  height: '100%',
                  background: `linear-gradient(90deg, ${from}, ${to})`,
                  transition: 'width 250ms cubic-bezier(.2,.7,.3,1)',
                }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
};

export default TopProductsList;
