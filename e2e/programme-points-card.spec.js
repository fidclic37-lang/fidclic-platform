// QA R7 F28 (2026-10-18): a « Points par euro dépensé » card (2 pts / €, a
// dessert at 100 points) told its customer « Encore 9 visites » and
// « +10 pts par visite ». The card now speaks the programme the shop set.
// The card's answer is reshaped in the browser — the demo store's own
// programme is left alone for the other specs.
// Runs against the local server only (scripts/dev_local.py — demo data in memory).
import { test, expect } from '@playwright/test';

const SLUG = 'cafe-lumiere';

test.use({ viewport: { width: 430, height: 932 } });

test('a points-per-euro card counts in points, not visits', async ({ page, request }) => {
  const pub = await (await request.get(`/api/join/${SLUG}/page`)).json();
  const slug = (pub.stores || [])[0]?.slug;
  const made = await (await request.post(`/api/join/${SLUG}`, { data: {
    name: 'Points Euro', phone: `07${String(Date.now()).slice(-8)}`, postal_code: '37000', birthday: '03/04/1992',
    consent: true, ...(slug ? { store: slug } : {}) } })).json();
  expect(made.barcode_id, JSON.stringify(made).slice(0, 200)).toBeTruthy();

  await page.route(`**/api/card/${made.barcode_id}**`, async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    body.card = { ...body.card, programme: 'points_euro', programme_kind: 'points_euro', points_mode: 'per_euro',
      points_per_euro: 2, reward_points: 100, reward_description: 'Un dessert offert', show_points: true };
    body.customer = { ...body.customer, points: 25, visits: 1 };
    await route.fulfill({ response: res, json: body });
  });
  await page.goto(`/card/${made.barcode_id}?k=${made.card_key}`);
  const pass = page.getByTestId('wallet-pass-preview');
  await expect(pass).toContainText('Encore 75 points · Un dessert offert');
  await expect(pass).not.toContainText(/visites?\b.*dessert/);

  await page.getByText('Le programme').first().click();
  await expect(page.getByTestId('programme-earning')).toContainText('2 pts par euro dépensé');
  await expect(page.getByTestId('programme-progress')).toContainText('Débloquée dès 100 points — 25 / 100');
  await expect(page.getByText('Points par visite')).toHaveCount(0);
  await expect(page.getByText(/après 10 visites/)).toHaveCount(0);
});
