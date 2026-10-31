/**
 * « Produits qui font revenir » in Analyses › Produits (user, 2026-10-31:
 * three columns by verdict, at the top of the tab). The engine's answer is
 * given here (its maths are api/tests/test_product_return.py); the block is
 * what is tested: the columns, the two views, the window, Pro vs Pro AI, the
 * pending state. Local server only.
 */
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
test.use({ viewport: { width: 1536, height: 960 } });

const P = (name, bucket, extra = {}) => ({ name, bucket, clients: 64, together: false, ...extra });
const FULL = {
  status: 'ready', level: 'full', view: 'first', refreshing: false, min_buyers: 30, can_edit: true,
  window_days: 21, window_source: 'rythme', usual_gap: 15, built_at: '2026-10-30T03:00:00+00:00',
  coverage: { total: 400, with_items: 288, pct: 72 },
  views: { first: {
    n: 380, base_rate: 0.5,
    products: [
      P('Coupe + Barbe', 'aimant', { together: true, back: 7, back_low: 6, back_high: 8, days_back: 19, ca90: 42.5, fiabilite: 'haute', ratio: 1.4 }),
      P('Coupe', 'aimant', { back: 6, back_low: 5, back_high: 7, days_back: 22, ca90: 38, fiabilite: 'moyenne', ratio: 1.2 }),
      P('Coupe enfant', 'neutre', { back: 5, back_low: 4, back_high: 7, days_back: 25, ca90: 30, fiabilite: 'moyenne', ratio: 1.0 }),
      P('Soin visage', 'one_shot', { back: 2, back_low: 1, back_high: 4, days_back: null, ca90: 12, fiabilite: 'faible', ratio: 0.6 }),
      P('Shampoing', 'everywhere', { back: 5 }),
      P('Gel', 'insufficient', { clients: 12, needed: 30 }),
    ],
    combos: [{ a: 'Coupe', b: 'Shampoing', effect: 'plus', n: 40, rate: 0.7 }],
  } },
};
const BUCKETS = {
  ...FULL, level: 'buckets',
  views: { first: { n: 380, products: FULL.views.first.products.map(({ name, bucket, clients, needed, together }) => ({ name, bucket, clients, needed, together })) } },
};

async function login(page, request) {
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const br = await (await request.get('/api/owner/branches', { headers: { Authorization: `Bearer ${login.access_token}` } })).json();
  const store = ((br && br.branches) || br || []).find((x) => x.status !== 'closed')?.id || '';
  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
    try { sessionStorage.removeItem('ft_pick_store'); } catch (_e) { /* ignore */ }
  }, [login.access_token, store]);
}

test('Pro AI: three columns, ranges, the two views, the window', async ({ page, request }) => {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await login(page, request);
  const asked = [];
  let put = null;
  await page.route('**/api/owner/analyses/produits-retour**', (route) => {
    const req = route.request();
    if (req.method() === 'PUT') {
      put = JSON.parse(req.postData() || '{}');
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ days: put.days, job_id: 'j1' }) });
    }
    const view = new URL(req.url()).searchParams.get('view') || 'first';
    asked.push(view);
    const body = view === 'all' ? { ...FULL, view: 'all', views: { all: { ...FULL.views.first, products: FULL.views.first.products.slice(2) } } } : FULL;
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
  await page.goto('/dashboard/analytics#produits');
  const block = page.getByTestId('product-return');
  await expect(block).toBeVisible({ timeout: 20_000 });
  await expect(block.getByRole('heading', { name: 'Produits qui font revenir' })).toBeVisible();
  await expect(block.getByTestId('pr-col-aimant')).toContainText('Aimant (2)');
  await expect(block.getByTestId('pr-col-neutre')).toContainText('Neutre (1)');
  await expect(block.getByTestId('pr-col-one_shot')).toContainText('One-shot (1)');
  const card = block.getByTestId('pr-card').filter({ hasText: 'Coupe + Barbe' });
  await expect(card).toContainText('7 sur 10 reviennent');
  await expect(card).toContainText('entre 6 et 8');
  await expect(card).toContainText('en 19 jours');
  await expect(card).toContainText('42,50 € sur 90 jours');
  await expect(card).toContainText('Fiabilité haute');
  await expect(card).toContainText('Toujours achetés ensemble');
  await expect(block).toContainText('Pas assez de données : Gel (12/30)');
  await expect(block).toContainText('Dans presque tous les paniers : Shampoing');
  await expect(block).toContainText('Ensemble, ils font revenir plus : Coupe + Shampoing');
  await expect(block).toContainText('Fenêtre : 21 jours (le rythme de votre commerce)');
  await expect(block).toContainText('Produits renseignés : 72 %');
  await block.screenshot({ path: 'test-results/product-return.png' });

  // the two views
  await block.getByRole('button', { name: 'Toutes les visites' }).click();
  await expect(block.getByTestId('pr-col-aimant')).toContainText('Aimant (0)');
  expect(asked).toContain('all');

  // the window
  await block.getByRole('button', { name: 'Modifier la fenêtre' }).click();
  await block.getByLabel('Jours').fill('30');
  await block.getByRole('button', { name: 'Recalculer' }).click();
  await expect.poll(() => put && put.days).toBe(30);
  expect(errors).toEqual([]);
});

test('Pro: the verdicts only, the details with Pro AI', async ({ page, request }) => {
  await login(page, request);
  await page.route('**/api/owner/analyses/produits-retour**', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(BUCKETS) }));
  await page.goto('/dashboard/analytics#produits');
  const block = page.getByTestId('product-return');
  await expect(block.getByTestId('pr-col-aimant')).toContainText('Coupe + Barbe', { timeout: 20_000 });
  await expect(block).not.toContainText('sur 10 reviennent');
  await expect(block.getByRole('button', { name: /Pro AI/ })).toBeVisible();
});

test('the first time: being computed, then the result', async ({ page, request }) => {
  await login(page, request);
  let n = 0;
  await page.route('**/api/owner/analyses/produits-retour**', (route) => {
    n += 1;
    const body = n === 1 ? { status: 'pending', level: 'full', view: 'first' } : FULL;
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
  await page.goto('/dashboard/analytics#produits');
  const block = page.getByTestId('product-return');
  await expect(block).toContainText('FidClic IA analyse vos produits', { timeout: 20_000 });
  await expect(block.getByTestId('pr-col-aimant')).toContainText('Aimant (2)', { timeout: 30_000 });
});

test('several establishments: one at a time', async ({ page, request }) => {
  await login(page, request);
  const gare = { ...FULL.views.first, products: [P('Barbe', 'aimant', { back: 8, back_low: 7, back_high: 9 })] };
  const body = { ...FULL, stores: [
    { store: 'b1', name: 'Centre', window_days: 21, window_source: 'rythme', coverage: { pct: 72 }, views: FULL.views },
    { store: 'b2', name: 'Gare', window_days: 21, window_source: 'rythme', coverage: { pct: 40 }, views: { first: gare } },
  ] };
  await page.route('**/api/owner/analyses/produits-retour**', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) }));
  await page.goto('/dashboard/analytics#produits');
  const block = page.getByTestId('product-return');
  await expect(block.getByTestId('pr-col-aimant')).toContainText('Aimant (2)', { timeout: 20_000 });
  await block.getByRole('button', { name: 'Gare' }).click();
  await expect(block.getByTestId('pr-col-aimant')).toContainText('Aimant (1)');
  await expect(block).toContainText('Produits renseignés : 40 %');
});

test('the real server: the block is there, whatever its state', async ({ page, request }) => {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await login(page, request);
  await page.goto('/dashboard/analytics#produits');
  await expect(page.getByTestId('product-return')).toBeVisible({ timeout: 20_000 });
  expect(errors).toEqual([]);
});

test('an account that may only see Analyses: no « Modifier »', async ({ page, request }) => {
  await login(page, request);
  await page.route('**/api/owner/analyses/produits-retour**', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...FULL, can_edit: false }) }));
  await page.goto('/dashboard/analytics#produits');
  const block = page.getByTestId('product-return');
  await expect(block).toContainText('Fenêtre : 21 jours', { timeout: 20_000 });
  await expect(block.getByRole('button', { name: 'Modifier la fenêtre' })).toHaveCount(0);
});
