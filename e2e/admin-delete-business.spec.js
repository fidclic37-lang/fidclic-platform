/**
 * Super admin › « Supprimer définitivement » a business (user, 2026-11-11):
 * the name typed to confirm, the business leaves « Tous » for « Supprimés »,
 * its page says so, and its owner can no longer sign in. Local server only —
 * on a business this test creates for itself.
 */
import { test, expect } from '@playwright/test';
import { signIn } from './helpers/menuOnScreen.js';

const ADMIN = { email: 'admin@fidelitour.com', password: 'Fidelit0ur!Adm' };   // local seed only
const SETTLE = { timeout: 60_000 };

test.use({ viewport: { width: 1536, height: 1000 } });

test('a business deleted by the super admin moves to « Supprimés », its owner is shut out', async ({ page, request }) => {
  // the admin list reads every business (≈5 s per load on the local mock database): room for three loads
  test.setTimeout(180_000);
  const H = await signIn(page, request, ADMIN);
  const name = `Boutique Test Suppr ${Date.now() % 100000}`;
  const made = await request.post('/api/admin/commerces', { headers: H, data: {
    name, sector: 'cafe', city: 'Tours', postal_code: '37000', owner_first_name: 'Test', owner_last_name: 'Owner',
    owner_email: `suppr${Date.now()}@example.test` } });
  expect(made.ok(), await made.text()).toBeTruthy();
  const { id: tid, owner } = await made.json();

  await page.goto(`/admin/commerces/${tid}`);
  await page.getByRole('button', { name: "Plus d'actions" }).click();
  await page.getByRole('button', { name: /Supprimer définitivement/ }).click();
  const go = page.getByRole('button', { name: 'Supprimer définitivement' });
  await page.getByPlaceholder(/commerce fermé/).fill('Compte de test e2e');
  await page.getByLabel('Nom du commerce').fill('pas le bon nom');
  await expect(go).toBeDisabled();
  await page.getByLabel('Nom du commerce').fill(name);
  await go.click();
  await expect(page.getByTestId('commerce-deleted')).toBeVisible(SETTLE);

  await page.goto('/admin/commerces');
  await page.getByPlaceholder(/Rechercher/).first().fill(name);
  await expect(page.getByText(name)).toHaveCount(0, SETTLE);
  await page.getByRole('button', { name: /^Supprimés/ }).click();
  await expect(page.getByText(name).first()).toBeVisible(SETTLE);

  // its owner is shut out
  const login = await request.post('/api/auth/login', { data: { email: owner.email, password: owner.password } });
  const tok = login.ok() ? (await login.json()).access_token : null;
  if (tok) {
    const me = await request.get('/api/auth/me', { headers: { Authorization: `Bearer ${tok}` } });
    expect([401, 403]).toContain(me.status());
  } else {
    expect([401, 403]).toContain(login.status());
  }
});
