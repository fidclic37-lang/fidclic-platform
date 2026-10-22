// A second card is never made behind someone's back (user, 2026-10-22:
// « khud se card add n ho jaaye jab tak customer ne n kiya ho khud se »).
// Each establishment keeps its own card — that is the rule — but a person who
// already holds one somewhere in this account is asked first, by name.
//
// Runs against the local server only (scripts/dev_local.py). Never production.
import { test, expect } from '@playwright/test';

const SLUG = 'cafe-lumiere';
const phone = () => `06${String(Date.now()).slice(-8)}`;

async function fill(page, name, tel) {
  await page.locator('#join-form input[type="text"]').first().fill(name);
  await page.locator('#join-phone').fill(tel);
  await page.locator('input[name="postal-code"]').fill('37000');
  await page.locator('input[name="bday"]').pressSequentially('19021992');
  await page.locator('#join-form input[type="checkbox"][required]').check();
  await page.getByRole('button', { name: /Rejoindre le programme/ }).click();
}

test.describe('a card at another establishment is a question, not a surprise', () => {
  test('the page names both shops, and only a yes makes the second card', async ({ page, request }) => {
    const pub = await (await request.get(`/api/join/${SLUG}/page`)).json();
    const stores = pub.stores || [];
    test.skip(stores.length < 2, 'a one-shop demo');
    const [a, b] = stores;

    // a card at the first establishment
    const tel = phone();
    const first = await (await request.post(`/api/join/${SLUG}`, { data: {
      name: 'Moi Deuxcartes', phone: tel, postal_code: '37000', birthday: '19/02/1992',
      consent: true, store: a.slug } })).json();
    expect(first.barcode_id, 'the first card was made').toBeTruthy();

    // the same person, same phone, at the second one
    await page.goto(`/join/${SLUG}/${b.slug}`);
    await expect(page.locator('#join-form')).toBeVisible();
    await fill(page, 'Moi Deuxcartes', tel);

    const ask = page.getByTestId('other-store-card');
    await expect(ask).toBeVisible({ timeout: 15_000 });
    await expect(ask).toContainText(a.name);           // where their card already is
    await expect(ask).toContainText(b.name);           // what they would also get
    // not signed up yet: the page is still the form
    await expect(page.getByText('Félicitations', { exact: false })).toHaveCount(0);

    // « Non merci » puts the question away and makes nothing
    await ask.getByRole('button', { name: 'Non merci' }).click();
    await expect(page.getByTestId('other-store-card')).toHaveCount(0);
    await expect(page.getByText('Félicitations', { exact: false })).toHaveCount(0);

    // ask again, and say yes
    await page.getByRole('button', { name: /Rejoindre le programme/ }).click();
    await expect(page.getByTestId('other-store-card')).toBeVisible({ timeout: 15_000 });
    await page.getByRole('button', { name: new RegExp(`Oui, je veux aussi celle de`) }).click();
    await expect(page.getByText('Félicitations', { exact: false }).first()).toBeVisible({ timeout: 15_000 });

    // two cards now, with different numbers, and the first one untouched
    const shown = await page.locator('body').innerText();
    expect(shown.includes(first.barcode_id), 'the new card is not the old one').toBe(false);
    const still = await request.get(`/api/card/${first.barcode_id}?k=${first.card_key}`);
    expect(still.status(), 'the first card still answers').toBe(200);
  });

  test('someone with no card here is never asked', async ({ page, request }) => {
    const pub = await (await request.get(`/api/join/${SLUG}/page`)).json();
    const stores = pub.stores || [];
    test.skip(stores.length < 2, 'a one-shop demo');
    await page.goto(`/join/${SLUG}/${stores[1].slug}`);
    await fill(page, 'Tout Neuf', phone());
    await expect(page.getByText('Félicitations', { exact: false }).first()).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId('other-store-card')).toHaveCount(0);
  });
});
