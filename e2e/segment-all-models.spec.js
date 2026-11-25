/**
 * Segmentation › « Voir tous les modèles » (user, 2026-11-25): it opened the
 * « Créer un segment » builder — « nonsense, balki saare segments aane
 * chahiye, kyunki create a segment button already hai ». It now unfolds every
 * ready-made model (used or not, empty or not) in place, and folds back.
 * Local server and demo data only.
 */
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
const ALL = ['Clients inactifs', 'Clients fidèles', 'Nouveaux clients', 'Gros paniers', 'Clients locaux',
  'Anniversaires du mois', 'Palier VIP', 'Anciens fidèles', 'Inscrits sans achat', 'Habitués du mois',
  'Petits paniers'];

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

const models = (page) => page.getByTestId('segment-models');
const card = (page, name) => models(page).getByTestId('segment-model').filter({ has: page.getByText(name, { exact: true }) });

test.use({ viewport: { width: 1440, height: 900 } });

test('« Voir tous les modèles » shows every model — not the builder', async ({ page, request }) => {
  await asOwner(page, request);
  await page.goto('/dashboard/segmentation');
  await expect(models(page).getByTestId('segment-model').first()).toBeVisible();
  const before = await models(page).getByTestId('segment-model').count();
  expect(before).toBeLessThanOrEqual(5);

  await page.getByRole('button', { name: 'Voir tous les modèles' }).click();
  await expect(page.getByRole('dialog', { name: 'Créer un segment' })).toHaveCount(0);
  await expect(page.getByText('Définissez vos critères')).toHaveCount(0);
  for (const name of ALL) await expect(card(page, name)).toHaveCount(1);
  await expect(models(page).getByTestId('segment-model')).toHaveCount(ALL.length);
  // each says how many clients it holds
  for (const name of ALL) await expect(card(page, name)).toContainText(/\d+ client/);

  // and folds back to the recommended row
  await page.getByRole('button', { name: 'Voir moins' }).click();
  await expect(models(page).getByTestId('segment-model')).toHaveCount(before);
});

test('a model already used says so and opens its segment; the others can be used', async ({ page, request }) => {
  const H = await asOwner(page, request);
  // start clean: no saved segment from an earlier run
  const pg = await (await request.get('/api/owner/segmentation/page', { headers: H })).json();
  for (const m of pg.all_models.filter((x) => x.adopted)) {
    await request.delete(`/api/owner/segmentation/segments/${m.segment_id}`, { headers: H });
  }
  await page.goto('/dashboard/segmentation');
  await page.getByRole('button', { name: 'Voir tous les modèles' }).click();
  const target = card(page, 'Petits paniers');
  await target.getByRole('button', { name: 'Utiliser ce segment' }).click();
  await expect(page.getByText(/Segment « Petits paniers » créé/)).toBeVisible();
  // the list stays open, the card now says it is in use
  await expect(target).toContainText('Déjà dans vos segments');
  await expect(target.getByRole('button', { name: 'Utiliser ce segment' })).toHaveCount(0);
  await target.getByRole('button', { name: 'Voir le segment' }).click();
  await expect(page.getByRole('dialog', { name: 'Petits paniers' })).toBeVisible();
  // clean up
  const after = await (await request.get('/api/owner/segmentation/page', { headers: H })).json();
  const made = after.all_models.find((x) => x.key === 'petits_paniers');
  await request.delete(`/api/owner/segmentation/segments/${made.segment_id}`, { headers: H });
});

test('« Créer un segment » still opens the builder', async ({ page, request }) => {
  await asOwner(page, request);
  await page.goto('/dashboard/segmentation');
  await page.getByRole('button', { name: 'Créer un segment' }).first().click();
  await expect(page.getByRole('dialog', { name: 'Créer un segment' })).toBeVisible();
});
