/**
 * Établissement › « Activité précise » (FidClic IA, 2026-10-25): under the
 * sector, the precise trade (Barbier, CBD, Opticien…) — where the client
 * brain starts the shop's usual rhythm. Chosen, saved, read back; a new
 * sector offers its own trades. Local server only.
 */
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
test.use({ viewport: { width: 1536, height: 960 } });

test('the owner picks the precise activity under the sector, and it stays', async ({ page, request }) => {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const store = ((br && br.branches) || br || []).find((x) => x.status !== 'closed')?.id || '';
  // the demo's sector is not one of the list: start from « Café / Salon de thé »
  expect((await request.put('/api/owner/etablissement', { headers: { ...H, 'X-FidClic-Store': store }, data: { business: { sector: 'cafe' } } })).ok()).toBeTruthy();
  const before = await (await request.get('/api/owner/etablissement', { headers: H })).json();
  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
    try { sessionStorage.removeItem('ft_pick_store'); } catch (_e) { /* ignore */ }
  }, [login.access_token, store]);
  await page.goto('/dashboard/parametres/etablissement');
  const activity = page.getByLabel('Activité précise');
  await expect(activity).toBeVisible({ timeout: 15_000 });
  const mine = before.activities.filter((a) => a.sector === 'cafe');
  expect(mine.length).toBeGreaterThan(1);
  await activity.selectOption(mine[1].value);
  await page.getByRole('button', { name: /Enregistrer les modifications/ }).click();
  await expect.poll(async () => (await (await request.get('/api/owner/etablissement', { headers: H })).json()).business.activity_key)
    .toBe(mine[1].value);
  await page.reload();
  await expect(page.getByLabel('Activité précise')).toHaveValue(mine[1].value, { timeout: 15_000 });
  // back to how it was
  await request.put('/api/owner/etablissement', { headers: H, data: { business: { activity_key: before.business.activity_key || '' } } });
  expect(errors).toEqual([]);
});
