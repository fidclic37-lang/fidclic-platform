/**
 * « Ajouter à Apple Wallet » works from any app (user, 2026-11-20: a client of
 * a shop opened his card in another browser, the button downloaded a file
 * instead of the Wallet card). On an iPhone only Safari hands a pass to
 * Wallet; Instagram, Facebook, Chrome… only download it.
 *
 *   · Safari: the button is the pass, as before
 *   · any other browser or app on an iPhone: the button opens this card in
 *     Safari (x-safari-https://…), with the card's key, ready to add — never
 *     the pass file there, so nothing downloads
 *   · Safari did not open: « Ouvrez dans Safari » with the steps and a
 *     « Copier le lien »
 *   · arrived in Safari from there (/card/<id>?k=…&wallet=apple): the card
 *     page has no « Ma carte » tab any more (user, 2026-11-25), so it starts
 *     the add itself — the same pass link the old button was — says so, and
 *     the address bar forgets ?wallet= (and the key, as before)
 *   · Android and computers: nothing changes
 *
 * The real Wallet sheet only exists on a real iPhone: here the phones are
 * stood in for by their user agents. Local server and demo shop only.
 */
import { test, expect } from '@playwright/test';

const SLUG = 'cafe-lumiere';
const IOS = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko)';
const UA = {
  safari: `${IOS} Version/18.1 Mobile/15E148 Safari/604.1`,
  instagram: `${IOS} Mobile/22B83 Instagram 357.0.0.25.101 (iPhone15,2; iOS 18_1; fr_FR; fr; scale=3.00; 1179x2556; 652397411)`,
  chrome: `${IOS} CriOS/131.0.6778.73 Mobile/15E148 Safari/604.1`,
  android: 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Mobile Safari/537.36',
};

function phone(ua) {
  return { userAgent: ua, viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true,
           permissions: ['clipboard-read', 'clipboard-write'] };
}

async function signUp(page) {
  // no Apple keys locally: the config says Apple is on, the pass is never built
  await page.route('**/api/wallet/config**', async (r) => {
    try {
      const real = await (await r.fetch()).json();
      await r.fulfill({ json: { ...real, apple: true, google: true } });
    } catch (_e) { /* the page closed while it was on its way */ }
  });
  await page.route('**/wallet-prepare**', (r) => r.fulfill({ json: { apple: true, google_url: null } }));
  await page.goto(`/join/${SLUG}`);
  await expect(page.getByLabel('Nom complet')).toBeVisible();
  const store = page.getByLabel('Votre établissement');
  if (await store.count()) await store.selectOption({ index: 1 });
  await page.getByLabel('Nom complet').fill('Safari Test');
  await page.locator('#join-phone').fill(`06${String(Date.now()).slice(-8)}`);
  await page.getByLabel('Code postal').fill('37000');
  await page.getByLabel(/Date de naissance/).fill('03041992');
  await page.locator('#join-form input[type="checkbox"]').check();
  await page.getByRole('button', { name: /Rejoindre/ }).click();
  await expect(page.getByText('Félicitations !')).toBeVisible();
  return page.evaluate(() => {
    try {
      const all = JSON.parse(localStorage.getItem('fidclic:my_cards') || localStorage.getItem('ft_my_cards') || 'null');
      return all;
    } catch (_e) { return null; }
  });
}

const apple = (page) => page.getByRole('link', { name: /Ajouter à Apple Wallet/ });

test.describe('Safari on an iPhone', () => {
  test.use(phone(UA.safari));
  test('the button is the pass, as before', async ({ page }) => {
    await signUp(page);
    await expect(apple(page)).toHaveAttribute('href', /^\/api\/card\/FT-[A-Z0-9]+\/apple-wallet\.pkpass(\?k=.+)?$/);
  });

  test('arrived from another app: the card page starts the Apple add itself, ?wallet= forgotten', async ({ page }) => {
    await signUp(page);
    const href = await apple(page).getAttribute('href');
    const card = href.match(/FT-[A-Z0-9]+/)[0];
    const passes = [];
    // the real pass needs Apple's keys: a stand-in file (a desktop browser saves
    // it; an iPhone opens Wallet's sheet over the page), and count
    await page.route('**/apple-wallet.pkpass**', (r) => {
      passes.push(r.request().url());
      return r.fulfill({ status: 200, contentType: 'application/vnd.apple.pkpass',
        headers: { 'Content-Disposition': 'attachment; filename="carte.pkpass"' }, body: 'stand-in' });
    });
    await page.route('**/apple-wallet/added', (r) => r.fulfill({ json: { added: false } }));
    await page.goto(`/card/${card}?wallet=apple`);
    await expect.poll(() => passes.length, { timeout: 30_000 }).toBe(1);
    await expect(page.getByTestId('apple-wallet-opening')).toBeVisible({ timeout: 30_000 });
    const u = new URL(passes[0]);
    expect(u.pathname).toBe(`/api/card/${card}/apple-wallet.pkpass`);
    expect(u.searchParams.get('k'), 'the card\'s own key, as the old button had it').toBeTruthy();
    await expect.poll(() => page.url()).not.toContain('wallet=');
    // a way to try again by hand: the same pass link
    await expect(page.getByTestId('apple-wallet-opening').getByRole('link', { name: /Réessayer/ }))
      .toHaveAttribute('href', new RegExp(`^/api/card/${card}/apple-wallet\\.pkpass`));
    // nothing else of the old « Ma carte »
    await expect(page.getByRole('tab', { name: 'Ma carte' })).toHaveCount(0);
    await page.reload();
    await page.waitForTimeout(1500);
    expect(passes.length, 'only once: a reload no longer carries ?wallet=').toBe(1);
  });
});

for (const [name, ua] of [['Instagram', UA.instagram], ['Chrome on an iPhone', UA.chrome]]) {
  test.describe(name, () => {
    test.use(phone(ua));
    test('the button opens this card in Safari, with its key — no pass, no download', async ({ page }) => {
      const passes = [];
      page.on('request', (r) => { if (r.url().includes('apple-wallet.pkpass')) passes.push(r.url()); });
      await signUp(page);
      const href = await apple(page).getAttribute('href');
      // the add page (user, 2026-11-25): the Wallet sheet at once, no second tap
      expect(href).toMatch(/^x-safari-https?:\/\/[^/]+\/card\/FT-[A-Z0-9]+\/ajouter\?/);
      const u = new URL(href.replace(/^x-safari-/, ''));
      expect(u.searchParams.get('k'), 'the card\'s own key goes along').toBeTruthy();
      expect(u.origin).toBe(new URL(page.url()).origin);                   // our own site, nowhere else
      await apple(page).click();
      expect(passes, 'nothing downloads').toEqual([]);
    });

    test('a ?wallet=apple link opened here (not Safari) never starts the pass (it would download)', async ({ page }) => {
      await signUp(page);
      const card = (await apple(page).getAttribute('href')).match(/FT-[A-Z0-9]+/)[0];
      const passes = [];
      page.on('request', (r) => { if (r.url().includes('apple-wallet.pkpass')) passes.push(r.url()); });
      await page.goto(`/card/${card}?wallet=apple`);
      await expect(page.getByRole('heading', { name: /Bonjour/ })).toBeVisible({ timeout: 15_000 });
      await page.waitForTimeout(1500);
      expect(passes).toEqual([]);
      await expect(page.getByTestId('apple-wallet-opening')).toHaveCount(0);
      await expect.poll(() => page.url()).not.toContain('wallet=');
    });

    test('Safari did not open: « Ouvrez dans Safari », the steps and « Copier le lien »', async ({ page }) => {
      await signUp(page);
      const href = await apple(page).getAttribute('href');
      await apple(page).click();                                            // here nothing opens Safari
      const help = page.getByTestId('apple-wallet-safari-help');
      await expect(help).toBeVisible({ timeout: 4000 });
      await expect(help).toContainText('Safari');
      await help.getByRole('button', { name: /Copier le lien/ }).click();
      await expect(help).toContainText(/Lien copié/);
      const copied = await page.evaluate(() => navigator.clipboard.readText());
      expect(copied).toBe(href.replace(/^x-safari-/, ''));
    });
  });
}

test.describe('Android', () => {
  test.use(phone(UA.android));
  test('nothing changes: no Safari link anywhere', async ({ page }) => {
    await signUp(page);
    await expect(page.getByRole('button', { name: /Ajouter à Google Wallet/ })).toBeVisible();   // the buttons are there
    const links = await page.locator('a[href^="x-safari"]').count();
    expect(links).toBe(0);
  });
});
