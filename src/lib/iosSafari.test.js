// Run: node --test src/lib/iosSafari.test.js
// « Ajouter à Apple Wallet » from any app (user, 2026-11-20): on an iPhone only
// Safari (and the Safari window apps open, same signature) hands a pass to
// Wallet. Anywhere else the page is sent to Safari.
import test from 'node:test';
import assert from 'node:assert/strict';
import { appleWalletPlace, safariLink } from './iosSafari.js';

const IOS = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko)';
const UA = {
  safari: `${IOS} Version/18.1 Mobile/15E148 Safari/604.1`,
  ipadSafari: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15',
  chrome: `${IOS} CriOS/131.0.6778.73 Mobile/15E148 Safari/604.1`,
  firefox: `${IOS} FxiOS/133.0 Mobile/15E148 Safari/605.1.15`,
  edge: `${IOS} EdgiOS/131.0.2903.68 Version/18.0 Mobile/15E148 Safari/604.1`,
  opera: `${IOS} Version/18.0 OPT/5.2.0 Mobile/15E148 Safari/604.1`,
  duck: `${IOS} Version/18.1 Mobile/15E148 Safari/604.1 Ddg/18.1`,
  google: `${IOS} GSA/343.0.695551749 Mobile/15E148 Safari/604.1`,
  instagram: `${IOS} Mobile/22B83 Instagram 357.0.0.25.101 (iPhone15,2; iOS 18_1; fr_FR; fr; scale=3.00; 1179x2556; 652397411)`,
  facebook: `${IOS} Mobile/22B83 [FBAN/FBIOS;FBAV/489.0.0.38.105;FBBV/668523093;FBDV/iPhone15,2;FBMD/iPhone;FBSN/iOS;FBSV/18.1;FBSS/3;FBCR/;FBID/phone;FBLC/fr_FR;FBOP/5]`,
  messenger: `${IOS} Mobile/22B83 [FBAN/MessengerForiOS;FBAV/486.0.0.40.109;FBBV/663853021;FBDV/iPhone15,2]`,
  tiktok: `${IOS} Mobile/22B83 musical_ly_37.3.0 JsSdk/2.0 NetType/WIFI Channel/App Store ByteLocale/fr Region/FR`,
  snapchat: `${IOS} Mobile/22B83 Snapchat/13.18.0.43 (like Safari/8619.1.26.30.5, panda)`,
  linkedin: `${IOS} Mobile/22B83 [LinkedInApp]/9.30.1660`,
  whatsapp: `${IOS} Mobile/22B83 WhatsApp/24.23.79`,
  bareWebView: `${IOS} Mobile/22B83`,
  android: 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Mobile Safari/537.36',
  macSafari: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15',
  macChrome: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36',
};

test('Safari on an iPhone or an iPad: the pass goes straight to Wallet', () => {
  assert.equal(appleWalletPlace(UA.safari, 5), 'safari');
  assert.equal(appleWalletPlace(UA.ipadSafari, 5), 'safari');       // iPadOS says « Macintosh », with a touch screen
});

test('any other browser on an iPhone: sent to Safari', () => {
  for (const k of ['chrome', 'firefox', 'edge', 'opera', 'duck', 'google']) {
    assert.equal(appleWalletPlace(UA[k], 5), 'other', k);
  }
});

test('an app\'s own browser (Instagram, Facebook, Messenger, TikTok, Snapchat, LinkedIn, WhatsApp, any web view): sent to Safari', () => {
  for (const k of ['instagram', 'facebook', 'messenger', 'tiktok', 'snapchat', 'linkedin', 'whatsapp', 'bareWebView']) {
    assert.equal(appleWalletPlace(UA[k], 5), 'other', k);
  }
});

test('not an iPhone or iPad: nothing changes', () => {
  assert.equal(appleWalletPlace(UA.android, 5), 'none');
  assert.equal(appleWalletPlace(UA.macSafari, 0), 'none');          // a Mac: no touch screen
  assert.equal(appleWalletPlace(UA.macChrome, 0), 'none');
  assert.equal(appleWalletPlace('', 0), 'none');
  assert.equal(appleWalletPlace(undefined, undefined), 'none');
});

test('the link that opens Safari: the same https page, behind Safari\'s own scheme', () => {
  assert.equal(safariLink('https://app.fidclic.com/card/FT-AB12CD34?k=xyz&wallet=apple'),
    'x-safari-https://app.fidclic.com/card/FT-AB12CD34?k=xyz&wallet=apple');
  assert.equal(safariLink('http://localhost:8811/card/FT-1'), 'x-safari-http://localhost:8811/card/FT-1');
  assert.equal(safariLink('javascript:alert(1)'), null);             // only a web page
  assert.equal(safariLink('x-safari-https://a.b/'), null);
  assert.equal(safariLink(''), null);
});
