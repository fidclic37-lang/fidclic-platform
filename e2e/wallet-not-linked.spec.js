/**
 * « Wallet mein tampons update nhi hue » (user, 2026-11-07): a scan says so when
 * the client's Wallet card can't be reached, and the till shows the QR that
 * puts it back. Real till, real server, local seed only.
 */
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only

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
  return { H: { ...H, 'X-FidClic-Store': store || 'all' }, store };
}

for (const [label, viewport] of [['desktop', { width: 1536, height: 960 }], ['phone', { width: 375, height: 812 }]]) {
  test.describe(label, () => {
    test.use({ viewport });

    test('a card no phone holds: the receipt says so and shows the QR to put it back', async ({ page, request }) => {
      test.setTimeout(120_000);
      const { H } = await asOwner(page, request);
      // a demo client whose card no iPhone registered (the seed registers none)
      const list = await (await request.get('/api/owner/clients/list?per_page=10', { headers: H })).json();
      const c = (list.rows || []).find((x) => x.barcode_id);
      const w = await (await request.get(`/api/owner/clients/${c.id}/wallet`, { headers: H })).json();
      test.skip(w.apple.devices.length > 0, 'this demo client has an iPhone registered');

      await page.goto('/dashboard/scan');
      await page.getByRole('button', { name: 'Saisir le code' }).click();
      await page.getByLabel('Code de la carte').fill(c.barcode_id);
      await expect(page.getByPlaceholder('0,00')).toBeVisible({ timeout: 15_000 });
      await page.getByPlaceholder('0,00').fill('5');
      await page.getByRole('button', { name: /Suivant/ }).click();
      await page.getByRole('button', { name: /^Enregistrer( la visite)?$/ }).locator('visible=true').first().click();
      await expect(page.getByTestId('visit-summary')).toBeVisible({ timeout: 15_000 });

      const warn = page.getByTestId('visit-summary').getByTestId('wallet-not-linked');
      await expect(warn).toBeVisible();
      await expect(warn).toContainText(/Wallet/);
      const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(over).toBeLessThanOrEqual(1);
      await page.screenshot({ path: `test-results/wallet-not-linked-${label}.png` });

      await warn.getByRole('button', { name: /Afficher le QR/ }).click();
      const dialog = page.getByRole('dialog', { name: 'Récupérer la carte' });
      await expect(dialog).toBeVisible();
      await dialog.getByRole('button', { name: /Afficher le QR en caisse/ }).click();
      await expect(dialog.locator('svg').filter({ has: page.locator('path') }).first()).toBeVisible();
      await expect(dialog.getByText(/Le client scanne ce QR/)).toBeVisible();
    });
  });
}
