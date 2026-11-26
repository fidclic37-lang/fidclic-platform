/**
 * Clients › « Historique d'achats » › Modifier / Supprimer un achat (user,
 * 2026-11-26): the business corrects what a client bought — products from its
 * own catalogue, quantities, the amount — and the figures follow. A visit made
 * at the till, then edited and deleted from the Clients page. Local server only.
 */
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
test.use({ viewport: { width: 1536, height: 960 } });

async function setup({ request }) {
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const store = ((br && br.branches) || br || []).find((x) => x.status !== 'closed')?.id || '';
  const SH = { ...H, 'X-FidClic-Store': store };
  const stamp = String(Date.now()).slice(-6);
  const coupe = `Coupe édit ${stamp}`;
  const soin = `Soin édit ${stamp}`;
  const a = await (await request.post('/api/owner/catalogue/products', { headers: SH, data: { name: coupe, price: 22, category: '' } })).json();
  await (await request.post('/api/owner/catalogue/products', { headers: SH, data: { name: soin, price: 8, category: '' } })).json();
  const pub = await (await request.get('/api/join/cafe-lumiere/page')).json();
  const signup = await (await request.post('/api/join/cafe-lumiere', { data: {
    name: `Édition ${stamp}`, phone: `07${String(Date.now()).slice(-8)}`, postal_code: '37000', birthday: '01/02/1990', consent: true,
    ...((pub.stores || []).length ? { store: pub.stores[0].slug } : {}) } })).json();
  const scan = await request.post('/api/owner/scan', { headers: SH, data: {
    barcode_id: signup.barcode_id, items: [{ item_id: a.id, qty: 2 }], branch_id: store || undefined } });
  expect(scan.ok(), await scan.text()).toBeTruthy();
  return { login, store, stamp, coupe, soin, customerId: signup.customer_id || signup.id, H };
}

async function openPurchases(page, login, store, stamp) {
  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
    try { sessionStorage.removeItem('ft_pick_store'); } catch (_e) { /* ignore */ }
  }, [login.access_token, store]);
  await page.goto('/dashboard/customers');
  await page.getByPlaceholder('Rechercher un client (nom, email, téléphone…)').fill(`Édition ${stamp}`);
  await page.getByRole('button', { name: `Édition ${stamp}`, exact: true }).click();
  await expect(page.getByRole('dialog', { name: 'Profil client' })).toBeVisible();
  await page.getByRole('tab', { name: "Historique d'achats" }).click();
  const panel = page.getByRole('dialog', { name: "Historique d'achats" });
  await expect(panel).toBeVisible();
  return panel;
}

test('the business corrects a purchase from its catalogue, then deletes it', async ({ page, request }) => {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const { login, store, stamp, coupe, soin } = await setup({ request });
  const panel = await openPurchases(page, login, store, stamp);

  // what the till recorded
  const row = panel.getByTestId('purchase-row').first();
  await expect(row).toContainText(`2 × ${coupe}`);
  await expect(row).toContainText('44,00');

  // — edit: one coupe less, a soin more → 22 + 8 = 30 €
  await row.getByRole('button', { name: 'Modifier' }).click();
  const editor = panel.getByTestId('purchase-editor');
  await expect(editor).toBeVisible();
  await editor.getByRole('button', { name: `Retirer un ${coupe}` }).click();
  await editor.getByPlaceholder('Ajouter un produit du catalogue…').fill(soin.slice(0, 12));
  await editor.getByRole('button', { name: new RegExp(`^${soin}`) }).click();
  await expect(editor.getByTestId('editor-total')).toContainText('30,00');
  await editor.getByLabel('Raison (facultatif)').fill('Erreur de caisse');
  await editor.getByRole('button', { name: 'Enregistrer' }).click();

  await expect(editor).toHaveCount(0);
  const edited = panel.getByTestId('purchase-row').first();
  await expect(edited).toContainText(`1 × ${coupe}`);
  await expect(edited).toContainText(`1 × ${soin}`);
  await expect(edited).toContainText('30,00');
  await expect(edited).toContainText('Modifié');
  await expect(panel.getByTestId('purchase-totals')).toContainText('30,00');
  await page.screenshot({ path: 'test-results/client-purchases-edited.png' });

  // — a manual amount: the till took 25 €
  await edited.getByRole('button', { name: 'Modifier' }).click();
  await editor.getByLabel('Montant encaissé différent du catalogue').check();
  await editor.getByLabel('Montant encaissé (€)').fill('25');
  await editor.getByRole('button', { name: 'Enregistrer' }).click();
  await expect(editor).toHaveCount(0);
  await expect(panel.getByTestId('purchase-row').first()).toContainText('25,00');
  await expect(panel.getByTestId('purchase-totals')).toContainText('25,00');

  // — delete, in two steps
  await panel.getByTestId('purchase-row').first().getByRole('button', { name: 'Modifier' }).click();
  await editor.getByRole('button', { name: 'Supprimer cet achat' }).click();
  await editor.getByRole('button', { name: 'Confirmer la suppression' }).click();
  await expect(panel.getByTestId('purchase-row')).toHaveCount(0);
  await expect(panel.getByText('Aucun achat enregistré pour ce client')).toBeVisible();
  await expect(panel.getByTestId('purchase-totals')).toContainText('0,00');
  expect(errors).toEqual([]);
});

test('on a phone the editor fits and the buttons are big enough', async ({ page, request }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const { login, store, stamp, coupe } = await setup({ request });
  const panel = await openPurchases(page, login, store, stamp);
  const row = panel.getByTestId('purchase-row').first();
  await row.getByRole('button', { name: 'Modifier' }).click();
  const editor = panel.getByTestId('purchase-editor');
  await expect(editor).toBeVisible();
  const box = await editor.getByRole('button', { name: `Retirer un ${coupe}` }).boundingBox();
  expect(box.height).toBeGreaterThanOrEqual(40);
  expect(box.width).toBeGreaterThanOrEqual(40);
  const noScroll = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
  expect(noScroll).toBeTruthy();
  await editor.getByRole('button', { name: 'Annuler' }).click();
  await expect(editor).toHaveCount(0);
});
