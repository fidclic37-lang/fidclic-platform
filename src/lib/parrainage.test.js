// Run: node --test src/lib/parrainage.test.js
// « Mes parrainages » words on the card page (user, 2026-11-26): the reward
// each side gets, when, and each friend's line — exactly what the shop set
// and what GET /api/card/{bc}/parrainages says was paid.
import test from 'node:test';
import assert from 'node:assert/strict';
import { amountText, meWhen, friendWhen, earnedStat, friendLine, showRewards, statusNote, dayFr } from './parrainage.js';

const P = (over = {}) => ({
  enabled: true, mode: 'once', need: 1,
  me: { kind: 'stamps', n: 2, label: '2 tampons' }, friend: { kind: 'stamps', n: 2, label: '2 tampons' },
  invited: 0, rewarded: 0, pending: 0, earned: { points: 0, stamps: 0, offers: 0, offer_text: '' }, earned_label: '',
  friends: [], more: 0, ...over,
});

test('amount: +n for tampons and points, the offer as written, nothing for nothing', () => {
  assert.equal(amountText({ kind: 'stamps', n: 2, label: '2 tampons' }), '+2 tampons');
  assert.equal(amountText({ kind: 'stamps', n: 1, label: '1 tampon' }), '+1 tampon');
  assert.equal(amountText({ kind: 'points', n: 50, label: '50 points' }), '+50 points');
  assert.equal(amountText({ kind: 'offer', text: '1 café offert', label: '1 café offert' }), '1 café offert');
  assert.equal(amountText({ kind: 'points', n: 0, label: '' }), '');
  assert.equal(amountText(null), '');
  assert.equal(amountText(undefined), '');
});

test('when you are paid: 1st visit, the owner\'s n-th visit, every visit, bonus then recurring', () => {
  assert.equal(meWhen(P()), 'quand votre ami vient en boutique');
  assert.equal(meWhen(P({ need: 2 })), 'quand votre ami vient 2 fois');
  assert.equal(meWhen(P({ need: 3 })), 'quand votre ami vient 3 fois');
  assert.equal(meWhen(P({ mode: 'every' })), 'à chaque visite de votre ami');
  assert.equal(meWhen(P({ mode: 'every', need: 2 })), 'à chaque visite de votre ami, dès sa 2e');
  assert.equal(meWhen(P({ mode: 'first_then', me: { kind: 'stamps', n: 2, label: '2 tampons', next_label: '1 tampon' } })),
    'quand votre ami vient en boutique, puis +1 tampon à chaque visite');
  assert.equal(meWhen(P({ mode: 'first_then', me: { kind: 'stamps', n: 2, label: '2 tampons', next_label: '' } })),
    'quand votre ami vient en boutique');
  assert.equal(meWhen(P({ need: 0 })), 'quand votre ami vient en boutique');   // never below 1
});

test('when the friend is paid', () => {
  assert.equal(friendWhen(P()), 'à sa 1re visite');
  assert.equal(friendWhen(P({ need: 2 })), 'à sa 2e visite');
  assert.equal(friendWhen(P({ mode: 'every' })), 'à chaque visite');
  assert.equal(friendWhen(P({ mode: 'every', need: 3 })), 'à chaque visite, dès sa 3e');
  assert.equal(friendWhen(P({ mode: 'first_then', friend: { kind: 'offer', text: 'x', label: 'x', next_label: '5 points' } })),
    'à sa 1re visite, puis +5 points à chaque visite');
});

test('the earned tile: in what was really paid', () => {
  assert.deepEqual(earnedStat(P()), { value: '0', label: 'Tampons gagnés' });
  assert.deepEqual(earnedStat(P({ me: { kind: 'points', n: 50, label: '50 points' } })), { value: '0', label: 'Points gagnés' });
  assert.deepEqual(earnedStat(P({ me: { kind: 'offer', text: 'x', label: 'x' } })), { value: '0', label: 'Offres gagnées' });
  assert.deepEqual(earnedStat(P({ earned: { points: 0, stamps: 1, offers: 0 } })), { value: '1', label: 'Tampon gagné' });
  assert.deepEqual(earnedStat(P({ earned: { points: 0, stamps: 6, offers: 0 } })), { value: '6', label: 'Tampons gagnés' });
  // paid in points before the shop moved to tampons: the points, not « 0 tampons »
  assert.deepEqual(earnedStat(P({ earned: { points: 75, stamps: 0, offers: 0 } })), { value: '75', label: 'Points gagnés' });
  assert.deepEqual(earnedStat(P({ earned: { points: 0, stamps: 0, offers: 1 } })), { value: '1', label: 'Offre gagnée' });
  assert.deepEqual(earnedStat(P({ earned: { points: 0, stamps: 0, offers: 3 } })), { value: '3', label: 'Offres gagnées' });
  // several kinds: each said, not added up
  assert.deepEqual(earnedStat(P({ earned: { points: 50, stamps: 4, offers: 0 }, earned_label: '4 tampons · 50 points' })),
    { value: '4 tampons · 50 points', label: 'Gagnés', mixed: true });
  assert.deepEqual(earnedStat(P({ me: null, earned: null })), { value: '0', label: 'Récompenses gagnées' });
});

test('dates in Paris, short French day', () => {
  assert.equal(dayFr('2026-11-05T10:00:00Z'), '5 nov.');
  assert.equal(dayFr('2026-11-30T23:30:00Z'), '1 déc.');       // already the 1st in Paris
  assert.equal(dayFr('2026-03-29T00:30:00Z'), '29 mars');      // DST night
  assert.equal(dayFr(''), '');
  assert.equal(dayFr(null), '');
  assert.equal(dayFr('pas une date'), '');
});

test('a friend\'s line: rewarded with what you got, pending with where they are', () => {
  const base = { first_name: 'Thomas', joined_at: '2026-11-03T10:00:00Z', need: 1, visits: 0 };
  assert.equal(friendLine({ ...base, status: 'rewarded', visits: 1, rewarded_at: '2026-11-05T10:00:00Z', given: '2 tampons', times: 1 }),
    'Récompensé le 5 nov. · 2 tampons pour vous');
  assert.equal(friendLine({ ...base, status: 'rewarded', visits: 1, rewarded_at: '2026-11-05T10:00:00Z', given: '6 tampons', times: 3 }),
    'Récompensé le 5 nov. · 6 tampons pour vous (3 visites)');
  assert.equal(friendLine({ ...base, status: 'rewarded', rewarded_at: '2026-11-05T10:00:00Z', given: '', times: 1 }),
    'Récompensé le 5 nov.');                                   // the shop gave this side nothing
  assert.equal(friendLine({ ...base, status: 'rewarded', rewarded_at: null, given: '2 tampons', times: 1 }),
    'Récompensé · 2 tampons pour vous');
  assert.equal(friendLine({ ...base, status: 'pending' }), 'Carte créée le 3 nov. · 1re visite à faire');
  assert.equal(friendLine({ ...base, status: 'pending', need: 2 }), 'Carte créée le 3 nov. · 0 visite sur 2');
  assert.equal(friendLine({ ...base, status: 'pending', need: 2, visits: 1 }), 'Carte créée le 3 nov. · 1 visite sur 2');
  assert.equal(friendLine({ ...base, status: 'pending', need: 3, visits: 2 }), 'Carte créée le 3 nov. · 2 visites sur 3');
  assert.equal(friendLine({ ...base, status: 'pending', joined_at: null }), 'Carte créée · 1re visite à faire');
});

test('the rewards row shows only when the programme is on and gives something', () => {
  assert.equal(showRewards(P()), true);
  assert.equal(showRewards(P({ enabled: false })), false);
  assert.equal(showRewards(P({ me: { kind: 'points', n: 0, label: '' }, friend: { kind: 'points', n: 0, label: '' } })), false);
  assert.equal(showRewards(P({ me: { kind: 'points', n: 0, label: '' } })), true);
  assert.equal(showRewards(null), false);
});

test('the note under the list', () => {
  assert.match(statusNote(P()), /à sa 1re visite/);
  assert.match(statusNote(P({ need: 2 })), /à sa 2e visite/);
});
