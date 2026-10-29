/**
 * FidClic Lab (user, 2026-10-29): Super admin › Commerces › a shop › ⋯ ›
 * « Export anonymisé (FidClic Lab) » saves the shop's history as one JSON
 * file, fetched in parts, without who the clients are. Local server only,
 * on the demo shop.
 */
import fs from 'fs';
import { test, expect } from '@playwright/test';

const ADMIN = { email: 'admin@fidelitour.com', password: 'Fidelit0ur!Adm' };   // local seed only
const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
test.use({ viewport: { width: 1536, height: 960 } });

test('the Super Admin saves an anonymous export of a shop', async ({ page, request }) => {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const login = await (await request.post('/api/auth/login', { data: ADMIN })).json();
  const owner = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const tid = owner.user?.tenant_id || 'tenant-1';
  // a merchant cannot ask for it
  const refused = await request.post('/api/admin/ai/lab/exports', { headers: { Authorization: `Bearer ${owner.access_token}` }, data: { tenant_id: tid } });
  expect([401, 403]).toContain(refused.status());

  await page.goto('/login');
  await page.evaluate((t) => localStorage.setItem('fidelitour_access_token', t), login.access_token);
  await page.goto(`/admin/commerces/${tid}`);
  await page.getByRole('button', { name: "Plus d'actions" }).click({ timeout: 20_000 });
  const item = page.getByRole('button', { name: /Export anonymisé \(FidClic Lab\)/ });
  await expect(item).toBeVisible();
  await page.screenshot({ path: 'test-results/lab-export-menu.png' });
  page.once('dialog', (dlg) => { expect(dlg.message()).toContain('sans nom, téléphone ni e-mail'); dlg.accept(); });
  const [download] = await Promise.all([page.waitForEvent('download', { timeout: 60_000 }), item.click()]);
  expect(download.suggestedFilename()).toMatch(/^fidclic-lab-[a-z_]+-\d{4}-\d{2}-\d{2}\.json$/);
  const file = await download.path();
  const data = JSON.parse(fs.readFileSync(file, 'utf-8'));
  expect(data.format).toBe('fidclic-lab/1');
  expect(data.customers.length).toBe(data.counts.customers);
  expect(data.visits.length).toBe(data.counts.visits);
  expect(data.visits.length).toBeGreaterThan(0);
  // nobody is named: not the demo's clients, not their e-mails or phones
  const blob = JSON.stringify(data);
  expect(blob).not.toMatch(/@[a-z0-9.-]+\.[a-z]{2,}/i);
  expect(blob).not.toMatch(/0[67]\d{8}/);
  expect(Object.keys(data.customers[0]).sort()).toEqual(['age', 'c', 'created_at', 'deleted', 'gender', 'pass', 'paused', 'postal', 'source', 'store']);
  await expect(page.getByText(/Export prêt/)).toBeVisible();
  await page.screenshot({ path: 'test-results/lab-export-done.png' });
  expect(errors).toEqual([]);
});
