/**
 * Historique: the last column shows the shop's own programme — tampons or
 * points — and switches to the other one (user, 2026-10-15). Local server only.
 */
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
test.use({ viewport: { width: 1536, height: 960 } });

test('points / tampons: the programme first, then a click', async ({ page, request }) => {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const store = ((br && br.branches) || br || []).find((x) => x.status !== 'closed')?.id || '';
  const meta = await (await request.get('/api/owner/history/filters', { headers: { ...H, 'X-FidClic-Store': store } })).json();
  expect(['points', 'stamps']).toContain(meta.unit);
  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
    try { sessionStorage.removeItem('ft_pick_store'); } catch (_e) { /* ignore */ }
  }, [login.access_token, store]);
  await page.goto('/dashboard/history');
  const group = page.getByRole('group', { name: 'Afficher les points ou les tampons' });
  await expect(group).toBeVisible();
  const first = meta.unit === 'stamps' ? 'Tampons' : 'Points';
  const other = meta.unit === 'stamps' ? 'Points' : 'Tampons';
  await expect(group.getByRole('button', { name: first })).toHaveAttribute('aria-pressed', 'true');
  await page.screenshot({ path: 'test-results/history-stamps.png' });
  await group.getByRole('button', { name: other }).click();
  await expect(group.getByRole('button', { name: other })).toHaveAttribute('aria-pressed', 'true');
  expect(errors).toEqual([]);
});
