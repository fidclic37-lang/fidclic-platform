/**
 * FidClic IA for an account without « Analyses » (pentest #427): the page says so
 * instead of showing the figures, and does not crash on an empty block. The
 * server's side (no figure sent at all) is api/tests/test_copilot_facts_perms.py;
 * here the answer of that account is played to the real page. Local server only.
 */
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
test.use({ viewport: { width: 1536, height: 960 } });

test('FidClic IA: figures locked, said plainly, nothing crashes', async ({ page, request }) => {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const br = await (await request.get('/api/owner/branches', { headers: { Authorization: `Bearer ${login.access_token}` } })).json();
  const store = ((br && br.branches) || br || []).find((x) => x.status !== 'closed')?.id || '';
  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
    try { sessionStorage.removeItem('ft_pick_store'); } catch (_e) { /* ignore */ }
  }, [login.access_token, store]);
  await page.route('**/api/owner/copilot/page**', async (route) => {
    const res = await route.fetch();
    const d = await res.json();
    d.activity = { days: 7, cards: [], locked: true };
    d.forecast = { ...d.forecast, days: [], mean: 0 };
    d.recommendations = { top: [], all: [], total: 0 };
    d.opportunities = { top: [], all: [], total: 0 };
    await route.fulfill({ response: res, json: d });
  });
  await page.goto('/dashboard/ai-assistant');
  await expect(page.getByTestId('copilot-activity-locked')).toContainText('page Analyses', { timeout: 20_000 });
  await expect(page.getByText('Chiffre d\'affaires', { exact: true })).toHaveCount(0);
  expect(errors).toEqual([]);
});
