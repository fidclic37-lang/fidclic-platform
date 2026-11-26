// The card page must open, or say so and offer a way out — never sit on a
// blank or loading screen (user, 2026-11-26: Chrome on one iPhone loaded the
// card link and stopped before asking whose card it was; Safari opened it).
//   • the « whose card » question never answered → the owner's link opens the
//     card anyway after a few seconds;
//   • the app never starts → the page reloads itself once;
//   • it still never starts → a plain screen with « Réessayer » and
//     « Ouvrir sans traduction » (and the Safari hint).
// Local server only (scripts/dev_local.py — demo data in memory).
import { test, expect } from '@playwright/test';

const SLUG = 'cafe-lumiere';

async function newCard(request) {
  const pub = await (await request.get(`/api/join/${SLUG}/page`)).json();
  const store = (pub.stores || [])[0]?.slug;
  const made = await (await request.post(`/api/join/${SLUG}`, { data: {
    name: 'Carte Robuste', phone: `06${String(Date.now()).slice(-8)}`, postal_code: '37000', birthday: '07/08/1993',
    consent: true, ...(store ? { store } : {}) } })).json();
  expect(made.barcode_id, JSON.stringify(made).slice(0, 200)).toBeTruthy();
  return made;
}

test('the « whose card » answer never comes: the owner link still opens the card', async ({ page, request }) => {
  test.setTimeout(60_000);
  const made = await newCard(request);
  await page.route((u) => u.pathname === `/api/card/${made.barcode_id}/whose`, () => { /* never answered */ });
  await page.goto(`/card/${made.barcode_id}?k=${made.card_key}`);
  await expect(page.getByTestId('card-page')).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId('points-box')).toBeVisible();
});

test('the app does not start the first time: the page reloads itself once and opens', async ({ page, request }) => {
  test.setTimeout(60_000);
  const made = await newCard(request);
  let blocked = 0;
  await page.route(/\/assets\/index-[^/]+\.js$/, (route) => {
    if (blocked === 0) { blocked += 1; return route.abort(); }
    return route.continue();
  });
  await page.goto(`/card/${made.barcode_id}?k=${made.card_key}`);
  await expect(page.getByTestId('card-page')).toBeVisible({ timeout: 30_000 });
  expect(blocked).toBe(1);
  await expect(page).not.toHaveURL(/[?&]_r=/);              // the retry mark leaves the address bar
});

test('the app never starts: a plain screen offers « Réessayer » and « Ouvrir sans traduction »', async ({ page, request }) => {
  test.setTimeout(60_000);
  const made = await newCard(request);
  await page.route(/\/assets\/index-[^/]+\.js$/, (route) => route.abort());
  // the phone's own language, set once (an init script runs again on every load)
  await page.addInitScript(() => {
    try {
      if (sessionStorage.getItem('e2e:seeded')) return;
      sessionStorage.setItem('e2e:seeded', '1');
      localStorage.setItem('fidelitour:lang', 'en');
      localStorage.setItem('fidclic:lang-chosen', '1');
    } catch (_e) { /* storage blocked */ }
  });
  await page.goto(`/card/${made.barcode_id}?k=${made.card_key}`);
  const box = page.getByTestId('card-stuck');
  await expect(box).toBeVisible({ timeout: 40_000 });
  await expect(box).toContainText('Safari');
  await expect(box.getByRole('button', { name: 'Réessayer' })).toBeVisible();
  const plain = box.getByRole('button', { name: 'Ouvrir sans traduction' });
  await expect(plain).toBeVisible();
  // « sans traduction » forgets the language this phone kept, then reloads
  await page.unroute(/\/assets\/index-[^/]+\.js$/);
  await plain.click();
  await expect(page.getByTestId('card-page')).toBeVisible({ timeout: 20_000 });
  // the app may write its own default back (i18next caches fr); English is gone
  expect(await page.evaluate(() => localStorage.getItem('fidelitour:lang'))).not.toBe('en');
  expect(await page.evaluate(() => localStorage.getItem('fidclic:lang-chosen'))).toBeNull();
});
