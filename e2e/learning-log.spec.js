/**
 * Learning log (user, 2026-11-02): the Copilote's 👍 / 👎 with a reason, the
 * composer sending the IA draft's id with what the owner sends, and Super
 * admin › FIDCLIC AI › Apprentissage. The capture, scrub, statuses and
 * outcomes are api/tests/test_learning_log.py. Local server only.
 */
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
const ADMIN = { email: 'admin@fidelitour.com', password: 'Fidelit0ur!Adm' };        // local seed only
test.use({ viewport: { width: 1536, height: 960 } });

async function owner(page, request) {
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

test('Copilote: 👎 with a reason and a note reaches the learning log', async ({ page, request }) => {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await owner(page, request);
  await page.route('**/api/owner/copilot/chat', (route) => {
    if (route.request().method() !== 'POST') return route.continue();
    return route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ id: 'ex123', can_vote: true, reply: 'Vos clients du mardi reviennent tous les 18 jours.', actions: [], sources: [], source: 'model' }) });
  });
  const votes = [];
  await page.route('**/api/owner/ai/feedback', (route) => { votes.push(route.request().postDataJSON()); return route.fulfill({ status: 200, body: '{"ok":true}' }); });
  await page.goto('/dashboard/ai-assistant');
  const box = page.getByPlaceholder('Posez votre question...');
  await box.fill('Qui revient le plus ?');
  await box.press('Enter');
  await expect(page.getByText('Vos clients du mardi reviennent tous les 18 jours.')).toBeVisible({ timeout: 20_000 });
  await page.getByTestId('vote-down').last().click();
  const why = page.getByTestId('vote-why');
  await why.getByRole('button', { name: 'Chiffre faux' }).click();
  await why.getByLabel('Détail').fill('Plutôt 25 jours');
  await why.getByTestId('vote-send').click();
  await expect.poll(() => votes.length).toBe(2);
  expect(votes[1]).toEqual({ id: 'ex123', vote: 'down', reason: 'faux_chiffre', text: 'Plutôt 25 jours' });
  await page.getByTestId('vote-up').last().click();
  await expect.poll(() => votes.at(-1)?.vote).toBe('up');
  await expect(page.getByText('Merci, FidClic IA en tient compte.')).toBeVisible();
  expect(errors).toEqual([]);
});

test('Composer: what is sent carries the IA draft it started from', async ({ page, request }) => {
  await owner(page, request);
  await page.route('**/api/owner/insights/templates/**', (route) => route.fulfill({ status: 200, contentType: 'application/json',
    body: JSON.stringify({ key: 'ia:en_retard', kind: 'offre', start_step: 2, title: 'On vous attend', message: 'Revenez cette semaine !',
      segment: 'all', ai_example_id: 'tpl42' }) }));
  const sent = [];
  await page.route('**/api/owner/campaigns/compose', (route) => { sent.push(route.request().postDataJSON());
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: 'k1', status: 'draft', audience: 0 }) }); });
  await page.goto('/dashboard/campaigns?template=ia:en_retard&from=insights');
  await page.getByRole('button', { name: 'Enregistrer en brouillon' }).click({ timeout: 20_000 });
  await expect.poll(() => sent.length).toBeGreaterThan(0);
  expect(sent[0].ai_example_id).toBe('tpl42');
});

test('Super admin › Apprentissage: figures, surfaces, export', async ({ page, request }) => {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const login = await (await request.post('/api/auth/login', { data: ADMIN })).json();
  await page.goto('/login');
  await page.evaluate((t) => localStorage.setItem('fidelitour_access_token', t), login.access_token);
  await page.goto('/admin/ai/apprentissage');
  await expect(page.getByRole('heading', { name: 'Apprentissage de FidClic IA' })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole('link', { name: 'Apprentissage' })).toBeVisible();
  await expect(page.getByTestId('learn-good')).toContainText('objectif 10');
  await expect(page.getByTestId('learn-surfaces')).toBeVisible();
  const dl = page.waitForEvent('download');
  await page.getByTestId('learn-export').click();
  expect((await dl).suggestedFilename()).toMatch(/\.jsonl$/);
  expect(errors).toEqual([]);
});
