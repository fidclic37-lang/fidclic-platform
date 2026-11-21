// Run: node --test src/lib/periodCalendar.test.js
// The simpler period menu (user, 2026-11-21): three tabs — Rapide, Mois,
// Calendrier — one calendar where one click is a day and two clicks are a
// from–to range, and one month grid. Same tokens as lib/period.js.
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  monthGrid, clickDay, selectionToken, selectionFromToken, tabFor, monthGroups,
  shiftMonth, canShift, startMonth, dayLabel, calendarMonths,
} from './periodCalendar.js';

// 21 Nov 2026, 12:00 in Paris
const NOW = new Date('2026-11-21T11:00:00Z');

const days = (grid) => grid.flat().filter(Boolean);

test('monthGrid: weeks start on Monday, blanks before the 1st', () => {
  // 1 Nov 2026 is a Sunday → six blanks, then the 1st
  const g = monthGrid('2026-11', NOW);
  assert.equal(g[0].length, 7);
  assert.deepEqual(g[0].slice(0, 6), [null, null, null, null, null, null]);
  assert.equal(g[0][6].date, '2026-11-01');
  assert.equal(days(g).length, 30);
});

test('monthGrid: a month starting on a Monday has no blank', () => {
  // 1 Feb 2027 is a Monday — but it is in the future: still drawn, all disabled
  const g = monthGrid('2027-02', NOW);
  assert.equal(g[0][0].date, '2027-02-01');
  assert.ok(days(g).every((c) => c.disabled));
});

test('monthGrid: February of a leap year has 29 days', () => {
  assert.equal(days(monthGrid('2028-02', NOW)).length, 29);
  assert.equal(days(monthGrid('2026-02', NOW)).length, 28);
});

test('monthGrid: the DST change (25 Oct 2026) neither skips nor repeats a day', () => {
  const ds = days(monthGrid('2026-10', NOW)).map((c) => c.date);
  assert.equal(ds.length, 31);
  assert.equal(new Set(ds).size, 31);
  assert.ok(ds.includes('2026-10-25') && ds.includes('2026-10-26'));
});

test('monthGrid: days after today (Paris) are disabled, today is marked', () => {
  const ds = days(monthGrid('2026-11', NOW));
  const t = ds.find((c) => c.date === '2026-11-21');
  assert.equal(t.today, true);
  assert.equal(t.disabled, false);
  assert.equal(ds.find((c) => c.date === '2026-11-22').disabled, true);
  assert.equal(ds.find((c) => c.date === '2026-11-20').today, false);
});

test('monthGrid: « today » follows Paris, not UTC (23:30 UTC on 30 Nov is 1 Dec in Paris)', () => {
  const late = new Date('2026-11-30T23:30:00Z');
  const dec = days(monthGrid('2026-12', late));
  assert.equal(dec.find((c) => c.date === '2026-12-01').disabled, false);
  assert.equal(dec.find((c) => c.date === '2026-12-01').today, true);
});

test('monthGrid: days older than two years are disabled', () => {
  // oldest accepted = today − 729 days = 2024-11-22
  const ds = days(monthGrid('2024-11', NOW));
  assert.equal(ds.find((c) => c.date === '2024-11-21').disabled, true);
  assert.equal(ds.find((c) => c.date === '2024-11-22').disabled, false);
});

test('monthGrid: a wrong month gives the current one', () => {
  assert.equal(days(monthGrid('nope', NOW))[0].date, '2026-11-01');
  assert.equal(days(monthGrid('2026-13', NOW))[0].date, '2026-11-01');
  assert.equal(days(monthGrid('', NOW))[0].date, '2026-11-01');
});

test('clickDay: first click is the start, second later click is the end', () => {
  let s = clickDay({ from: '', to: '' }, '2026-11-10');
  assert.deepEqual(s, { from: '2026-11-10', to: '' });
  s = clickDay(s, '2026-11-15');
  assert.deepEqual(s, { from: '2026-11-10', to: '2026-11-15' });
});

test('clickDay: a second click before the start swaps the two', () => {
  const s = clickDay({ from: '2026-11-15', to: '' }, '2026-11-10');
  assert.deepEqual(s, { from: '2026-11-10', to: '2026-11-15' });
});

test('clickDay: the same day twice is that one day', () => {
  const s = clickDay({ from: '2026-11-10', to: '' }, '2026-11-10');
  assert.deepEqual(s, { from: '2026-11-10', to: '2026-11-10' });
});

test('clickDay: a third click starts a new choice', () => {
  const s = clickDay({ from: '2026-11-10', to: '2026-11-15' }, '2026-11-03');
  assert.deepEqual(s, { from: '2026-11-03', to: '' });
});

test('clickDay: a range across two months', () => {
  const s = clickDay({ from: '2026-10-28', to: '' }, '2026-11-04');
  assert.deepEqual(s, { from: '2026-10-28', to: '2026-11-04' });
});

test('clickDay: no state or garbage → starts from the clicked day', () => {
  assert.deepEqual(clickDay(undefined, '2026-11-10'), { from: '2026-11-10', to: '' });
  assert.deepEqual(clickDay({ from: '2026-11-10', to: '' }, 'bad'), { from: '2026-11-10', to: '' });
});

test('selectionToken: nothing → empty, one day → d, a range → r', () => {
  assert.equal(selectionToken({ from: '', to: '' }), '');
  assert.equal(selectionToken(undefined), '');
  assert.equal(selectionToken({ from: '2026-11-10', to: '' }), 'd2026-11-10');
  assert.equal(selectionToken({ from: '2026-11-10', to: '2026-11-10' }), 'd2026-11-10');
  assert.equal(selectionToken({ from: '2026-11-10', to: '2026-11-15' }), 'r2026-11-10_2026-11-15');
});

test('selectionFromToken: reads d and r tokens back, nothing for the others', () => {
  assert.deepEqual(selectionFromToken('d2026-11-10'), { from: '2026-11-10', to: '2026-11-10' });
  assert.deepEqual(selectionFromToken('r2026-11-10_2026-11-15'), { from: '2026-11-10', to: '2026-11-15' });
  for (const t of ['mtd', '7', '45d', 'm2026-10', '', null, 'zzz']) {
    assert.deepEqual(selectionFromToken(t), { from: '', to: '' }, String(t));
  }
});

test('tabFor: presets and « les derniers N » → Rapide, a month → Mois, a day or range → Calendrier', () => {
  for (const t of ['1', 'mtd', '7', '30', '90', '365', '45d', '6m']) assert.equal(tabFor(t), 'quick', t);
  assert.equal(tabFor('m2026-10'), 'month');
  assert.equal(tabFor('d2026-11-10'), 'calendar');
  assert.equal(tabFor('r2026-11-10_2026-11-15'), 'calendar');
  for (const t of ['', null, undefined, 'zzz']) assert.equal(tabFor(t), 'quick', String(t));
});

test('monthGroups: 24 months offered, newest year first, the future greyed', () => {
  const g = monthGroups(NOW);
  assert.deepEqual(g.map((y) => y.year), [2026, 2025, 2024]);
  assert.ok(g.every((y) => y.months.length === 12));
  const on = g.flatMap((y) => y.months).filter((m) => !m.disabled);
  assert.equal(on.length, 24);
  const nov = g[0].months[10];
  assert.equal(nov.key, 'm2026-11');
  assert.equal(nov.current, true);
  assert.equal(nov.label, 'Novembre 2026');
  assert.equal(nov.short, 'Nov.');
  assert.equal(g[0].months[11].disabled, true);   // décembre 2026
  assert.equal(g[2].months[11].disabled, false);  // décembre 2024 — the 24th month
  assert.equal(g[2].months[10].disabled, true);   // novembre 2024 — 25 months back
});

test('monthGroups: in January the current year has one month', () => {
  const g = monthGroups(new Date('2027-01-10T11:00:00Z'));
  assert.equal(g[0].year, 2027);
  assert.equal(g[0].months.filter((m) => !m.disabled).length, 1);
  assert.equal(g.flatMap((y) => y.months).filter((m) => !m.disabled).length, 24);
});

test('shiftMonth: across years both ways', () => {
  assert.equal(shiftMonth('2026-12', 1), '2027-01');
  assert.equal(shiftMonth('2026-01', -1), '2025-12');
  assert.equal(shiftMonth('2026-05', 0), '2026-05');
});

test('canShift: never past this month, never before the oldest month', () => {
  assert.equal(canShift('2026-11', 1, NOW), false);
  assert.equal(canShift('2026-10', 1, NOW), true);
  assert.equal(canShift('2024-11', -1, NOW), false);   // oldest day 2024-11-22 is in Nov 2024
  assert.equal(canShift('2024-12', -1, NOW), true);
});

test('startMonth: the calendar opens on the chosen day, else on this month', () => {
  assert.equal(startMonth('d2026-08-15', NOW), '2026-08');
  assert.equal(startMonth('r2026-07-28_2026-08-03', NOW), '2026-07');
  assert.equal(startMonth('m2026-03', NOW), '2026-03');
  assert.equal(startMonth('mtd', NOW), '2026-11');
  assert.equal(startMonth('', NOW), '2026-11');
});

test('dayLabel: the French name a screen reader and the tests read', () => {
  assert.equal(dayLabel('2026-11-01'), '1 novembre 2026');
  assert.equal(dayLabel('2026-02-28'), '28 février 2026');
});

test('calendarMonths: this month back to the oldest day\'s month', () => {
  const c = calendarMonths(NOW);
  assert.equal(c[0].ym, '2026-11');
  assert.equal(c[0].label, 'Novembre 2026');
  assert.equal(c.at(-1).ym, '2024-11');      // oldest day 2024-11-22
  assert.equal(c.length, 25);
  // on the 1st, the oldest day falls further in its month — still listed
  assert.equal(calendarMonths(new Date('2026-12-01T11:00:00Z')).at(-1).ym, '2024-12');
});
