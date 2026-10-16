// The signup's « Félicitations » page (user, 2026-10-13, QA BUG-008), in a real
// browser:
//   • an iPhone sees only « Ajouter à Apple Wallet », an Android phone only
//     Google's, and neither offers « Voir ma carte » — the card goes to the
//     Wallet; a computer gets « Voir ma carte »;
//   • the card shown is the very pass the Wallet gets (GET …/pass-view), not
//     a drawing of an older layout;
//   • the button is on screen the moment the page is (user, 2026-10-16: it sat
//     under a card 500 px tall and needed a scroll), and the pass is got ready
//     without waiting for that card to be drawn.
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


// The button must need no scroll — it is the one thing the customer has to do.
for (const [size, w, h] of [['iPhone 14', 390, 844], ['iPhone SE', 375, 667]]) {
  test.describe(`${size}`, () => {
    test.use({ userAgent: UA.iphone, viewport: { width: w, height: h } });
    test('« Ajouter à Apple Wallet » is on screen without scrolling', async ({ page }) => {
      await signUp(page);
      // measured once the card is really drawn: the iOS 27 poster is ~500 px
      // tall, and that is what used to push the button off screen
      const card = page.locator('[translate="no"]').first();
      await expect(card).toBeVisible({ timeout: 15000 });
      await expect.poll(async () => (await card.boundingBox())?.height || 0,
        { message: 'the card has its real height' }).toBeGreaterThan(300);
      const btn = page.getByText(/Apple Wallet/).first();
      await expect(btn).toBeVisible();
      const box = await btn.boundingBox();
      expect(await page.evaluate(() => window.scrollY)).toBe(0);
      expect(box.y).toBeGreaterThan(0);
      expect(box.y + box.height, `the button ends at ${Math.round(box.y + box.height)} px of ${h}`).toBeLessThanOrEqual(h);
      // and the card is below it, not above
      expect((await card.boundingBox()).y).toBeGreaterThan(box.y);
    });
  });
}

test.describe('a slow card', () => {
  test.use({ userAgent: UA.iphone, viewport: { width: 390, height: 844 } });
  test('the pass is got ready without waiting for the card to be drawn', async ({ page }) => {
    // the card's own view takes 6 s; the button must not wait for it
    await page.route('**/pass-view**', async (r) => {
      await new Promise((ok) => setTimeout(ok, 6000));
      await r.fulfill({ status: 500, contentType: 'application/json', body: '{"detail":"slow"}' });
    });
    const prepared = [];
    page.on('request', (q) => { if (q.url().includes('wallet-prepare')) prepared.push(Date.now()); });
    const t0 = Date.now();
    await signUp(page);
    await expect(page.getByText(/Apple Wallet/).first()).toBeVisible();
    await expect.poll(() => prepared.length, { timeout: 4000, message: 'wallet-prepare asked for while the card is still loading' }).toBeGreaterThan(0);
    expect(prepared[0] - t0, 'prepared well before the 6 s card').toBeLessThan(5000);
  });
});
