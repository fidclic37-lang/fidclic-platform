/*
 * « Ma carte en ligne » (MyWalletCardPage, photo/tabs redesign 2026-11-25):
 * the words the page shows, worked out here so the page only draws them.
 *
 *   activityTime  « Aujourd’hui · 14:26 », « Hier · 11:03 », « 12 nov. · 09:17 »
 *                 — the shop's clock (Europe/Paris), 24 h, never AM/PM
 *   activityRow   one line of « Mes dernières activités »
 *   pointsBox     the points / tampons / cagnotte box under the photo
 *   tabFromSearch / searchForTab   the bottom tabs in the address bar
 *   socialLinks   the shop's networks for « Suivez-nous »
 *
 * Run the tests: node --test src/lib/cardPage.test.js
 */
import { programmeOf, earningRule, isCashback, euros } from './programme.js';
import { cycleVisits } from './cardCycle.js';

const TZ = 'Europe/Paris';

// ---------------------------------------------------------------- times

// The API writes naive UTC datetimes (« 2026-11-25T13:26:00 ») — no zone means UTC.
const NAIVE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/;
function toMs(at) {
  if (typeof at === 'number') return Number.isFinite(at) ? at : NaN;
  if (typeof at !== 'string' || !at.trim()) return NaN;
  const s = at.trim();
  return Date.parse(NAIVE.test(s) ? `${s}Z` : s);
}

const dayFmt = new Intl.DateTimeFormat('en-CA', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit' });
const clockFmt = new Intl.DateTimeFormat('fr-FR', { timeZone: TZ, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
const shortFmt = new Intl.DateTimeFormat('fr-FR', { timeZone: TZ, day: 'numeric', month: 'short' });
const longFmt = new Intl.DateTimeFormat('fr-FR', { timeZone: TZ, day: 'numeric', month: 'short', year: 'numeric' });

const parisDay = (ms) => dayFmt.format(ms);                 // « 2026-11-25 »
function dayBefore(ymd) {
  const [y, m, d] = ymd.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d - 1)).toISOString().slice(0, 10);
}

/** « Aujourd’hui · 14:26 » / « Hier · 11:03 » / « 12 nov. · 09:17 » / « 31 déc. 2025 · 23:30 », or ''. */
export function activityTime(at, now = Date.now()) {
  const ms = toMs(at);
  if (!Number.isFinite(ms)) return '';
  const clock = clockFmt.format(ms);
  const day = parisDay(ms);
  const today = parisDay(now);
  if (day === today) return `Aujourd’hui · ${clock}`;
  if (day === dayBefore(today)) return `Hier · ${clock}`;
  const sameYear = day.slice(0, 4) === today.slice(0, 4);
  return `${(sameYear ? shortFmt : longFmt).format(ms)} · ${clock}`;
}

// ---------------------------------------------------------------- activity rows

const pos = (v) => { const n = Number(v); return Number.isFinite(n) && n > 0 ? Math.round(n) : 0; };
const num = (n) => n.toLocaleString('fr-FR');
const ptsText = (n) => `+ ${num(n)} point${n > 1 ? 's' : ''}`;
const stampsText = (n) => `+ ${num(n)} tampon${n > 1 ? 's' : ''}`;

function earned(item, card) {
  const stamps = pos(item.stamps);
  const points = pos(item.points);
  if (programmeOf(card) === 'stamps' && stamps) return stampsText(stamps);
  if (points) return isCashback(card) ? `+ ${euros(points)}` : ptsText(points);
  if (stamps) return stampsText(stamps);
  return null;
}

/** One activity line: { icon, title, sub, plus } — null for anything unknown. */
export function activityRow(item, card = {}) {
  if (!item || typeof item !== 'object') return null;
  if (item.kind === 'visit') {
    const stampsCard = programmeOf(card) === 'stamps';
    const icon = stampsCard ? 'stamp' : 'coin';
    const won = earned(item, card);
    if (!won) return { icon, title: 'Visite en magasin', sub: '', plus: null };
    const stampLine = won.includes('tampon');
    return { icon, title: won, sub: stampLine ? 'Visite en magasin' : 'Achat en magasin', plus: null };
  }
  if (item.kind === 'reward') {
    return { icon: 'gift', title: 'Récompense débloquée',
      sub: String(item.title || card.reward_description || 'Votre récompense'), plus: null };
  }
  if (item.kind === 'referral') {
    const friend = String(item.friend || '').trim();
    const plus = earned(item, card);
    if (item.role === 'filleul') {
      return { icon: 'people', title: 'Bienvenue', sub: `parrainé par ${friend || 'un proche'}`, plus };
    }
    return { icon: 'people', title: 'Parrainage validé', sub: `${friend || 'Un proche'} a rejoint`, plus };
  }
  return null;
}

// ---------------------------------------------------------------- the points box

const READY = 'Votre récompense est prête : présentez votre carte en caisse !';
const leftLine = (left, one, many) => (left === 1
  ? { message: `Plus qu’un ${one} pour obtenir votre récompense !`, strong: `un ${one}` }
  : { message: `Plus que ${num(left)} ${many} pour obtenir votre récompense !`, strong: `${num(left)} ${many}` });

/**
 * What the box under the photo says: { label, big, unit, message, strong,
 * scale, progress } — progress 0..1, or null when the card has no goal.
 * `strong` is the part of `message` set in bold (null: nothing bold).
 */
export function pointsBox(card = {}, customer = {}) {
  card = card || {};
  customer = customer || {};
  const kind = programmeOf(card);
  const reward = card.reward_description || 'votre récompense';
  if (kind === 'stamps') {
    const threshold = pos(card.reward_threshold) || pos(card.reward_threshold_stamps) || 10;
    const perStamp = pos(card.visits_per_stamp) || 1;
    const stamps = Math.min(threshold, Math.floor(cycleVisits(customer) / perStamp));
    const left = threshold - stamps;
    const words = left > 0 ? leftLine(left, 'tampon', 'tampons') : { message: READY, strong: null };
    return { label: 'Mes tampons', big: String(stamps), unit: `/ ${threshold} tampons`, ...words,
      scale: `${stamps} / ${threshold} tampons · ${reward}`, progress: Math.round((stamps / threshold) * 1000) / 1000 };
  }
  const balance = parseInt(customer.points, 10) || 0;
  if (kind === 'cashback') {
    return { label: 'Ma cagnotte', big: euros(balance), unit: '', message: earningRule(card) || '', strong: null,
      scale: card.reward_description || '', progress: null };
  }
  const goal = pos(card.reward_points);
  const base = { label: 'Mes points fidélité', big: num(balance), unit: 'points' };
  if (!goal) return { ...base, message: earningRule(card) || '', strong: null, scale: '', progress: null };
  const left = Math.max(0, goal - balance);
  const words = left > 0 ? leftLine(left, 'point', 'points') : { message: READY, strong: null };
  return { ...base, ...words, scale: `${num(Math.min(balance, goal))} / ${num(goal)} points`,
    progress: Math.min(1, Math.round((balance / goal) * 1000) / 1000) };
}

// ---------------------------------------------------------------- tabs in the URL

export const TABS = ['accueil', 'carte', 'recompenses', 'compte'];
const VIEWS = [...TABS, 'historique'];
const ONE_SHOT = ['offre', 'notify', 'wallet', 'k'];

/** The tab the address bar asks for. « programme » (the Wallet tile) is Récompenses. */
export function tabFromSearch(search) {
  const q = new URLSearchParams(typeof search === 'string' ? search : '');
  const o = (q.get('onglet') || '').toLowerCase();
  if (o === 'programme') return 'recompenses';
  if (VIEWS.includes(o)) return o;
  if (!o && q.get('wallet') === 'apple') return 'carte';
  return 'accueil';
}

/** The address bar for `tab`: the shop's view stays, one-shot params go. */
export function searchForTab(search, tab) {
  const q = new URLSearchParams(typeof search === 'string' ? search : '');
  for (const k of ONE_SHOT) q.delete(k);
  q.delete('onglet');
  if (VIEWS.includes(tab) && tab !== 'accueil') q.set('onglet', tab);
  const s = q.toString();
  return s ? `?${s}` : '';
}

// ---------------------------------------------------------------- networks

const NETWORKS = {
  instagram: 'Instagram', tiktok: 'TikTok', snapchat: 'Snapchat', facebook: 'Facebook', youtube: 'YouTube',
  x: 'X', twitter: 'X', linkedin: 'LinkedIn', pinterest: 'Pinterest', whatsapp: 'WhatsApp',
};

/** [{ network, label, url }] — https links only, in the shop's order. */
export function socialLinks(socials) {
  if (!Array.isArray(socials)) return [];
  const out = [];
  for (const s of socials) {
    if (!s || typeof s !== 'object') continue;
    const url = String(s.url || '').trim();
    if (!/^https:\/\/[^\s/]+\.[^\s]+$/i.test(url)) continue;
    const raw = String(s.network || '').trim().toLowerCase();
    const network = raw || 'site';
    const label = NETWORKS[network] || (raw ? raw.charAt(0).toUpperCase() + raw.slice(1) : 'Site web');
    out.push({ network: network === 'twitter' ? 'x' : network, label, url });
  }
  return out;
}
