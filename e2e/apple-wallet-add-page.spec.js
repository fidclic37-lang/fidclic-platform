/**
 * « Ajouter à Apple Wallet » from Chrome (or any app) on an iPhone, in one go
 * (user, 2026-11-25: Chrome → the old card page → tap → « Ouvrir dans
 * Safari » → tap again… « itne saare steps n ho »).
 *
 *   · Chrome / an app: the button opens /card/<id>/ajouter in Safari, with
 *     the card's key — not the card page
 *   · that page shows the Wallet sheet by itself (no second tap), keeps the
 *     key in the link it was given (Soan, Royal Trim Liberté, 2026-11-25: the
 *     key was gone from the phone's memory by the tap — five 403), and once
 *     the iPhone has the card: « Carte ajoutée » and the « Bienvenue »
 *     notification to touch — never shoebox:// (it opened the other cards)
 *   · a wrong or missing key: a plain sentence, no pass asked
 *   · not Safari: back to Safari; not an iPhone: « Voir ma carte »
 *
 * The real Wallet sheet only exists on a real iPhone: here the phones are
 * stood in for by their user agents. Local server and demo shop only.
 */
import { test, expect } from '@playwright/test';

const SLUG = 'cafe-lumiere';
const IOS = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko)';
const UA = {
  safari: `${IOS} Version/26.6.1 Mobile/15E148 Safari/604.1`,
  chrome: `${IOS} CriOS/131.0.6778.73 Mobile/15E148 Safari/604.1`,
  instagram: `${IOS} Mobile/22B83 Instagram 357.0.0.25.101 (iPhone15,2; iOS 18_1; fr_FR; fr; scale=3.00; 1179x2556; 652397411)`,
  android: 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Mobile Safari/537.36',
};
const uniquePhone = (p) => `${p}${String(Math.floor(Math.random() * 1e8)).padStart(8, '0')}`;
const phone = (ua) => ({ userAgent: ua, viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, acceptDownloads: true });

// a fresh client: signed up on the page, its card number and key read back
async function newCard(browser) {
  const ctx = await browser.newContext(phone(UA.safari));
  const page = await ctx.newPage();
  await page.route('**/api/wallet/config**', (r) => r.fulfill({ json: { apple: true, google: true } }));
  await page.route('**/wallet-prepare**', (r) => r.fulfill({ json: { apple: true, google_url: null } }));
  await page.goto(`/join/${SLUG}`);
  await expect(page.getByLabel('Nom complet')).toBeVisible();
  const store = page.getByLabel('Votre établissement');
  if (await store.count()) await store.selectOption({ index: 1 });
  await page.getByLabel('Nom complet').fill('Ajout Test');
  await page.locator('#join-phone').fill(uniquePhone('06'));
  await page.getByLabel('Code postal').fill('37000');
  await page.getByLabel(/Date de naissance/).fill('03041992');
  await page.locator('#join-form input[type="checkbox"]').check();
  await page.getByRole('button', { name: /Rejoindre/ }).click();
  await expect(page.getByText('Félicitations !')).toBeVisible();
  const mine = await page.evaluate(() => JSON.parse(localStorage.getItem('fidclic:my_cards') || '{}'));
  await ctx.close();
  const [bc, key] = Object.entries(mine)[0];
  return { bc, key };
}

// the phone's side of the pass: every pass asked is noted, none is built
async function watchPass(page, answers = []) {
  const passes = [];
  const asked = [];
  await page.route('**/api/wallet/config**', (r) => r.fulfill({ json: { apple: true, google: true } }));
  await page.route('**/apple-wallet.pkpass**', (r) => {
    passes.push(new URL(r.request().url()).searchParams.get('k'));
    r.fulfill({ contentType: 'application/vnd.apple.pkpass', body: 'PK-e2e',
                headers: { 'Content-Disposition': 'attachment; filename=card.pkpass' } });
  });
  await page.route('**/apple-wallet/added**', async (r) => {
    const k = new URL(r.request().url()).searchParams.get('k') || r.request().headers()['x-card-key'] || null;
    asked.push(k);
    if (answers.length) { r.fulfill({ json: { added: answers.shift() } }); return; }
    await r.continue();                     // the real server: it checks the key
  });
  return { passes, asked };
}

test.describe('Chrome on an iPhone, after the signup', () => {
  test.use(phone(UA.chrome));
  test('the Apple button opens the add page in Safari, with the key — not the card page', async ({ page }) => {
    await page.route('**/api/wallet/config**', (r) => r.fulfill({ json: { apple: true, google: true } }));
    await page.route('**/wallet-prepare**', (r) => r.fulfill({ json: { apple: true, google_url: null } }));
    await page.goto(`/join/${SLUG}`);
    await expect(page.getByLabel('Nom complet')).toBeVisible();
    const store = page.getByLabel('Votre établissement');
    if (await store.count()) await store.selectOption({ index: 1 });
    await page.getByLabel('Nom complet').fill('Chrome Test');
    await page.locator('#join-phone').fill(uniquePhone('07'));
    await page.getByLabel('Code postal').fill('37000');
    await page.getByLabel(/Date de naissance/).fill('03041992');
    await page.locator('#join-form input[type="checkbox"]').check();
    await page.getByRole('button', { name: /Rejoindre/ }).click();
    await expect(page.getByText('Félicitations !')).toBeVisible();
    const apple = page.getByRole('link', { name: /Ajouter à Apple Wallet/ });
    await expect(apple).toHaveAttribute('href', /^x-safari-https?:\/\/[^/]+\/card\/FT-[A-Z0-9]+\/ajouter\?k=[0-9a-f]+$/);
  });
});

test.describe('the add page, in Safari', () => {
  test.use(phone(UA.safari));

  test('the Wallet sheet comes by itself, the key rides along, then « Carte ajoutée » + the notification', async ({ browser, page }) => {
    const { bc, key } = await newCard(browser);
    const { passes, asked } = await watchPass(page, [false, false, true]);
    await page.goto(`/card/${bc}/ajouter?k=${key}`);
    await expect.poll(() => passes.length, { message: 'the pass was asked without a tap', timeout: 6000 }).toBeGreaterThan(0);
    expect(passes[0]).toBe(key);
    await expect(page).not.toHaveURL(/k=/);                       // the key leaves the address bar
    await expect(page.getByText(/Carte ajoutée à Apple Wallet/)).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/notification/i)).toBeVisible();
    expect(asked.every((k) => k === key), 'each question carries the key').toBe(true);
    expect(await page.locator('a[href^="shoebox:"]').count(), 'never shoebox://').toBe(0);
    await expect(page.getByRole('link', { name: /Ajouter à Apple Wallet/ })).toHaveCount(0);
  });

  test('sheet closed: one tap adds it again — even with the phone\'s memory gone', async ({ browser, page }) => {
    const { bc, key } = await newCard(browser);
    const { passes } = await watchPass(page, Array(200).fill(false));
    await page.goto(`/card/${bc}/ajouter?k=${key}`);
    await expect.poll(() => passes.length, { timeout: 6000 }).toBe(1);
    await page.evaluate(() => localStorage.clear());
    const again = page.getByRole('link', { name: /Ajouter à Apple Wallet/ });
    await expect(again).toBeVisible();
    await again.click();
    await expect.poll(() => passes.length, { timeout: 6000 }).toBe(2);
    expect(passes[1]).toBe(key);
  });

  test('a wrong key: a plain sentence, no pass asked', async ({ browser, page }) => {
    const { bc } = await newCard(browser);
    const { passes } = await watchPass(page);
    await page.goto(`/card/${bc}/ajouter?k=0000000000deadbeef00`);
    await expect(page.getByText(/ne permet pas d'ajouter/)).toBeVisible();
    await page.waitForTimeout(1500);
    expect(passes).toEqual([]);
    expect(await page.content()).not.toContain('"detail"');
  });

  test('no key at all: the same sentence, no pass asked, nothing asked', async ({ page }) => {
    const { passes, asked } = await watchPass(page);
    await page.goto('/card/FT-NOKEY001/ajouter');
    await expect(page.getByText(/ne permet pas d'ajouter/)).toBeVisible();
    await page.waitForTimeout(1500);
    expect(passes).toEqual([]);
    expect(asked).toEqual([]);
  });

  test('not a card number: the same sentence', async ({ page }) => {
    const { passes } = await watchPass(page);
    await page.goto('/card/..%2Fadmin/ajouter?k=abc');
    await expect(page.getByText(/ne permet pas d'ajouter/)).toBeVisible();
    expect(passes).toEqual([]);
  });
});

test.describe('the add page, elsewhere', () => {
  test('in an app (Instagram): back to Safari, to this same page — nothing downloaded', async ({ browser }) => {
    const { bc, key } = await newCard(browser);
    const ctx = await browser.newContext(phone(UA.instagram));
    const page = await ctx.newPage();
    const { passes } = await watchPass(page);
    await page.goto(`/card/${bc}/ajouter?k=${key}`);
    const go = page.getByRole('link', { name: /Ajouter à Apple Wallet/ });
    await expect(go).toHaveAttribute('href', new RegExp(`^x-safari-https?://[^/]+/card/${bc}/ajouter\\?k=${key}$`));
    await page.waitForTimeout(1500);
    expect(passes).toEqual([]);
    await ctx.close();
  });

  test('an Android phone: « Voir ma carte », no Apple pass', async ({ browser }) => {
    const { bc, key } = await newCard(browser);
    const ctx = await browser.newContext(phone(UA.android));
    const page = await ctx.newPage();
    const { passes } = await watchPass(page);
    await page.goto(`/card/${bc}/ajouter?k=${key}`);
    await expect(page.getByRole('link', { name: /Voir ma carte/ })).toBeVisible();
    await page.waitForTimeout(1500);
    expect(passes).toEqual([]);
    await ctx.close();
  });
});

test.describe('Safari, the signup\'s own button', () => {
  test.use(phone(UA.safari));
  test('the phone\'s memory gone before the tap: the pass still carries the key', async ({ page }) => {
    const { passes, asked } = await watchPass(page, [true]);
    await page.route('**/wallet-prepare**', (r) => r.fulfill({ json: { apple: true, google_url: null } }));
    await page.goto(`/join/${SLUG}`);
    await expect(page.getByLabel('Nom complet')).toBeVisible();
    const store = page.getByLabel('Votre établissement');
    if (await store.count()) await store.selectOption({ index: 1 });
    await page.getByLabel('Nom complet').fill('Memoire Test');
    await page.locator('#join-phone').fill(uniquePhone('06'));
    await page.getByLabel('Code postal').fill('37000');
    await page.getByLabel(/Date de naissance/).fill('03041992');
    await page.locator('#join-form input[type="checkbox"]').check();
    await page.getByRole('button', { name: /Rejoindre/ }).click();
    await expect(page.getByText('Félicitations !')).toBeVisible();
    const apple = page.getByRole('link', { name: /Ajouter à Apple Wallet/ });
    await expect(apple).toBeVisible();
    await page.evaluate(() => localStorage.clear());
    await apple.click();
    await expect.poll(() => passes.length, { timeout: 6000 }).toBe(1);
    expect(passes[0], 'the pass carries the key').toMatch(/^[0-9a-f]{20}$/);
    await expect(page.getByText(/Carte ajoutée à Apple Wallet/)).toBeVisible({ timeout: 15_000 });
    expect(asked[0], 'the question carries the key').toBe(passes[0]);
    expect(await page.locator('a[href^="shoebox:"]').count()).toBe(0);
  });
});
