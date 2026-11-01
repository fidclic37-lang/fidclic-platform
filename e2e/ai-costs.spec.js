/**
 * Super admin › FIDCLIC AI › Coûts IA (user, 2026-11-01): what every model
 * call cost, per shop / feature / day, each shop's monthly AI budget (raised
 * here, then enforced) and the platform's daily cap; the merchant whose
 * budget is used up reads « Limite IA du mois atteinte » on the dashboard.
 * The meter's maths and guards are api/tests/test_ai_meter.py. Local server only.
 */
import { test, expect } from '@playwright/test';

const ADMIN = { email: 'admin@fidelitour.com', password: 'Fidelit0ur!Adm' };   // local seed only
const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
test.use({ viewport: { width: 1536, height: 960 } });

test('Coûts IA: the figures, a shop budget raised and given back, the limits', async ({ page, request }) => {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const login = await (await request.post('/api/auth/login', { data: ADMIN })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const d = await (await request.get('/api/admin/ai/costs', { headers: H })).json();
  const shop = d.shops.find((s) => !s.custom_limit) || d.shops[0];
  const before = d.settings;

  await page.goto('/login');
  await page.evaluate((t) => localStorage.setItem('fidelitour_access_token', t), login.access_token);
  await page.goto('/admin/ai/couts');
  await expect(page.getByRole('heading', { name: 'Coûts IA' })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole('link', { name: 'Coûts IA' })).toBeVisible();
  await expect(page.getByTestId('cost-today')).toContainText('plafond');
  await expect(page.getByTestId('cost-features')).toBeVisible();
  const row = page.getByTestId(`cost-shop-${shop.tenant_id}`);
  await expect(row).toContainText(shop.name);

  // raise this shop's budget to 40 €, then back to its plan's default
  await row.getByRole('spinbutton').fill('40');
  await row.getByRole('button', { name: 'Enregistrer' }).click();
  await expect(page.getByText(`${shop.name} : budget IA 40 € par mois.`)).toBeVisible();
  let after = await (await request.get('/api/admin/ai/costs', { headers: H })).json();
  expect(after.shops.find((s) => s.tenant_id === shop.tenant_id).limit_eur).toBe(40);
  const row2 = page.getByTestId(`cost-shop-${shop.tenant_id}`);
  await row2.getByRole('spinbutton').fill('');
  await row2.getByRole('button', { name: 'Enregistrer' }).click();
  await expect(page.getByText(`${shop.name} : retour au budget de son offre.`)).toBeVisible();
  after = await (await request.get('/api/admin/ai/costs', { headers: H })).json();
  expect(after.shops.find((s) => s.tenant_id === shop.tenant_id).custom_limit).toBe(false);

  // the limits: the platform's daily cap
  await page.getByTestId('cost-set-global_day_eur').fill('30');
  await page.getByTestId('cost-settings-save').click();
  await expect(page.getByText('Limites enregistrées.')).toBeVisible();
  after = await (await request.get('/api/admin/ai/costs', { headers: H })).json();
  expect(after.settings.global_day_eur).toBe(30);
  await page.screenshot({ path: 'test-results/ai-costs.png', fullPage: true });
  await request.put('/api/admin/ai/costs/settings', { headers: H, data: { global_day_eur: before.global_day_eur } });
  expect(errors).toEqual([]);
});

test('the merchant at its AI budget reads it on the dashboard, no euros', async ({ page, request }) => {
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const br = await (await request.get('/api/owner/branches', { headers: { Authorization: `Bearer ${login.access_token}` } })).json();
  const store = ((br && br.branches) || br || []).find((x) => x.status !== 'closed')?.id || '';
  await page.route('**/api/owner/limit-alerts', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ alerts: [{ key: 'ai_budget', what: 'FidClic IA', pct: 100, upgrade: null,
      message: "Limite IA du mois atteinte : FidClic IA répond avec des réponses simplifiées jusqu'au 1er décembre." }] }),
  }));
  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    localStorage.removeItem('fidclic:limit-banner');
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
    try { sessionStorage.removeItem('ft_pick_store'); } catch (_e) { /* ignore */ }
  }, [login.access_token, store]);
  await page.goto('/dashboard');
  const banner = page.getByText(/Limite IA du mois atteinte/);
  await expect(banner).toBeVisible({ timeout: 20_000 });
  await expect(banner).not.toContainText('€');
});
