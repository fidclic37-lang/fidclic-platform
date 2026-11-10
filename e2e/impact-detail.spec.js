/**
 * « Impact FidClic » clicked (user, 2026-11-10): the detail opens on the page
 * the card sits on — the Tableau de bord, or Analyses — by action, by visit,
 * by day, and its total is the card's. Local server and demo data only.
 */
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
const SETTLE = { timeout: 30_000 };

async function asOwner(page, request) {
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const store = ((br && br.branches) || br || []).find((b) => b.status !== 'closed')?.id || '';
  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
    try { sessionStorage.removeItem('ft_pick_store'); } catch (_e) { /* ignore */ }
  }, [login.access_token, store]);
  return { ...H, ...(store ? { 'X-FidClic-Store': store } : {}) };
}

const card = (page) => page.getByRole('region', { name: 'Impact FidClic', exact: true });
const detail = (page) => page.getByTestId('impact-detail');
const digits = (s) => (s || '').replace(/[^\d,]/g, '');

test.use({ viewport: { width: 1536, height: 1000 } });

test('Tableau de bord: the card opens its detail right there, by action, visit and day', async ({ page, request }) => {
  const SH = await asOwner(page, request);
  const api = await (await request.get('/api/owner/home/impact?days=30', { headers: SH })).json();

  await page.goto('/dashboard');
  await expect(card(page)).toBeVisible(SETTLE);
  await expect(detail(page)).toHaveCount(0);

  await card(page).getByRole('button', { name: /Voir le détail/ }).click();
  await expect(detail(page)).toBeVisible(SETTLE);
  await expect(page).toHaveURL(/\/dashboard\/?$/);                       // same page
  await expect(detail(page).getByRole('tab', { name: 'Par action' })).toHaveAttribute('aria-selected', 'true');

  // the total is the card's
  const cardValue = digits(await card(page).locator('span.rounded-full').first().innerText());
  await expect.poll(async () => digits(await detail(page).locator('p b').first().innerText()), SETTLE).toBe(cardValue);

  if (api.actions.length) {
    // an action → its visits
    const first = api.actions[0];
    await detail(page).getByRole('button', { name: first.name }).first().click();
    await expect(detail(page).getByRole('tab', { name: 'Par visite' })).toHaveAttribute('aria-selected', 'true');
    await expect(detail(page).locator('tbody tr').first()).toContainText(first.name);
  }

  await detail(page).getByRole('tab', { name: 'Par jour' }).click();
  if (api.days.length) {
    await expect(detail(page).getByLabel('CA FidClic par jour')).toBeVisible();
    await detail(page).getByLabel('CA FidClic par jour').locator('button').last().click();
    await expect(detail(page).getByRole('tab', { name: 'Par visite' })).toHaveAttribute('aria-selected', 'true');
  }

  // the Parrainage tile opens the detail on the parrains
  await card(page).getByRole('button', { name: 'Parrainage' }).click();
  await expect(detail(page).getByRole('button', { name: /^Parrainage/, pressed: true })).toBeVisible();

  // CSV
  const [dl] = await Promise.all([page.waitForEvent('download'), detail(page).getByRole('button', { name: /Exporter/ }).click()]);
  expect(dl.suggestedFilename()).toMatch(/^fidclic-impact-.*\.csv$/);

  await detail(page).getByRole('button', { name: 'Fermer le détail' }).click();
  await expect(detail(page)).toHaveCount(0);
});

test('Analyses: the same card opens its detail inside Analyses', async ({ page, request }) => {
  await asOwner(page, request);
  await page.goto('/dashboard/analytics');
  await expect(card(page)).toBeVisible(SETTLE);
  await card(page).getByRole('button', { name: 'Visites générées' }).click();
  await expect(detail(page)).toBeVisible(SETTLE);
  await expect(page).toHaveURL(/\/dashboard\/analytics/);
  await expect(detail(page).getByRole('tab', { name: 'Par visite' })).toHaveAttribute('aria-selected', 'true');
  const cardValue = digits(await card(page).locator('span.rounded-full').first().innerText());
  await expect.poll(async () => digits(await detail(page).locator('p b').first().innerText()), SETTLE).toBe(cardValue);
});
