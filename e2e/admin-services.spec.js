/**
 * Super admin › a business's services, one by one (user, 2026-11-11). The
 * admin switches a service off on the business's page; its owner reads
 * « désactivé par FidClic » there; « Tout couper » closes the till and the
 * signup page too; « Tout rétablir » brings everything back.
 * Local server and the demo shop only.
 */
import { test, expect } from '@playwright/test';
import { OWNER, signIn } from './helpers/menuOnScreen.js';

const ADMIN = { email: 'admin@fidelitour.com', password: 'Fidelit0ur!Adm' };   // local seed only
const SETTLE = { timeout: 30_000 };

test.use({ viewport: { width: 1536, height: 1000 } });

test('a service switched off by the super admin is off for the owner, and back on', async ({ page, browser, request }) => {
  const H = await signIn(page, request, OWNER);
  const tenant = await (await request.get('/api/owner/tenant', { headers: H })).json();
  const tid = tenant.id || tenant.tenant_id;
  const slug = tenant.slug;

  // the super admin, in another window
  const admin = await (await browser.newContext({ viewport: { width: 1536, height: 1000 } })).newPage();
  await signIn(admin, request, ADMIN);
  await admin.goto(`/admin/commerces/${tid}`);
  await admin.getByRole('button', { name: 'Services' }).click();
  const camp = admin.getByRole('switch', { name: 'Campagnes' });
  await expect(camp).toHaveAttribute('aria-checked', 'true', SETTLE);
  await camp.click();
  await expect(camp).toHaveAttribute('aria-checked', 'false', SETTLE);

  // the owner: Campagnes says it, no upgrade offer
  await page.goto('/dashboard/campaigns');
  const pick = page.getByText('Choisissez votre établissement');
  const box = page.getByTestId('service-disabled');
  await expect(pick.or(box).first()).toBeVisible(SETTLE);
  if (await pick.isVisible()) await page.getByText(/Main$/).last().click();
  await expect(box).toBeVisible(SETTLE);
  await expect(box).toContainText('désactivé par FidClic');
  await expect(box.getByRole('button', { name: /Contacter le support/ })).toBeVisible();
  await expect(page.getByText(/Passer à|offre supérieure/)).toHaveCount(0);
  // another page still works
  await page.goto('/dashboard/automations');
  await expect(page.getByRole('button', { name: "Plus d'actions" }).first()).toBeVisible(SETTLE);

  // Tout couper: the till and the signup page close too
  admin.once('dialog', (d) => d.accept());
  await admin.getByRole('button', { name: 'Tout couper' }).click();
  await expect(admin.getByText('Tous les services sont coupés')).toBeVisible(SETTLE);
  await page.goto('/dashboard/scan');
  await expect(page.getByTestId('service-disabled')).toContainText('Cartes de fidélité', SETTLE);
  const visitor = await (await browser.newContext()).newPage();
  await visitor.goto(`/join/${slug}`);
  await expect(visitor.getByTestId('signups-closed')).toBeVisible(SETTLE);

  // Tout rétablir
  await admin.getByRole('button', { name: 'Tout rétablir' }).click();
  await expect(admin.getByRole('switch', { name: 'Campagnes' })).toHaveAttribute('aria-checked', 'true', SETTLE);
  await page.goto('/dashboard/campaigns');
  await expect(page.getByRole('button', { name: "Plus d'actions" }).first()).toBeVisible(SETTLE);
  await visitor.goto(`/join/${slug}`);
  await expect(visitor.getByTestId('signups-closed')).toHaveCount(0, SETTLE);
});
