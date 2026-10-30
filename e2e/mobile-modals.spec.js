/**
 * Phone: a window opened from a page sits ABOVE the bottom tab bar (user,
 * 2026-10-30: « mobile mein jab business ko kisi customer ko tampons ya
 * points add krna hota hai … blue button jo save krne k liye hota hai woh
 * aata hi nhi, n hi scroll kr paate »). The page's <main> made its own layer
 * (z-10) under the tab bar (z-40), so the bottom of every window — its save
 * button — was painted under the bar and could not be reached. Local server only.
 */
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only

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

// the button is on screen and nothing is painted over it
async function reachable(page, button) {
  await button.scrollIntoViewIfNeeded();
  const b = await button.boundingBox();
  const vp = page.viewportSize();
  expect(b, 'the button is laid out').toBeTruthy();
  expect(b.y + b.height, 'its bottom is on screen').toBeLessThanOrEqual(vp.height);
  const mine = await button.evaluate((el) => {
    const r = el.getBoundingClientRect();
    const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
    return !!hit && (hit === el || el.contains(hit));
  });
  expect(mine, 'nothing (the tab bar) covers the button').toBe(true);
}

async function openRowAction(page, label) {
  await page.goto('/dashboard/customers');
  const more = page.getByRole('button', { name: "Plus d'actions" }).first();
  await more.scrollIntoViewIfNeeded();
  await more.click();
  await page.getByRole('button', { name: label }).click();
}

for (const [w, h] of [[375, 812], [390, 844], [320, 568]]) {
  test.describe(`phone ${w}×${h}`, () => {
    test.use({ viewport: { width: w, height: h }, isMobile: true, hasTouch: true });

    test('Ajuster points / tampons: the save button can be reached and saves', async ({ page, request }) => {
      await signIn(page, request);
      await openRowAction(page, 'Ajuster points / tampons');
      const dlg = page.getByRole('dialog', { name: 'Ajuster points / tampons' });
      await expect(dlg).toBeVisible();
      await dlg.getByRole('button', { name: 'Ajouter 1 — Tampons' }).click();
      await dlg.getByPlaceholder(/visite oubliée/).fill('Test e2e mobile');
      const save = dlg.getByRole('button', { name: /Enregistrer l'ajustement/ });
      await reachable(page, save);
      await save.click();
      await expect(dlg).toHaveCount(0);
    });

    test('Modifier la fiche: the save button can be reached', async ({ page, request }) => {
      await signIn(page, request);
      await openRowAction(page, 'Modifier la fiche');
      const dlg = page.getByRole('dialog', { name: 'Modifier la fiche' });
      await expect(dlg).toBeVisible();
      await reachable(page, dlg.getByRole('button', { name: /Enregistrer/ }));
    });
  });
}
