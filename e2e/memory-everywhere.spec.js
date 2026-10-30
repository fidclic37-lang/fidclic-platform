/**
 * « Ce que FidClic IA retient » partout (user, 2026-10-30): a fact the owner
 * told FidClic IA changes the advice of the pages that rank ideas, and the
 * card says it — « Selon ce que vous avez dit : … ». Local server only.
 */
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
test.use({ viewport: { width: 1536, height: 960 } });

test('the advice follows what the owner said', async ({ page, request }) => {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const store = ((br && br.branches) || br || []).find((x) => x.status !== 'closed')?.id || '';
  for (const it of (await (await request.get('/api/me/ai-memory', { headers: H })).json()).items) {
    await request.delete(`/api/me/ai-memory/${it.id}`, { headers: H });
  }
  const SH = { ...H, 'X-FidClic-Store': store };
  const before = (await (await request.get('/api/owner/copilot/page', { headers: SH })).json()).recommendations.all;
  const near = before.find((r) => r.key === 'proximite');
  expect(near, 'the demo shop has clients nearby to test with').toBeTruthy();

  await request.post('/api/me/ai-memory', { headers: H, data: { text: 'Ma cible : les clients du quartier' } });
  const after = (await (await request.get('/api/owner/copilot/page', { headers: SH })).json()).recommendations.all;
  const up = after.find((r) => r.key === 'proximite');
  expect(up.why_rank.selon).toBe('Selon ce que vous avez dit : « Ma cible : les clients du quartier »');
  expect(after.indexOf(up)).toBeLessThanOrEqual(before.indexOf(near));

  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
    try { sessionStorage.removeItem('ft_pick_store'); } catch (_e) { /* ignore */ }
  }, [login.access_token, store]);
  await page.goto('/dashboard/ai-assistant');
  const said = page.getByTestId('reco-said').filter({ hasText: 'Ma cible : les clients du quartier' }).first();
  await expect(said).toBeVisible({ timeout: 20_000 });
  await said.locator('xpath=../..').screenshot({ path: 'test-results/reco-said.png' });

  for (const it of (await (await request.get('/api/me/ai-memory', { headers: H })).json()).items) {
    await request.delete(`/api/me/ai-memory/${it.id}`, { headers: H });
  }
  expect(errors).toEqual([]);
});
