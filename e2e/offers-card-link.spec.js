// QA F34 (2026-10-11): the owner opened a client's card from the dashboard
// (« Voir sa carte », ?vue=commerce), went to « Mes offres », pressed « Voir ma
// carte » — and ANOTHER card opened: the one this browser holds for the shop.
// The offers page dropped ?vue=commerce, so the card page took the owner's
// browser for a customer's phone and sent it to « its own » card.
//
// Runs against the local server only (scripts/dev_local.py — demo data in
// memory). Never point it at production.
import { test, expect } from '@playwright/test';

const SLUG = 'cafe-lumiere';
const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
const tel = (n) => `07${String(Date.now() + n).slice(-8)}`;

async function card(request, name, n) {
  const pub = await (await request.get(`/api/join/${SLUG}/page`)).json();
  const store = (pub.stores || [])[0]?.slug;
  const res = await request.post(`/api/join/${SLUG}`, { data: {
    name, phone: tel(n), postal_code: '37000', birthday: '03/04/1992', consent: true, ...(store ? { store } : {}) } });
  expect(res.ok(), await res.text()).toBeTruthy();
  return res.json();
}

test('the owner reviewing a client: « Mes offres » and back stays on THAT client', async ({ page, request }) => {
  const mine = await card(request, 'Owner Perso', 1);          // a card this browser holds for the shop
  const client = await card(request, 'Client Revue', 2);       // the client the owner looks at
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();

  await page.goto('/login');
  await page.evaluate(([t, bc, k]) => {
    localStorage.setItem('fidelitour_access_token', t);
    localStorage.setItem('fidclic:my_cards', JSON.stringify({ [bc]: k }));
  }, [login.access_token, mine.barcode_id, mine.card_key]);

  await page.goto(`/card/${client.barcode_id}?vue=commerce`);
  await expect(page.getByText('Client', { exact: false }).first()).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`/card/${client.barcode_id}`));

  await page.getByRole('link', { name: /Mes offres/ }).click();
  await expect(page).toHaveURL(new RegExp(`/card/${client.barcode_id}/offres\\?vue=commerce`));

  await page.getByRole('link', { name: 'Voir ma carte' }).click();
  await page.waitForLoadState('networkidle');
  await expect(page, 'still the client the owner opened').toHaveURL(new RegExp(`/card/${client.barcode_id}\\?vue=commerce`));
  await page.waitForTimeout(1000);                              // a redirect would have happened by now
  expect(page.url()).not.toContain(mine.barcode_id);

  // the back arrow too
  await page.getByRole('link', { name: /Mes offres/ }).click();
  await page.getByRole('link', { name: 'Retour à ma carte' }).click();
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(1000);
  expect(page.url()).toContain(`/card/${client.barcode_id}`);
  expect(page.url()).not.toContain(mine.barcode_id);

  // a customer's own phone is unchanged: scanning someone else's card of the
  // shop still opens the phone's own card (card QR ownership, #154)
  await page.evaluate(() => localStorage.removeItem('fidelitour_access_token'));
  await page.goto(`/card/${client.barcode_id}`);
  await expect(page).toHaveURL(new RegExp(`/card/${mine.barcode_id}`));
});
