/**
 * Sector playbooks (user, 2026-10-26: a café was getting salon advice), in a
 * real browser on the local server: the demo shop is made a barbier, then
 * Insights speaks of the barbier's trade, shows no « Estimation du secteur »
 * and no drink; a sourced figure links to its source. Put back as it was.
 */
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
test.use({ viewport: { width: 1536, height: 960 } });

test('Insights advises the shop’s own activity, with only sourced figures', async ({ page, request }) => {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const store = ((br && br.branches) || br || []).find((x) => x.status !== 'closed')?.id || '';
  const before = (await (await request.get('/api/owner/etablissement', { headers: H })).json()).business;
  const put = (business) => request.put('/api/owner/etablissement', { headers: { ...H, 'X-FidClic-Store': store }, data: { business } });
  try {
    expect((await put({ sector: 'salon', activity_key: 'barbier' })).ok()).toBeTruthy();
    await page.goto('/login');
    await page.evaluate(([t, s]) => {
      localStorage.setItem('fidelitour_access_token', t);
      if (s) localStorage.setItem('ft_selected_branch_v1', s);
      try { sessionStorage.removeItem('ft_pick_store'); } catch (_e) { /* ignore */ }
    }, [login.access_token, store]);
    await page.goto('/dashboard/insights');
    await expect(page.getByText('pour votre activité : Barbier')).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText('Estimation du secteur')).toHaveCount(0);
    await expect(page.getByText(/boisson/i)).toHaveCount(0);
    await page.getByRole('button', { name: /Voir toutes les actions/ }).click();
    // the learning ranking (2026-10-30) may put it behind « Voir toutes les opportunités »
    const moreOpps = page.getByRole('button', { name: /Voir toutes les opportunités/ });
    if (await moreOpps.isVisible()) await moreOpps.click();
    await expect(page.getByText('Proposez le prochain rendez-vous en caisse').first()).toBeVisible();
    const source = page.getByRole('link', { name: /Source : BrightLocal/ });
    await expect(source.first()).toBeVisible();
    await expect(source.first()).toHaveAttribute('href', /^https:\/\/www\.brightlocal\.com\//);
    await expect(source.first()).toHaveAttribute('rel', /noopener/);
  } finally {
    await put({ sector: before.sector || 'cafe', activity_key: before.activity_key || '' });
  }
  expect(errors).toEqual([]);
});
