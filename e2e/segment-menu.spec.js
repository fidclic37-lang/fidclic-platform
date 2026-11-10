/**
 * Segmentation › « Vos segments » › ⋮ (user, 2026-11-10): the menu of a row
 * near the bottom opened under the table's edge and was cut — « kisi bhi 3
 * dots mein click kro woh properly visible hona chahiye ». Every row's menu
 * now opens whole on the screen: below its button, or above when there is
 * no room below. Local server and demo data only.
 */
import { test, expect } from '@playwright/test';
import { placeMenu } from '../src/lib/placeMenu.js';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
const SETTLE = { timeout: 30_000 };

test.describe('placeMenu (where a menu opens)', () => {
  test('below its button when it fits', () => {
    expect(placeMenu({ anchorTop: 100, anchorBottom: 130, height: 120, viewH: 800 })).toBe(134);
  });
  test('above its button when there is no room below', () => {
    expect(placeMenu({ anchorTop: 700, anchorBottom: 730, height: 120, viewH: 800 })).toBe(700 - 4 - 120);
  });
  test('exactly at the edge still fits below', () => {
    // 734 + 58 = 792 = 800 - 8
    expect(placeMenu({ anchorTop: 700, anchorBottom: 730, height: 58, viewH: 800 })).toBe(734);
  });
  test('room on neither side: as high as it needs, never above the top', () => {
    expect(placeMenu({ anchorTop: 60, anchorBottom: 90, height: 700, viewH: 720 })).toBe(12);
    expect(placeMenu({ anchorTop: 60, anchorBottom: 90, height: 900, viewH: 720 })).toBe(8);
  });
  test('nonsense in, a usable place out', () => {
    expect(placeMenu({ anchorTop: NaN, anchorBottom: undefined, height: 0, viewH: 0 })).toBe(8);
  });
});

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

for (const size of [{ width: 1536, height: 1000 }, { width: 1280, height: 640 }]) {
  test(`every ⋮ menu of « Vos segments » opens whole on screen (${size.width}×${size.height})`, async ({ page, request }) => {
    await page.setViewportSize(size);
    await asOwner(page, request);
    await page.goto('/dashboard/segmentation');
    const dots = page.getByRole('button', { name: /^Actions pour le segment/ });
    await expect(dots.first()).toBeVisible(SETTLE);
    const n = await dots.count();
    expect(n).toBeGreaterThan(1);
    for (const i of [0, n - 1]) {                        // the first row and the last one
      const b = dots.nth(i);
      await b.scrollIntoViewIfNeeded();
      // the last row: put it at the very bottom of the window, where it used to be cut
      if (i === n - 1) {
        await b.evaluate((el) => el.scrollIntoView({ block: 'end' }));
      }
      await b.click();
      const menu = page.getByRole('menu');
      await expect(menu).toBeVisible();
      await expect(menu.getByRole('menuitem', { name: /Créer une campagne/ })).toBeVisible();
      const box = await menu.boundingBox();
      const vp = page.viewportSize();
      expect(box.y).toBeGreaterThanOrEqual(0);
      expect(box.y + box.height).toBeLessThanOrEqual(vp.height);
      expect(box.x).toBeGreaterThanOrEqual(0);
      expect(box.x + box.width).toBeLessThanOrEqual(vp.width);
      // every line clickable as it is, nothing to scroll
      for (const item of await menu.getByRole('menuitem').all()) {
        await expect(item).toBeInViewport({ ratio: 1 });
      }
      await page.keyboard.press('Escape');
      await expect(menu).toHaveCount(0);
    }
  });
}
