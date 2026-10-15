/**
 * « Ajouter un produit » in the order an owner thinks (user, 2026-10-15):
 * 1. category (buttons, or a new one on the spot), 2. name, 3. price —
 * then one « Ajouter » that stays open for the next one. Local server only.
 */
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
test.use({ viewport: { width: 1536, height: 960 } });

test('category → name → price, several in a row, then done', async ({ page, request }) => {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
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
  await page.goto('/dashboard/catalogue');
  await page.getByRole('button', { name: 'Ajouter un produit' }).first().click();
  const dlg = page.getByRole('dialog');
  await expect(dlg.getByText('Ajouter un produit ou un service')).toBeVisible();
  // the three steps, in this order
  const steps = await dlg.locator('section p').allInnerTexts();
  expect(steps.map((t) => t.replace(/\s+/g, ' ').trim()).slice(0, 3).map((t) => t.replace(/^\d\s*/, '')))
    .toEqual(['Catégorie (facultatif)', 'Nom du produit ou du service', 'Prix']);
  await expect(dlg.getByText(/Plus d.options/)).toBeVisible();
  await expect(dlg.getByText('Description courte (facultatif)')).toHaveCount(0);   // waits under « Plus d'options »
  await page.screenshot({ path: 'test-results/product-form.png' });

  const cat = `Coupes ${String(Date.now()).slice(-5)}`;
  await dlg.getByRole('radio', { name: /Nouvelle catégorie/ }).click();
  await dlg.getByLabel('Nom de la nouvelle catégorie').fill(cat);
  await dlg.getByLabel('Nom de la nouvelle catégorie').press('Enter');          // → the name
  await page.keyboard.type('Coupe enfant');
  await page.keyboard.press('Enter');                                           // → the price
  await page.keyboard.type('18');
  await dlg.getByRole('button', { name: 'Ajouter', exact: true }).click();
  await expect(dlg.getByRole('button', { name: /Ajouter et continuer/ })).toHaveCount(0);   // one button only
  await expect(dlg.getByTestId('added-in-a-row')).toContainText('Coupe enfant');
  // the category stays chosen, the rest is empty, the name has the focus
  await expect(dlg.getByRole('radio', { name: cat })).toHaveAttribute('aria-checked', 'true');
  await expect(dlg.getByLabel('Nom du produit ou du service')).toBeFocused();
  await expect(dlg.getByLabel('Prix en euros')).toHaveValue('');
  await page.keyboard.type('Coupe + barbe');
  await dlg.getByLabel('Prix en euros').fill('29,50');
  await dlg.getByLabel('Prix en euros').press('Enter');                         // Enter adds too
  await expect(dlg.getByTestId('added-in-a-row')).toContainText('Coupe + barbe');
  await dlg.getByRole('button', { name: 'Terminer' }).click();
  await expect(dlg).toHaveCount(0);

  const after = await (await request.get('/api/owner/catalogue/page', { headers: H })).json();
  const mine = after.products.filter((p) => p.category === cat).map((p) => [p.name, p.price]).sort();
  expect(mine).toEqual([['Coupe + barbe', 29.5], ['Coupe enfant', 18]]);
  expect(errors).toEqual([]);
});
