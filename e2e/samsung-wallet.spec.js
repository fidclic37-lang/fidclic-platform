// « Ajouter à Samsung Wallet » (user, 2026-11-11), in a real browser, against
// the local server only (scripts/dev_local.py) — run with the portal's ids:
//   SAMSUNG_WALLET_PARTNER_ID=4164397867037138496 SAMSUNG_WALLET_CARD_ID=3jina31gjvr00 \
//   SAMSUNG_WALLET_CERT_ID=XVli npx playwright test e2e/samsung-wallet.spec.js
//   • an Android phone gets Google's AND Samsung's button (Chrome on a Galaxy
//     hides the model), an iPhone never Samsung's;
//   • the button opens Samsung's Data Fetch Link for this card, and Samsung
//     then gets the card (GET /api/samsung-wallet/cards/{card}/{refId}) with
//     the very QR the till scans.
// a.swallet.link is answered here: no request leaves the machine.
import { test, expect } from '@playwright/test';

const SLUG = 'cafe-lumiere';
const CARD = '3jina31gjvr00';
const UA = {
  iphone: 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1',
  galaxy: 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36',
};

test.skip(!process.env.SAMSUNG_WALLET_CARD_ID, 'needs the Samsung ids in the local server env');

async function signUp(page) {
  // Apple / Google have no keys locally: their part of the config is answered here,
  // Samsung's comes from the real server
  await page.route('**/api/wallet/config**', async (r) => {
    const real = await (await r.fetch()).json();
    await r.fulfill({ json: { ...real, apple: true, google: true } });
  });
  await page.route('**/wallet-prepare**', (r) => r.fulfill({ json: { apple: true, google_url: null } }));
  await page.route('https://a.swallet.link/**', (r) => r.fulfill({ contentType: 'text/html', body: '<h1>Samsung Wallet</h1>' }));
  await page.goto(`/join/${SLUG}`);
  await expect(page.getByLabel('Nom complet')).toBeVisible();
  const store = page.getByLabel('Votre établissement');
  if (await store.count()) await store.selectOption({ index: 1 });
  await page.getByLabel('Nom complet').fill('Samsung Test');
  await page.locator('#join-phone').fill(`06${String(Date.now()).slice(-8)}`);
  await page.getByLabel('Code postal').fill('37000');
  await page.getByLabel(/Date de naissance/).fill('03041992');
  await page.locator('#join-form input[type="checkbox"]').check();
  await page.getByRole('button', { name: /Rejoindre/ }).click();
  await expect(page.getByText('Félicitations !')).toBeVisible();
}

// Test switch (SAMSUNG_WALLET_TENANTS): a shop not on the list never sees the button.
const SHOPS = (process.env.SAMSUNG_WALLET_TENANTS || '').split(',').map((s) => s.trim()).filter(Boolean);
const ON_HERE = !SHOPS.length || SHOPS.includes(SLUG);

test.describe('a Galaxy phone, shop not on the test list', () => {
  test.use({ userAgent: UA.galaxy, viewport: { width: 375, height: 812 } });
  test.skip(ON_HERE, 'run with SAMSUNG_WALLET_TENANTS=another-shop');
  test('no Samsung button, Google still there', async ({ page }) => {
    await signUp(page);
    await expect(page.getByText(/Ajouter à Google Wallet/)).toBeVisible();
    await expect(page.getByText(/Samsung Wallet/)).toHaveCount(0);
  });
});

test.describe('a Galaxy phone (Chrome)', () => {
  test.use({ userAgent: UA.galaxy, viewport: { width: 375, height: 812 } });
  test.skip(!ON_HERE, 'this shop is not on the test list');

  test('Google and Samsung buttons; Samsung opens its link and gets the card', async ({ page, request }) => {
    test.setTimeout(90_000);
    await signUp(page);
    const samsung = page.getByRole('button', { name: /Ajouter à Samsung Wallet/ });
    await expect(samsung).toBeVisible();
    await expect(page.getByText(/Ajouter à Google Wallet/)).toBeVisible();
    await expect(page.getByText(/Ajouter à Apple Wallet/)).toHaveCount(0);
    const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(over).toBeLessThanOrEqual(1);
    await page.screenshot({ path: 'test-results/samsung-signup-galaxy.png' });

    await samsung.click();
    await page.waitForURL(/a\.swallet\.link/);
    const url = page.url();
    expect(url).toMatch(new RegExp(`^https://a\\.swallet\\.link/atw/v3/XVli/${CARD}#Clip\\?pdata=[A-Za-z0-9_-]{16,32}$`));
    const ref = url.split('pdata=')[1];

    // what Samsung's server then does
    const r = await request.get(`/api/samsung-wallet/cards/${CARD}/${ref}`, {
      headers: { Authorization: 'Bearer x.y.z', 'x-request-id': '0'.repeat(32) } });
    expect(r.status()).toBe(200);
    const card = (await r.json()).card;
    expect(card.type).toBe('loyalty');
    const at = card.data[0].attributes;
    expect(at.title.length).toBeGreaterThan(0);
    expect(at['barcode.value']).toMatch(/\/card\/FT-/);
    expect(at['barcode.ptSubFormat']).toBe('QR_CODE');

    const added = await request.post(`/api/samsung-wallet/cards/${CARD}/${ref}?cc2=fr&event=ADDED`, {
      headers: { Authorization: 'Bearer x.y.z', 'x-request-id': '1'.repeat(32) }, data: {} });
    expect(added.status()).toBe(200);
    const none = await request.get(`/api/samsung-wallet/cards/${CARD}/not-a-real-reference-00`);
    expect(none.status()).toBe(204);
  });
});

test.describe('an iPhone', () => {
  test.use({ userAgent: UA.iphone, viewport: { width: 390, height: 844 } });
  test('never the Samsung button', async ({ page }) => {
    await signUp(page);
    await expect(page.getByText(/Ajouter à Apple Wallet/).first()).toBeVisible();
    await expect(page.getByText(/Samsung Wallet/)).toHaveCount(0);
  });
});
