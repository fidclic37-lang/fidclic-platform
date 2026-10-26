/**
 * The groupe témoin stays anonymous (user, 2026-10-26): a campaign with a
 * témoin lists everyone it targeted — those messaged and the témoin, mixed,
 * in alphabetical order, never marked — and says so; the counts tell how
 * many. The old campaign list no longer carries the témoin's ids. Local
 * server only.
 */
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
test.use({ viewport: { width: 1536, height: 960 } });

test('a campaign with a témoin names everyone targeted, without saying who was held back', async ({ page, request }) => {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const store = ((br && br.branches) || br || []).find((x) => x.status !== 'closed')?.id || '';
  const SH = { ...H, 'X-FidClic-Store': store };
  const title = `Témoin privé ${Date.now() % 100000}`;
  const sent = await request.post('/api/owner/campaigns/compose', { headers: SH,
    data: { title, message: 'Bonjour {prénom}', audience: { mode: 'all' } } });
  expect(sent.ok(), await sent.text()).toBeTruthy();
  const res = await sent.json();
  expect(res.temoin).toBeGreaterThan(0);

  // the old list: the campaign, never its témoin
  const old = await (await request.get('/api/owner/campaigns', { headers: SH })).json();
  const row = old.find((c) => c.id === res.id);
  expect(row).toBeTruthy();
  expect(row.holdout_ids).toBeUndefined();
  const detail = await (await request.get(`/api/owner/campaigns/${res.id}/detail`, { headers: SH })).json();
  expect(detail.recipients_targeted).toBe(true);
  expect(detail.recipients_list.length + detail.recipients_more).toBe(res.audience + res.temoin);

  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
    try { sessionStorage.removeItem('ft_pick_store'); } catch (_e) { /* ignore */ }
  }, [login.access_token, store]);
  await page.goto('/dashboard/campaigns');
  await page.getByRole('row', { name: `Ouvrir la campagne ${title}` }).click();
  const box = page.getByRole('dialog', { name: `Campagne ${title}` });
  await expect(box).toBeVisible({ timeout: 15_000 });
  await expect(box.getByTestId('recipients-targeted-note')).toContainText('groupe témoin');
  await expect(box.getByText(`${(res.audience + res.temoin).toLocaleString('fr-FR')} clients ciblés`)).toBeVisible();
  const names = await box.getByTestId('campaign-recipients').locator('span.rounded-full')
    .evaluateAll((els) => els.map((e) => e.firstChild.textContent));        // the name, without its card number
  const fold = (n) => n.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  const keys = names.map(fold);
  expect(names.length).toBeGreaterThan(0);
  expect(keys).toEqual([...keys].sort());                                  // alphabetical, accents aside
  await page.screenshot({ path: 'test-results/temoin-privacy.png' });
  expect(errors).toEqual([]);
});
