/**
 * The period a page reads its figures over — Tableau de bord and Analyses.
 *
 * A period is a short token, so it fits in the URL and in localStorage:
 *   '1' '7' '30' '90' '365'   the offered ones (« Aujourd'hui » is '1')
 *   '45d' / '6m'              one the merchant typed, in days or in months
 *   'mtd'                     « Ce mois-ci » — the 1st of this month until now
 *   'm2026-10'                a whole calendar month (1 → 28/29/30/31)
 *   'd2026-10-15'             one date
 *   'r2026-10-05_2026-10-20'  a from–to range
 * (user, 2026-11-03). Dates are the shop's — Paris — calendar.
 *
 * `periodParams(token)` is what the API reads: { days } for the first two,
 * { date_from, date_to } for the calendar ones (api/features/period.span).
 *
 * ONE PERIOD FOR BOTH PAGES, « CE MOIS-CI » ON THE 1ST
 *   The choice is kept under one key for the Tableau de bord and Analyses,
 *   with the month it was made in: a new month opens on « Ce mois-ci ».
 *
 * The API reaches back two years: 730 jours, 24 mois.
 */
export const MAX_DAYS = 730;
export const MAX_MONTHS = 24;
export const DEFAULT_PERIOD = 'mtd';
const KEY = 'fidclic:period';

export const PRESETS = [
  { key: '1', label: "Aujourd'hui" },
  { key: 'mtd', label: 'Ce mois-ci' },
  { key: '7', label: '7 derniers jours' },
  { key: '30', label: '30 derniers jours' },
  { key: '90', label: '90 derniers jours' },
  { key: '365', label: '12 derniers mois' },
];

const MOIS = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août',
  'septembre', 'octobre', 'novembre', 'décembre'];
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
const pad = (n) => String(n).padStart(2, '0');

/** Today in Paris, 'YYYY-MM-DD'. */
export const today = (now = new Date()) =>
  new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Paris' }).format(now);

const lastDay = (y, m) => new Date(Date.UTC(y, m, 0)).getUTCDate();       // m 1-12
const isDate = (s) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s || '');
  if (!m) return false;
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
  return mo >= 1 && mo <= 12 && d >= 1 && d <= lastDay(y, mo);
};
const dayNumber = (s) => Date.UTC(+s.slice(0, 4), +s.slice(5, 7) - 1, +s.slice(8, 10)) / 86400000;
/** The oldest date the API accepts. */
export const oldest = (now = new Date()) => {
  const d = new Date((dayNumber(today(now)) - (MAX_DAYS - 1)) * 86400000);
  return d.toISOString().slice(0, 10);
};

/** Why a from–to pair cannot be read, or '' when it can. */
export function rangeError(from, to, now = new Date()) {
  if (!isDate(from) || !isDate(to)) return 'Choisissez une date de début et une date de fin.';
  if (from > to) return 'La date de début est après la date de fin.';
  if (from > today(now)) return "Cette période n'a pas encore commencé.";
  if (from < oldest(now)) return 'Deux ans en arrière au maximum.';
  return '';
}

/** The months offered, this one first, back two years: [{ key, label }]. */
export function months(now = new Date()) {
  let [y, m] = today(now).split('-').map(Number);
  const out = [];
  for (let i = 0; i < MAX_MONTHS; i += 1) {
    out.push({ key: `m${y}-${pad(m)}`, label: `${cap(MOIS[m - 1])} ${y}${i === 0 ? ' (en cours)' : ''}` });
    if (m === 1) { y -= 1; m = 12; } else m -= 1;
  }
  return out;
}

function parse(token, now = new Date()) {
  const t = String(token ?? '').trim();
  if (t === 'mtd') return { kind: 'mtd' };
  let m = /^m(\d{4})-(\d{2})$/.exec(t);
  if (m) {
    const from = `${m[1]}-${m[2]}-01`;
    if (!isDate(from)) return null;
    const to = `${m[1]}-${m[2]}-${pad(lastDay(+m[1], +m[2]))}`;
    if (from > today(now) || to < oldest(now)) return null;
    return { kind: 'month', y: +m[1], m: +m[2], from, to };
  }
  m = /^d(\d{4}-\d{2}-\d{2})$/.exec(t);
  if (m) return rangeError(m[1], m[1], now) ? null : { kind: 'day', from: m[1], to: m[1] };
  m = /^r(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})$/.exec(t);
  if (m) return rangeError(m[1], m[2], now) ? null : { kind: 'range', from: m[1], to: m[2] };
  m = /^(\d+)([dm]?)$/.exec(t);
  if (!m) return null;
  const n = Number(m[1]);
  const unit = m[2] || 'd';
  if (!n || n < 1) return null;
  if (unit === 'd' && n > MAX_DAYS) return null;
  if (unit === 'm' && n > MAX_MONTHS) return null;
  return { kind: 'last', n, unit, preset: !m[2] && PRESETS.some((p) => p.key === String(n)) };
}

export const validPeriod = (token, now) => parse(token, now) !== null;
export const isCustomLast = (token) => { const p = parse(token); return !!p && p.kind === 'last' && !p.preset; };
export const lastParts = (token) => { const p = parse(token); return p && p.kind === 'last' ? p : null; };

export function periodDays(token) {
  const p = parse(token);
  if (!p) return 30;
  if (p.kind !== 'last') {
    const t = today();
    const from = p.kind === 'mtd' ? `${t.slice(0, 8)}01` : p.from;
    const to = p.kind === 'mtd' ? t : (p.to > t ? t : p.to);
    return dayNumber(to) - dayNumber(from) + 1;
  }
  if (p.unit === 'd') return p.n;
  const now = new Date();
  now.setHours(0, 0, 0, 0);
  const from = new Date(now);
  from.setMonth(from.getMonth() - p.n);
  return Math.min(MAX_DAYS, Math.max(1, Math.round((now - from) / 86400000)));
}

/** The query the API reads for this period. */
export function periodParams(token, now = new Date()) {
  const p = parse(token, now);
  if (!p) return { days: 30 };
  if (p.kind === 'last') return { days: periodDays(token) };
  if (p.kind === 'mtd') { const t = today(now); return { date_from: `${t.slice(0, 8)}01`, date_to: t }; }
  const o = oldest(now);
  return { date_from: p.from < o ? o : p.from, date_to: p.to };
}

const short = (s) => `${Number(s.slice(8, 10))} ${MOIS[Number(s.slice(5, 7)) - 1]}`;

export function periodLabel(token) {
  const p = parse(token);
  if (!p) return '30 derniers jours';
  if (p.kind === 'mtd') return 'Ce mois-ci';
  if (p.kind === 'month') return `${cap(MOIS[p.m - 1])} ${p.y}`;
  if (p.kind === 'day') return `${short(p.from)} ${p.from.slice(0, 4)}`;
  if (p.kind === 'range') {
    const [a, b] = [p.from, p.to];
    if (a.slice(0, 7) === b.slice(0, 7)) return `${Number(a.slice(8, 10))} → ${short(b)} ${b.slice(0, 4)}`;
    if (a.slice(0, 4) === b.slice(0, 4)) return `${short(a)} → ${short(b)} ${b.slice(0, 4)}`;
    return `${short(a)} ${a.slice(0, 4)} → ${short(b)} ${b.slice(0, 4)}`;
  }
  if (p.preset) return PRESETS.find((x) => x.key === String(p.n)).label;
  if (p.unit === 'm') return p.n === 1 ? 'Le dernier mois' : `${p.n} derniers mois`;
  return p.n === 1 ? "Aujourd'hui" : `${p.n} derniers jours`;
}

/** The period a page opens on: the link's (?period=, or an old ?days=),
 *  else the one chosen this month on either page, else « Ce mois-ci ». */
export function readPeriod(search = window.location.search) {
  const q = new URLSearchParams(search);
  for (const v of [q.get('period'), q.get('days')]) if (validPeriod(v)) return v;
  try {
    const s = JSON.parse(localStorage.getItem(KEY) || 'null');
    if (s && s.m === today().slice(0, 7) && validPeriod(s.p)) return s.p;
  } catch (_e) { /* ignore */ }
  return DEFAULT_PERIOD;
}

export function savePeriod(token) {
  try { localStorage.setItem(KEY, JSON.stringify({ p: token, m: today().slice(0, 7) })); } catch (_e) { /* ignore */ }
}
