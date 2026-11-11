// Run: node --test src/lib/phoneWallet.test.js
import test from 'node:test';
import assert from 'node:assert/strict';
import { phoneWallet, phoneWallets, walletOrder } from './phoneWallet.js';

const UA = {
  iphone: 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1',
  ipad: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/18.0 Safari/605.1.15',
  pixel: 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/126.0 Mobile Safari/537.36',
  galaxyChrome: 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 Chrome/126.0 Mobile Safari/537.36',
  galaxyInternet: 'Mozilla/5.0 (Linux; Android 14; SM-S921B) AppleWebKit/537.36 SamsungBrowser/25.0 Chrome/121.0 Mobile Safari/537.36',
  mac: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126.0 Safari/537.36',
};

test('the phone’s own Wallet (unchanged): iPhone → apple, Android → google, computer → none', () => {
  assert.equal(phoneWallet(UA.iphone, 5), 'apple');
  assert.equal(phoneWallet(UA.ipad, 5), 'apple');
  assert.equal(phoneWallet(UA.pixel, 5), 'google');
  assert.equal(phoneWallet(UA.mac, 0), null);
});

test('the Wallets a phone can hold: an Android phone may be a Galaxy (Chrome hides the model)', () => {
  assert.deepEqual(phoneWallets(UA.iphone, 5), ['apple']);
  assert.deepEqual(phoneWallets(UA.pixel, 5), ['google', 'samsung']);
  assert.deepEqual(phoneWallets(UA.galaxyChrome, 5), ['google', 'samsung']);
  assert.deepEqual(phoneWallets(UA.mac, 0), []);
  assert.deepEqual(phoneWallets('', 0), []);
});

test('a Galaxy that says so (Samsung Internet, SM- model): Samsung first', () => {
  assert.deepEqual(phoneWallets(UA.galaxyInternet, 5), ['samsung', 'google']);
});

test('the order of the buttons: the phone’s Wallets first, then the rest', () => {
  assert.deepEqual(walletOrder(UA.iphone, 5), ['apple', 'google', 'samsung']);
  assert.deepEqual(walletOrder(UA.pixel, 5), ['google', 'samsung', 'apple']);
  assert.deepEqual(walletOrder(UA.galaxyInternet, 5), ['samsung', 'google', 'apple']);
  assert.deepEqual(walletOrder(UA.mac, 0), ['apple', 'google', 'samsung']);
});
