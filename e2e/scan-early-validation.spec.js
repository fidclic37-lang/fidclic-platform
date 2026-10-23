// The till says what is wrong before the récap, not at the final save (QA R7,
// 2026-10-18): « abc » showed 0,00 € in the summary and « -1 » reached it; a
// deleted client's card opened the visit form and was refused at « Enregistrer ».
// Runs against the local server only (scripts/dev_local.py — demo data in memory).
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only

test.use({ viewport: { width: 1536, height: 960 } });

async function setup(page, request) {
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const store = ((br && br.branches) || br || []).find((b) => b.status !== 'closed')?.id || '';
  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
  }, [login.access_token, store]);
  const pub = await (await request.get('/api/join/cafe-lumiere/page')).json();
  const slug = (pub.stores || []).find((x) => x.id === store)?.slug;
  const name = `Caisse ${Date.now() % 100000}`;
  const made = await (await request.post('/api/join/cafe-lumiere', { data: {
    name, phone: `07${String(Date.now()).slice(-8)}`, postal_code: '37000', birthday: '03/04/1992',
    consent: true, ...(slug ? { store: slug } : {}) } })).json();
  return { H: { ...H, ...(store ? { 'X-FidClic-Store': store } : {}) }, made, name };
}

async function scan(page, code) {
  await page.goto('/dashboard/scan');
  await page.getByRole('button', { name: 'Saisir le code' }).click();
  await page.getByLabel('Code de la carte').fill(code);
}

test('a wrong amount is said under the field and stops « Suivant »', async ({ page, request }) => {
  const { made } = await setup(page, request);
  await scan(page, made.barcode_id);
  await expect(page.getByText('Client scanné')).toBeVisible({ timeout: 10_000 });
  const amount = page.getByLabel('Montant payé');
  const next = page.getByRole('button', { name: /^Suivant/ }).first();

  await amount.fill('abc');
  await expect(amount, 'letters never get in').toHaveValue('');

  await amount.fill('-1');
  await expect(page.getByRole('alert').filter({ hasText: /négatif/ })).toBeVisible();
  await expect(next).toBeDisabled();

  await amount.fill('12,50');
  await expect(page.getByRole('alert')).toHaveCount(0);
  await expect(next).toBeEnabled();
  await next.click();
  await expect(page.getByTestId('visit-review')).toContainText('12,50');
});

test('a deleted client is refused at the scan, not at the final save', async ({ page, request }) => {
  const { H, made, name } = await setup(page, request);
  const rows = (await (await request.get(`/api/owner/clients/list?per_page=20&search=${encodeURIComponent(name)}`, { headers: H })).json()).rows || [];
  const cid = made.customer_id || rows.find((c) => c.name === name)?.id;
  const del = await request.post(`/api/owner/clients/${cid}/delete`, { headers: H });
  expect(del.ok(), await del.text()).toBeTruthy();

  await scan(page, made.barcode_id);
  await expect(page.getByText(/ce client a été supprimé/)).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText('Client scanné')).toHaveCount(0);
  await expect(page.getByLabel('Montant payé')).toHaveCount(0);
});
