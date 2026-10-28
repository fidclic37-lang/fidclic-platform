/**
 * The period menu (Tableau de bord, Analyses) opened past the left edge of a
 * phone (user, 2026-10-28: « jours waala dropdown kat jaa rha hai »): it was
 * pinned to the button's right edge while the button sits on the left. It
 * now opens wherever it fits, and its custom row (number + unit + Appliquer)
 * stays inside the menu at the phone's 16 px field size. Local server only.
 */
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only

// signed in as the demo owner, its first open store picked (no store screen)
async function signIn(page, request) {
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const store = ((br && br.branches) || br || []).find((x) => x.status !== 'closed')?.id || '';
  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
    try { sessionStorage.removeItem('ft_pick_store'); } catch (_e) { /* ignore */ }
  }, [login.access_token, store]);
}

const inside = async (page, w) => {
  const menu = page.getByRole('listbox');
  await expect(menu).toBeVisible();
  const m = await menu.boundingBox();
  expect(m.x, 'menu left edge on screen').toBeGreaterThanOrEqual(0);
  expect(m.x + m.width, 'menu right edge on screen').toBeLessThanOrEqual(w);
  for (const el of [page.getByLabel('Nombre'), page.getByLabel('Unité'), page.getByRole('button', { name: 'Appliquer' })]) {
    const b = await el.boundingBox();
    expect(b.x, 'inside the menu (left)').toBeGreaterThanOrEqual(m.x);
    expect(b.x + b.width, 'inside the menu (right)').toBeLessThanOrEqual(m.x + m.width + 0.5);
  }
};

async function open(page, request, url) {
  await signIn(page, request);
  await page.goto(url);
  await page.getByRole('button', { name: 'Période analysée' }).first().click();
}

for (const w of [320, 375, 390, 430]) {
  test.describe(`phone ${w} px`, () => {
    test.use({ viewport: { width: w, height: 844 }, isMobile: true, hasTouch: true });
    test('Tableau de bord: the period menu stays on screen', async ({ page, request }) => {
      await open(page, request, '/dashboard');
      await inside(page, w);
      // and it still works: a custom period applies
      await page.getByLabel('Nombre').fill('45');
      await page.getByRole('button', { name: 'Appliquer' }).click();
      await expect(page.getByRole('button', { name: 'Période analysée' }).first()).toContainText('45 derniers jours');
    });
  });
}

test.describe('phone 390 px — Analyses', () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  test('Analyses: the period menu stays on screen', async ({ page, request }) => {
    await open(page, request, '/dashboard/analytics');
    await inside(page, 390);
  });
});

test('computer: the menu stays on screen too', async ({ page, request }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, request, '/dashboard');
  const m = await page.getByRole('listbox').boundingBox();
  expect(m.x).toBeGreaterThanOrEqual(0);
  expect(m.x + m.width).toBeLessThanOrEqual(1440);
});
