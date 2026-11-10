/**
 * Super admin › Commerces › a business with several boutiques (user,
 * 2026-11-10: Royal Trim's three stores could not be seen). « Boutiques »
 * lists them; « Voir » shows the same page for that store only; « Accéder au
 * compte » opens the account directly in that store, for that tab only.
 * Local server only, on the demo chain (Boulangerie Saint-Michel, 3 stores).
 */
import { test, expect } from '@playwright/test';

const ADMIN = { email: 'admin@fidelitour.com', password: 'Fidelit0ur!Adm' };   // local seed only
test.use({ viewport: { width: 1536, height: 960 } });
// the local mongomock server answers a business's page in ~15 s on the demo seed
test.setTimeout(240_000);

test('the super admin sees each boutique of a franchise and opens one', async ({ page, request, context }) => {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const login = await (await request.post('/api/auth/login', { data: ADMIN })).json();
  const A = { Authorization: `Bearer ${login.access_token}` };
  const api = await (await request.get('/api/admin/commerces/tenant-2/stores', { headers: A })).json();
  expect(api.multi).toBe(true);
  expect(api.stores.length).toBeGreaterThanOrEqual(3);
  const second = api.stores.find((s) => !s.is_main);

  await page.goto('/login');
  await page.evaluate((t) => localStorage.setItem('fidelitour_access_token', t), login.access_token);
  await page.goto('/admin/commerces/tenant-2');
  await page.getByRole('button', { name: 'Boutiques', exact: true }).click({ timeout: 60_000 });
  const table = page.getByTestId('stores-table');
  await expect(table.locator('tbody tr')).toHaveCount(api.stores.length);
  await expect(table.locator(`tr[data-store="${second.id}"]`)).toContainText(second.name);
  await page.screenshot({ path: 'test-results/admin-stores-list.png' });

  // « Voir »: the same page, that store's figures
  const asked = page.waitForRequest((r) => r.url().includes(`/api/admin/commerces/tenant-2?store=${encodeURIComponent(second.id)}`));
  await table.locator(`tr[data-store="${second.id}"]`).getByRole('button', { name: 'Voir' }).click();
  await asked;
  await expect(page).toHaveURL(new RegExp(`store=${second.id}`));
  await expect(page.getByTestId('store-picker')).toHaveValue(second.id, { timeout: 60_000 });
  await expect(page.getByTestId('commerce-title')).toContainText(second.name, { timeout: 60_000 });
  const one = await (await request.get(`/api/admin/commerces/tenant-2?store=${second.id}`, { headers: A })).json();
  expect(one.store.id).toBe(second.id);
  expect(one.kpis.find((k) => k.key === 'clients').value).toBe(second.clients);
  await page.screenshot({ path: 'test-results/admin-stores-one.png' });

  // its Clients tab asks for that store's clients
  const clients = page.waitForRequest((r) => r.url().includes('/api/admin/commerces/tenant-2/clients') && r.url().includes(`store=${second.id}`));
  await page.getByRole('button', { name: 'Clients', exact: true }).click();
  await clients;

  // back to the whole business from the picker
  await page.getByTestId('store-picker').selectOption('');
  await expect(page).not.toHaveURL(/store=/);

  // « Accéder au compte » from that boutique: the tab opens in it, nothing else changes
  await page.getByRole('button', { name: 'Boutiques', exact: true }).click();
  const [view] = await Promise.all([
    context.waitForEvent('page'),
    table.locator(`tr[data-store="${second.id}"]`).getByRole('button', { name: 'Accéder au compte' }).click(),
  ]);
  const ownerCall = view.waitForRequest((r) => r.url().includes('/api/owner/') && r.headers()['x-fidclic-store'] === second.id, { timeout: 30_000 });
  await view.waitForURL(/\/dashboard/, { timeout: 30_000 });
  await ownerCall;
  expect(await view.evaluate(() => sessionStorage.getItem('ft_selected_branch_v1'))).toBe(second.id);
  // the menu under the logo names that store
  await expect(view.getByText(second.name).first()).toBeVisible({ timeout: 60_000 });
  // the store picker never asks: the dashboard is already in that store
  await expect(view.getByText('Choisissez votre établissement')).toHaveCount(0);
  await view.screenshot({ path: 'test-results/admin-stores-view-as.png' });
  // the super admin's own tab keeps no store
  expect(await page.evaluate(() => localStorage.getItem('ft_selected_branch_v1'))).toBeNull();

  // « Commerces » list: each boutique of the franchise on its own line
  await page.goto('/admin/commerces');
  const sub = page.locator('tr[data-store-row]');
  await expect(sub.first()).toBeVisible({ timeout: 60_000 });
  for (const s of api.stores) await expect(page.locator(`tr[data-store-row="${s.id}"]`)).toContainText(s.name);
  await page.screenshot({ path: 'test-results/admin-stores-in-list.png' });
  await page.locator(`tr[data-store-row="${second.id}"]`).click();
  await expect(page).toHaveURL(new RegExp(`/admin/commerces/tenant-2\\?store=${second.id}`));
  // the boutique's own name on top, not the franchise's
  await expect(page.getByTestId('commerce-title')).toContainText(second.name, { timeout: 60_000 });
  await expect(page.getByText('Boutique de la franchise')).toBeVisible();
  await page.screenshot({ path: 'test-results/admin-stores-title.png' });

  // a one-shop business has no « Boutiques » tab
  const all = await (await request.get('/api/admin/commerces?per_page=50', { headers: A })).json();
  let solo = null;
  for (const c of all.rows || all.items || []) {
    const s = await (await request.get(`/api/admin/commerces/${c.id}/stores`, { headers: A })).json();
    if (s.multi === false) { solo = c.id; break; }
  }
  expect(solo).toBeTruthy();
  await page.goto(`/admin/commerces/${solo}`);
  await expect(page.getByRole('button', { name: "Vue d'ensemble" })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole('button', { name: 'Boutiques', exact: true })).toHaveCount(0);
  expect(errors).toEqual([]);
});
