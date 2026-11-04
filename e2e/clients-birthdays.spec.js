/**
 * Clients and Segmentation (user, 2026-11-04):
 *  1. « Anniversaires du mois » shows 30 → clicking it lists those 30, whatever
 *     was left in the search;
 *  2. a search does not come back when the owner leaves and returns;
 *  3. every filter changes the list, and a slow old answer never replaces a newer one;
 *  4. Segmentation has the same segment by default, with the same number.
 * Local server and demo data only.
 */
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
const SETTLE = { timeout: 30_000 };

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
  return { ...H, ...(store ? { 'X-FidClic-Store': store } : {}) };
}

// demo data has few birthdays this month: give two clients one, through the fiche
async function withBirthdays(request, SH) {
  const list = await (await request.get('/api/owner/clients/list?per_page=5', { headers: SH })).json();
  const mm = String(new Date(new Date().toLocaleString('en-US', { timeZone: 'Europe/Paris' })).getMonth() + 1).padStart(2, '0');
  for (const r of list.rows.slice(0, 2)) {
    const f = await (await request.get(`/api/owner/clients/${r.id}/fiche`, { headers: SH })).json();
    const put = await request.put(`/api/owner/clients/${r.id}/fiche`, { headers: SH, data: { name: f.name || r.name, birthday: `${mm}-15` } });
    expect(put.ok(), await put.text()).toBeTruthy();
  }
  const ov = await (await request.get('/api/owner/clients/overview', { headers: SH })).json();
  return ov.segments.find((s) => s.key === 'birthday').count;
}

const chip = (page) => page.getByRole('button', { name: /Anniversaires du mois/ }).first();
const box = (page) => page.getByPlaceholder('Rechercher un client (nom, email, téléphone…)');
const listTotal = (page) => page.getByTestId('clients-total');
// the old page stays on screen while the next one's file loads
const toCampaigns = async (page) => {
  await page.getByRole('link', { name: 'Campagnes' }).first().click();
  await expect(page).toHaveURL(/campaigns/);
  await expect(box(page)).toHaveCount(0, SETTLE);
};

test.use({ viewport: { width: 1536, height: 1000 } });

test('the number on the filter is the number of the list, whatever was searched', async ({ page, request }) => {
  const SH = await asOwner(page, request);
  const n = await withBirthdays(request, SH);
  expect(n).toBeGreaterThan(0);
  await page.goto('/dashboard/customers?q=birthdays&hl=birthdays');
  await expect(box(page)).toHaveValue('birthdays', SETTLE);
  await expect(listTotal(page)).toHaveText(/^0/, SETTLE);
  await chip(page).click();
  await expect(box(page)).toHaveValue('');
  await expect(listTotal(page)).toHaveText(new RegExp(`^${n}\\b`), SETTLE);
});

test('a search that finds nobody says so, and can be removed from there', async ({ page, request }) => {
  await asOwner(page, request);
  await page.goto('/dashboard/customers');
  await box(page).fill('Zzz Personne');
  const empty = page.getByTestId('clients-empty');
  await expect(empty).toContainText('« Zzz Personne »', SETTLE);
  await empty.getByRole('button', { name: 'Effacer la recherche' }).click();
  await expect(box(page)).toHaveValue('');
  await expect(page.getByTestId('clients-empty')).toHaveCount(0, SETTLE);
});

test('leaving and coming back: both search bars are empty', async ({ page, request }) => {
  await asOwner(page, request);
  await page.goto('/dashboard');
  const header = page.getByRole('textbox', { name: /recherche|search/i }).first();
  await header.fill('Zzz Personne');
  await header.press('Enter');
  await expect(page).toHaveURL(/\/dashboard\/customers/);
  await expect(box(page)).toHaveValue('Zzz Personne', SETTLE);
  await expect(header).toHaveValue('');                         // its text went to the page
  await expect(page).not.toHaveURL(/[?&]q=/);                   // and nothing stays in the address

  await toCampaigns(page);
  await page.goBack();
  await expect(page).toHaveURL(/\/dashboard\/customers/);
  await expect(box(page)).toHaveValue('', SETTLE);

  await box(page).fill('Marie');
  await toCampaigns(page);
  await page.getByRole('link', { name: 'Clients' }).first().click();
  await expect(box(page)).toHaveValue('', SETTLE);

  await header.fill('quelque chose');
  await toCampaigns(page);
  await expect(header).toHaveValue('');
});

test('a search emptied by hand does not come back when a filter changes the address', async ({ page, request }) => {
  await asOwner(page, request);
  await page.goto('/dashboard/customers?q=Zzz&segment=vip');
  await expect(box(page)).toHaveValue('Zzz', SETTLE);
  await box(page).fill('');
  await chip(page).click();
  await page.waitForTimeout(500);
  await expect(box(page)).toHaveValue('');
});

test('every filter changes the list', async ({ page, request }) => {
  await asOwner(page, request);
  await page.goto('/dashboard/customers');
  await expect(listTotal(page)).toHaveText(/^[1-9]/, SETTLE);
  const asked = (query) => page.waitForResponse((r) => r.url().includes('/clients/list') && r.url().includes(query) && r.status() === 200, SETTLE);

  for (const [label, key] of [['Dépenses', 'spend'], ["Date d'inscription", 'joined'], ['Source', 'source'], ['Carte', 'card']]) {
    const sel = page.locator('label').filter({ hasText: new RegExp(`^${label}`) }).locator('select').first();
    const values = await sel.locator('option').evaluateAll((o) => o.map((x) => x.value).filter(Boolean));
    const wait = asked(`${key}=${encodeURIComponent(values[0])}`);
    await sel.selectOption(values[0]);
    const data = await (await wait).json();
    await expect(listTotal(page)).toHaveText(new RegExp(`^${data.total}\\b`), SETTLE);
    await sel.selectOption('');
  }

  // Segment and Statut are the multi-choice boxes
  await page.getByRole('button', { name: 'Segment', exact: true }).click();
  const wait = asked('segment=loyal');
  await page.getByRole('group', { name: 'Choix — Segment' }).getByRole('checkbox', { name: 'Clients fidèles' }).check();
  const data = await (await wait).json();
  await expect(listTotal(page)).toHaveText(new RegExp(`^${data.total}\\b`), SETTLE);
});

test('a slow old answer never replaces the newer one', async ({ page, request }) => {
  await asOwner(page, request);
  let held = false;
  await page.route('**/api/owner/clients/list*', async (route) => {
    if (!held && route.request().url().includes('search=Zzz')) {
      held = true;
      await new Promise((r) => setTimeout(r, 2500));   // the old question answers last
    }
    await route.continue();
  });
  await page.goto('/dashboard/customers');
  await expect(listTotal(page)).toHaveText(/^[1-9]/, SETTLE);
  const all = await listTotal(page).textContent();
  await box(page).fill('Zzz');
  await page.waitForRequest((r) => r.url().includes('search=Zzz'));
  await box(page).fill('');
  await page.waitForTimeout(3500);
  await expect(listTotal(page)).toHaveText(all);
});

test('the list shows it is updating', async ({ page, request }) => {
  await asOwner(page, request);
  await page.goto('/dashboard/customers');
  await expect(listTotal(page)).toHaveText(/^[1-9]/, SETTLE);
  await page.route('**/api/owner/clients/list*', async (route) => {
    await new Promise((r) => setTimeout(r, 1200));
    await route.continue();
  });
  await box(page).fill('a');
  await expect(page.getByTestId('clients-updating')).toBeVisible(SETTLE);
  await expect(page.getByTestId('clients-updating')).toHaveCount(0, SETTLE);
});

test('Segmentation has « Anniversaires du mois » by default, with the same clients', async ({ page, request }) => {
  const SH = await asOwner(page, request);
  const n = await withBirthdays(request, SH);
  await page.goto('/dashboard/segmentation');
  const row = page.getByRole('row', { name: /Anniversaires du mois/ });
  await expect(row).toBeVisible(SETTLE);
  await expect(row).toContainText(`${n} `);
  await row.getByRole('button', { name: 'Voir' }).click();
  await expect(page.getByRole('heading', { name: 'Anniversaires du mois' })).toBeVisible(SETTLE);
  await expect(page.getByText('Anniversaire : ce mois-ci')).toBeVisible();
  await expect(page.getByText(new RegExp(`^${n} clients? — recomptés`))).toBeVisible();
});
