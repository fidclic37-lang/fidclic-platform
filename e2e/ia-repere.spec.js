/**
 * Tableau de bord › « FidClic IA a repéré » (user, 2026-10-25): habitués en
 * retard, pas revenus après la 1ère visite, viennent moins souvent — each
 * with « Pourquoi ? », its clients (a Clients chip) and the composer written
 * for them with {produit_habituel}. Local server only.
 */
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
test.use({ viewport: { width: 1536, height: 960 } });

test('the three lists, why, their clients and the message', async ({ page, request }) => {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const store = ((br && br.branches) || br || []).find((x) => x.status !== 'closed')?.id || '';
  const det = (await (await request.get('/api/owner/brain/detectors', { headers: { ...H, 'X-FidClic-Store': store } })).json()).detectors;
  expect(det.map((d) => d.key)).toEqual(['en_retard', 'one_timers', 'moins_souvent']);

  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
    try { sessionStorage.removeItem('ft_pick_store'); } catch (_e) { /* ignore */ }
  }, [login.access_token, store]);
  await page.goto('/dashboard');
  const card = page.getByTestId('ia-spotted');
  await expect(card).toBeVisible({ timeout: 20_000 });
  for (const d of det) await expect(card.getByTestId(`ia-${d.key}`)).toContainText(d.label);
  const row = card.getByTestId('ia-one_timers');
  await row.getByRole('button', { name: /Pourquoi/ }).click();
  await expect(row).toContainText('Venus une seule fois');
  await page.screenshot({ path: 'test-results/ia-repere.png' });

  const any = det.find((d) => d.count > 0);
  if (any) {
    // the number the owner reads on the card is the one the composer and the list get
    const shown = Number((await card.getByTestId(`ia-${any.key}`).innerText()).match(/\d+/)[0]);
    any.count = shown;
    await card.getByTestId(`ia-${any.key}-cta`).click();
    await expect(page).toHaveURL(/\/dashboard\/campaigns/);
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible({ timeout: 15_000 });
    await expect(dialog.getByText(/produit_habituel/).first()).toBeVisible();   // the variable, as a chip
    await dialog.getByRole('button', { name: /^Suivant/ }).click();
    // a message goes to the store's OWN members (multi-store, 2026-10-12): at most the card's number
    const chosen = dialog.getByText(/\d+ clients? choisis?/).first();
    await expect(chosen).toBeVisible({ timeout: 20_000 });
    const n = Number((await chosen.innerText()).match(/\d+/)[0]);
    expect(n).toBeGreaterThan(0);
    expect(n).toBeLessThanOrEqual(any.count);
    // … and when it is fewer, the screen says why (user, 2026-10-25)
    const note = dialog.getByTestId('audience-note');
    if (n < any.count) await expect(note).toContainText(`${any.count} clients repérés, dont ${n} inscrit`);
    else await expect(note).toHaveCount(0);
    await page.screenshot({ path: 'test-results/ia-repere-note.png' });
    // the same list on the Clients page
    await page.goto(`/dashboard/customers?segment=${any.key}`);
    await expect(page.getByRole('heading', { name: new RegExp(`${any.count} clients?`) })).toBeVisible({ timeout: 20_000 });
  }
  expect(errors).toEqual([]);
});
