// Run: node --test src/lib/cardPage.test.js
// « Ma carte en ligne » redesign (2026-11-25): the words of the points box,
// the activity rows and their Paris times, the tabs in the address bar and the
// shop's networks — pure helpers, so the page only draws.
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  activityTime, activityRow, pointsBox, tabFromSearch, searchForTab, socialLinks, TABS,
} from './cardPage.js';

const nb = (s) => String(s).replace(/[  ]/g, ' ');
// 2026-11-25 is a winter day in Paris (UTC+1)
const NOW = Date.parse('2026-11-25T13:30:00Z');          // 14:30 in Paris

test('activityTime: today, yesterday, this year, another year — Paris, 24 h', () => {
  assert.equal(activityTime('2026-11-25T13:26:00Z', NOW), 'Aujourd’hui · 14:26');
  assert.equal(activityTime('2026-11-24T10:03:00Z', NOW), 'Hier · 11:03');
  assert.equal(activityTime('2026-11-12T08:17:00Z', NOW), '12 nov. · 09:17');
  assert.equal(activityTime('2025-12-31T22:30:00Z', NOW), '31 déc. 2025 · 23:30');
  // afternoon hours are never AM/PM
  assert.equal(activityTime('2026-11-25T12:05:00Z', NOW), 'Aujourd’hui · 13:05');
});

test('activityTime: Paris midnight, not UTC midnight', () => {
  // 23:30 UTC on the 24th is already 00:30 on the 25th in Paris
  assert.equal(activityTime('2026-11-24T23:30:00Z', NOW), 'Aujourd’hui · 00:30');
  // 22:59 UTC on the 24th is still 23:59 on the 24th in Paris
  assert.equal(activityTime('2026-11-24T22:59:00Z', NOW), 'Hier · 23:59');
  // just after Paris midnight, the evening before is « Hier »
  const justAfter = Date.parse('2026-11-24T23:01:00Z');   // 00:01 Paris on the 25th
  assert.equal(activityTime('2026-11-24T20:00:00Z', justAfter), 'Hier · 21:00');
});

test('activityTime: DST changes (end of March, end of October)', () => {
  const spring = Date.parse('2026-03-29T12:00:00Z');      // 14:00 CEST, the day clocks went forward
  assert.equal(activityTime('2026-03-29T00:30:00Z', spring), 'Aujourd’hui · 01:30');
  assert.equal(activityTime('2026-03-29T01:30:00Z', spring), 'Aujourd’hui · 03:30');
  assert.equal(activityTime('2026-03-28T22:30:00Z', spring), 'Hier · 23:30');
  const autumn = Date.parse('2026-10-25T12:00:00Z');      // the day clocks went back
  assert.equal(activityTime('2026-10-25T00:30:00Z', autumn), 'Aujourd’hui · 02:30');
  assert.equal(activityTime('2026-10-25T01:30:00Z', autumn), 'Aujourd’hui · 02:30');
  assert.equal(activityTime('2026-10-24T21:59:00Z', autumn), 'Hier · 23:59');
});

test('activityTime: new year — 31 Dec is « Hier » on 1 Jan, an older year shows the year', () => {
  const jan1 = Date.parse('2027-01-01T09:00:00Z');
  assert.equal(activityTime('2026-12-31T18:00:00Z', jan1), 'Hier · 19:00');
  assert.equal(activityTime('2026-12-30T18:00:00Z', jan1), '30 déc. 2026 · 19:00');
});

test('activityTime: a server time without zone is UTC; garbage is empty', () => {
  assert.equal(activityTime('2026-11-25T13:26:00', NOW), 'Aujourd’hui · 14:26');
  assert.equal(activityTime('2026-11-25T13:26:00.123456', NOW), 'Aujourd’hui · 14:26');
  assert.equal(activityTime('2026-11-25T14:26:00+01:00', NOW), 'Aujourd’hui · 14:26');
  for (const bad of [null, undefined, '', 'hier', 0 / 0, {}]) assert.equal(activityTime(bad, NOW), '');
});

const POINTS = { programme_kind: 'points_euro', reward_description: 'Café offert' };
const STAMPS = { programme_kind: 'stamps', reward_description: 'Café offert' };
const CASH = { programme_kind: 'cashback' };

test('activityRow: a visit in the programme\'s own unit', () => {
  assert.deepEqual(activityRow({ kind: 'visit', at: 'x', points: 150, amount: 15 }, POINTS),
    { icon: 'coin', title: '+ 150 points', sub: 'Achat en magasin', plus: null });
  assert.deepEqual(activityRow({ kind: 'visit', points: 1 }, POINTS).title, '+ 1 point');
  assert.deepEqual(activityRow({ kind: 'visit', stamps: 1, points: 10 }, STAMPS),
    { icon: 'stamp', title: '+ 1 tampon', sub: 'Visite en magasin', plus: null });
  assert.equal(activityRow({ kind: 'visit', stamps: 2 }, STAMPS).title, '+ 2 tampons');
  assert.equal(nb(activityRow({ kind: 'visit', points: 150 }, CASH).title), '+ 1,50 €');
  // nothing earned: still a visit, calmly
  assert.deepEqual(activityRow({ kind: 'visit' }, STAMPS), { icon: 'stamp', title: 'Visite en magasin', sub: '', plus: null });
  assert.equal(nb(activityRow({ kind: 'visit', points: 1500 }, POINTS).title), '+ 1 500 points');
});

test('activityRow: reward, referral (both sides), unknown', () => {
  assert.deepEqual(activityRow({ kind: 'reward', title: 'Café offert ☕' }, POINTS),
    { icon: 'gift', title: 'Récompense débloquée', sub: 'Café offert ☕', plus: null });
  assert.equal(activityRow({ kind: 'reward' }, POINTS).sub, 'Café offert');
  assert.deepEqual(activityRow({ kind: 'referral', role: 'parrain', points: 300, friend: 'Léa' }, POINTS),
    { icon: 'people', title: 'Parrainage validé', sub: 'Léa a rejoint', plus: '+ 300 points' });
  assert.equal(activityRow({ kind: 'referral', role: 'parrain', stamps: 2, friend: 'Léa' }, STAMPS).plus, '+ 2 tampons');
  assert.equal(activityRow({ kind: 'referral', role: 'parrain' }, POINTS).sub, 'Un proche a rejoint');
  assert.equal(activityRow({ kind: 'referral', role: 'parrain' }, POINTS).plus, null);
  assert.deepEqual(activityRow({ kind: 'referral', role: 'filleul', friend: 'Tom', points: 50 }, POINTS),
    { icon: 'people', title: 'Bienvenue', sub: 'parrainé par Tom', plus: '+ 50 points' });
  assert.equal(activityRow({ kind: 'referral', role: 'filleul' }, POINTS).sub, 'parrainé par un proche');
  assert.equal(activityRow({ kind: 'what' }, POINTS), null);
  assert.equal(activityRow(null, POINTS), null);
  assert.equal(activityRow({ kind: 'visit', points: -5 }, POINTS).title, 'Visite en magasin');
});

test('pointsBox: points card with a goal', () => {
  const b = pointsBox({ ...POINTS, reward_points: 1000 }, { points: 650 });
  assert.equal(b.label, 'Mes points fidélité');
  assert.equal(b.big, '650');
  assert.equal(b.unit, 'points');
  assert.equal(nb(b.message), 'Plus que 350 points pour obtenir votre récompense !');
  assert.equal(nb(b.strong), '350 points');
  assert.equal(nb(b.scale), '650 / 1 000 points');
  assert.equal(b.progress, 0.65);
  const one = pointsBox({ ...POINTS, reward_points: 100 }, { points: 99 });
  assert.equal(one.message, 'Plus qu’un point pour obtenir votre récompense !');
  const full = pointsBox({ ...POINTS, reward_points: 100 }, { points: 140 });
  assert.equal(full.progress, 1);
  assert.equal(full.message, 'Votre récompense est prête : présentez votre carte en caisse !');
  assert.equal(full.strong, null);
});

test('pointsBox: points card without a goal tells how to earn, no bar', () => {
  const b = pointsBox({ programme_kind: 'points_visit', points_per_visit: 10 }, { points: 0 });
  assert.equal(b.big, '0');
  assert.equal(b.unit, 'points');
  assert.equal(b.progress, null);
  assert.equal(b.message, '+10 pts à chaque passage');
});

test('pointsBox: tampons card counts this card only', () => {
  const b = pointsBox({ ...STAMPS, reward_threshold: 10 }, { cycle_visits: 3, visits: 23 });
  assert.equal(b.label, 'Mes tampons');
  assert.equal(b.big, '3');
  assert.equal(b.unit, '/ 10 tampons');
  assert.equal(b.message, 'Plus que 7 tampons pour obtenir votre récompense !');
  assert.equal(b.strong, '7 tampons');
  assert.equal(b.scale, '3 / 10 tampons · Café offert');
  assert.equal(b.progress, 0.3);
  assert.equal(pointsBox({ ...STAMPS, reward_threshold: 10 }, { cycle_visits: 9 }).message,
    'Plus qu’un tampon pour obtenir votre récompense !');
  const full = pointsBox({ ...STAMPS, reward_threshold: 10 }, { cycle_visits: 12 });
  assert.equal(full.big, '10');
  assert.equal(full.progress, 1);
  // a missing / zero / silly threshold falls back to 10
  assert.equal(pointsBox({ ...STAMPS, reward_threshold: 0 }, {}).unit, '/ 10 tampons');
  assert.equal(pointsBox(STAMPS, null).big, '0');
  // visits per tampon
  assert.equal(pointsBox({ ...STAMPS, reward_threshold: 5, visits_per_stamp: 2 }, { cycle_visits: 5 }).big, '2');
});

test('pointsBox: a cagnotte reads in euros', () => {
  const b = pointsBox({ ...CASH, cashback_rate: 5 }, { points: 1250 });
  assert.equal(b.label, 'Ma cagnotte');
  assert.equal(nb(b.big), '12,50 €');
  assert.equal(b.unit, '');
  assert.equal(b.progress, null);
  assert.equal(b.message, '5 % de chaque achat dans votre cagnotte');
});

test('tabs from the address bar, and back', () => {
  assert.deepEqual(TABS, ['accueil', 'carte', 'recompenses', 'compte']);
  assert.equal(tabFromSearch(''), 'accueil');
  assert.equal(tabFromSearch('?onglet=carte'), 'carte');
  assert.equal(tabFromSearch('?onglet=recompenses'), 'recompenses');
  assert.equal(tabFromSearch('?onglet=programme'), 'recompenses');   // the Wallet « Programme » tile
  assert.equal(tabFromSearch('?onglet=compte'), 'compte');
  assert.equal(tabFromSearch('?onglet=historique'), 'historique');
  assert.equal(tabFromSearch('?onglet=offres'), 'accueil');
  assert.equal(tabFromSearch('?onglet=nimporte'), 'accueil');
  assert.equal(tabFromSearch('?wallet=apple'), 'carte');             // « Ajouter à Apple Wallet » from another app
  assert.equal(tabFromSearch('?wallet=apple&onglet=compte'), 'compte');
  assert.equal(tabFromSearch(undefined), 'accueil');
});

test('searchForTab keeps the shop view, drops one-shot params', () => {
  assert.equal(searchForTab('', 'carte'), '?onglet=carte');
  assert.equal(searchForTab('?onglet=carte', 'accueil'), '');
  assert.equal(searchForTab('?vue=commerce', 'compte'), '?vue=commerce&onglet=compte');
  assert.equal(searchForTab('?vue=commerce&onglet=compte', 'accueil'), '?vue=commerce');
  assert.equal(searchForTab('?offre=c1&notify=1&wallet=apple&k=abc&onglet=programme', 'recompenses'), '?onglet=recompenses');
  assert.equal(searchForTab('?vue=commerce', 'nimporte'), '?vue=commerce');
});

test('socialLinks: only real https links, known networks branded, order kept', () => {
  assert.deepEqual(socialLinks(undefined), []);
  assert.deepEqual(socialLinks(null), []);
  assert.deepEqual(socialLinks('instagram'), []);
  assert.deepEqual(socialLinks([]), []);
  const out = socialLinks([
    { network: 'Instagram', url: 'https://instagram.com/royaltrim' },
    { network: 'tiktok', url: 'javascript:alert(1)' },
    { network: 'snapchat', url: 'http://snapchat.com/add/x' },
    { network: 'facebook', url: '' },
    null,
    { network: 'tiktok', url: 'https://www.tiktok.com/@royaltrim' },
    { network: 'mastodon', url: 'https://mastodon.social/@x' },
    { url: 'https://x.com/y' },
  ]);
  assert.deepEqual(out.map((s) => s.network), ['instagram', 'tiktok', 'mastodon', 'site']);
  assert.equal(out[0].label, 'Instagram');
  assert.equal(out[1].label, 'TikTok');
  assert.equal(out[2].label, 'Mastodon');
  assert.equal(out[3].label, 'Site web');
  assert.equal(out[0].url, 'https://instagram.com/royaltrim');
});
