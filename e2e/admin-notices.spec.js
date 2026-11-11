/**
 * Super admin › Notifications (user, 2026-11-11): FidClic writes to one
 * business, several, or all — and the chosen business's owner reads it in the
 * bell. Never to the business's customers. Local server only, on demo data.
 */
import { test, expect } from '@playwright/test';

const ADMIN = { email: 'admin@fidelitour.com', password: 'Fidelit0ur!Adm' };          // local seed only
const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };     // local seed only
test.use({ viewport: { width: 1536, height: 960 } });
test.setTimeout(240_000);

test('the super admin writes to one chosen business, its owner reads it in the bell', async ({ page, request, browser }, info) => {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const admin = await (await request.post('/api/auth/login', { data: ADMIN })).json();
  // the old « broadcast to every shop's customers » is closed
  const old = await request.post('/api/admin/broadcast', { headers: { Authorization: `Bearer ${admin.access_token}` },
    data: { subject: 'x', body: 'y', filters: {} } });
  expect(old.status(), await old.text()).toBe(410);
  const owner = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const me = await (await request.get('/api/owner/tenant', { headers: { Authorization: `Bearer ${owner.access_token}` } })).json();
  const shop = me.name;
  expect(shop).toBeTruthy();
  const title = `Maintenance e2e ${Date.now()}`;

  await page.goto('/login');
  await page.evaluate((t) => localStorage.setItem('fidelitour_access_token', t), admin.access_token);
  await page.goto('/admin');
  await page.getByRole('link', { name: 'Notifications' }).first().click();
  await expect(page.getByRole('heading', { name: 'Notifications' })).toBeVisible({ timeout: 60_000 });

  // nothing chosen → no send
  await page.getByLabel('Titre', { exact: false }).first().fill(title);
  await page.locator('#nt-body').fill('Coupure de 22:00 à 22:30.');
  await expect(page.getByTestId('notice-summary')).toHaveText('Aucun commerce choisi');
  await expect(page.getByRole('button', { name: 'Envoyer' })).toBeDisabled();

  // one business, found by its name
  await page.getByLabel('Chercher un commerce').fill(shop.slice(0, 6));
  await page.getByTestId('notice-targets').getByLabel(shop, { exact: true }).check();
  await expect(page.getByTestId('notice-summary')).toHaveText('1 commerce');
  await page.getByRole('radio', { name: 'Important' }).click();
  await page.getByRole('button', { name: 'Envoyer' }).click();
  await expect(page.getByText('Les clients de ces commerces ne reçoivent rien.')).toBeVisible();
  await page.getByRole('button', { name: "Confirmer l'envoi" }).click();
  await expect(page.getByTestId('notice-history').getByText(title)).toBeVisible({ timeout: 30_000 });
  await page.screenshot({ path: 'test-results/admin-notices.png', fullPage: true });

  // « Tous les commerces » is a choice, never the default
  await page.getByRole('radio', { name: /Tous les commerces/ }).click();
  await expect(page.getByText("Un commerce qui s'inscrit plus tard ne le recevra pas.", { exact: false })).toBeVisible();

  // the owner's bell
  const bell = await (await request.get('/api/owner/notices', { headers: { Authorization: `Bearer ${owner.access_token}` } })).json();
  expect(bell.alerts.map((a) => a.title)).toContain(title);
  const ctx = await browser.newContext({ baseURL: info.project.use.baseURL, viewport: { width: 1536, height: 960 } });
  const op = await ctx.newPage();
  op.on('pageerror', (e) => errors.push(e.message));
  const OH = { Authorization: `Bearer ${owner.access_token}` };
  const br = await (await request.get('/api/owner/branches', { headers: OH })).json();
  const store = ((br && br.branches) || br || []).find((b) => b.status !== 'closed')?.id || '';
  await op.goto('/login');
  await op.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
    try { sessionStorage.removeItem('ft_pick_store'); } catch (_e) { /* ignore */ }
  }, [owner.access_token, store]);
  await op.goto('/dashboard/notifications');
  await expect(op.getByText(title)).toBeVisible({ timeout: 60_000 });
  await op.screenshot({ path: 'test-results/admin-notices-owner.png', fullPage: false });
  await ctx.close();

  expect(errors).toEqual([]);
});
