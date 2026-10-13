// Labels and design, QA R6 (2026-10-11), in a real browser:
//   F33 — « Aperçu client » showed ARGENT for a sample with 7 visits whatever
//         the ladder: the palier now follows the owner's own ladder;
//   BUG-002 — the sign-up's « Secteur » opened the phone's native picker
//         (black, oversized in dark mode): FidClic's own list now.
// (F30 — the plan's « clients actifs » wording — is the server's: unit test.)
// Runs against the local server only (scripts/dev_local.py — demo data in memory).
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
const LABELS = { bronze: /bronze/i, silver: /argent/i, gold: /^or$/i, vip: /vip/i };

test.use({ viewport: { width: 1536, height: 960 } });

test('F33 — the sample client\'s palier follows the ladder', async ({ page, request }) => {
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const store = ((br && br.branches) || br || []).find((b) => b.status !== 'closed')?.id || '';
  const s = await (await request.get('/api/owner/card/settings', { headers: { ...H, ...(store ? { 'X-FidClic-Store': store } : {}) } })).json();
  const isPoints = (s.programme?.programme || 'stamps') !== 'stamps';
  const value = isPoints ? 1200 : 7;
  const expected = (s.tiers || []).reduce((acc, t) => (value >= Number(t.min) ? t.key : acc), 'bronze');

  await page.goto('/login');
  await page.evaluate(([t, st]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (st) localStorage.setItem('ft_selected_branch_v1', st);
  }, [login.access_token, store]);
  await page.goto('/dashboard/card');
  await page.getByRole('button', { name: /Aperçu client/ }).click();
  const preview = page.locator('div.fixed.inset-0').filter({ hasText: 'Ce que voit votre client' });
  await expect(preview).toBeVisible();
  await expect(preview.getByText(LABELS[expected]).first(), `the ladder gives ${expected}`).toBeVisible();
  if (expected !== 'silver') await expect(preview.getByText(/^argent$/i)).toHaveCount(0);
});

test('BUG-002 — the sector is picked from FidClic\'s own list', async ({ page }) => {
  const json = (route, body) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) });
  await page.route('**/api/auth/me', (r) => json(r, { email: 'new@shop.fr', role: 'business_owner', tenant_id: 't9',
    onboarding_status: 'company' }));
  await page.route('**/api/onboarding/status', (r) => json(r, { terms_accepted: true, prefill: {} }));
  await page.goto('/login');
  await page.evaluate(() => localStorage.setItem('fidelitour_access_token', 'a-new-account'));
  await page.goto('/onboarding/entreprise');

  const sector = page.getByRole('button', { name: /secteur/i });
  await expect(sector).toBeVisible();
  await expect(page.locator('select').filter({ hasText: /Café|Restaurant/ })).toHaveCount(0);   // no native picker
  await sector.click();
  const list = page.getByRole('listbox');
  await expect(list).toBeVisible();
  await expect(list).toHaveCSS('background-color', 'rgb(255, 255, 255)');
  await list.getByRole('option', { name: /Restaurant/ }).click();
  await expect(list).toHaveCount(0);
  await expect(sector).toHaveText(/Restaurant/);
  // the keyboard too
  await sector.focus();
  await page.keyboard.press('ArrowDown');
  await expect(page.getByRole('listbox')).toBeVisible();
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('Enter');
  await expect(sector).not.toHaveText(/Restaurant/);
  await page.keyboard.press('Escape');
  await expect(page.getByRole('listbox')).toHaveCount(0);
});
