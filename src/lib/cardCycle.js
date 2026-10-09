/**
 * The visits on the CURRENT card (user, 2026-10-09: « the meter must restart
 * after a full card, claimed or not »). The server sends `cycle_visits` —
 * visits since the last full card — while `visits` stays the lifetime count
 * (tiers, « Visites »). Previews and the designer have no real customer, so
 * they fall back to `visits`.
 */
export function cycleVisits(customer) {
  const c = customer?.cycle_visits;
  if (c !== undefined && c !== null && Number.isFinite(Number(c))) return Math.max(0, Number(c));
  return parseInt(customer?.visits, 10) || 0;
}

/** Full cards not yet handed over — still valid at the counter. */
export const rewardsPending = (customer) => Math.max(0, parseInt(customer?.rewards_pending, 10) || 0);
