/**
 * Super Admin › Commerces says where each business's own Apple Wallet id
 * stands (user, 2026-10-30: one id per business, made by the platform). On
 * the local server App Store Connect is not set, so it says so — the cards
 * stay under the common id. Local server only.
 */
import { test, expect } from '@playwright/test';

const ADMIN = { email: 'admin@fidelitour.com', password: 'Fidelit0ur!Adm' };   // local seed only
test.use({ viewport: { width: 1536, height: 960 } });

test('Commerces: the Apple Wallet line, and no key in the answer', async ({ page, request }) => {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const login = await (await request.post('/api/auth/login', { data: ADMIN })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const api = await request.get('/api/admin/wallet-identities', { headers: H });
  expect(api.status()).toBe(200);
  const body = await api.text();
  expect(body).not.toContain('PRIVATE KEY');
  expect(JSON.parse(body).configured).toBe(false);

  await page.goto('/login');
  await page.evaluate((t) => localStorage.setItem('fidelitour_access_token', t), login.access_token);
  await page.goto('/admin/commerces');
  const line = page.getByTestId('wallet-identities');
  await expect(line).toBeVisible({ timeout: 15_000 });
  await expect(line).toContainText('App Store Connect');
  await page.screenshot({ path: 'test-results/wallet-identities.png' });
  expect(errors).toEqual([]);
});

test('a business owner cannot read it', async ({ request }) => {
  const login = await (await request.post('/api/auth/login', { data: { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' } })).json();
  const r = await request.get('/api/admin/wallet-identities', { headers: { Authorization: `Bearer ${login.access_token}` } });
  expect(r.status()).toBe(403);
});
