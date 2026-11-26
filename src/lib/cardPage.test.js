// Run: node --test src/lib/cardPage.test.js
// « Ma carte en ligne » redesign (2026-11-25): the words of the points box,
// the activity rows and their Paris times, the tabs in the address bar and the
// shop's networks — pure helpers, so the page only draws.
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  activityTime, activityRow, pointsBox, tabFromSearch, searchForTab, socialLinks, TABS, VIEWS, cardViewPath, navActive,
  followNetworks, ctaOf, CTA_DEFAULT_LABEL, appleAddHref,
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

test('tabs from the address bar, and back — everything in the card page (round 4, 2026-11-26)', () => {
  assert.deepEqual(TABS, ['accueil', 'historique', 'recompenses', 'compte']);
  assert.deepEqual(VIEWS, ['accueil', 'historique', 'recompenses', 'compte', 'programme', 'parrainage']);
  assert.equal(tabFromSearch(''), 'accueil');
  assert.equal(tabFromSearch('?onglet=carte'), 'accueil', 'old « Ma carte » links land on Accueil');
  assert.equal(tabFromSearch('?onglet=CARTE'), 'accueil');
  assert.equal(tabFromSearch('?onglet=recompenses'), 'recompenses', 'the bottom « Récompenses » = « Vos offres », in the page');
  assert.equal(tabFromSearch('?onglet=offres'), 'recompenses', 'the old offers page');
  assert.equal(tabFromSearch('?onglet=programme'), 'programme', 'the Wallet « Programme » tile: the programme view');
  assert.equal(tabFromSearch('?onglet=PROGRAMME'), 'programme');
  assert.equal(tabFromSearch('?onglet=parrainage'), 'parrainage');
  assert.equal(tabFromSearch('?onglet=partager'), 'parrainage', 'the old share page');
  assert.equal(tabFromSearch('?onglet=compte'), 'compte');
  assert.equal(tabFromSearch('?onglet=historique'), 'historique');
  assert.equal(tabFromSearch('?onglet=nimporte'), 'accueil');
  assert.equal(tabFromSearch('?onglet='), 'accueil');
  assert.equal(tabFromSearch('?wallet=apple'), 'accueil', '« Ajouter à Apple Wallet » from another app: the home');
  assert.equal(tabFromSearch('?wallet=apple&onglet=compte'), 'compte');
  assert.equal(tabFromSearch('?onglet=compte&onglet=historique'), 'compte', 'the first one wins');
  assert.equal(tabFromSearch(undefined), 'accueil');
  assert.equal(tabFromSearch(null), 'accueil');
});

test('searchForTab keeps the shop view, drops one-shot params', () => {
  assert.equal(searchForTab('', 'historique'), '?onglet=historique');
  assert.equal(searchForTab('', 'carte'), '', 'no « carte » tab to write');
  assert.equal(searchForTab('?onglet=historique', 'accueil'), '');
  assert.equal(searchForTab('?vue=commerce', 'compte'), '?vue=commerce&onglet=compte');
  assert.equal(searchForTab('?vue=commerce&onglet=compte', 'accueil'), '?vue=commerce');
  assert.equal(searchForTab('?offre=c1&notify=1&wallet=apple&k=abc&onglet=programme', 'recompenses'), '?onglet=recompenses');
  assert.equal(searchForTab('?vue=commerce', 'parrainage'), '?vue=commerce&onglet=parrainage');
  assert.equal(searchForTab('', 'programme'), '?onglet=programme');
  assert.equal(searchForTab('?vue=commerce', 'nimporte'), '?vue=commerce');
});

// round 4 (user, 2026-11-26): no page opens another page — the old addresses
// /card/{bc}/offres and /card/{bc}/partager open the card page on that view,
// every parameter kept (the owner key, ?vue=commerce, ?offre=) for the gate
test('cardViewPath: the old offers / share addresses → the card page on their view', () => {
  assert.equal(cardViewPath('/card/FT-AB12CD34/offres', ''), '/card/FT-AB12CD34?onglet=recompenses');
  assert.equal(cardViewPath('/card/FT-AB12CD34/offres/', ''), '/card/FT-AB12CD34?onglet=recompenses', 'a trailing slash');
  assert.equal(cardViewPath('/card/FT-AB12CD34/partager', ''), '/card/FT-AB12CD34?onglet=parrainage');
  assert.equal(cardViewPath('/card/FT-AB12CD34/offres', '?vue=commerce'), '/card/FT-AB12CD34?vue=commerce&onglet=recompenses');
  assert.equal(cardViewPath('/card/FT-AB12CD34/offres', '?k=s3cr%C3%A9t&offre=c1'), '/card/FT-AB12CD34?k=s3cr%C3%A9t&offre=c1&onglet=recompenses',
    'the owner key goes to the gate, which keeps it on the phone and drops it from the bar');
  assert.equal(cardViewPath('/card/FT-AB12CD34/partager', '?onglet=compte'), '/card/FT-AB12CD34?onglet=parrainage', 'the path decides');
  assert.equal(cardViewPath('/card/ft-ab12cd34/OFFRES', ''), '/card/ft-ab12cd34?onglet=recompenses');
  assert.equal(cardViewPath('/card/FT-AB12CD34', '?onglet=compte'), null, 'the card page itself: nothing to do');
  assert.equal(cardViewPath('/card/FT-AB12CD34/ajouter', '?k=x'), null, 'the Apple add page stays a page');
  assert.equal(cardViewPath('/card/FT-AB12CD34/nimporte', ''), null);
  assert.equal(cardViewPath('/join/x/offres', ''), null);
  assert.equal(cardViewPath('/card//offres', ''), null);
  assert.equal(cardViewPath(undefined, undefined), null);
  assert.equal(cardViewPath('/card/FT-AB%2F..%2Fx/offres', ''), '/card/FT-AB%2F..%2Fx?onglet=recompenses', 'an odd id stays one segment');
});

test('navActive: which bottom item is lit — all four are tabs of this page now', () => {
  assert.equal(navActive('accueil'), 'accueil');
  assert.equal(navActive('historique'), 'historique');
  assert.equal(navActive('recompenses'), 'recompenses', 'Récompenses is in the page (round 4)');
  assert.equal(navActive('compte'), 'compte');
  assert.equal(navActive('programme'), null, 'the programme view: no item lit');
  assert.equal(navActive('parrainage'), null, 'the Parrainage view: no item lit (a back arrow leads home)');
  assert.equal(navActive('carte'), null, 'no « Ma carte » item');
  assert.equal(navActive(undefined), null);
  assert.equal(navActive('nimporte'), null);
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

// user, 2026-11-25: « Suivez-nous » always, with the 4 networks; one not added says so
test('followNetworks: always the 4 networks, in order, url or null', () => {
  const four = ['instagram', 'facebook', 'tiktok', 'snapchat'];
  for (const empty of [undefined, null, [], 'x', [null, 3]]) {
    const out = followNetworks(empty);
    assert.deepEqual(out.map((n) => n.network), four);
    assert.ok(out.every((n) => n.url === null), JSON.stringify(out));
  }
  const out = followNetworks([
    { network: 'tiktok', url: 'https://www.tiktok.com/@royaltrim' },
    { network: 'facebook', url: 'javascript:alert(1)' },
    { network: 'Instagram', url: 'https://www.instagram.com/royaltrim' },
    { network: 'youtube', url: 'https://youtube.com/@x' },
    { network: 'instagram', url: 'https://www.instagram.com/second' },
  ]);
  assert.deepEqual(out.map((n) => n.network), four, 'the same 4, never more');
  assert.deepEqual(out.map((n) => n.label), ['Instagram', 'Facebook', 'TikTok', 'Snapchat']);
  assert.equal(out[0].url, 'https://www.instagram.com/royaltrim', 'the first one of a network wins');
  assert.equal(out[1].url, null, 'a javascript: link is not a link');
  assert.equal(out[2].url, 'https://www.tiktok.com/@royaltrim');
  assert.equal(out[3].url, null);
});

test('ctaOf: the store\'s button, default « Prendre rendez-vous », https only', () => {
  assert.equal(CTA_DEFAULT_LABEL, 'Prendre rendez-vous');
  for (const c of [undefined, null, {}, { cta: null }, { cta: 'x' }, { cta: [] }]) {
    assert.deepEqual(ctaOf(c), { label: 'Prendre rendez-vous', url: null });
  }
  assert.deepEqual(ctaOf({ cta: { label: '  Commander  ', url: 'https://www.ubereats.com/fr/store/x' } }),
    { label: 'Commander', url: 'https://www.ubereats.com/fr/store/x' });
  assert.deepEqual(ctaOf({ cta: { label: '', url: null } }), { label: 'Prendre rendez-vous', url: null });
  assert.equal(ctaOf({ cta: { label: 'x'.repeat(29) } }).label, 'Prendre rendez-vous', 'too long: the default');
  assert.equal(ctaOf({ cta: { label: 'x'.repeat(28) } }).label, 'x'.repeat(28), '28 is the limit');
  assert.equal(ctaOf({ cta: { label: 42 } }).label, 'Prendre rendez-vous');
  for (const bad of ['javascript:alert(1)', 'JAVASCRIPT:alert(1)', 'data:text/html,<b>x', 'http://planity.com/x',
    '//evil.com', 'https://', 'https://a b.com', ' https://ok.com/x y', 'https://user:pw@evil.com', 'https://a.com\\@b.com',
    'https://' + 'a'.repeat(500) + '.com', 'vbscript:x', 42, '', null]) {
    assert.equal(ctaOf({ cta: { label: 'Voir', url: bad } }).url, null, String(bad));
  }
  assert.equal(ctaOf({ cta: { label: 'Voir', url: ' https://www.planity.com/royal-trim ' } }).url, 'https://www.planity.com/royal-trim');
});

// « Ajouter à Apple Wallet » from another app lands here (?wallet=apple, in
// Safari): the page starts the same add the old « Ma carte » button did
test('appleAddHref: the pass link for a ?wallet=apple arrival in Safari only', () => {
  const base = { search: '?wallet=apple', barcodeId: 'FT-AB12CD34', key: 'kk', place: 'safari', appleOn: true };
  assert.equal(appleAddHref(base), '/api/card/FT-AB12CD34/apple-wallet.pkpass?k=kk');
  assert.equal(appleAddHref({ ...base, key: '' }), '/api/card/FT-AB12CD34/apple-wallet.pkpass');
  assert.equal(appleAddHref({ ...base, key: 'a&b=c' }), '/api/card/FT-AB12CD34/apple-wallet.pkpass?k=a%26b%3Dc');
  assert.equal(appleAddHref({ ...base, search: '' }), null, 'no ?wallet=apple: nothing');
  assert.equal(appleAddHref({ ...base, search: '?wallet=google' }), null);
  assert.equal(appleAddHref({ ...base, place: 'other' }), null, 'Instagram / Chrome would download a file');
  assert.equal(appleAddHref({ ...base, place: 'none' }), null, 'Android / computers: nothing');
  assert.equal(appleAddHref({ ...base, appleOn: false }), null, 'Apple Wallet not on for this card');
  assert.equal(appleAddHref({ ...base, barcodeId: '' }), null);
  assert.equal(appleAddHref({ ...base, barcodeId: 'FT/../x' }), '/api/card/FT%2F..%2Fx/apple-wallet.pkpass?k=kk');
  assert.equal(appleAddHref({}), null);
});
