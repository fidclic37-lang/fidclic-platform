/**
 * The offers a customer has running right now, as the card shows them: the
 * shop's own offer first, then the campaigns still live, newest first.
 *
 * ONE list for the card's « Mes offres · N en cours » and the offers page behind
 * it (user, 2026-11-25: the card said « 2 en cours », the page « Pas d'offre en
 * ce moment »). The server already keeps only the live campaigns in `offers`
 * (défis apart, they have their own « Défi en cours »); `notifications` is every
 * campaign of the last 45 days, ended ones included, so it never counts here.
 */
const ts = (s) => {
  const t = Date.parse(s || '');
  return Number.isFinite(t) ? t : 0;
};

export function liveOffers(data, now = Date.now()) {
  const seen = new Set();
  const out = [];
  for (const o of data?.offers || []) {
    if (!o || !o.id || seen.has(o.id)) continue;
    if (o.valid_until && ts(o.valid_until) && ts(o.valid_until) < now) continue;
    seen.add(o.id);
    out.push({ ...o, _ts: o.kind === 'primary' ? 9e15 : ts(o.sent_at) });
  }
  return out.sort((a, b) => b._ts - a._ts);
}
