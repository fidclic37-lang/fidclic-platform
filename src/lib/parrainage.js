// « Mes parrainages » on the card page (user, 2026-11-26): the words of each
// side's reward and each friend's line, from GET /api/card/{bc}/parrainages.
// Pure functions — tests in parrainage.test.js.

const ordinal = (n) => (n === 1 ? '1re' : `${n}e`);
const need = (p) => Math.max(1, Number(p?.need) || 1);

/** « +2 tampons », « +50 points », the offer as the shop wrote it, or « ». */
export function amountText(r) {
  if (!r || !r.label) return '';
  return r.kind === 'offer' ? r.label : `+${r.label}`;
}

function nextPart(p, side) {
  const next = p?.mode === 'first_then' ? p?.[side]?.next_label : '';
  return next ? `, puis +${next} à chaque visite` : '';
}

/** When the parrain (this card) is paid. */
export function meWhen(p) {
  const n = need(p);
  if (p?.mode === 'every') return `à chaque visite de votre ami${n > 1 ? `, dès sa ${ordinal(n)}` : ''}`;
  const first = n > 1 ? `quand votre ami vient ${n} fois` : 'quand votre ami vient en boutique';
  return first + nextPart(p, 'me');
}

/** When the friend is paid. */
export function friendWhen(p) {
  const n = need(p);
  if (p?.mode === 'every') return `à chaque visite${n > 1 ? `, dès sa ${ordinal(n)}` : ''}`;
  return `à sa ${ordinal(n)} visite` + nextPart(p, 'friend');
}

const KIND_LABEL = {
  stamps: ['Tampon gagné', 'Tampons gagnés'],
  points: ['Point gagné', 'Points gagnés'],
  offers: ['Offre gagnée', 'Offres gagnées'],
};

/** The « gagnés » tile, in what was really paid (a points payment made
 *  before the shop moved to tampons stays points). */
export function earnedStat(p) {
  const e = p?.earned || {};
  const kinds = ['stamps', 'points', 'offers'].filter((k) => Number(e[k]) > 0);
  if (kinds.length > 1) return { value: p.earned_label || '', label: 'Gagnés', mixed: true };
  if (kinds.length === 1) {
    const k = kinds[0], n = Number(e[k]);
    return { value: String(n), label: KIND_LABEL[k][n > 1 ? 1 : 0] };
  }
  const k = { stamps: 'stamps', points: 'points', offer: 'offers' }[p?.me?.kind];
  return { value: '0', label: k ? KIND_LABEL[k][1] : 'Récompenses gagnées' };
}

/** « 5 nov. » in Paris time, « » for nothing readable. */
export function dayFr(v) {
  if (!v) return '';
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return '';
  return new Intl.DateTimeFormat('fr-FR', { day: 'numeric', month: 'short', timeZone: 'Europe/Paris' }).format(d);
}

/** The line under a friend's first name. */
export function friendLine(f) {
  if (f?.status === 'rewarded') {
    const day = dayFr(f.rewarded_at);
    let s = day ? `Récompensé le ${day}` : 'Récompensé';
    if (f.given) s += ` · ${f.given} pour vous${Number(f.times) > 1 ? ` (${f.times} visites)` : ''}`;
    return s;
  }
  const day = dayFr(f?.joined_at);
  const n = need(f), v = Math.max(0, Number(f?.visits) || 0);
  const where = n === 1 && v === 0 ? '1re visite à faire' : `${v} visite${v > 1 ? 's' : ''} sur ${n}`;
  return `${day ? `Carte créée le ${day}` : 'Carte créée'} · ${where}`;
}

/** The « Vous gagnez / Votre ami gagne » row: programme on, something given. */
export function showRewards(p) {
  return !!(p && p.enabled && (p.me?.label || p.friend?.label));
}

export function statusNote(p) {
  return `« Récompensé » : votre ami est venu, la récompense est donnée. « En attente » : il a créé sa carte, la récompense arrive à sa ${ordinal(need(p))} visite.`;
}
