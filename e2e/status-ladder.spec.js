/**
 * Statut ladder (user, 2026-11-25): an owner's « 45 jours » rule never
 * reached anybody — Bientôt perdu and Dormant were asked first. On Règles
 * clients the time line and the frequency are two ladders now: a step says
 * only where it starts, the page shows where it ends, how many clients it
 * holds, and who moves before it is saved. The « Statut des clients » donut
 * (Tableau de bord, Analyses) is the Statut column; a slice opens its clients.
 * Local server and demo data only.
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
    localStorage.clear();
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
    try { sessionStorage.removeItem('ft_pick_store'); } catch (_e) { /* ignore */ }
  }, [login.access_token, store]);
  return H;
}

const payload = (rules) => ({
  rules: rules.map((r) => ({ id: r.id, key: r.key || null, name: r.name, icon: r.icon, tone: r.tone,
    description: r.description || '', enabled: !!r.enabled, conditions: r.conditions })),
});

let saved = null;
let headers = null;
test.beforeEach(async ({ request }) => {
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  headers = { Authorization: `Bearer ${login.access_token}` };
  saved = (await (await request.get('/api/owner/customer-rules', { headers })).json()).rules;
  // start from the shop's rules without any owner step
  await request.put('/api/owner/customer-rules', { headers, data: payload(saved.filter((r) => r.key || r.group === 'custom')) });
});
test.afterEach(async ({ request }) => {
  await request.put('/api/owner/customer-rules', { headers, data: payload(saved) });
});

test.use({ viewport: { width: 1440, height: 900 } });

const row = (page, name) => page.getByRole('row').filter({ has: page.getByText(name, { exact: true }) });

test('the two ladders show where each step starts and ends', async ({ page, request }) => {
  await asOwner(page, request);
  await page.goto('/dashboard/parametres/regles-clients');
  await expect(page.getByText("1 · D'abord : depuis quand n'est-il pas venu ?")).toBeVisible();
  await expect(page.getByText('2 · Puis : à quelle fréquence vient-il ?')).toBeVisible();
  await expect(row(page, 'Client actif')).toContainText('0 – 30 jours');
  await expect(row(page, 'Client bientôt perdu')).toContainText('31 – 89 jours');
  await expect(row(page, 'Client dormant')).toContainText('90 jours et plus');
  await expect(row(page, 'Client très actif')).toContainText('8 visites / mois et plus');
  // each says how many clients it holds
  await expect(row(page, 'Client actif')).toContainText(/\d+ client/);
  // drag and drop is gone: the order IS the ladder
  await expect(page.getByRole('button', { name: /^Déplacer/ })).toHaveCount(0);
});

test('a step « à partir de 45 jours » gets its clients — and Bientôt perdu now ends at 44', async ({ page, request }) => {
  await asOwner(page, request);
  await page.goto('/dashboard/parametres/regles-clients');
  await page.getByRole('button', { name: 'Ajouter une étape au temps' }).click();
  const dlg = page.getByRole('dialog', { name: 'Nouvelle étape' });
  await expect(dlg).toBeVisible();
  await dlg.getByLabel("Nom de l'étape").fill('À relancer');
  const start = dlg.getByLabel('À partir de');
  await start.fill('45');
  await expect(dlg.getByTestId('step-range')).toHaveText('Cette étape ira de 45 à 89 jours.');
  // the impact is said before saving
  await expect(dlg.getByTestId('step-impact')).toHaveText(/Aucun client ne change de statut\.|passe|passent|changent/);
  await dlg.getByRole('button', { name: "Ajouter l'étape" }).click();
  await expect(dlg).toHaveCount(0);
  await expect(row(page, 'À relancer')).toContainText('45 – 89 jours');
  await expect(row(page, 'Client bientôt perdu')).toContainText('31 – 44 jours');
  // and the server agrees
  const rules = (await (await request.get('/api/owner/customer-rules', { headers })).json()).rules;
  const step = rules.find((r) => r.name === 'À relancer');
  expect(step.group).toBe('absence');
  expect(step.range).toEqual({ from: 45, to: 89 });
});

test('a step on the same day as another is refused, with the reason, and nothing is added', async ({ page, request }) => {
  await asOwner(page, request);
  await page.goto('/dashboard/parametres/regles-clients');
  await page.getByRole('button', { name: 'Ajouter une étape au temps' }).click();
  const dlg = page.getByRole('dialog', { name: 'Nouvelle étape' });
  await dlg.getByLabel("Nom de l'étape").fill('Doublon');
  await dlg.getByLabel('À partir de').fill('31');
  await expect(dlg.getByTestId('step-impact')).toContainText('Client bientôt perdu');
  await expect(dlg.getByRole('button', { name: "Ajouter l'étape" })).toBeDisabled();
  await dlg.getByRole('button', { name: 'Annuler' }).click();
  await expect(row(page, 'Doublon')).toHaveCount(0);
});

test('a frequency step sits between Fidèle and Très actif', async ({ page, request }) => {
  await asOwner(page, request);
  await page.goto('/dashboard/parametres/regles-clients');
  await page.getByRole('button', { name: 'Ajouter une étape à la fréquence' }).click();
  const dlg = page.getByRole('dialog', { name: 'Nouvelle étape' });
  await dlg.getByLabel("Nom de l'étape").fill('Habitué');
  await expect(dlg.getByLabel('À partir de')).toHaveValue('6');
  await dlg.getByRole('button', { name: "Ajouter l'étape" }).click();
  await expect(row(page, 'Habitué')).toContainText('6 visites / mois et plus');
  const names = await page.getByTestId('rule-name').allTextContents();
  expect(names.indexOf('Habitué')).toBe(names.indexOf('Client fidèle') + 1);
  expect(names.indexOf('Client très actif')).toBe(names.indexOf('Habitué') + 1);
});

for (const where of [{ name: 'Tableau de bord', path: '/dashboard', api: '/api/owner/home/overview' },
  { name: 'Analyses', path: '/dashboard/analytics', api: '/api/owner/analyses' }]) {
  test(`${where.name}: « Statut des clients » slices are the statuses and open their clients`, async ({ page, request }) => {
    await asOwner(page, request);
    const answer = page.waitForResponse((r) => r.url().includes(where.api) && r.status() === 200);
    await page.goto(where.path);
    const body = await (await answer).json();
    const mix = (body.data || body).status_mix;
    expect(mix.total).toBeGreaterThan(0);
    const statusKeys = (await (await request.get('/api/owner/clients/overview', { headers })).json()).statuses.map((s) => s.key);
    for (const s of mix.slices) expect(statusKeys).toContain(s.key);
    // every status keeps its own colour — Bientôt perdu (orange) had no dot
    for (const s of mix.slices) {
      const dot = page.getByRole('button', { name: new RegExp(`^${s.label}`) }).first().locator('span').first();
      expect(await dot.evaluate((el) => getComputedStyle(el).backgroundColor), s.label).not.toMatch(/rgba\(0, 0, 0, 0\)|transparent/);
    }
    const first = mix.slices[0];
    const list = page.waitForResponse((r) => r.url().includes('/api/owner/clients/list') && r.url().includes(`status=${first.key}`));
    await page.getByRole('button', { name: new RegExp(`^${first.label}`) }).first().click();
    await expect(page).toHaveURL(new RegExp(`/dashboard/customers\\?statut=${first.key}`));
    const got = await (await list).json();
    expect(got.total).toBe(first.count);
  });
}
