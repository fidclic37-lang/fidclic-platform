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
  // whichever idea the demo shows today: the ranking draws a new order each day, and ideas sent
  // recently by other specs make way — an aim moves an idea up, a « jamais » moves it down
  const UP = [['proximite', 'Ma cible : les clients du quartier'], ['palier_vip', 'Ma cible : les clients fidèles'],
              ['etudiants', 'Ma cible : les étudiants'], ['seconde_visite', 'Ma cible : les nouveaux clients'],
              ['relance_inactifs', 'Ma cible : les clients inactifs'], ['a_risque', 'Ma cible : les clients inactifs']];
  const DOWN = [['relance_inactifs', 'Je ne fais jamais de relance'], ['a_risque', 'Je ne fais jamais de relance'],
                ['offre_jour', 'Je ne fais jamais de promo']];
  const pick = (list) => list.find(([k]) => before.some((r) => r.key === k));
  const [key, fact] = pick(UP) || pick(DOWN) || [];
  const goesUp = !!pick(UP);
  expect(key, `the demo shows an idea the test knows (got ${before.map((r) => r.key).join(', ')})`).toBeTruthy();
  const was = before.findIndex((r) => r.key === key);

  await request.post('/api/me/ai-memory', { headers: H, data: { text: fact } });
  const after = (await (await request.get('/api/owner/copilot/page', { headers: SH })).json()).recommendations.all;
  const now = after.findIndex((r) => r.key === key);
  if (goesUp) {
    expect(after[now].why_rank.selon).toBe(`Selon ce que vous avez dit : « ${fact} »`);
    expect(now).toBeLessThanOrEqual(was);
  } else if (now === -1) {
    // gone below what the plan shows (Pro: 3 ideas) — moved down, as asked
    expect(after.length).toBeGreaterThan(0);
  } else {
    expect(after[now].why_rank.selon).toBe(`Selon ce que vous avez dit : « ${fact} »`);
    expect(now).toBeGreaterThanOrEqual(was);
  }

  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
    try { sessionStorage.removeItem('ft_pick_store'); } catch (_e) { /* ignore */ }
  }, [login.access_token, store]);
  await page.goto('/dashboard/ai-assistant');
  if (now !== -1) {                                               // shown: its card says why
    const all = page.getByRole('button', { name: /Voir toutes/ }).first();
    if (now >= 3 && await all.count()) await all.click();        // below the first three: in « Voir toutes »
    const said = page.getByTestId('reco-said').filter({ hasText: fact }).first();
    await expect(said).toBeVisible({ timeout: 20_000 });
    await said.locator('xpath=../..').screenshot({ path: 'test-results/reco-said.png' });
  }

  for (const it of (await (await request.get('/api/me/ai-memory', { headers: H })).json()).items) {
    await request.delete(`/api/me/ai-memory/${it.id}`, { headers: H });
  }
  expect(errors).toEqual([]);
});
