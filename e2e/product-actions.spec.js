/**
 * « Produits qui font revenir » — the actions (PR3, user 2026-10-31): the
 * One-shot buyers who did not come back and the new clients are one click
 * from the composer (an offer on the Aimant product), the groupe témoin's
 * answer is on the product card, and the Insights, Tableau de bord and Fiche
 * client say it too. The engine's answers are given here (its maths and the
 * audiences are api/tests/test_product_actions.py); the screens are tested.
 * Local server only.
 */
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
test.use({ viewport: { width: 1536, height: 960 } });

const SOIN = 'aaaaaaaaaa';
const COUPE = 'bbbbbbbbbb';
const P = (name, bucket, extra = {}) => ({ name, bucket, clients: 64, together: false, ...extra });
const FULL = {
  status: 'ready', level: 'full', view: 'first', refreshing: false, min_buyers: 30, can_edit: true,
  window_days: 21, window_source: 'rythme', usual_gap: 15, built_at: '2026-10-30T03:00:00+00:00',
  coverage: { total: 400, with_items: 288, pct: 72 },
  actions: { aimant: { ref: COUPE, name: 'Coupe', back: 7 }, one_shot: [{ ref: SOIN, name: 'Soin visage', back: 2, lapsed: 12 }], new: 6 },
  views: { first: { n: 380, combos: [], products: [
    P('Coupe', 'aimant', { ref: COUPE, back: 7, back_low: 6, back_high: 8, days_back: 19, ca90: 42.5, fiabilite: 'haute',
      test: { ready: false, ready_on: '2026-11-07T12:00:00+00:00', enough: false } }),
    P('Gel', 'neutre', { ref: 'cccccccccc', back: 5, back_low: 4, back_high: 6 }),
    P('Soin visage', 'one_shot', { ref: SOIN, back: 2, back_low: 1, back_high: 3, fiabilite: 'moyenne',
      test: { ready: true, rate: 50, temoin_rate: 25, enough: false } }),
  ] } },
};
const TEMPLATE = (key) => ({
  key, kind: 'offre', start_step: 1, title: '⭐ Découvrez « Coupe »',
  message: 'Une offre sur « Coupe » vous attend à votre prochaine visite, sur présentation de votre carte.',
  segment: 'all', audience: { label: 'Ont pris « Soin visage », pas revenus', hint: 'FidClic IA · Produits', ids: ['x1', 'x2'] },
});

async function login(page, request) {
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
  return { H, store };
}

async function composerAsked(page) {
  const asked = [];
  await page.route('**/api/owner/insights/templates/**', (route) => {
    const key = decodeURIComponent(new URL(route.request().url()).pathname.split('/templates/')[1]);
    asked.push(key);
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(TEMPLATE(key)) });
  });
  return asked;
}

test('Analyses: one click from the One-shot buyers to the composer, the test on the card', async ({ page, request }) => {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await login(page, request);
  await page.route('**/api/owner/analyses/produits-retour**', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(FULL) }));
  const asked = await composerAsked(page);
  await page.goto('/dashboard/analytics#produits');
  const block = page.getByTestId('product-return');
  const soin = block.getByTestId('pr-card').filter({ hasText: 'Soin visage' });
  await expect(soin).toContainText('Test : 50 % revenus vs 25 % témoin (peu de clients)', { timeout: 20_000 });
  await expect(soin.getByTestId('pr-act')).toHaveText('Relancer ces 12 clients');
  const coupe = block.getByTestId('pr-card').filter({ hasText: 'Coupe' });
  await expect(coupe).toContainText('Test en cours : résultat le 7 nov.');
  await expect(coupe.getByTestId('pr-act')).toHaveText('Proposer aux 6 nouveaux clients');
  await expect(block.getByTestId('pr-card').filter({ hasText: 'Gel' }).getByTestId('pr-act')).toHaveCount(0);
  await block.screenshot({ path: 'test-results/product-actions.png' });

  await soin.getByTestId('pr-act').click();
  await expect.poll(() => asked[0]).toBe(`pr:os:${SOIN}`);
  await expect(page).toHaveURL(/\/dashboard\/campaigns/);
  expect(errors).toEqual([]);
});

test('Pro: no buttons, no test (the details are Pro AI)', async ({ page, request }) => {
  await login(page, request);
  const pro = { ...FULL, level: 'buckets', actions: undefined,
    views: { first: { n: 380, products: FULL.views.first.products.map(({ name, bucket, clients }) => ({ name, bucket, clients })) } } };
  await page.route('**/api/owner/analyses/produits-retour**', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(pro) }));
  await page.goto('/dashboard/analytics#produits');
  const block = page.getByTestId('product-return');
  await expect(block.getByTestId('pr-col-one_shot')).toContainText('Soin visage', { timeout: 20_000 });
  await expect(block.getByTestId('pr-act')).toHaveCount(0);
  await expect(block.getByTestId('pr-test')).toHaveCount(0);
});

test('Tableau de bord: the best Aimant and the worst One-shot', async ({ page, request }) => {
  await login(page, request);
  await page.route('**/api/owner/home/overview**', async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    body.product_return = { aimant: { name: 'Coupe', back: 7 }, one_shot: { name: 'Soin visage', back: 2 } };
    return route.fulfill({ response: res, body: JSON.stringify(body) });
  });
  await page.goto('/dashboard');
  const card = page.getByTestId('home-product-return');
  await expect(card).toContainText('Aimant · Coupe — 7 sur 10 reviennent', { timeout: 20_000 });
  await expect(card).toContainText('One-shot · Soin visage — 2 sur 10 reviennent');
  await card.click();
  await expect(page).toHaveURL(/\/dashboard\/analytics#produits/);
});

test('Insights: the One-shot card opens the composer on its clients', async ({ page, request }) => {
  await login(page, request);
  const card = {
    key: 'produit_one_shot', category: { key: 'fidelisation', label: 'Fidélisation' },
    title: '« Soin visage » ne fait pas revenir',
    body: '12 clients ont pris « Soin visage » et ne sont pas revenus. Proposez-leur « Coupe » : 7 sur 10 de ses acheteurs reviennent, contre 2 sur 10. Dernier test : 50 % revenus contre 25 % pour le groupe témoin.',
    image: 'fidelite', icon: 'repeat', impact: { label: 'Non chiffré', kind: 'conseil', euros: null, basis: 'Conseil' },
    difficulty: { label: 'Facile', tone: 'green', filled: 3 },
    cta: { label: 'Relancer ces 12 clients', kind: 'template', template: `pr:os:${SOIN}` }, done: false,
  };
  await page.route('**/api/owner/insights/page**', async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    body.opportunities.shown = [card, ...(body.opportunities.shown || [])].slice(0, 3);
    body.opportunities.all = [card, ...(body.opportunities.all || [])];
    return route.fulfill({ response: res, body: JSON.stringify(body) });
  });
  const asked = await composerAsked(page);
  await page.goto('/dashboard/insights');
  await expect(page.getByText('« Soin visage » ne fait pas revenir').first()).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText(/Dernier test : 50 % revenus/).first()).toBeVisible();
  await page.getByRole('button', { name: 'Relancer ces 12 clients' }).first().click();
  await expect.poll(() => asked[0]).toBe(`pr:os:${SOIN}`);
});

test('Fiche client: the kind of each product, the Aimant to propose, Contacter', async ({ page, request }) => {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await login(page, request);
  const stamp = String(Date.now()).slice(-6);
  const pub = await (await request.get('/api/join/cafe-lumiere/page')).json();
  const made = await (await request.post('/api/join/cafe-lumiere', { data: {
    name: `Fiche Produits ${stamp}`, phone: `07${String(Date.now()).slice(-8)}`, postal_code: '37000', birthday: '01/02/1990', consent: true,
    ...((pub.stores || []).length ? { store: pub.stores[0].slug } : {}) } })).json();
  await page.route('**/api/owner/clients/*/profil', async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    const id = body.client?.id;
    body.produits = { tags: [{ name: 'Soin visage', bucket: 'one_shot', label: 'One-shot' }],
                      suggest: { name: 'Coupe', back: 7, template: `prc:${id}` } };
    return route.fulfill({ response: res, body: JSON.stringify(body) });
  });
  const asked = await composerAsked(page);
  await page.goto('/dashboard/customers');
  const name = `Fiche Produits ${stamp}`;
  await page.getByPlaceholder('Rechercher un client (nom, email, téléphone…)').fill(name);
  await page.getByRole('button', { name, exact: true }).click();
  const panel = page.getByRole('dialog', { name: 'Profil client' });
  await expect(panel.getByTestId('profile-products')).toContainText('Soin visage (One-shot)', { timeout: 10_000 });
  await expect(panel.getByTestId('profile-product-suggest')).toContainText('Coupe');
  await expect(panel.getByTestId('profile-product-suggest')).toContainText('7 clients sur 10 reviennent');
  await panel.getByTestId('profile-product-cta').click();
  await expect.poll(() => asked[0]).toMatch(/^prc:/);
  expect(asked[0]).not.toBe('prc:undefined');
  expect(made && (made.id || made.customer_id || made.barcode_id)).toBeTruthy();
  expect(errors).toEqual([]);
});
