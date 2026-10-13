/**
 * « Enregistrer une visite » — the redesigned till.
 *
 * Drives the real page against the real server: scan a card, pick services
 * from the catalogue drawer with quantities, watch the amount follow, apply
 * one reward, register. What the page claims must be what the server wrote.
 */
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only

async function asOwner(page, request) {
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const br = await (await request.get('/api/owner/branches', { headers: { Authorization: `Bearer ${login.access_token}` } })).json();
  const store = ((br && br.branches) || br || []).find((b) => b.status !== 'closed')?.id || '';
  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
  }, [login.access_token, store]);
  return login.access_token;
}

test.describe.serial('the till records a visit', () => {
  test.use({ viewport: { width: 1536, height: 960 } });

  let token; let H; let card;

  test('a catalogue and a client to scan', async ({ page, request }) => {
    token = await asOwner(page, request);
    H = { Authorization: `Bearer ${token}` };
    // a catalogue the drawer can show
    expect((await request.put('/api/owner/catalog', { headers: H, data: { items: [
      { name: 'Coupe femme', price: 45, category: 'Coupe' },
      { name: 'Brushing', price: 25, category: 'Brushing' },
      { name: 'Coloration', price: 70, category: 'Couleur' },
    ] } })).status()).toBe(200);
    const clients = await (await request.get('/api/owner/clients/list?per_page=5', { headers: H })).json();
    const first = (clients.rows || [])[0];
    expect(first, 'the seed has at least one client').toBeTruthy();
    card = first.barcode_id;
    expect(card, 'that client has a card').toBeTruthy();
  });

  test('scan, pick two services with quantities, the amount follows', async ({ page, request }) => {
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await asOwner(page, request);                 // each test gets a fresh browser
    await page.goto('/dashboard/scan');
    await expect(page.getByRole('heading', { name: 'Enregistrer une visite' })).toBeVisible();

    await page.getByRole('button', { name: 'Saisir le code' }).click();
    await page.getByLabel('Code de la carte').fill(card);

    // the client answers for themselves
    await expect(page.getByText('Client scanné')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText('Client depuis le')).toBeVisible();   // « Carte de fidélité » is also the sidebar's

    // nothing picked → nothing owed
    await expect(page.getByPlaceholder('0,00')).toHaveValue('');

    // the catalogue drawer, with quantities
    await page.getByRole('button', { name: /Choisir un (service|produit)/ }).click();
    const drawer = page.getByRole('dialog');
    await expect(drawer).toBeVisible();
    await drawer.getByRole('button', { name: 'Plus Coupe femme' }).click();
    await drawer.getByRole('button', { name: 'Plus Brushing' }).click();
    await drawer.getByRole('button', { name: 'Plus Brushing' }).click();     // ×2
    await expect(drawer.getByRole('button', { name: /Ajouter 95,00/ })).toBeVisible();
    await drawer.getByRole('button', { name: /Ajouter 95,00/ }).click();

    // both lines are on the page at a glance, not hidden in a dropdown
    await expect(page.getByText('Coupe femme')).toBeVisible();
    await expect(page.getByText('Brushing')).toBeVisible();
    await expect(page.getByPlaceholder('0,00')).toHaveValue('95.00');

    // removing everything brings it back to nothing
    await page.getByRole('button', { name: 'Retirer Coupe femme' }).click();
    await expect(page.getByPlaceholder('0,00')).toHaveValue('50.00');
    expect(errors, `page errors: ${errors.join(' | ')}`).toEqual([]);
  });

  test('the visit is written with its lines and its amount', async ({ page, request }) => {
    await asOwner(page, request);
    await page.goto('/dashboard/scan');
    await page.getByRole('button', { name: 'Saisir le code' }).click();
    await page.getByLabel('Code de la carte').fill(card);
    await expect(page.getByText('Client scanné')).toBeVisible({ timeout: 10_000 });

    await page.getByRole('button', { name: /Choisir un (service|produit)/ }).click();
    const drawer2 = page.getByRole('dialog');
    await drawer2.getByRole('button', { name: 'Plus Coloration' }).click();
    await drawer2.getByRole('button', { name: /Ajouter 70,00/ }).click();

    const mine = async () => {
      const b = await (await request.get('/api/owner/clients/list?per_page=200', { headers: H })).json();
      return (b.rows || []).find((c) => c.barcode_id === card) || {};
    };
    const before = await mine();
    await page.getByRole('button', { name: 'Enregistrer la visite' }).click();
    await expect(page.getByText(/Visite enregistrée/)).toBeVisible({ timeout: 15_000 });

    // the server really counted it: one more visit, 70 € more spent
    const after = await mine();
    expect(after.visits).toBe((before.visits || 0) + 1);
    expect(Math.round((after.spent - (before.spent || 0)) * 100) / 100).toBe(70);
    // and the form is clean for the next client
    await expect(page.getByPlaceholder('0,00')).toHaveValue('');
  });
});
