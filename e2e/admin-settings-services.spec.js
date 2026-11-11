/**
 * Super admin › Paramètres › Services (user, 2026-11-11): every service with
 * its state, what is missing (names only) and « Tester ». Local server only.
 */
import { test, expect } from '@playwright/test';

const ADMIN = { email: 'admin@fidelitour.com', password: 'Fidelit0ur!Adm' };   // local seed only
test.use({ viewport: { width: 1536, height: 960 } });
test.setTimeout(180_000);

test('the super admin reads every service and tests the database', async ({ page, request }) => {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const login = await (await request.post('/api/auth/login', { data: ADMIN })).json();
  const api = await (await request.get('/api/admin/settings/services', { headers: { Authorization: `Bearer ${login.access_token}` } })).json();

  await page.goto('/login');
  await page.evaluate((t) => localStorage.setItem('fidelitour_access_token', t), login.access_token);
  await page.goto('/admin');
  await page.getByRole('link', { name: 'Paramètres' }).first().click();
  await expect(page.getByRole('heading', { name: 'Paramètres', exact: true })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId('services-summary')).toContainText(`${api.summary.ready} services sur ${api.summary.total}`);
  await expect(page.locator('[data-service]')).toHaveCount(api.summary.total);

  // a missing service names what to add in Vercel
  const missing = api.groups.flatMap((g) => g.items).find((i) => !i.present && i.missing.length);
  if (missing) await expect(page.locator(`[data-service="${missing.key}"]`)).toContainText(missing.missing[0]);

  // « Tester » the database: a real ping
  await page.getByRole('button', { name: /Tester Base de données/ }).click();
  await expect(page.getByTestId('result-mongo')).toContainText('La base répond', { timeout: 30_000 });
  await page.screenshot({ path: 'test-results/admin-settings-services.png', fullPage: true });
  expect(errors).toEqual([]);
});
