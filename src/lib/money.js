/**
 * A French amount, the same everywhere (QA, 2026-10-08: the dashboard read
 * « 93,1 € », Segmentation « 145.33 € », Insights « 15,5 € »):
 * cents are always two digits — 93,10 € — and a whole amount has none —
 * 1 200 €.
 */
export function eur(n) {
  const v = Math.round((Number(n) || 0) * 100) / 100;
  const cents = Math.abs(v % 1) > 0.0001;
  return `${v.toLocaleString('fr-FR', { minimumFractionDigits: cents ? 2 : 0, maximumFractionDigits: 2 })} €`;
}

export default eur;
