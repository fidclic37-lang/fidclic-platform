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
