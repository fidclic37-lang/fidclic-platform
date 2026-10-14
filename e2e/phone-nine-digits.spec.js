// France's phone on the sign-up forms (user, 2026-10-14: « country code hi 0 ka
// kaam krta, toh ye 0 ka compulsion htao and 9 digits ka niyam rkho »): next
// to « +33 » the field takes the 9 digits, a 0 typed in front is dropped, and
// the number is kept as « 06… » as before — for clients and for businesses.
// Runs against the local server only (scripts/dev_local.py — demo data in memory).
import { test, expect } from '@playwright/test';

const SLUG = 'cafe-lumiere';
const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only

test('a client signs up with the 9 digits after +33', async ({ page, request }) => {
  const nine = `6${String(Date.now()).slice(-8)}`;
  await page.goto(`/join/${SLUG}`);
  const form = page.locator('#join-form');
  await expect(form).toBeVisible();
  const tel = page.locator('#join-phone');

  await tel.fill(`0${nine}`);
  await expect(tel, 'the 0 typed in front is dropped: +33 is the 0').toHaveValue(nine);
  await tel.fill('');
  await tel.pressSequentially(`0${nine}`);
  await expect(tel, 'typed key by key too').toHaveValue(nine);
  await tel.fill(nine);

  const store = form.getByLabel('Votre établissement');
  if (await store.count()) await store.selectOption({ index: 1 });
  await form.locator('input[type="text"]').first().fill('Neuf Chiffres');
  await page.locator('input[name="postal-code"]').fill('37000');
  await page.locator('input[name="bday"]').pressSequentially('01021990');
  await form.locator('input[type="checkbox"][required]').check();
  await page.getByRole('button', { name: /Rejoindre le programme/ }).click();
  await expect(page.getByText('Félicitations', { exact: false }).first()).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText(/0 suivi de 9 chiffres/)).toHaveCount(0);

  // kept as before, with its 0: the same person as « 06 … » everywhere else
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const rows = (await (await request.get('/api/owner/clients/list?per_page=500', {
    headers: { Authorization: `Bearer ${login.access_token}`, 'X-FidClic-Store': 'all' } })).json()).rows || [];
  expect(rows.find((c) => c.name === 'Neuf Chiffres' && String(c.phone || '').replace(/\D/g, '') === `0${nine}`),
    'stored as 0 + the 9 digits').toBeTruthy();
});

test('too few digits: the 9-digit rule, without any 0', async ({ page }) => {
  await page.goto(`/join/${SLUG}`);
  const form = page.locator('#join-form');
  const store = form.getByLabel('Votre établissement');
  if (await store.count()) await store.selectOption({ index: 1 });
  await form.locator('input[type="text"]').first().fill('Trop Court');
  await page.locator('#join-phone').fill('61234');
  await page.locator('input[name="postal-code"]').fill('37000');
  await page.locator('input[name="bday"]').pressSequentially('01021990');
  await form.locator('input[type="checkbox"][required]').check();
  await page.getByRole('button', { name: /Rejoindre le programme/ }).click();
  await expect(page.getByText(/9 chiffres après \+33/).first()).toBeVisible();
});

test('the business sign-up takes the 9 digits too', async ({ page }) => {
  await page.goto('/register');
  const tel = page.locator('input[autocomplete="tel"]');
  await expect(tel).toHaveAttribute('placeholder', '6 12 34 56 78');
  await tel.fill('0612345678');
  await expect(tel).toHaveValue('612345678');
  await tel.fill('6123456789');
  await expect(tel, 'never more than 9').toHaveValue('612345678');
});
