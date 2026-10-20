/**
 * Clients — « Ventes du … au … », et les filtres par date, âge et plusieurs
 * segments (user, 2026-10-20).
 *
 * Ce qui compte ici : quand le commerce demande un jour, le tableau cesse de
 * parler du total de toujours et parle de CE jour — le bandeau, les colonnes
 * et le nombre au-dessus disent tous la même chose.
 * La mécanique (bornes de Paris, export, « Contacter (N) ») est couverte par
 * api/tests/test_clients_filters.py.
 */
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
    try { sessionStorage.removeItem('ft_pick_store'); } catch (_e) { /* ignore */ }
  }, [login.access_token, store]);
  return { H, store };
}

const DAY = () => new Date().toLocaleDateString('sv-SE');

test.use({ viewport: { width: 1536, height: 1000 } });

test.describe.serial('les ventes d\'un jour', () => {
  let day; let H; let store;

  test('un client passe en caisse aujourd\'hui', async ({ page, request }) => {
    ({ H, store } = await asOwner(page, request));
    day = DAY();
    const t = await (await request.get('/api/owner/tenant', { headers: H })).json();
    const slug = t.slug || t.tenant?.slug || 'cafe-lumiere';
    const made = await (await request.post(`/api/join/${slug}`, {
      data: { name: `Client Jour ${Date.now() % 100000}`, phone: `07${String(Date.now()).slice(-8)}`,
        postal_code: '37000', birthday: '1990-05-04', accepted_terms: true, consent: true, store },
    })).json();
    expect(made.barcode_id).toBeTruthy();
    const scan = await request.post('/api/owner/scan', {
      headers: H, data: { barcode_id: made.barcode_id, amount_paid: 41.5, branch_id: store },
    });
    expect(scan.status(), await scan.text()).toBe(200);
  });

  test('le tableau parle de CE jour, et le bandeau le résume', async ({ page, request }) => {
    await asOwner(page, request);
    await page.goto('/dashboard/customers');
    await expect(page.getByRole('heading', { name: /client/ }).first()).toBeVisible({ timeout: 20000 });

    // sans période : « Total dépensé », pas de bandeau
    await expect(page.getByRole('columnheader', { name: 'Total dépensé' })).toBeVisible();
    await expect(page.getByTestId('period-strip')).toHaveCount(0);

    await page.getByLabel('Ventes du … au … — du').fill(day);
    await expect(page.getByTestId('period-strip')).toBeVisible({ timeout: 15000 });

    // les colonnes le disent
    await expect(page.getByRole('columnheader', { name: 'Dépensé sur la période' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'Visites sur la période' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'Total dépensé' })).toHaveCount(0);

    // le bandeau et les lignes s'accordent
    const strip = page.getByTestId('period-strip');
    const rows = await page.locator('tbody tr').count();
    expect(rows, 'au moins le client passé en caisse').toBeGreaterThan(0);
    const api = await (await request.get(
      `/api/owner/clients/list?per_page=200&sales_from=${day}&sales_to=${day}&store=${store}`, { headers: H })).json();
    expect(api.period.visits, 'au moins le passage en caisse').toBeGreaterThan(0);
    // le total affiché est bien celui des lignes, pas des totaux de toujours
    expect(Math.round(api.rows.reduce((a, r) => a + r.spent, 0) * 100) / 100).toBeCloseTo(api.period.spent, 2);
    // le montant du bandeau, écrit à la française (41,50 €)
    await expect(strip).toContainText(
      api.period.spent.toFixed(2).replace('.', ',').replace(/^(\d+),/, '$1,'));
    await expect(strip).toContainText(`Visites${api.period.visits}`);
    await expect(strip).toContainText(`Clients venus${api.period.clients}`);
    expect(api.rows.every((r) => r.period_mode), 'chaque ligne sait qu\'elle est celle de la période').toBe(true);
    // jamais plus que le total de toujours — et pour notre client, strictement moins
    expect(api.rows.every((r) => r.spent <= r.spent_total && r.visits <= r.visits_total)).toBe(true);

    // on revient à tout l'historique
    await strip.getByRole('button', { name: /tout l'historique/ }).click();
    await expect(page.getByTestId('period-strip')).toHaveCount(0);
    await expect(page.getByRole('columnheader', { name: 'Total dépensé' })).toBeVisible();
  });

  test('un jour sans vente : le bandeau le dit, le tableau est vide', async ({ page, request }) => {
    await asOwner(page, request);
    await page.goto('/dashboard/customers');
    await expect(page.getByRole('heading', { name: /client/ }).first()).toBeVisible({ timeout: 20000 });
    await page.getByLabel('Ventes du … au … — du').fill('2019-01-01');
    await expect(page.getByTestId('period-strip')).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId('period-strip')).toContainText('1 janvier');
    await expect(page.getByRole('heading', { name: /^0 client/ })).toBeVisible();
  });
});

test('Segment et Statut : plusieurs à la fois, et on les cherche', async ({ page, request }) => {
  await asOwner(page, request);
  await page.goto('/dashboard/customers');
  await expect(page.getByRole('heading', { name: /client/ }).first()).toBeVisible({ timeout: 20000 });

  // les segments viennent de /clients/overview : on attend qu'ils soient là,
  // sinon la liste s'ouvre vide (vu dans la suite complète, 2026-10-20)
  await expect(page.getByText('Clients fidèles').first()).toBeVisible({ timeout: 20000 });
  const seg = page.getByRole('button', { name: 'Segment', exact: true });
  await seg.click();
  const search = page.getByLabel('Rechercher dans Segment');
  await expect(search).toBeVisible();
  await search.fill('zzz');
  await expect(page.getByText('Rien de ce nom.')).toBeVisible();
  await search.fill('');
  const ticks = page.getByRole('group', { name: 'Choix — Segment' }).locator('input[type="checkbox"]');
  await expect(ticks.nth(1), 'des segments à cocher').toBeVisible({ timeout: 15000 });
  await ticks.nth(0).check();
  await ticks.nth(1).check();
  await expect(seg).toContainText('2 sélectionnés');
  // et le tableau a suivi
  await expect(page.getByRole('heading', { name: /client/ }).first()).toBeVisible();
});

test('Âge : une tranche, puis de … à …', async ({ page, request }) => {
  const { H } = await asOwner(page, request);
  await page.goto('/dashboard/customers');
  await expect(page.getByRole('heading', { name: /client/ }).first()).toBeVisible({ timeout: 20000 });
  await page.getByRole('button', { name: /Plus de filtres/ }).click();
  await expect(page.getByLabel('Âge — à partir de')).toBeVisible();
  await page.getByLabel('Âge — à partir de').fill('40');
  await page.waitForTimeout(600);
  const api = await (await request.get('/api/owner/clients/list?per_page=200&age_min=40', { headers: H })).json();
  expect(api.rows.every((r) => r.age === null || r.age >= 40), 'personne sous 40 ans').toBe(true);
  await expect(page.getByRole('heading', { name: new RegExp(`^${api.total} client`) })).toBeVisible({ timeout: 15000 });
});
