// Money typed by mistake (QA report, 2026-10-11), in a real browser:
//   F31 — the price of a product erased and saved: it became free (0 €)
//         without a word. Now « Prix obligatoire »; a 0 typed on purpose is fine.
//   BUG-004 — on the scan page a product picked then taken off again (« − »
//         down to 0) left its total in « Montant payé », editable again.
//
// Runs against the local server only (scripts/dev_local.py — demo data in
// memory). Never point it at production.
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only

async function asOwner(page, request) {
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const store = ((br && br.branches) || br || []).find((b) => b.status !== 'closed')?.id || '';
  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
  }, [login.access_token, store]);
  return { ...H, ...(store ? { 'X-FidClic-Store': store } : {}) };
}

test.describe.serial('money typed by mistake', () => {
  test.use({ viewport: { width: 1536, height: 960 } });

  test('F31 — an erased price is refused, the product keeps its price', async ({ page, request }) => {
    const H = await asOwner(page, request);
    const name = `Menu test ${Date.now() % 100000}`;
    const made = await request.post('/api/owner/catalogue/products', { headers: H, data: { name, price: 11.11 } });
    expect(made.ok(), await made.text()).toBeTruthy();

    await page.goto('/dashboard/catalogue');
    await page.getByRole('button', { name: `Modifier ${name}` }).click();
    const price = page.getByPlaceholder('0,00');
    await expect(price).toHaveValue('11,11');
    await price.fill('');
    await page.getByRole('button', { name: /^Enregistrer/ }).click();
    await expect(page.getByText(/Prix obligatoire/)).toBeVisible();

    const list = await (await request.get('/api/owner/catalogue/page', { headers: H })).json();
    expect((list.products || []).find((p) => p.name === name)?.price, 'still 11,11 €').toBe(11.11);

    // 0 on purpose: a free product
    await price.fill('0');
    await page.getByRole('button', { name: /^Enregistrer/ }).click();
    await expect(page.getByText(/Prix obligatoire/)).toHaveCount(0);
    await expect.poll(async () => {
      const l = await (await request.get('/api/owner/catalogue/page', { headers: H })).json();
      return (l.products || []).find((p) => p.name === name)?.price;
    }).toBe(0);
  });

  test('BUG-004 — a product taken off again leaves no amount behind', async ({ page, request }) => {
    const H = await asOwner(page, request);
    const name = `Café test ${Date.now() % 100000}`;
    const made = await request.post('/api/owner/catalogue/products', { headers: H, data: { name, price: 10 } });
    expect(made.ok(), await made.text()).toBeTruthy();

    await page.goto('/dashboard/scan');
    const amount = page.locator('#scan-amount');
    await expect(amount).toBeVisible();
    await page.getByRole('button', { name: /Sélectionner un produit/ }).click();
    const row = page.locator('div.flex.items-center').filter({ hasText: name }).filter({ has: page.getByRole('button', { name: 'Retirer' }) }).last();
    await row.getByRole('button', { name: 'Ajouter' }).click();
    await expect(amount).toHaveValue(/^10[.,]00$/);
    await row.getByRole('button', { name: 'Retirer' }).click();
    await expect(amount, 'nothing picked: no amount left behind').toHaveValue('');
    await expect(amount).toBeEditable();
  });
});
