/**
 * Super admin › Dashboard (user, 2026-11-09: « dashboard pr 3 shops and analyse
 * mein 10 dikha rha h, aisa mismatch kyun h »). The Commerces tile counts the
 * businesses in trial or paying and now says « sur M inscrits »; the donut
 * shows where every registered business stands, summing to the same M. Every
 * figure opens its businesses. The maths is api/tests/test_admin_dashboard_status.py.
 * Local server only.
 */
import { test, expect } from '@playwright/test';

const ADMIN = { email: 'admin@fidelitour.com', password: 'Fidelit0ur!Adm' };   // local seed only
test.use({ viewport: { width: 1536, height: 960 } });

test.setTimeout(180_000);
test('Dashboard: « sur M inscrits » and the standing donut agree and open their shops', async ({ page, request }) => {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const login = await (await request.post('/api/auth/login', { data: ADMIN })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const d = await (await request.get('/api/admin/dashboard', { headers: H })).json();
  const tile = d.kpis.find((k) => k.key === 'commerces');
  expect(tile.registered).toBe(d.total);
  expect(d.statuses.reduce((a, r) => a + r.count, 0)).toBe(d.total);

  await page.goto('/login');
  await page.evaluate((t) => localStorage.setItem('fidelitour_access_token', t), login.access_token);
  await page.goto('/admin');
  const reg = page.getByTestId('commerces-registered');
  await expect(reg).toHaveText(`sur ${d.total} inscrits`, { timeout: 90_000 });

  const donut = page.getByTestId('status-donut');
  await expect(page.getByRole('heading', { name: 'Répartition par statut' })).toBeVisible();
  await expect(page.getByText('Répartition par plan')).toHaveCount(0);
  await expect(donut).toContainText(`${d.total}`);
  await expect(donut).toContainText('inscrits');
  for (const r of d.statuses) await expect(donut).toContainText(r.label);
  await page.screenshot({ path: 'test-results/admin-dashboard-status.png', fullPage: false });

  // « sur M inscrits » opens all M
  await reg.click();
  await expect(page.getByRole('heading', { name: 'Tous les commerces inscrits' })).toBeVisible();
  const all = await (await request.get('/api/admin/dashboard/list/inscrits', { headers: H })).json();
  expect(all.rows.length).toBe(d.total);
  for (const row of all.rows.slice(0, 3)) await expect(page.getByText(row.name).first()).toBeVisible();
  await page.getByRole('button', { name: 'Fermer' }).click();
  await expect(page.getByRole('heading', { name: 'Tous les commerces inscrits' })).toHaveCount(0);

  // each slice opens exactly its count
  for (const r of d.statuses) {
    await donut.getByRole('button', { name: new RegExp(`^${r.label}`) }).click();
    const lst = await (await request.get(`/api/admin/dashboard/list/${r.list}`, { headers: H })).json();
    expect(lst.rows.length).toBe(r.count);
    await expect(page.getByRole('heading', { name: lst.title })).toBeVisible();
    await page.getByRole('button', { name: 'Fermer' }).click();
    await expect(page.getByRole('heading', { name: lst.title })).toHaveCount(0);
  }
  expect(errors).toEqual([]);
});
