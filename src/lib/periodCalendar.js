/**
 * The simpler period menu (user, 2026-11-21): three tabs — Rapide, Mois,
 * Calendrier. Rapide holds the presets and « les derniers N jours / mois »,
 * Mois is a grid of the 24 months the API reaches, Calendrier is one month
 * of days where one click picks a day and a second click closes a du → au
 * range. The tokens are lib/period.js's — nothing the API reads changes.
 *
 * Dates are 'YYYY-MM-DD' strings on the shop's (Paris) calendar; months are
 * 'YYYY-MM'. Pure functions, no React, so node --test covers them.
 */
import { MAX_MONTHS, today, oldest, validPeriod } from './period.js';

const MOIS = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août',
  'septembre', 'octobre', 'novembre', 'décembre'];
const SHORT = ['Janv.', 'Févr.', 'Mars', 'Avr.', 'Mai', 'Juin', 'Juil.', 'Août', 'Sept.', 'Oct.', 'Nov.', 'Déc.'];
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
const pad = (n) => String(n).padStart(2, '0');
const lastDay = (y, m) => new Date(Date.UTC(y, m, 0)).getUTCDate();       // m 1-12
const isDate = (s) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s || '');
  if (!m) return false;
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
  return mo >= 1 && mo <= 12 && d >= 1 && d <= lastDay(y, mo);
};
const isMonth = (s) => {
  const m = /^(\d{4})-(\d{2})$/.exec(s || '');
  return !!m && Number(m[2]) >= 1 && Number(m[2]) <= 12;
};

/** « 15 octobre 2026 » — the day buttons' names. */
export const dayLabel = (iso) =>
  `${Number(iso.slice(8, 10))} ${MOIS[Number(iso.slice(5, 7)) - 1]} ${iso.slice(0, 4)}`;

/** « Octobre 2026 ». */
export const monthLabel = (ym) => `${cap(MOIS[Number(ym.slice(5, 7)) - 1])} ${ym.slice(0, 4)}`;

/** 'YYYY-MM' moved by `delta` months. */
export function shiftMonth(ym, delta) {
  const [y, m] = ym.split('-').map(Number);
  const i = y * 12 + (m - 1) + delta;
  return `${Math.floor(i / 12)}-${pad((i % 12) + 1)}`;
}

/** Whether the calendar may move `delta` months from `ym`: never past this
 *  month, never before the month of the oldest day the API reads. */
export function canShift(ym, delta, now = new Date()) {
  const to = shiftMonth(ym, delta);
  return to <= today(now).slice(0, 7) && to >= oldest(now).slice(0, 7);
}

/** One month as weeks of seven cells, Monday first; null before the 1st and
 *  after the last day. Each day: { date, day, today, disabled }. */
export function monthGrid(ym, now = new Date()) {
  const t = today(now);
  const o = oldest(now);
  const key = isMonth(ym) ? ym : t.slice(0, 7);
  const [y, m] = key.split('-').map(Number);
  // getUTCDay: 0 = Sunday … 6 = Saturday → blanks before a Monday-first week
  const lead = (new Date(Date.UTC(y, m - 1, 1)).getUTCDay() + 6) % 7;
  const cells = Array(lead).fill(null);
  for (let d = 1; d <= lastDay(y, m); d += 1) {
    const date = `${key}-${pad(d)}`;
    cells.push({ date, day: d, today: date === t, disabled: date > t || date < o });
  }
  while (cells.length % 7) cells.push(null);
  const weeks = [];
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));
  return weeks;
}

/** The choice after one more click: start, then end (swapped when it comes
 *  before the start), then a fresh start. */
export function clickDay(sel, date) {
  const from = sel && isDate(sel.from) ? sel.from : '';
  const to = sel && isDate(sel.to) ? sel.to : '';
  if (!isDate(date)) return { from, to };
  if (!from || to) return { from: date, to: '' };
  return date < from ? { from: date, to: from } : { from, to: date };
}

/** The period token for a calendar choice: '' when nothing is picked. */
export function selectionToken(sel) {
  if (!sel || !isDate(sel.from)) return '';
  if (!isDate(sel.to) || sel.to === sel.from) return `d${sel.from}`;
  return `r${sel.from}_${sel.to}`;
}

/** A day or range token back to the calendar's { from, to }. */
export function selectionFromToken(token) {
  const t = String(token ?? '');
  let m = /^d(\d{4}-\d{2}-\d{2})$/.exec(t);
  if (m && isDate(m[1])) return { from: m[1], to: m[1] };
  m = /^r(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})$/.exec(t);
  if (m && isDate(m[1]) && isDate(m[2])) return { from: m[1], to: m[2] };
  return { from: '', to: '' };
}

/** The tab a period opens the menu on. */
export function tabFor(token) {
  const t = String(token ?? '');
  if (/^m\d{4}-\d{2}$/.test(t)) return 'month';
  if (/^[dr]\d{4}-/.test(t)) return 'calendar';
  return 'quick';
}

/** The month the calendar opens on: the chosen day's, the chosen month, else this one. */
export function startMonth(token, now = new Date()) {
  const t = String(token ?? '');
  const m = /^[dmr](\d{4}-\d{2})/.exec(t);
  if (m && isMonth(m[1])) return m[1];
  return today(now).slice(0, 7);
}

/** The Mois tab: every year the 24 months touch, newest first, twelve
 *  months each; the ones outside the 24 greyed. */
export function monthGroups(now = new Date()) {
  const cur = today(now).slice(0, 7);
  const first = shiftMonth(cur, -(MAX_MONTHS - 1));
  const years = [];
  for (let y = Number(cur.slice(0, 4)); y >= Number(first.slice(0, 4)); y -= 1) {
    const ms = [];
    for (let m = 1; m <= 12; m += 1) {
      const ym = `${y}-${pad(m)}`;
      ms.push({
        key: `m${ym}`, ym, label: monthLabel(ym), short: SHORT[m - 1],
        current: ym === cur, disabled: ym > cur || ym < first,
      });
    }
    years.push({ year: y, months: ms });
  }
  return years;
}

/** The months the calendar's « Mois affiché » list offers, this one first,
 *  back to the month of the oldest day the API reads (24 or 25 of them). */
export function calendarMonths(now = new Date()) {
  const cur = today(now).slice(0, 7);
  const first = oldest(now).slice(0, 7);
  const out = [];
  for (let ym = cur; ym >= first; ym = shiftMonth(ym, -1)) out.push({ ym, label: monthLabel(ym) });
  return out;
}

export { validPeriod };
