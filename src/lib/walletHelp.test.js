// Run: node --test src/lib/walletHelp.test.js
import test from 'node:test';
import assert from 'node:assert/strict';
import { walletHelp, WALLET_NAMES } from './walletHelp.js';

test('no answer, or a linked card: nothing to say', () => {
  assert.equal(walletHelp(null), null);
  assert.equal(walletHelp(undefined), null);
  assert.equal(walletHelp({}), null);
  assert.equal(walletHelp({ linked: true, where: 'google', wallet: 'google' }), null);
});

test('never in a Wallet: a soft note, no steps, the visit is already on the card', () => {
  const h = walletHelp({ linked: false, reason: 'never_added', wallet: null });
  assert.equal(h.tone, 'info');
  assert.equal(h.steps.length, 0);
  assert.match(h.title, /pas encore dans un Wallet/);
  assert.match(h.note, /elle aura déjà cette visite/);
});

test('removed from Apple Wallet: red, Apple steps in order (updates → refresh → re-add)', () => {
  const h = walletHelp({ linked: false, reason: 'removed', wallet: 'apple' });
  assert.equal(h.tone, 'error');
  assert.equal(h.steps.length, 3);
  assert.match(h.steps[0], /Mises à jour automatiques/);
  assert.match(h.steps[1], /Actualiser/);
  assert.match(h.steps[2], /Supprimer la carte du Wallet, puis la rajouter/);
  assert.match(h.title, /mises à jour coupées/);
});

test('downloaded on an iPhone, never linked: same Apple steps, its own title', () => {
  const h = walletHelp({ linked: false, reason: 'downloaded_not_registered', wallet: 'apple' });
  assert.equal(h.tone, 'error');
  assert.match(h.steps[0], /Mises à jour automatiques/);
  assert.match(h.title, /reliée à aucun téléphone/);
});

test('removed from Google Wallet: Google steps, never the iPhone ones', () => {
  const h = walletHelp({ linked: false, reason: 'removed', wallet: 'google' });
  assert.equal(h.tone, 'error');
  assert.match(h.title, /Google Wallet/);
  assert.match(h.steps.join(' '), /même compte Google/);
  assert.match(h.steps.join(' '), /Ajouter à Google Wallet/);
  assert.doesNotMatch(h.steps.join(' '), /Mises à jour automatiques/);
});

test('an unknown reason or an older server (no `wallet`): the Apple steps, never a crash', () => {
  for (const link of [{ linked: false, reason: 'whatever' }, { linked: false, reason: 'removed' }, { linked: false }]) {
    const h = walletHelp(link);
    assert.equal(h.tone, 'error');
    assert.equal(h.steps.length, 3);
  }
});

test('Wallet names for the green line', () => {
  assert.equal(WALLET_NAMES.apple, 'Apple Wallet');
  assert.equal(WALLET_NAMES.google, 'Google Wallet');
});

test('removed from Samsung Wallet: Samsung steps (Samsung account, re-add), never the iPhone or Google ones', () => {
  const h = walletHelp({ linked: false, reason: 'removed', wallet: 'samsung' });
  assert.equal(h.tone, 'error');
  assert.match(h.title, /Samsung Wallet/);
  const all = h.steps.join(' ');
  assert.match(all, /compte Samsung/);
  assert.match(all, /Ajouter à Samsung Wallet/);
  assert.doesNotMatch(all, /Mises à jour automatiques|Google/);
  assert.equal(WALLET_NAMES.samsung, 'Samsung Wallet');
});

test('never added: the note names the three Wallets', () => {
  assert.match(walletHelp({ linked: false, reason: 'never_added' }).note, /Samsung Wallet/);
});
