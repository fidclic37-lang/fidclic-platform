// Run: node --test src/lib/cardReview.test.js
// « Donner mon avis » (Mon compte) opens for 14 days after the client's last
// visit — the rule the page already had, now a pure helper (2026-11-25).
import test from 'node:test';
import assert from 'node:assert/strict';
import { reviewOpen, REVIEW_WINDOW_DAYS } from './cardPage.js';

const NOW = Date.parse('2026-11-25T13:30:00Z');
const DAY = 864e5;
const at = (ms) => new Date(ms).toISOString();

test('the window is 14 days', () => {
  assert.equal(REVIEW_WINDOW_DAYS, 14);
});

test('reviewOpen: no visit, unreadable date → closed', () => {
  assert.equal(reviewOpen(undefined, NOW), false);
  assert.equal(reviewOpen(null, NOW), false);
  assert.equal(reviewOpen('', NOW), false);
  assert.equal(reviewOpen('hier', NOW), false);
  assert.equal(reviewOpen({}, NOW), false);
  assert.equal(reviewOpen(0, NOW), false);
});

test('reviewOpen: a visit today, 5 minutes ago, 13 days ago → open', () => {
  assert.equal(reviewOpen(at(NOW), NOW), true);
  assert.equal(reviewOpen(at(NOW - 5 * 60_000), NOW), true);
  assert.equal(reviewOpen(at(NOW - 13 * DAY), NOW), true);
});

test('reviewOpen: exactly 14 days is still open, a millisecond more is closed', () => {
  assert.equal(reviewOpen(at(NOW - 14 * DAY), NOW), true);
  assert.equal(reviewOpen(at(NOW - 14 * DAY - 1), NOW), false);
  assert.equal(reviewOpen(at(NOW - 40 * DAY), NOW), false);
});

test('reviewOpen: a phone clock a little behind the server still opens it', () => {
  assert.equal(reviewOpen(at(NOW + 90_000), NOW), true);
});

test('reviewOpen: the server sends ISO with Z — across the DST change (26 Oct) it counts real time', () => {
  // 2026-10-25 01:30 Paris (summer) → 2026-11-08 01:30 Paris (winter) = 14 days + 1 h
  assert.equal(reviewOpen('2026-10-24T23:30:00Z', Date.parse('2026-11-08T00:30:00Z')), false);
  assert.equal(reviewOpen('2026-10-24T23:30:00Z', Date.parse('2026-11-07T23:30:00Z')), true);
});
