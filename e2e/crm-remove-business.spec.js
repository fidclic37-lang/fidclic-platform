/**
 * CRM › Prospects › « Supprimer du CRM » a FidClic business (user, 2026-11-15):
 * it leaves the CRM only — still in Super admin › Commerces, never re-added by
 * the CRM's sync. Local server only, on a business this test creates.
 */
import { test, expect } from '@playwright/test';
import { signIn } from './helpers/menuOnScreen.js';

const ADMIN = { email: 'admin@fidelitour.com', password: 'Fidelit0ur!Adm' };   // local seed only

test.use({ viewport: { width: 1536, height: 1000 } });

test('a FidClic business removed from the CRM stays a business', async ({ page, request }) => {
  test.setTimeout(150_000);
  const H = await signIn(page, request, ADMIN);
  const name = `CRM Retrait ${Date.now() % 100000}`;
  const made = await request.post('/api/admin/commerces', { headers: H, data: {
    name, sector: 'cafe', city: 'Tours', postal_code: '37000', owner_first_name: 'Test', owner_last_name: 'Owner',
    owner_email: `crmretrait${Date.now()}@example.test` } });
  expect(made.ok(), await made.text()).toBeTruthy();
  const { id: tid } = await made.json();

  await page.goto('/admin/crm/prospects');
  await page.getByPlaceholder(/Rechercher/).first().fill(name);
  const row = page.getByRole('row').filter({ hasText: name });
  await expect(row).toHaveCount(1, { timeout: 60_000 });
  page.once('dialog', async (d) => {
    expect(d.message()).toContain('Le commerce reste sur FidClic');
    await d.accept();
  });
  await row.getByRole('button', { name: 'Actions', exact: true }).click();
  await page.getByRole('menuitem', { name: 'Supprimer du CRM' }).click();
  await expect(page.getByRole('row').filter({ hasText: name })).toHaveCount(0, { timeout: 30_000 });

  // the CRM opens again (its sync runs): not back
  await page.reload();
  await page.getByPlaceholder(/Rechercher/).first().fill(name);
  await expect(page.getByText('0 prospect', { exact: false }).first()).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole('row').filter({ hasText: name })).toHaveCount(0);

  // still a business on FidClic
  const c = await request.get(`/api/admin/commerces/${tid}`, { headers: H });
  expect(c.ok()).toBeTruthy();
  const list = await (await request.get(`/api/admin/commerces?q=${encodeURIComponent(name)}`, { headers: H })).json();
  expect(list.rows.map((r) => r.id)).toContain(tid);
});
