/**
 * Super admin › Dashboard (user, 2026-11-11): « Chiffre d'affaires total »
 * opens EVERY shop (deleted, suspended, résiliée, trial over too) and adds up
 * to the figure; « Impact FidClic » is a new figure with its own list by shop.
 * Local server only, on the demo data.
 */
import { test, expect } from '@playwright/test';

const ADMIN = { email: 'admin@fidelitour.com', password: 'Fidelit0ur!Adm' };   // local seed only
test.use({ viewport: { width: 1536, height: 960 } });
test.setTimeout(240_000);

test('CA and Impact FidClic open every shop, and add up', async ({ page, request }) => {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const login = await (await request.post('/api/auth/login', { data: ADMIN })).json();
  const A = { Authorization: `Bearer ${login.access_token}` };
  const dash = await (await request.get('/api/admin/dashboard', { headers: A })).json();
  const K = Object.fromEntries(dash.kpis.map((k) => [k.key, k]));
  expect(K.impact).toBeTruthy();
  const ca = await (await request.get('/api/admin/dashboard/list/ca', { headers: A })).json();
  const sum = ca.rows.reduce((a, r) => a + (r.metric || 0), 0);
  expect(Math.abs(sum - K.ca.value)).toBeLessThan(0.05);
  const imp = await (await request.get('/api/admin/dashboard/list/impact', { headers: A })).json();
  expect(imp.rows.length).toBe(ca.rows.length);
  expect(Math.abs(imp.rows.reduce((a, r) => a + (r.metric || 0), 0) - K.impact.value)).toBeLessThan(0.05);

  await page.goto('/login');
  await page.evaluate((t) => localStorage.setItem('fidelitour_access_token', t), login.access_token);
  await page.goto('/admin');
  await expect(page.getByText('Impact FidClic').first()).toBeVisible({ timeout: 60_000 });
  await page.screenshot({ path: 'test-results/admin-dashboard-impact.png', fullPage: false });

  // the CA tile → every shop
  await page.getByText("Chiffre d'affaires total").first().click();
  const dlg = page.getByRole('dialog', { name: "Chiffre d'affaires par commerce" });
  await expect(dlg).toBeVisible({ timeout: 60_000 });
  await expect(dlg.locator('tbody tr')).toHaveCount(ca.rows.length, { timeout: 30_000 });
  await page.keyboard.press('Escape');

  // the Impact tile → its own list, every shop
  await page.getByText('Impact FidClic').first().click();
  const d2 = page.getByRole('dialog', { name: 'Impact FidClic par commerce' });
  await expect(d2).toBeVisible({ timeout: 60_000 });
  await expect(d2.getByRole('columnheader', { name: 'CA FidClic' })).toBeVisible();
  await expect(d2.locator('tbody tr')).toHaveCount(imp.rows.length, { timeout: 30_000 });
  await page.screenshot({ path: 'test-results/admin-dashboard-impact-list.png', fullPage: false });
  expect(errors).toEqual([]);
});
