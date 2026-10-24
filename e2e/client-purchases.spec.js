/**
 * Clients › a client's « Historique d'achats » (user, 2026-10-15): the day,
 * the hour, what was bought and how much. A visit made at the till here, then
 * read back from the Clients page. Local server only.
 */
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
test.use({ viewport: { width: 1536, height: 960 } });

test('the client name opens what they bought, when, and for how much', async ({ page, request }) => {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const store = ((br && br.branches) || br || []).find((x) => x.status !== 'closed')?.id || '';
  const SH = { ...H, 'X-FidClic-Store': store };
  // a catalogue line and a fresh client, then a visit at the till
  const stamp = String(Date.now()).slice(-6);
  const product = `Coupe test ${stamp}`;
  const made = await (await request.post('/api/owner/catalogue/products', { headers: SH, data: { name: product, price: 22, category: '' } })).json();
  const pub = await (await request.get('/api/join/cafe-lumiere/page')).json();
  const signup = await (await request.post('/api/join/cafe-lumiere', { data: {
    name: `Achat ${stamp}`, phone: `07${String(Date.now()).slice(-8)}`, postal_code: '37000', birthday: '01/02/1990', consent: true,
    ...((pub.stores || []).length ? { store: pub.stores[0].slug } : {}) } })).json();
  const scan = await request.post('/api/owner/scan', { headers: SH, data: {
    barcode_id: signup.barcode_id, items: [{ item_id: made.id, qty: 2 }], branch_id: store || undefined } });
  expect(scan.ok(), await scan.text()).toBeTruthy();

  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
    try { sessionStorage.removeItem('ft_pick_store'); } catch (_e) { /* ignore */ }
  }, [login.access_token, store]);
  await page.goto('/dashboard/customers');
  await page.getByPlaceholder('Rechercher un client (nom, email, téléphone…)').fill(`Achat ${stamp}`);
  await page.getByRole('button', { name: `Achat ${stamp}`, exact: true }).click();

  // it opens on « Profil » (FidClic IA, 2026-10-24); the purchases are the tab beside it
  await expect(page.getByRole('dialog', { name: 'Profil client' })).toBeVisible();
  await page.getByRole('tab', { name: "Historique d'achats" }).click();
  const panel = page.getByRole('dialog', { name: "Historique d'achats" });
  await expect(panel).toBeVisible();
  await expect(panel.getByTestId('purchase-totals')).toContainText('1');
  await expect(panel.getByTestId('purchase-totals')).toContainText('44,00');
  const row = panel.getByTestId('purchase-row').first();
  await expect(row).toContainText(`2 × ${product}`);
  await expect(row).toContainText('44,00');
  await expect(row).toContainText(/à \d{2}:\d{2}/);
  await page.screenshot({ path: 'test-results/client-purchases.png' });
  await panel.getByRole('button', { name: 'Fermer' }).click();
  await expect(panel).toHaveCount(0);
  expect(errors).toEqual([]);
});
