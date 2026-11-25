// The signup's « Félicitations » page, in a real browser:
//   • an iPhone sees only « Ajouter à Apple Wallet », an Android phone only
//     Google's, and neither offers « Voir ma carte » — the card goes to the
//     Wallet; a computer gets « Voir ma carte » (QA BUG-008, 2026-10-13);
//   • no card on the page any more — the fireworks and the buttons only
//     (user, 2026-11-25): the card is looked at in the Wallet, not here;
//   • the button is on screen the moment the page is, and the pass is got
//     ready at once (user, 2026-10-16);
//   • the button opens the phone's own Wallet (user, 2026-11-25): Google's
//     is a plain link to Google Wallet as soon as it is ready; Apple's adds the
//     card, and once the iPhone has told the server the card is in its Wallet,
//     the page says « Carte ajoutée » and points to the card's « Bienvenue »
//     notification, which opens that card (shoebox:// opened the other cards).
// The local server has no Apple / Google keys: /api/wallet/config is answered
// here as on production. Runs against the local server only (scripts/dev_local.py).
import { test, expect } from '@playwright/test';

const SLUG = 'cafe-lumiere';
const UA = {
  iphone: 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1',
  iphone27: 'Mozilla/5.0 (iPhone; CPU iPhone OS 27_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/27.0 Mobile/15E148 Safari/604.1',
  android: 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36',
};
const GOOGLE_SAVE = 'https://pay.google.com/gp/v/save/e2e-token';

async function signUp(page, { googleUrl = null } = {}) {
  await page.route('**/api/wallet/config**', (r) => r.fulfill({ contentType: 'application/json', body: '{"apple":true,"google":true}' }));
  await page.route('**/wallet-prepare**', (r) => r.fulfill({ contentType: 'application/json', body: JSON.stringify({ apple: true, google_url: googleUrl }) }));
  const views = [];
  page.on('request', (q) => { if (q.url().includes('/pass-view') || q.url().includes('/wallet-strip')) views.push(q.url()); });
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
  ['iPhone on iOS 27', UA.iphone27, /Apple Wallet/, /Google Wallet/],
  ['Android', UA.android, /Google Wallet/, /Apple Wallet/]]) {
  test.describe(`${device}`, () => {
    test.use({ userAgent: ua, viewport: { width: 390, height: 844 } });
    test('the fireworks and its own Wallet button — no card, no « Voir ma carte »', async ({ page }) => {
      const views = await signUp(page);
      await expect(page.getByText(own).first()).toBeVisible();
      await expect(page.getByText(other)).toHaveCount(0);
      await expect(page.getByRole('link', { name: /Voir ma carte/ })).toHaveCount(0);
      await expect(page.locator('canvas[aria-hidden="true"]'), 'the fireworks').toHaveCount(1);
      await page.waitForTimeout(2500);                  // a card would have been drawn by now
      expect(views, 'the card is not drawn on this page').toEqual([]);
      await expect(page.getByRole('button', { name: /Au dos de la carte/ })).toHaveCount(0);
      await expect(page.getByRole('button', { name: 'iOS 27', exact: true })).toHaveCount(0);
      await expect(page.getByText('Wallet Test')).toHaveCount(0);   // the card's own name line
    });
  });
}

test.describe('a computer', () => {
  test.use({ viewport: { width: 1280, height: 900 } });
  test('« Voir ma carte », no Wallet button, no card', async ({ page }) => {
    const views = await signUp(page);
    await expect(page.getByRole('link', { name: /Voir ma carte/ })).toBeVisible();
    await expect(page.getByText(/Ajouter à (Apple|Google) Wallet/)).toHaveCount(0);
    await page.waitForTimeout(1500);
    expect(views).toEqual([]);
  });
});

// The button must need no scroll — it is the one thing the customer has to do.
for (const [size, w, h] of [['iPhone 14', 390, 844], ['iPhone SE', 375, 667]]) {
  test.describe(`${size}`, () => {
    test.use({ userAgent: UA.iphone, viewport: { width: w, height: h } });
    test('« Ajouter à Apple Wallet » is on screen without scrolling', async ({ page }) => {
      await signUp(page);
      const btn = page.getByText(/Apple Wallet/).first();
      await expect(btn).toBeVisible();
      const box = await btn.boundingBox();
      expect(await page.evaluate(() => window.scrollY)).toBe(0);
      expect(box.y).toBeGreaterThan(0);
      expect(box.y + box.height, `the button ends at ${Math.round(box.y + box.height)} px of ${h}`).toBeLessThanOrEqual(h);
    });
  });
}

test.describe('ready at once', () => {
  test.use({ userAgent: UA.iphone, viewport: { width: 390, height: 844 } });
  test('the pass is got ready as soon as the page shows', async ({ page }) => {
    const prepared = [];
    page.on('request', (q) => { if (q.url().includes('wallet-prepare')) prepared.push(Date.now()); });
    await signUp(page);
    const shown = Date.now();
    await expect(page.getByText(/Apple Wallet/).first()).toBeVisible();
    await expect.poll(() => prepared.length, { timeout: 4000, message: 'wallet-prepare asked for' }).toBeGreaterThan(0);
    expect(prepared[0] - shown).toBeLessThan(4000);
  });
});


// ── the button opens the Wallet ────────────────────────────────────────────

test.describe('Android: Google Wallet', () => {
  test.use({ userAgent: UA.android, viewport: { width: 390, height: 844 } });
  test('ready: the button is the Google Wallet link itself (Android hands it to the app)', async ({ page }) => {
    await signUp(page, { googleUrl: GOOGLE_SAVE });
    const link = page.getByRole('link', { name: /Ajouter à Google Wallet/ });
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute('href', GOOGLE_SAVE);
  });
  test('not ready yet: the button asks for the link, then goes to Google Wallet', async ({ page }) => {
    await page.route('**/google-wallet', (r) => r.fulfill({ json: { url: GOOGLE_SAVE } }));
    await page.route('https://pay.google.com/**', (r) => r.fulfill({ contentType: 'text/html', body: '<p>Google Wallet</p>' }));
    await signUp(page);
    await page.getByRole('button', { name: /Ajouter à Google Wallet/ }).click();
    await expect(page).toHaveURL(GOOGLE_SAVE);
  });
});

test.describe('iPhone: Apple Wallet', () => {
  test.use({ userAgent: UA.iphone, viewport: { width: 390, height: 844 }, acceptDownloads: true });

  async function tapApple(page, answers) {
    const asked = [];
    await page.route('**/apple-wallet.pkpass**', (r) => r.fulfill({
      contentType: 'application/vnd.apple.pkpass', body: 'PK-e2e', headers: { 'Content-Disposition': 'attachment; filename=card.pkpass' },
    }));
    await page.route('**/apple-wallet/added**', (r) => {
      asked.push(r.request().headers()['x-card-key'] || new URL(r.request().url()).searchParams.get('k'));
      r.fulfill({ json: { added: answers.length ? answers.shift() : true } });
    });
    await signUp(page);
    const apple = page.getByRole('link', { name: /Ajouter à Apple Wallet/ });
    await expect(apple).toHaveAttribute('href', /\/api\/card\/FT-[A-Z0-9]+\/apple-wallet\.pkpass/);
    await apple.click();
    return asked;
  }

  test('added: « Carte ajoutée » and the « Bienvenue » notification to touch — never shoebox://', async ({ page }) => {
    const asked = await tapApple(page, [false, false, true]);
    await expect(page.getByText(/Carte ajoutée à Apple Wallet/)).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/notification/i)).toBeVisible();
    // shoebox:// opened Wallet on the other cards (user, 2026-11-25)
    expect(await page.locator('a[href^="shoebox:"]').count()).toBe(0);
    await expect(page.getByRole('link', { name: /Ouvrir Apple Wallet/ })).toHaveCount(0);
    await expect(page.getByRole('link', { name: /Ajouter à Apple Wallet/ }), 'already added: no second « Ajouter »').toHaveCount(0);
    expect(asked.length, 'asked until added, then stopped').toBe(3);
    expect(asked.every(Boolean), 'each question carries the card\'s own key').toBe(true);
    await page.waitForTimeout(3000);
    expect(asked.length, 'no more questions once added').toBe(3);
  });

  test('not added (the customer closed the sheet): nothing changes, no « Ouvrir »', async ({ page }) => {
    await tapApple(page, Array(200).fill(false));
    await page.waitForTimeout(5000);
    await expect(page.getByRole('link', { name: /Ajouter à Apple Wallet/ })).toBeVisible();
    await expect(page.getByText(/Carte ajoutée/)).toHaveCount(0);
  });

  test('nothing is asked before the tap', async ({ page }) => {
    const asked = [];
    await page.route('**/apple-wallet/added**', (r) => { asked.push(1); r.fulfill({ json: { added: true } }); });
    await signUp(page);
    await page.waitForTimeout(4000);
    expect(asked).toEqual([]);
    await expect(page.getByRole('link', { name: /Ouvrir Apple Wallet/ })).toHaveCount(0);
  });
});
