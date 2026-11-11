/**
 * The ⋮ menus (user, 2026-11-10: « kisi bhi 3 dots mein click kro woh properly
 * visible hona chahiye »): one check for every page — the first row's menu
 * and the last row's, the last one pushed to the very bottom of the window,
 * each whole on the screen with every line in view; Échap and a click
 * elsewhere close it. Local server and demo data only.
 */
import { expect } from '@playwright/test';

const SETTLE = { timeout: 30_000 };
export const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
export const SIZES = [{ width: 1536, height: 1000 }, { width: 1280, height: 640 }];

export async function signIn(page, request, who = OWNER) {
  const login = await (await request.post('/api/auth/login', { data: who })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  let store = '';
  try {
    const br = await (await request.get('/api/owner/branches', { headers: H })).json();
    store = ((br && br.branches) || br || []).find((b) => b.status !== 'closed')?.id || '';
  } catch (_e) { /* not a shop account */ }
  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
    try { sessionStorage.removeItem('ft_pick_store'); } catch (_e) { /* ignore */ }
  }, [login.access_token, store]);
  return H;
}

export async function wholeOnScreen(page, menu) {
  const box = await menu.boundingBox();
  const vp = page.viewportSize();
  expect(box.y).toBeGreaterThanOrEqual(0);
  expect(box.y + box.height).toBeLessThanOrEqual(vp.height);
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(vp.width);
  for (const item of await menu.getByRole('menuitem').all()) await expect(item).toBeInViewport({ ratio: 1 });
}

/** `dots`: a locator for the page's ⋮ buttons, once it is loaded. */
export async function checkMenus(page, dots, { min = 2 } = {}) {
  await expect(dots.first()).toBeVisible(SETTLE);
  const n = await dots.count();
  expect(n).toBeGreaterThanOrEqual(min);
  for (const i of [...new Set([0, n - 1])]) {
    const b = dots.nth(i);
    await b.evaluate((el, block) => el.scrollIntoView({ block }), i === 0 ? 'center' : 'end');
    await b.click();
    const menu = page.getByRole('menu');
    await expect(menu).toBeVisible();
    await wholeOnScreen(page, menu);
    await page.keyboard.press('Escape');
    await expect(menu).toHaveCount(0);
  }
  await dots.first().evaluate((el) => el.scrollIntoView({ block: 'center' }));
  await dots.first().click();
  await expect(page.getByRole('menu')).toBeVisible();
  if (n > 1) {                                         // another row's ⋮: only one menu open
    await dots.nth(1).click();
    await expect(page.getByRole('menu')).toHaveCount(1);
    await dots.nth(1).click();                         // its own button closes it
    await expect(page.getByRole('menu')).toHaveCount(0);
    await dots.first().click();
    await expect(page.getByRole('menu')).toBeVisible();
  }
  await page.mouse.click(5, 5);                        // elsewhere
  await expect(page.getByRole('menu')).toHaveCount(0);
}
