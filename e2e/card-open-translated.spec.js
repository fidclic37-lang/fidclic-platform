// A card link that « ne s'ouvre pas » on one phone (user, 2026-11-26): Chrome on
// an iPhone loaded the page, ran the app, then never asked whose card it was —
// Safari on the same phone and a friend's phone opened it. That Chrome had the
// page in English (the FidClic translator: fidelitour:lang = en, its cache
// full). The card must open whatever language and cache the phone carries.
// Local server only (scripts/dev_local.py — demo data in memory).
import { test, expect } from '@playwright/test';

const SLUG = 'cafe-lumiere';

async function newCard(request) {
  const pub = await (await request.get(`/api/join/${SLUG}/page`)).json();
  const store = (pub.stores || [])[0]?.slug;
  const made = await (await request.post(`/api/join/${SLUG}`, { data: {
    name: 'Chrome Anglais', phone: `07${String(Date.now()).slice(-8)}`, postal_code: '37000', birthday: '05/06/1990',
    consent: true, ...(store ? { store } : {}) } })).json();
  expect(made.barcode_id, JSON.stringify(made).slice(0, 200)).toBeTruthy();
  return made;
}

// Google's translate endpoint answers like the real one: [[["EN","FR"], …]]
async function fakeGoogle(page) {
  await page.route('https://translate.googleapis.com/**', (route) => {
    const q = new URL(route.request().url()).searchParams.get('q') || '';
    route.fulfill({ contentType: 'application/json', body: JSON.stringify([[[`EN ${q}`, q]]]) });
  });
}

for (const cache of ['empty', 'full']) {
  test(`a card opens on a phone set to English (${cache} translation cache)`, async ({ page, request }) => {
    const made = await newCard(request);
    await fakeGoogle(page);
    await page.addInitScript((full) => {
      try {
        localStorage.setItem('fidelitour:lang', 'en');
        localStorage.setItem('fidclic:lang-chosen', '1');
        if (full) {
          const big = {};
          for (let i = 0; i < 4000; i += 1) big[`Texte numéro ${i}`] = { en: `Text number ${i}` };
          big['Chargement de votre carte…'] = { en: 'Loading your card…' };
          localStorage.setItem('fidelitour:translations', JSON.stringify(big));
        }
      } catch (_e) { /* storage blocked */ }
    }, cache === 'full');

    const whose = page.waitForRequest((r) => r.url().endsWith(`/api/card/${made.barcode_id}/whose`) && r.method() === 'POST',
      { timeout: 8000 });
    await page.goto(`/card/${made.barcode_id}?k=${made.card_key}`);
    await whose;                                              // the app asked whose card it is
    await expect(page.getByTestId('card-page')).toBeVisible({ timeout: 10000 });
    await expect(page.getByTestId('points-box')).toBeVisible();
  });
}
