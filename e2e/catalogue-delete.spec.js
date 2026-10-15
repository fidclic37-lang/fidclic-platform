/**
 * What the owner deletes is gone (user, 2026-10-15): a category deleted takes
 * its products with it — not into « Sans catégorie » — and a name with « / »
 * (« Coupe/Coiffage/Barbe ») can be deleted. Local server only.
 */
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
test.use({ viewport: { width: 1536, height: 960 } });

test('deleting « Coupe/Coiffage/Barbe » deletes it and its products', async ({ page, request }) => {
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const store = ((br && br.branches) || br || []).find((x) => x.status !== 'closed')?.id || '';
  const stamp = String(Date.now()).slice(-5);
  const cat = `Coupe/Coiffage/Barbe ${stamp}`;
  for (const [name, price] of [[`Contours ${stamp}`, 12], [`Barbe express ${stamp}`, 15]]) {
    expect((await request.post('/api/owner/catalogue/products', { headers: H, data: { name, price, category: cat } })).ok()).toBeTruthy();
  }
  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
    try { sessionStorage.removeItem('ft_pick_store'); } catch (_e) { /* ignore */ }
  }, [login.access_token, store]);
  await page.goto('/dashboard/catalogue');
  await page.getByRole('tab', { name: 'Catégories' }).click();
  await page.getByRole('button', { name: `Supprimer ${cat}` }).click();
  // by default its products go too, and the dialog says so
  await expect(page.getByText(/et ses 2 produits seront supprimés/)).toBeVisible();
  await page.getByRole('button', { name: 'Supprimer', exact: true }).click();
  await expect(page.getByText(/Catégorie et 2 produits supprimés/)).toBeVisible();

  const after = await (await request.get('/api/owner/catalogue/page', { headers: H })).json();
  expect(after.categories.map((c) => c.name)).not.toContain(cat);
  expect(after.products.map((p) => p.name).filter((n) => n.endsWith(stamp))).toEqual([]);
});
