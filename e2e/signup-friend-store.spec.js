// A friend's link never asks for a store, and the form never hides a refusal
// (user, 2026-10-14, ROYAL TRIM: « Corrigez les champs en rouge » with nothing
// red — the server wanted « Choisissez votre établissement », a field the page
// hides on a friend's link). The filleul joins the store of the card scanned.
//
// Runs against the local server only (scripts/dev_local.py). Never production.
import { test, expect } from '@playwright/test';

const SLUG = 'cafe-lumiere';

async function fill(page, name, tel) {
  await page.locator('#join-form input[type="text"]').first().fill(name);
  await page.locator('#join-phone').fill(tel);
  await page.locator('input[name="postal-code"]').fill('37000');
  await page.locator('input[name="bday"]').pressSequentially('19021992');
  await page.locator('#join-form input[type="checkbox"][required]').check();
  await page.getByRole('button', { name: /Rejoindre le programme/ }).click();
}

test("a friend's link: no store asked, the card is made", async ({ page, request }) => {
  const pub = await (await request.get(`/api/join/${SLUG}/page`)).json();
  test.skip((pub.stores || []).length < 2, 'a one-shop demo');
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  // a card number the server does not know (a card from before the stores is
  // the same case server-side): the main shop, nothing to choose
  await page.goto(`/join/${SLUG}?p=FT-NOSUCH99`);
  await expect(page.locator('#join-form')).toBeVisible();
  await expect(page.getByLabel('Votre établissement')).toHaveCount(0);
  await fill(page, 'Gabin Ami', `07${String(Date.now()).slice(-8)}`);
  await expect(page.getByTestId('join-errors')).toHaveCount(0);
  await expect(page.getByText('Félicitations', { exact: false }).first()).toBeVisible();
  expect(errors).toEqual([]);
});

test("a friend's real card: its store named in the form", async ({ page, request }) => {
  const pub = await (await request.get(`/api/join/${SLUG}/page`)).json();
  const stores = pub.stores || [];
  test.skip(stores.length < 2, 'a one-shop demo');
  const s2 = stores[1];
  const made = await (await request.post(`/api/join/${SLUG}`, { data: { name: 'Parrain Deux', phone: `06${String(Date.now()).slice(-8)}`,
    postal_code: '37000', birthday: '03/04/1992', consent: true, store: s2.slug } })).json();
  await page.goto(`/join/${SLUG}?p=${made.barcode_id}`);
  await expect(page.getByLabel('Votre établissement')).toHaveCount(0);
  await expect(page.locator('#join-form')).toContainText(s2.name);
});

test('every refusal is written above the button, not only « en rouge »', async ({ page }) => {
  await page.goto(`/join/${SLUG}?p=FT-NOSUCH99`);
  await page.locator('#join-form input[type="checkbox"][required]').check();
  await page.locator('#join-form').evaluate((f) => { f.noValidate = true; });
  await page.getByRole('button', { name: /Rejoindre le programme/ }).click();
  const box = page.getByTestId('join-errors');
  await expect(box).toBeVisible();
  await expect(box).toContainText('Indiquez votre nom.');
  await expect(box).toContainText('Code postal');
});
