/**
 * CRM › Prospects › « Activité sur les réseaux » (user, 2026-11-15): set in the
 * form next to the links, shown on the prospect, and a filter classifies the
 * list. Local server only, on prospects this test creates.
 */
import { test, expect } from '@playwright/test';
import { signIn } from './helpers/menuOnScreen.js';

const ADMIN = { email: 'admin@fidelitour.com', password: 'Fidelit0ur!Adm' };   // local seed only

test.use({ viewport: { width: 1536, height: 1000 } });

test('set a level in the form, see it, filter the list by it', async ({ page, request }) => {
  test.setTimeout(150_000);
  const H = await signIn(page, request, ADMIN);
  const tag = `Soc${Date.now() % 100000}`;
  for (const [n, act] of [['Actif', 'tres_actif'], ['Dormant', 'inactif']]) {
    const r = await request.post('/api/crm/prospects', { headers: H, data: { name: `${tag} ${n}`, city: 'Tours', social_activity: act } });
    expect(r.ok(), await r.text()).toBeTruthy();
  }

  await page.goto('/admin/crm/prospects');
  // the form: the four levels, next to the links
  await page.getByRole('button', { name: /Ajouter un prospect/ }).click();
  const level = page.locator('select').filter({ has: page.locator('option', { hasText: 'Moyennement actif' }) }).last();
  await expect(level.locator('option')).toHaveText(['— Non renseigné', 'Très actif', 'Moyennement actif', 'Peu actif', 'Inactif']);
  await page.getByLabel('Nom du commerce *').fill(`${tag} Form`);
  await level.selectOption('peu_actif');
  await page.getByRole('button', { name: 'Enregistrer' }).last().click();
  await expect.poll(async () => {
    const l = await (await request.get(`/api/crm/prospects?q=${tag} Form`, { headers: H })).json();
    return l.rows[0]?.social_activity_label;
  }, { timeout: 30_000 }).toBe('Peu actif');

  // the filter classifies
  await page.goto('/admin/crm/prospects');
  await page.getByPlaceholder(/Rechercher/).first().fill(tag);
  await expect(page.getByRole('row').filter({ hasText: tag })).toHaveCount(3, { timeout: 60_000 });
  const filter = page.locator('select').filter({ has: page.locator('option', { hasText: 'Toute activité réseaux' }) });
  await filter.selectOption('tres_actif');
  await expect(page.getByRole('row').filter({ hasText: tag })).toHaveCount(1, { timeout: 30_000 });
  await expect(page.getByRole('row').filter({ hasText: `${tag} Actif` })).toHaveCount(1);
  await filter.selectOption('inactif');
  await expect(page.getByRole('row').filter({ hasText: `${tag} Dormant` })).toHaveCount(1, { timeout: 30_000 });
  await expect(page.getByRole('row').filter({ hasText: tag })).toHaveCount(1);

  // shown on the prospect
  await page.getByRole('row').filter({ hasText: `${tag} Dormant` }).click();
  await expect(page.getByTestId('social-activity')).toHaveText('Inactif', { timeout: 30_000 });
});
