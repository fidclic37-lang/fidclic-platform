// The signup's « Félicitations » page (user, 2026-10-13, QA BUG-008), in a real
// browser:
//   • an iPhone sees only « Ajouter à Apple Wallet », an Android phone only
//     Google's, and neither offers « Voir ma carte » — the card goes to the
//     Wallet; a computer gets « Voir ma carte »;
//   • the card shown is the very pass the Wallet gets (GET …/pass-view), not
//     a drawing of an older layout.
// The local server has no Apple / Google keys: /api/wallet/config is answered
// here as on production. Runs against the local server only (scripts/dev_local.py).
import { test, expect } from '@playwright/test';

const SLUG = 'cafe-lumiere';
const UA = {
  iphone: 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1',
  android: 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36',
};

async function signUp(page) {
  await page.route('**/api/wallet/config**', (r) => r.fulfill({ contentType: 'application/json', body: '{"apple":true,"google":true}' }));
  await page.route('**/wallet-prepare**', (r) => r.fulfill({ contentType: 'application/json', body: '{"apple":true,"google_url":null}' }));
  const views = [];
  page.on('request', (q) => { if (q.url().includes('/pass-view')) views.push(q.url()); });
  await page.goto(`/join/${SLUG}`);
  await expect(page.getByLabel('Nom complet')).toBeVisible();
  const store = page.getByLabel('Votre établissement');
  if (await store.count()) await store.selectOption({ index: 1 });
  await page.getByLabel('Nom complet').fill('Wallet Test');
  await page.locator('#join-phone').fill(`07${String(Date.now()).slice(-8)}`);
  await page.getByLabel('Code postal').fill('37000');
  await page.getByLabel(/Date de naissance/).fill('03041992');
  await page.locator('#join-form input[type="checkbox"]').check();
  await page.getByRole('button', { name: /Rejoindre/ }).click();
  await expect(page.getByText('Félicitations !')).toBeVisible();
  return views;
}

for (const [device, ua, own, other] of [['iPhone', UA.iphone, /Apple Wallet/, /Google Wallet/],
  ['Android', UA.android, /Google Wallet/, /Apple Wallet/]]) {
  test.describe(`${device}`, () => {
    test.use({ userAgent: ua, viewport: { width: 390, height: 844 } });
    test(`only its own Wallet, no « Voir ma carte », the live card`, async ({ page }) => {
      const views = await signUp(page);
      await expect(page.getByText(own).first()).toBeVisible();
      await expect(page.getByText(other)).toHaveCount(0);
      await expect(page.getByRole('link', { name: /Voir ma carte/ })).toHaveCount(0);
      await expect.poll(() => views.length, { message: 'the card is the real pass (…/pass-view)' }).toBeGreaterThan(0);
    });
  });
}

test.describe('a computer', () => {
  test.use({ viewport: { width: 1280, height: 900 } });
  test('« Voir ma carte », no Wallet button', async ({ page }) => {
    await signUp(page);
    await expect(page.getByRole('link', { name: /Voir ma carte/ })).toBeVisible();
    await expect(page.getByText(/Ajouter à (Apple|Google) Wallet/)).toHaveCount(0);
  });
});
