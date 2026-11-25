// Run: node --test src/lib/walletOpen.test.js
// « Ajouter à Apple Wallet », then the Wallet opens (user, 2026-11-25). iOS
// adds the card and comes back to Safari without telling the page; the
// iPhone tells our server, and the page waits for that word.
import test from 'node:test';
import assert from 'node:assert/strict';
import { waitForAppleAdd, APPLE_WALLET_APP, WAIT } from './walletOpen.js';

// a fake clock: sleep moves time on, nothing really waits
function clock() {
  let t = 0;
  return { now: () => t, sleep: async (ms) => { t += ms; } };
}

test('the Wallet app link', () => {
  assert.equal(APPLE_WALLET_APP, 'shoebox://');
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
  // hidden the whole time: false, never asked
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
