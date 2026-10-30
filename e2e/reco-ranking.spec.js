/**
 * La recommandation qui apprend (user, 2026-10-30): every idea card on the
 * Copilote, Insights and the Tableau de bord says « Pourquoi en premier ? »
 * — what was learned for it here (and from shops like this one). Local
 * server only.
 */
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
test.use({ viewport: { width: 1536, height: 960 } });

test('each idea says why it is where it is', async ({ page, request }) => {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const store = ((br && br.branches) || br || []).find((x) => x.status !== 'closed')?.id || '';
  const SH = { ...H, 'X-FidClic-Store': store };
  const cp = await (await request.get('/api/owner/copilot/page', { headers: SH })).json();
  const recs = cp.recommendations.all;
  expect(recs.length).toBeGreaterThan(0);
  expect(recs.every((r) => (r.why_rank || {}).text)).toBeTruthy();

  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
    try { sessionStorage.removeItem('ft_pick_store'); } catch (_e) { /* ignore */ }
  }, [login.access_token, store]);

  // Copilote
  await page.goto('/dashboard/ai-assistant');
  const ask = page.getByRole('button', { name: 'Pourquoi en premier ?' }).first();
  await expect(ask).toBeVisible({ timeout: 20_000 });
  await ask.click();
  await expect(page.getByTestId('reco-why').first()).toHaveText(/\S.+\./);
  await page.screenshot({ path: 'test-results/reco-why-copilote.png' });

  // Tableau de bord
  await page.goto('/dashboard');
  const home = page.getByRole('button', { name: 'Pourquoi en premier ?' }).first();
  await expect(home).toBeVisible({ timeout: 20_000 });
  await home.click();
  await expect(page.getByTestId('reco-why').first()).toBeVisible();

  // Insights
  await page.goto('/dashboard/insights');
  const ins = page.getByRole('button', { name: 'Pourquoi en premier ?' }).first();
  await expect(ins).toBeVisible({ timeout: 20_000 });
  await ins.click();
  await expect(page.getByTestId('reco-why').first()).toBeVisible();
  await page.screenshot({ path: 'test-results/reco-why-insights.png' });
  expect(errors).toEqual([]);
});
