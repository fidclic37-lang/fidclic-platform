/**
 * « Card Google Wallet mein tha, till ne bola add nahi hai » (user, 2026-11-11,
 * a client at a live shop: scanned 20 s before Google saved the
 * card). The receipt now:
 *   • says « pas encore dans un Wallet » softly (not a red error) and turns
 *     green by itself once the client adds the card;
 *   • in red only when the card is in a Wallet but cut off, with the steps
 *     worth trying for that Wallet (Apple / Google) and the QR to re-add it.
 * Real till, real server, local seed only.
 */
import crypto from 'node:crypto';
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
const PASS_SECRET = process.env.PASS_AUTH_SECRET || process.env.JWT_SECRET || 'dev-local-secret';
const passAuth = (serial) => `ApplePass ${crypto.createHmac('sha256', PASS_SECRET).update(serial).digest('hex').slice(0, 40)}`;
const PASSES = '/api/passes/v1/devices';

async function asOwner(page, request) {
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const store = ((br && br.branches) || br || []).find((b) => b.status !== 'closed')?.id || '';
  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
    try { sessionStorage.removeItem('ft_pick_store'); } catch (_e) { /* ignore */ }
  }, [login.access_token, store]);
  return { ...H, 'X-FidClic-Store': store || 'all' };
}

/** A demo client no phone holds and no other test touched (index per test + viewport). */
async function freeClient(request, H, index) {
  const list = await (await request.get('/api/owner/clients/list?per_page=40', { headers: H })).json();
  const rows = (list.rows || []).filter((x) => x.barcode_id);
  const c = rows[index];
  const w = await (await request.get(`/api/owner/clients/${c.id}/wallet`, { headers: H })).json();
  test.skip(w.apple.devices.length > 0 || w.google.saved, 'this demo client already holds a Wallet card');
  return c;
}

/** The iPhone's Wallet registering / unregistering the card (Apple's own calls). */
const register = (request, serial, device) => request.post(`${PASSES}/${device}/registrations/pass.e2e.test/${serial}`,
  { headers: { Authorization: passAuth(serial) }, data: { pushToken: `tok-${device}` } });
const unregister = (request, serial, device) => request.delete(`${PASSES}/${device}/registrations/pass.e2e.test/${serial}`,
  { headers: { Authorization: passAuth(serial) } });

async function recordVisit(page, barcode) {
  await page.goto('/dashboard/scan');
  await page.getByRole('button', { name: 'Saisir le code' }).click();
  await page.getByLabel('Code de la carte').fill(barcode);
  await expect(page.getByPlaceholder('0,00')).toBeVisible({ timeout: 15_000 });
  await page.getByPlaceholder('0,00').fill('5');
  await page.getByRole('button', { name: /Suivant/ }).click();
  await page.getByRole('button', { name: /^Enregistrer( la visite)?$/ }).locator('visible=true').first().click();
  await expect(page.getByTestId('visit-summary')).toBeVisible({ timeout: 15_000 });
  return page.getByTestId('visit-summary');
}

async function noSideScroll(page) {
  const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(over).toBeLessThanOrEqual(1);
}

const VIEWPORTS = [['desktop', { width: 1536, height: 960 }, 0], ['phone', { width: 375, height: 812 }, 10]];

for (const [label, viewport, base] of VIEWPORTS) {
  test.describe(label, () => {
    test.use({ viewport });

    test('never in a Wallet: a soft note, then green by itself once the iPhone adds the card', async ({ page, request }) => {
      test.setTimeout(120_000);
      const H = await asOwner(page, request);
      const c = await freeClient(request, H, base + 1);
      const summary = await recordVisit(page, c.barcode_id);

      const note = summary.getByTestId('wallet-not-linked');
      await expect(note).toBeVisible();
      await expect(note).toHaveAttribute('data-reason', 'never_added');
      await expect(note).toHaveAttribute('data-tone', 'info');
      await expect(note).toContainText(/pas encore dans un Wallet/);
      await expect(note).toContainText(/elle aura déjà cette visite/);
      await expect(note.getByRole('button', { name: /QR/ })).toBeVisible();
      await noSideScroll(page);
      await page.screenshot({ path: `test-results/wallet-never-${label}.png` });

      // the client adds the card now: its iPhone registers it
      expect((await register(request, c.barcode_id, `e2e-${label}-a`)).status()).toBeLessThan(300);
      const ok = summary.getByTestId('wallet-linked-now');
      await expect(ok).toBeVisible({ timeout: 20_000 });
      await expect(ok).toContainText(/Carte ajoutée à Apple Wallet/);
      await expect(summary.getByTestId('wallet-not-linked')).toHaveCount(0);
      await page.screenshot({ path: `test-results/wallet-linked-now-${label}.png` });
    });

    test('removed from Apple Wallet: red, with the steps worth trying and the QR', async ({ page, request }) => {
      test.setTimeout(120_000);
      const H = await asOwner(page, request);
      const c = await freeClient(request, H, base + 2);
      const dev = `e2e-${label}-b`;
      expect((await register(request, c.barcode_id, dev)).status()).toBeLessThan(300);
      expect((await unregister(request, c.barcode_id, dev)).status()).toBe(200);
      const summary = await recordVisit(page, c.barcode_id);

      const warn = summary.getByTestId('wallet-not-linked');
      await expect(warn).toHaveAttribute('data-reason', 'removed');
      await expect(warn).toHaveAttribute('data-wallet', 'apple');
      await expect(warn).toHaveAttribute('data-tone', 'error');
      const steps = warn.getByTestId('wallet-steps').locator('li');
      expect(await steps.count()).toBeGreaterThanOrEqual(3);
      await expect(warn).toContainText(/Mises à jour automatiques/);
      await expect(warn).toContainText(/Actualiser|tirer/i);
      await expect(warn).toContainText(/supprimer la carte|rajouter/i);
      await noSideScroll(page);
      await page.screenshot({ path: `test-results/wallet-removed-apple-${label}.png`, fullPage: true });

      await warn.getByRole('button', { name: /QR/ }).click();
      await expect(page.getByRole('dialog', { name: 'Récupérer la carte' })).toBeVisible();
    });

    test('removed from Google Wallet: Google steps (same Google account, re-add)', async ({ page, request }) => {
      test.setTimeout(120_000);
      const H = await asOwner(page, request);
      const c = await freeClient(request, H, base + 3);
      // Google's « del » callback is signed by Google; the scan answer says it instead
      await page.route('**/api/owner/scan', async (route) => {
        if (route.request().method() !== 'POST') return route.continue();
        const res = await route.fetch();
        const body = await res.json();
        body.wallet_link = { linked: false, where: null, reason: 'removed', wallet: 'google' };
        return route.fulfill({ response: res, json: body });
      });
      const summary = await recordVisit(page, c.barcode_id);
      const warn = summary.getByTestId('wallet-not-linked');
      await expect(warn).toHaveAttribute('data-wallet', 'google');
      await expect(warn).toHaveAttribute('data-tone', 'error');
      await expect(warn).toContainText(/Google Wallet/);
      await expect(warn).toContainText(/même compte Google/);
      await expect(warn).not.toContainText(/Mises à jour automatiques/);
      await noSideScroll(page);
      await page.screenshot({ path: `test-results/wallet-removed-google-${label}.png`, fullPage: true });
    });
  });
}
