/**
 * Campagnes › list › ⋮ (user, 2026-11-10: « kisi bhi 3 dots mein click kro woh
 * properly visible hona chahiye »): the menu of the last campaigns opened under
 * the table's edge and was cut. It now opens whole on the screen (below, or
 * above when there is no room), and a click elsewhere closes it.
 * Local server and demo data only.
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
}

async function wholeOnScreen(page, menu) {
  const box = await menu.boundingBox();
  const vp = page.viewportSize();
  expect(box.y).toBeGreaterThanOrEqual(0);
  expect(box.y + box.height).toBeLessThanOrEqual(vp.height);
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(vp.width);
  for (const item of await menu.getByRole('menuitem').all()) await expect(item).toBeInViewport({ ratio: 1 });
}

for (const size of [{ width: 1536, height: 1000 }, { width: 1280, height: 640 }]) {
  test(`every campaign's ⋮ menu opens whole on screen (${size.width}×${size.height})`, async ({ page, request }) => {
    await page.setViewportSize(size);
    await asOwner(page, request);
    await page.goto('/dashboard/campaigns');
    await page.getByLabel('Campagnes par page').selectOption('20');
    const dots = page.getByRole('button', { name: "Plus d'actions" });
    await expect(dots.first()).toBeVisible(SETTLE);
    const n = await dots.count();
    expect(n).toBeGreaterThan(1);
    for (const i of [0, n - 1]) {                       // the first row and the last one
      const b = dots.nth(i);
      await b.evaluate((el, block) => el.scrollIntoView({ block }), i === 0 ? 'center' : 'end');
      await b.click();
      const menu = page.getByRole('menu');
      await expect(menu).toBeVisible();
      await wholeOnScreen(page, menu);
      await page.keyboard.press('Escape');
      await expect(menu).toHaveCount(0);
    }
    // a click elsewhere closes it
    await dots.first().evaluate((el) => el.scrollIntoView({ block: 'center' }));
    await dots.first().click();
    await expect(page.getByRole('menu')).toBeVisible();
    await page.getByRole('heading').first().click({ force: true });
    await expect(page.getByRole('menu')).toHaveCount(0);
  });
}
