// Run: node --test src/lib/walletOpen.test.js
// « Ajouter à Apple Wallet », then that card on the iPhone (user, 2026-11-25).
// iOS adds the card and comes back to the browser without telling the page;
// the iPhone tells our server, and the page waits for that word. The card is
// then opened by its own « Bienvenue » banner — no web page may open Wallet.
import test from 'node:test';
import assert from 'node:assert/strict';
import { waitForAppleAdd, WAIT, passHref, addPageHref } from './walletOpen.js';
import * as walletOpen from './walletOpen.js';

// a fake clock: sleep moves time on, nothing really waits
function clock() {
  let t = 0;
  return { now: () => t, sleep: async (ms) => { t += ms; } };
}

test('no shoebox:// any more: it opened Wallet on the other cards (user, 2026-11-25)', () => {
  assert.equal(walletOpen.APPLE_WALLET_APP, undefined);
});

test('the pass link carries the card\'s own key — the phone\'s memory may be gone', () => {
  assert.equal(passHref('FT-AB12CD34', 'k3y'), '/api/card/FT-AB12CD34/apple-wallet.pkpass?k=k3y');
  assert.equal(passHref('ft-ab12cd34', 'k3y'), '/api/card/FT-AB12CD34/apple-wallet.pkpass?k=k3y');
  assert.equal(passHref('FT-AB12CD34', 'a b&c'), '/api/card/FT-AB12CD34/apple-wallet.pkpass?k=a%20b%26c');
  assert.equal(passHref('FT-AB12CD34', ''), '/api/card/FT-AB12CD34/apple-wallet.pkpass');
  assert.equal(passHref('FT-AB12CD34', null), '/api/card/FT-AB12CD34/apple-wallet.pkpass');
  assert.equal(passHref('', 'k'), null);
  assert.equal(passHref('../admin', 'k'), null, 'only a card number');
});

test('the add page, for Safari: one tap less than the card page', () => {
  assert.equal(addPageHref('https://app.fidclic.com', 'FT-AB12CD34', 'k3y'),
    'https://app.fidclic.com/card/FT-AB12CD34/ajouter?k=k3y');
  assert.equal(addPageHref('https://app.fidclic.com/', 'ft-ab12cd34', 'k3y'),
    'https://app.fidclic.com/card/FT-AB12CD34/ajouter?k=k3y');
  assert.equal(addPageHref('https://app.fidclic.com', 'FT-AB12CD34', ''), null, 'no key: Safari could never add it');
  assert.equal(addPageHref('https://app.fidclic.com', '', 'k'), null);
  assert.equal(addPageHref('javascript:alert(1)', 'FT-AB12CD34', 'k'), null, 'a web page only');
});

test('added at the third answer: true, and no more questions', async () => {
  const c = clock();
  const answers = [false, false, true, true];
  let asked = 0;
  const r = await waitForAppleAdd({ ask: async () => answers[asked++], ...c });
  assert.equal(r, true);
  assert.equal(asked, 3);
});

test('never added: false once the time is up, with a bounded number of questions', async () => {
  const c = clock();
  let asked = 0;
  const r = await waitForAppleAdd({ ask: async () => { asked += 1; return false; }, ...c });
  assert.equal(r, false);
  assert.ok(c.now() >= WAIT.until, `stopped at ${c.now()} ms`);
  assert.ok(asked <= Math.ceil(WAIT.until / WAIT.every) + 1, `${asked} questions`);
  assert.ok(asked >= 10, `${asked} questions: kept asking`);
});

test('the first question waits a moment: the sheet is still open', async () => {
  const c = clock();
  let firstAt = null;
  await waitForAppleAdd({ ask: async () => { if (firstAt === null) firstAt = c.now(); return true; }, ...c });
  assert.ok(firstAt >= WAIT.every, `first asked at ${firstAt} ms`);
});

test('a failing question (network) is not an answer: it keeps asking', async () => {
  const c = clock();
  let asked = 0;
  const r = await waitForAppleAdd({
    ask: async () => { asked += 1; if (asked < 3) throw new Error('offline'); return true; }, ...c,
  });
  assert.equal(r, true);
  assert.equal(asked, 3);
});

test('page hidden (the Wallet or another app in front): no question asked', async () => {
  const c = clock();
  let asked = 0;
  let hiddenUntil = 10_000;
  const r = await waitForAppleAdd({
    ask: async () => { asked += 1; return true; }, hidden: () => c.now() < hiddenUntil, ...c,
  });
  assert.equal(r, true);
  assert.equal(asked, 1);
  assert.ok(c.now() >= hiddenUntil);
  const c2 = clock();
  asked = 0;
  hiddenUntil = Infinity;
  const r2 = await waitForAppleAdd({ ask: async () => { asked += 1; return true; }, hidden: () => true, ...c2 });
  assert.equal(r2, false);
  assert.equal(asked, 0);
});

test('cancelled (the page left, a second tap): false, no more questions', async () => {
  const c = clock();
  let asked = 0;
  let stop = false;
  const r = await waitForAppleAdd({
    ask: async () => { asked += 1; if (asked === 2) stop = true; return false; }, cancelled: () => stop, ...c,
  });
  assert.equal(r, false);
  assert.equal(asked, 2);
});

test('a strange answer (null, "yes", {}) is not « added »', async () => {
  for (const odd of [null, undefined, 'yes', 1, {}, { added: true }]) {
    const c = clock();
    let n = 0;
    const r = await waitForAppleAdd({ ask: async () => { n += 1; return n === 1 ? odd : true; }, ...c });
    assert.equal(r, true);
    assert.equal(n, 2, `${JSON.stringify(odd)} was taken as added`);
  }
});
