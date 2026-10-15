/**
 * The owner's phone at the till (user, 2026-10-15: « mobile mein ekdm easy,
 * especially for scanning »): the scanner from the bottom bar, the client in
 * one line, products as tiles, the next step always at the bottom, and the
 * camera inside the screen. Local server only.
 */
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

test('phone: scan → tiles → Suivant → Enregistrer, all at the thumb', async ({ page, request }) => {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const store = ((br && br.branches) || br || []).find((x) => x.status !== 'closed')?.id || '';
  expect((await request.put('/api/owner/catalog', { headers: H, data: { items: [
    { name: 'Coupe homme', price: 22, category: 'Coupes' }, { name: 'Coupe + barbe', price: 29, category: 'Coupes' },
    { name: 'Shampoing', price: 5, category: 'Soins' } ] } })).ok()).toBeTruthy();
  const clients = await (await request.get('/api/owner/clients/list?per_page=3', { headers: H })).json();
  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
    try { sessionStorage.removeItem('ft_pick_store'); } catch (_e) { /* ignore */ }
  }, [login.access_token, store]);
  await page.goto('/dashboard');

  // the scanner, in the bottom bar, one tap from any page
  const nav = page.getByRole('navigation', { name: 'Navigation principale' });
  await expect(nav).toBeVisible();
  await nav.getByRole('link', { name: 'Scanner une carte' }).click();
  await expect(page).toHaveURL(/\/dashboard\/scan/);
  // the camera box stays inside the screen
  const box = await page.locator('video').locator('..').boundingBox();
  expect(box.x + box.width, 'camera inside the screen').toBeLessThanOrEqual(390);

  await page.getByRole('button', { name: 'Saisir le code' }).click();
  await page.getByLabel('Code de la carte').fill(clients.rows[0].barcode_id);
  await expect(page.getByTestId('client-line')).toBeVisible({ timeout: 10_000 });
  await page.getByRole('button', { name: 'Ajouter Coupe + barbe' }).click();
  await page.getByRole('button', { name: 'Ajouter Shampoing' }).click();
  await page.getByRole('button', { name: 'Ajouter Shampoing' }).click();
  const bar = page.getByTestId('phone-action-bar');
  await expect(bar).toContainText('39,00');
  // the bar is on screen without scrolling, above the bottom bar
  const b = await bar.boundingBox();
  const n = await nav.boundingBox();
  expect(b.y + b.height).toBeLessThanOrEqual(n.y + 1);
  await bar.getByRole('button', { name: /Suivant/ }).click();
  await expect(page.getByTestId('visit-review')).toContainText('1 × Coupe + barbe, 2 × Shampoing');
  await bar.getByRole('button', { name: /Enregistrer/ }).click();
  await expect(page.getByTestId('visit-summary')).toContainText('39,00', { timeout: 15_000 });
  await bar.getByRole('button', { name: /Scanner une autre carte/ }).click();
  await expect(page.getByTestId('client-line')).toHaveCount(0);
  expect(errors).toEqual([]);
});
