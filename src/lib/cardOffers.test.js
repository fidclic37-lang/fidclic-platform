// Run: node --test src/lib/cardOffers.test.js
// « Mes offres · 2 en cours » on the card, but « Pas d'offre en ce moment » once
// opened (user, 2026-11-25): the card counted every campaign
// of the last 45 days (notifications), ended ones and défis included, while the
// offers page lists only what is live. One list now, for both.
import test from 'node:test';
import assert from 'node:assert/strict';
import { liveOffers } from './cardOffers.js';

const NOW = Date.parse('2026-11-25T10:00:00Z');
const camp = (id, sent, extra = {}) => ({ id, kind: 'campaign', title: id, sent_at: sent, ...extra });

test('nothing to show: no data, no offers, empty lists', () => {
  assert.deepEqual(liveOffers(null, NOW), []);
  assert.deepEqual(liveOffers(undefined, NOW), []);
  assert.deepEqual(liveOffers({}, NOW), []);
  assert.deepEqual(liveOffers({ offers: [], notifications: [] }, NOW), []);
});

test('the bug: past campaigns in notifications are NOT offers', () => {
  const data = {
    offers: [],
    notifications: [camp('fini', '2026-11-01T09:00:00Z'), camp('defi', '2026-11-20T09:00:00Z')],
  };
  assert.deepEqual(liveOffers(data, NOW), []);
});

test('one live campaign: one offer', () => {
  const data = { offers: [camp('a', '2026-11-24T09:00:00Z', { valid_until: '2026-12-01T22:59:59Z' })],
    notifications: [camp('a', '2026-11-24T09:00:00Z'), camp('old', '2026-10-20T09:00:00Z')] };
  assert.deepEqual(liveOffers(data, NOW).map((o) => o.id), ['a']);
});

test('an offer whose end has passed is dropped; ending right now is kept', () => {
  const data = { offers: [
    camp('passee', '2026-11-10T09:00:00Z', { valid_until: '2026-11-25T09:59:59Z' }),
    camp('pile', '2026-11-10T09:00:00Z', { valid_until: '2026-11-25T10:00:00Z' }),
    camp('sans-fin', '2026-11-10T09:00:00Z', { valid_until: null }),
  ] };
  assert.deepEqual(liveOffers(data, NOW).map((o) => o.id).sort(), ['pile', 'sans-fin']);
});

test('the shop’s own offer leads, then newest first; duplicates and id-less rows once/never', () => {
  const data = { offers: [
    camp('vieux', '2026-11-01T09:00:00Z'),
    { id: 'offer-main', kind: 'primary', title: 'Offre du moment' },
    camp('neuf', '2026-11-24T09:00:00Z'),
    camp('neuf', '2026-11-24T09:00:00Z'),
    camp(undefined, '2026-11-24T09:00:00Z'),
  ] };
  assert.deepEqual(liveOffers(data, NOW).map((o) => o.id), ['offer-main', 'neuf', 'vieux']);
});

test('a broken date never throws and never jumps ahead of the shop offer', () => {
  const data = { offers: [camp('x', 'pas une date'), { id: 'offer-main', kind: 'primary' }] };
  assert.deepEqual(liveOffers(data, NOW).map((o) => o.id), ['offer-main', 'x']);
});

test('defaults to the current time', () => {
  const data = { offers: [camp('futur', '2026-11-24T09:00:00Z', { valid_until: '2999-01-01T00:00:00Z' }),
    camp('passe', '2026-11-24T09:00:00Z', { valid_until: '2000-01-01T00:00:00Z' })] };
  assert.deepEqual(liveOffers(data).map((o) => o.id), ['futur']);
});

// ---------------------------------------------------------------- round 4: the offers in the card page
// (user, 2026-11-26) « Vos offres » is a tab of the card page now: its words
// helpers live here, shared with the old page (kept unrouted for a rollback).
import { personal, rewardPic, badgeKind, sectorLook } from './cardOffers.js';

test('personal: every variable of the Campagnes wizard, missing values safe', () => {
  const who = { name: 'Marie Dupont', points: 120, visits: 4, _shop: 'ROYAL TRIM', _reward: 'Une coupe', _missing: 6 };
  assert.equal(personal('Bonjour {prenom} / {first_name} / {PRÉNOM}', who), 'Bonjour Marie / Marie / Marie');
  assert.equal(personal('{nom} chez {nom_commerce}', who), 'Marie Dupont chez ROYAL TRIM');
  assert.equal(personal('{points} pts, {visites} visites, {points_manquants} à faire : {prochaine_récompense}', who),
    '120 pts, 4 visites, 6 à faire : Une coupe');
  assert.equal(personal('{prochaine_recompense}', {}), 'votre récompense');
  assert.equal(personal('{points} {visits} {points_remaining}', {}), '0 0 0');
  assert.equal(personal('{prenom}', { name: '' }), '');
  assert.equal(personal(null, who), '');
  assert.equal(personal(undefined), '');
  assert.equal(personal('{inconnu}', who), '{inconnu}', 'an unknown variable stays as written');
  assert.equal(personal('<b>{prenom}</b>', { name: '<i>x</i> y' }), '<b><i>x</i></b>', 'text only: React escapes it');
});

test('rewardPic: the reward\'s words first, then the trade, then a gift', () => {
  assert.equal(rewardPic('Un café offert', 'salon'), '☕');
  assert.equal(rewardPic('Une coupe offerte', 'cafe'), '💇');
  assert.equal(rewardPic('-10 % sur tout', 'cafe'), '🏷️');
  assert.equal(rewardPic('Surprise', 'pizzeria'), '🍕');
  assert.equal(rewardPic('', 'nimporte'), '🎁');
  assert.equal(rewardPic(null, null), '🎁');
});

test('badgeKind: a discount, something free, or news', () => {
  assert.equal(badgeKind({ title: '-20 % ce week-end' }), 'discount');
  assert.equal(badgeKind({ title: 'Remise fidèle' }), 'discount');
  assert.equal(badgeKind({ title: 'Café offert', body: '' }), 'gift');
  assert.equal(badgeKind({ description: 'un dessert gratuit' }), 'gift');
  assert.equal(badgeKind({ title: 'Nouvelle carte des vins' }), 'news');
  assert.equal(badgeKind({}), 'news');
  assert.equal(badgeKind(null), 'news');
});

test('sectorLook: an emoji and a picture tint per trade, a default otherwise', () => {
  assert.equal(sectorLook('cafe')[0], '☕');
  assert.equal(sectorLook('salon')[0], '💇');
  assert.equal(sectorLook('nimporte')[0], '🎁');
  assert.equal(sectorLook(undefined)[0], '🎁');
  assert.equal(sectorLook('__proto__')[0], '🎁', 'no prototype key');
});
