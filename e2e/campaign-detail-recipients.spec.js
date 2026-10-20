// A sent campaign says to whom and by whom (user, 2026-10-20: « campaign ki
// details mein ye kyun nhi dekh paa rhe ki kisko target kiya gaya tha »).
// Runs against the local server only (scripts/dev_local.py — demo data in memory).
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only

test.use({ viewport: { width: 1536, height: 960 } });

test('the campaign detail names its recipients and its sender', async ({ page, request }) => {
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const store = ((br && br.branches) || br || []).find((b) => b.status !== 'closed')?.id || '';
  const SH = { ...H, ...(store ? { 'X-FidClic-Store': store } : {}) };
  const rows = (await (await request.get('/api/owner/clients/list?per_page=50', { headers: SH })).json()).rows || [];
  const one = rows.find((c) => c.name);
  expect(one, 'the demo has a client').toBeTruthy();
  const title = `Pour ${one.name} ${Date.now() % 100000}`;
  const sent = await request.post('/api/owner/campaigns/compose', { headers: SH,
    data: { title, message: 'Bonjour {prénom} !', customer_ids: [one.id] } });
  expect(sent.ok(), await sent.text()).toBeTruthy();

  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
  }, [login.access_token, store]);
  await page.goto('/dashboard/campaigns');
  await page.getByText(title).first().click();
  const chips = page.getByTestId('campaign-recipients');
  await expect(chips).toContainText(one.name);
  await expect(page.getByText('Envoyée par')).toBeVisible();
});
