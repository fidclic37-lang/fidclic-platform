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

// ---------------------------------------------------------------- words and pictures
// « Vos offres » lives in the card page since round 4 (user, 2026-11-26,
// components/CardOffersContent); the same helpers as the old page.

/**
 * A campaign written with {first_name} / {prenom} reads with the customer's
 * own — and the Campagnes wizard's {nom_commerce}, {points}, {visites},
 * {prochaine_récompense}, {points_manquants}, read from `c` (the customer plus
 * _shop, _reward, _missing). Text only: React escapes what it draws.
 */
export const personal = (text, c = {}) => String(text ?? '')
  .replace(/\{(first_name|prenom|prénom)\}/gi, String(c?.name || '').split(' ')[0] || '')
  .replace(/\{(name|nom)\}/gi, c?.name || '')
  .replace(/\{(nom_commerce|business_name)\}/gi, c?._shop || '')
  .replace(/\{points\}/gi, String(c?.points ?? 0))
  .replace(/\{(visites|visits)\}/gi, String(c?.visits ?? 0))
  .replace(/\{(prochaine_récompense|prochaine_recompense)\}/gi, c?._reward || 'votre récompense')
  .replace(/\{(points_manquants|points_to_next_reward|points_remaining)\}/gi, String(c?._missing ?? 0));

// The shop's trade (Mon établissement › secteur) gives the pictures when an
// offer has no photo of its own: [emoji, tint class].
const SECTOR_LOOK = {
  cafe: ['☕', 'cafe'], restaurant: ['🍽️', 'resto'], pizzeria: ['🍕', 'pizza'], bakery: ['🥐', 'bakery'],
  bar: ['🍹', 'bar'], spa: ['💆', 'spa'], salon: ['💇', 'salon'], gym: ['💪', 'gym'], retail: ['🛍️', 'retail'],
};
export const sectorLook = (sector) => (Object.prototype.hasOwnProperty.call(SECTOR_LOOK, sector) ? SECTOR_LOOK[sector] : ['🎁', 'other']);

const REWARD_PICS = [
  [/dessert|g[âa]teau|p[âa]tisserie|cookie|cr[êe]pe|glace/i, '🍰'],
  [/caf[ée]|coffee|expresso|espresso|cappuccino|latte|th[ée]\b/i, '☕'],
  [/cocktail|bi[èe]re|verre|ap[ée]ro/i, '🍹'],
  [/boisson|soda|jus|smoothie/i, '🥤'],
  [/pizza/i, '🍕'],
  [/burger|sandwich|tacos|kebab/i, '🍔'],
  [/croissant|viennoiserie|pain|baguette/i, '🥐'],
  [/menu|repas|plat|d[ée]jeuner|d[îi]ner/i, '🍽️'],
  [/coupe|brushing|coiffure|barbe/i, '💇'],
  [/massage|soin|manucure/i, '💆'],
  [/%|remise|r[ée]duction|bon d.achat|€/i, '🏷️'],
];
/** What the reward is, as a picture: its words first, then the trade. */
export const rewardPic = (text, sector) => (REWARD_PICS.find(([re]) => re.test(text || '')) || [])[1] || sectorLook(sector)[0];

/** The small badge beside an offer: 'discount', 'gift' (something free) or 'news'. */
export function badgeKind(item) {
  const t = `${item?.title || ''} ${item?.description || item?.body || ''}`;
  if (/%|remise|r[ée]duction|-\s?\d/i.test(t)) return 'discount';
  if (/offert|gratuit|achet[ée]|cadeau/i.test(t)) return 'gift';
  return 'news';
}
