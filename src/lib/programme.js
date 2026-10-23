/*
 * The card's programme as the till applies it (api/features/loyalty_card._programme),
 * and the words that describe it to a customer (QA R7 F28, 2026-10-18: a
 * « Points par euro » card told its customers « Encore 9 visites » and
 * « +10 pts par visite »). One place, so the card, its « Le programme » sheet
 * and the designer's preview say the same thing as the Wallet pass.
 */
const KINDS = ['points_euro', 'points_visit', 'stamps', 'cashback'];

export function programmeOf(card = {}) {
  const k = String(card.programme_kind || '').trim().toLowerCase();
  if (KINDS.includes(k)) return k;
  const p = String(card.programme || '').trim().toLowerCase();
  if (p === 'points') return 'points_euro';
  if (KINDS.includes(p)) return p;
  return card.points_mode === 'per_euro' ? 'points_euro' : 'stamps';
}

const n = (v, d) => { const x = Number(v); return Number.isFinite(x) && x > 0 ? x : d; };
const fr = (v) => String(v).replace('.', ',');
const pts = (v) => `${v} point${v > 1 ? 's' : ''}`;

/** How a customer earns, in one line — null for a tampons card (one visit, one tampon). */
export function earningRule(card = {}) {
  const kind = programmeOf(card);
  if (kind === 'points_euro') return `${fr(n(card.points_per_euro, 10))} pt${n(card.points_per_euro, 10) > 1 ? 's' : ''} par euro dépensé`;
  if (kind === 'points_visit') return `+${n(card.points_per_visit, 10)} pts à chaque passage`;
  if (kind === 'cashback') return `${fr(n(card.cashback_rate, 5))} % de chaque achat dans votre cagnotte`;
  return null;
}

/** What the card still owes for its reward, in the programme's own unit. */
export function rewardProgress(card = {}, { points = 0, stamps = 0, threshold = 10 } = {}) {
  const reward = card.reward_description || 'votre récompense';
  if (programmeOf(card) === 'stamps') {
    const left = Math.max(0, threshold - stamps);
    return { left, unit: left > 1 ? 'tampons' : 'tampon', reward,
      line: left > 0 ? `Encore ${left} ${left > 1 ? 'tampons' : 'tampon'} · ${reward}` : reward,
      rule: `${reward} après ${threshold} tampon${threshold > 1 ? 's' : ''}` };
  }
  const goal = parseInt(card.reward_points, 10) || 0;
  if (!goal) return { left: null, unit: 'points', reward, line: reward, rule: reward };
  const left = Math.max(0, goal - (parseInt(points, 10) || 0));
  return { left, unit: 'points', reward,
    line: left > 0 ? `Encore ${pts(left)} · ${reward}` : 'Récompense débloquée : présentez votre carte !',
    rule: `${reward} dès ${pts(goal)}` };
}

/* A cagnotte (« Cagnotte (% du ticket) ») is euros, not points (QA R7 F39,
   user 2026-10-20: « cashback ko euros mein hi dikhao »). Its balance is kept
   in cents, like every other ledger. */
export const isCashback = (card = {}) => programmeOf(card) === 'cashback';
export const euros = (cents) => `${(Number(cents || 0) / 100).toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`;
/** « 1,00 € » on a cagnotte card, « 100 pts » elsewhere. */
export const balanceText = (card = {}, points = 0) => (isCashback(card) ? euros(points) : `${parseInt(points, 10) || 0} pts`);
/** The balance's own name: « Cagnotte », or the card's « Points » label. */
export const balanceLabel = (card = {}) => (isCashback(card)
  ? ((card.points_label && card.points_label.toLowerCase() !== 'points') ? card.points_label : 'Cagnotte')
  : (card.points_label || 'Points'));
