/**
 * The business types its own interval (user, 2026-11-04: « ek baar unko gaya,
 * toh fir next us fixed days k interval k baad hi jaaye »). Géolocalisation up
 * to a year (was 90 days), Relance from 1 day (was 7), Personnalisée any number
 * (was a fixed list). Local server only.
 */
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only

async function setup(page, request) {
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
  return { ...H, ...(store ? { 'X-FidClic-Store': store } : {}) };
}

const MSG = { title: 'Bonjour', body: 'Un message' };
const AUD = { mode: 'all', pick: 'all', passants: 'all', filters: {} };

async function draft(request, SH, scenario, trigger, schedule = {}) {
  const r = await request.post('/api/owner/automations', { headers: SH, data: {
    scenario, name: `E2E ${scenario} ${Date.now()}`, status: 'draft', trigger, message: MSG, targeting: AUD,
    schedule: { days: 'all', window: false, holidays: true, tz: 'Europe/Paris', hour: '10:00', ...schedule } } });
  expect(r.ok(), await r.text()).toBeTruthy();
  return (await r.json()).id;
}

const saved = async (request, SH, id) => {
  const { rows } = await (await request.get('/api/owner/automations', { headers: SH })).json();
  return rows.find((r) => r.id === id);
};

// the draft's save is on the last step, Résumé
async function saveFromSummary(page) {
  await page.getByRole('button', { name: /Résumé/ }).first().click();
  await page.getByRole('button', { name: /Enregistrer en brouillon/ }).first().click();
}

test.describe('the interval is the business own number', () => {
  test.use({ viewport: { width: 1536, height: 960 } });

  test('Géolocalisation: 120 days stays 120, the lock screen is explained', async ({ page, request }) => {
    const SH = await setup(page, request);
    const id = await draft(request, SH, 'geo', { cooldown_days: 7, weather: [], stores: [] });
    await page.goto(`/dashboard/automations/${id}?step=5`);
    const x = page.getByLabel('Délai entre deux messages');
    await x.fill('120');
    await x.blur();
    await expect(x).toHaveValue('120');
    await expect(page.getByTestId('geo-interval-note')).toContainText('écran verrouillé');
    await page.getByRole('button', { name: /Enregistrer en brouillon/ }).first().click();
    await expect.poll(async () => (await saved(request, SH, id)).trigger.cooldown_days, { timeout: 15_000 }).toBe(120);
  });

  test('Relance: every 3 days stays 3', async ({ page, request }) => {
    const SH = await setup(page, request);
    const id = await draft(request, SH, 'inactive', { days: 30, repeat: 'every', every_days: 30 });
    await page.goto(`/dashboard/automations/${id}?step=2`);
    const x = page.getByLabel('Relancer tous les');
    await x.fill('3');
    await x.blur();
    await expect(x).toHaveValue('3');
    await page.getByRole('button', { name: "Plus d'actions" }).click();
    await page.getByRole('menuitem', { name: /Enregistrer en brouillon/ }).click();
    await expect.poll(async () => (await saved(request, SH, id)).trigger.every_days, { timeout: 15_000 }).toBe(3);
  });

  test('Personnalisée: any number of days, typed', async ({ page, request }) => {
    const SH = await setup(page, request);
    const id = await draft(request, SH, 'custom', { type: 'action', action: 'visit', repeat: 'every', delay_value: 0, delay_unit: 'hours' },
      { dedupe: true, min_gap_days: 7 });
    await page.goto(`/dashboard/automations/${id}`);
    await page.getByRole('navigation', { name: 'Étapes' }).getByRole('button', { name: /Planification/ }).click();
    await page.getByRole('tab', { name: /Règles d'envoi/ }).click();
    const x = page.getByLabel('Intervalle entre deux envois');
    await x.fill('13');
    await saveFromSummary(page);
    await expect.poll(async () => Number((await saved(request, SH, id)).schedule.min_gap_days), { timeout: 15_000 }).toBe(13);
  });

  test('Établissement no longer shows a second interval: it points to the automation', async ({ page, request }) => {
    await setup(page, request);
    await page.goto('/dashboard/parametres/etablissement');
    await expect(page.getByTestId('geo-interval-link')).toContainText('Automatisations › Géolocalisation', { timeout: 15_000 });
    await expect(page.getByText('Délai avant un nouveau rappel')).toHaveCount(0);
  });
});
