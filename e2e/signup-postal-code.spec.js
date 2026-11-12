/**
 * Signup › « Code postal » (user, 2026-11-12): « 37000 le rha, lekin 37001,
 * 37002… nhi le rha… pin code pure France ka accept krna chahiye ». Every
 * French postal code is taken — CEDEX codes too — and a code that is not
 * French is still refused. Local server and demo data only.
 */
import { test, expect } from '@playwright/test';

const SLUG = 'cafe-lumiere';

async function fill(page, code) {
  await page.route('**/api/wallet/config**', (r) => r.fulfill({ contentType: 'application/json', body: '{"apple":true,"google":true}' }));
  await page.route('**/wallet-prepare**', (r) => r.fulfill({ contentType: 'application/json', body: '{"apple":true,"google_url":null}' }));
  await page.goto(`/join/${SLUG}`);
  await expect(page.getByLabel('Nom complet')).toBeVisible();
  const store = page.getByLabel('Votre établissement');
  if (await store.count()) await store.selectOption({ index: 1 });
  await page.getByLabel('Nom complet').fill('Code Postal Test');
  await page.locator('#join-phone').fill(`07${String(Date.now()).slice(-8)}`);
  await page.getByLabel('Code postal').fill(code);
  await page.getByLabel(/Date de naissance/).fill('03041992');
  await page.locator('#join-form input[type="checkbox"]').check();
  await page.getByRole('button', { name: /Rejoindre/ }).click();
}

for (const code of ['37001', '37002', '37010', '75008']) {
  test(`${code} is taken: the card is made`, async ({ page }) => {
    await fill(page, code);
    await expect(page.getByText('Félicitations !')).toBeVisible({ timeout: 20_000 });
  });
}

test('a code that is not French is still refused', async ({ page }) => {
  await fill(page, '99999');
  await expect(page.getByText(/Code postal inconnu en France/).first()).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText('Félicitations !')).toHaveCount(0);
});
