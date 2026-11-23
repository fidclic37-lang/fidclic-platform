/**
 * « Une erreur d'affichage est survenue » (user, 2026-11-23): on the Tableau
 * de bord, the period menu of « Évolution du chiffre d'affaires » opens over
 * the chart. The owner picks a period, the menu closes, the cursor is now on
 * a column of the OLD series (say the 20th day of « 30 derniers jours »), the
 * new, shorter series arrives — and the chart read point 20 of 7. The whole
 * page went down. Same chart on Analyses. Local server only.
 */
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
const thisMonth = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Paris' }).format(new Date()).slice(0, 7);

async function signIn(page, request) {
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const store = ((br && br.branches) || br || []).find((x) => x.status !== 'closed')?.id || '';
  await page.goto('/login');
  await page.evaluate(([t, s, st]) => {
    localStorage.clear();
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
    localStorage.setItem('fidclic:period', st);                    // « 30 derniers jours »: 30 columns
    try { sessionStorage.removeItem('ft_pick_store'); } catch (_e) { /* ignore */ }
  }, [login.access_token, store, JSON.stringify({ p: '30', m: thisMonth() })]);
}

// Every *_series in the answer for the new period becomes `make(series)`.
function reshape(obj, make) {
  if (Array.isArray(obj)) return obj.map((v) => reshape(v, make));
  if (obj && typeof obj === 'object') {
    return Object.fromEntries(Object.entries(obj).map(([k, v]) =>
      [k, /_series$/.test(k) && Array.isArray(v) ? make(v) : reshape(v, make)]));
  }
  return obj;
}
async function newPeriodAnswers(page, path, make) {
  await page.route((u) => u.pathname === path && u.searchParams.get('days') === '7', async (route) => {
    const res = await route.fetch();
    await route.fulfill({ response: res, json: reshape(await res.json(), make) });
  });
}

const menu = (page) => page.getByRole('dialog', { name: 'Choisir la période' });

/** Rest the cursor on column `n` of `chart`, then pick « 7 derniers jours »
 *  without moving it — what a click on a menu lying over the chart does. */
async function pickWhileOnColumn(page, chart, n) {
  await chart.locator('rect[role="button"]').nth(n).hover();
  await expect(chart.getByTestId('trend-tip')).toBeVisible();
  await menu(page).getByRole('button', { name: '7 derniers jours' }).dispatchEvent('click');
}

function watch(page) {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  return errors;
}

test.use({ viewport: { width: 1440, height: 900 } });

test('Tableau de bord: a period picked with the cursor on the chart keeps the page up', async ({ page, request }) => {
  const errors = watch(page);
  await signIn(page, request);
  await newPeriodAnswers(page, '/api/owner/home/overview', (s) => s.slice(-2));
  await page.goto('/dashboard');
  const chart = page.getByTestId('trend-chart').first();
  await expect(chart.locator('rect[role="button"]')).toHaveCount(30);
  // the chart's own menu, the one of the screenshot
  await page.getByRole('button', { name: 'Période analysée' }).nth(1).click();
  await expect(menu(page)).toBeVisible();
  const done = page.waitForResponse((r) => r.url().includes('/api/owner/home/overview') && r.url().includes('days=7'));
  await pickWhileOnColumn(page, chart, 12);
  await done;
  await expect(chart.locator('rect[role="button"]')).toHaveCount(2);
  await expect(page.getByText("Une erreur d'affichage est survenue")).toHaveCount(0);
  expect(errors).toEqual([]);
  // and the chart still reads a point
  await chart.locator('rect[role="button"]').nth(1).hover();
  await expect(chart.getByTestId('trend-tip')).toBeVisible();
});

test('Tableau de bord: a pinned point of the old period does not crash either', async ({ page, request }) => {
  const errors = watch(page);
  await signIn(page, request);
  await newPeriodAnswers(page, '/api/owner/home/overview', (s) => s.slice(-2));
  await page.goto('/dashboard');
  const chart = page.getByTestId('trend-chart').first();
  await chart.locator('rect[role="button"]').nth(25).focus();
  await page.keyboard.press('Enter');                               // pinned on day 26
  await expect(chart.getByTestId('trend-detail')).toBeVisible();
  // change the period without a click outside the chart (keyboard)
  await page.getByRole('button', { name: 'Période analysée' }).first().focus();
  await page.keyboard.press('Enter');
  await menu(page).getByRole('button', { name: '7 derniers jours' }).focus();
  await page.keyboard.press('Enter');
  await expect(chart.locator('rect[role="button"]')).toHaveCount(2);
  await expect(page.getByText("Une erreur d'affichage est survenue")).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('Analyses: the same chart, the same period switch, the page stays up', async ({ page, request }) => {
  const errors = watch(page);
  await signIn(page, request);
  await newPeriodAnswers(page, '/api/owner/analyses', (s) => s.slice(-2));
  await page.goto('/dashboard/analytics');
  const chart = page.getByTestId('trend-chart').first();
  await chart.scrollIntoViewIfNeeded();
  await expect(chart.locator('rect[role="button"]')).toHaveCount(30);
  await page.getByRole('button', { name: 'Période analysée' }).first().click();
  await expect(menu(page)).toBeVisible();
  await chart.scrollIntoViewIfNeeded();
  const done = page.waitForResponse((r) => r.url().includes('/api/owner/analyses') && r.url().includes('days=7'));
  await pickWhileOnColumn(page, chart, 20);
  await done;
  await expect(chart.locator('rect[role="button"]')).toHaveCount(2);
  await expect(page.getByText("Une erreur d'affichage est survenue")).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('a broken point in the answer is skipped, not fatal', async ({ page, request }) => {
  const errors = watch(page);
  await signIn(page, request);
  await newPeriodAnswers(page, '/api/owner/home/overview', (s) => [null, ...s.slice(-3), 'x']);
  await page.goto('/dashboard');
  const chart = page.getByTestId('trend-chart').first();
  await page.getByRole('button', { name: 'Période analysée' }).first().click();
  await menu(page).getByRole('button', { name: '7 derniers jours' }).click();
  await expect(chart.locator('rect[role="button"]')).toHaveCount(3);
  await expect(page.getByText("Une erreur d'affichage est survenue")).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('if a chart ever breaks, only that card says so — the page stays', async ({ page, request }) => {
  await signIn(page, request);
  // a label that is an object cannot be drawn: the chart itself fails
  await newPeriodAnswers(page, '/api/owner/home/overview', (s) => [{ ...s[0], label: { x: 1 } }]);
  await page.goto('/dashboard');
  await page.getByRole('button', { name: 'Période analysée' }).first().click();
  await menu(page).getByRole('button', { name: '7 derniers jours' }).click();
  await expect(page.getByTestId('trend-chart-error').first()).toBeVisible();
  await expect(page.getByTestId('trend-chart-error').first()).toContainText("Ce graphique n'a pas pu s'afficher.");
  await expect(page.getByText("Une erreur d'affichage est survenue")).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Période analysée' }).first()).toContainText('7 derniers jours');
  // back to a good period, the chart comes back by itself
  await page.getByRole('button', { name: 'Période analysée' }).first().click();
  await menu(page).getByRole('button', { name: '30 derniers jours' }).click();
  await expect(page.getByTestId('trend-chart').first().locator('rect[role="button"]')).toHaveCount(30);
});
