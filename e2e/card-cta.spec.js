/**
 * The card page's 3rd home tile (user, 2026-11-25): « Prendre rendez-vous » by
 * default, its name and link set ONLY by the FidClic super admin, per
 * établissement, in Super admin › Commerces › <business> › Paramètres ›
 * « Bouton de la carte client ». A shop without bookings types any name.
 *
 *   · two stores of the demo chain get two different buttons; each store's
 *     card shows its own
 *   · the owner's login is refused on the admin route
 *   · the home at 390 px: a black card with a gold photo, the button set,
 *     the networks partly set (screenshot when CARD_SHOT_DIR is set)
 *
 * Local server and demo data only (Boulangerie Saint-Michel, tenant-2).
 *   npx vite build && E2E_PORT=8811 npx playwright test e2e/card-cta.spec.js
 */
import { test, expect } from '@playwright/test';

const ADMIN = { email: 'admin@fidelitour.com', password: 'Fidelit0ur!Adm' };   // local seed only
const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
const CHAIN = { id: 'tenant-2', slug: 'boulangerie-saint-michel' };
const SHOTS = process.env.CARD_SHOT_DIR || '';
const SETTLE = { timeout: 60_000 };
test.setTimeout(240_000);

const bearer = async (request, who) => {
  const login = await (await request.post('/api/auth/login', { data: who })).json();
  expect(login.access_token, JSON.stringify(login).slice(0, 200)).toBeTruthy();
  return { token: login.access_token, H: { Authorization: `Bearer ${login.access_token}` } };
};

async function joinStore(request, slug, store, name) {
  const made = await (await request.post(`/api/join/${slug}`, { data: {
    name, phone: `07${String(Date.now()).slice(-8)}`, postal_code: '37000', birthday: '03/04/1992',
    consent: true, ...(store ? { store } : {}) } })).json();
  expect(made.barcode_id, JSON.stringify(made).slice(0, 200)).toBeTruthy();
  return made;
}

test('two stores, two buttons — each store\'s card shows its own; only the super admin writes them', async ({ page, request, browser }) => {
  const { H: A } = await bearer(request, ADMIN);
  const list = await (await request.get(`/api/admin/commerces/${CHAIN.id}/card-cta`, { headers: A })).json();
  expect(list.stores.length).toBeGreaterThanOrEqual(2);
  const [s1, s2] = list.stores;
  const put = (sid, body) => request.put(`/api/admin/commerces/${CHAIN.id}/card-cta/${encodeURIComponent(sid)}`, { headers: A, data: body });
  expect((await put(s1.id, { label: 'Prendre rendez-vous', url: 'https://www.planity.com/saint-michel-centre' })).status()).toBe(200);
  expect((await put(s2.id, { label: 'Commander', url: 'https://www.ubereats.com/fr/store/saint-michel' })).status()).toBe(200);
  expect((await put(s2.id, { label: 'Commander', url: 'javascript:alert(1)' })).status(), 'a javascript: link is refused').toBe(400);

  // the owner cannot write it (nor read the admin list) — in a context of its
  // own: a login's cookie would stand in for the admin's header afterwards
  const ownerCtx = await browser.newContext();
  const { H: O } = await bearer(ownerCtx.request, OWNER);
  expect([401, 403]).toContain((await ownerCtx.request.put(`/api/admin/commerces/${CHAIN.id}/card-cta/${s1.id}`, { headers: O, data: { label: 'Hacked' } })).status());
  expect([401, 403]).toContain((await ownerCtx.request.get(`/api/admin/commerces/${CHAIN.id}/card-cta`, { headers: O })).status());
  await ownerCtx.close();

  // one card in each store
  const pub = await (await request.get(`/api/join/${CHAIN.slug}/page`)).json();
  const slugOf = (sid) => (pub.stores || []).find((s) => s.id === sid)?.slug;
  const c1 = await joinStore(request, CHAIN.slug, slugOf(s1.id), 'Client Centre');
  const c2 = await joinStore(request, CHAIN.slug, slugOf(s2.id), 'Client Second');
  const ctaOf = async (c) => (await (await request.get(`/api/card/${c.barcode_id}`, { headers: { 'X-Card-Key': c.card_key } })).json()).card.cta;
  expect(await ctaOf(c1)).toEqual({ label: 'Prendre rendez-vous', url: 'https://www.planity.com/saint-michel-centre' });
  expect(await ctaOf(c2)).toEqual({ label: 'Commander', url: 'https://www.ubereats.com/fr/store/saint-michel' });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/card/${c2.barcode_id}?k=${c2.card_key}`);
  const tile = page.getByTestId('card-cta');
  await expect(tile).toHaveText(/Commander/, SETTLE);
  await expect(tile).toHaveAttribute('href', 'https://www.ubereats.com/fr/store/saint-michel');
  await expect(tile).toHaveAttribute('target', '_blank');
  await page.goto(`/card/${c1.barcode_id}?k=${c1.card_key}`);
  await expect(page.getByTestId('card-cta')).toHaveAttribute('href', 'https://www.planity.com/saint-michel-centre', SETTLE);

  // back to the default for the other specs
  expect((await put(s1.id, { label: 'Prendre rendez-vous', url: '' })).status()).toBe(200);
  expect((await put(s2.id, { label: 'Prendre rendez-vous', url: '' })).status()).toBe(200);
  expect(await ctaOf(c2)).toEqual({ label: 'Prendre rendez-vous', url: null });
});

test('Super admin › Paramètres › « Bouton de la carte client »: each store, name + link, Enregistrer', async ({ page, request }) => {
  const { token, H: A } = await bearer(request, ADMIN);
  const list = await (await request.get(`/api/admin/commerces/${CHAIN.id}/card-cta`, { headers: A })).json();
  const second = list.stores[1];
  await page.setViewportSize({ width: 1536, height: 1000 });
  await page.goto('/login');
  await page.evaluate((t) => localStorage.setItem('fidelitour_access_token', t), token);
  await page.goto(`/admin/commerces/${CHAIN.id}`);
  await page.getByRole('button', { name: 'Paramètres', exact: true }).click(SETTLE);
  const sec = page.getByTestId('card-cta-section');
  await expect(sec.getByRole('heading', { name: 'Bouton de la carte client' })).toBeVisible(SETTLE);
  await expect(sec.locator('[data-store]')).toHaveCount(list.stores.length);
  const row = sec.locator(`[data-store="${second.id}"]`);
  await expect(row).toContainText(second.name);
  const label = row.getByLabel('Nom du bouton');
  const link = row.getByLabel('Lien');
  await expect(label).toHaveValue('Prendre rendez-vous');
  // a bad link: the server's words, nothing saved
  await label.fill('Voir le menu');
  await link.fill('http://menu.example.fr');
  await row.getByRole('button', { name: 'Enregistrer' }).click();
  await expect(row.getByRole('alert')).toContainText('https://');
  // a good one
  await link.fill('https://menu.example.fr/saint-michel');
  await row.getByRole('button', { name: 'Enregistrer' }).click();
  await expect(row.getByRole('status')).toHaveText('Enregistré', SETTLE);
  const again = await (await request.get(`/api/admin/commerces/${CHAIN.id}/card-cta`, { headers: A })).json();
  expect(again.stores.find((s) => s.id === second.id)).toMatchObject({ label: 'Voir le menu', url: 'https://menu.example.fr/saint-michel', is_set: true });
  await sec.scrollIntoViewIfNeeded();
  if (SHOTS) await sec.screenshot({ path: `${SHOTS}/admin-card-cta-section.png` });
  // a 390 px window too (the super admin on a phone)
  await page.setViewportSize({ width: 390, height: 844 });
  await sec.scrollIntoViewIfNeeded();
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/admin-card-cta-section-390.png`, fullPage: false });
  await request.put(`/api/admin/commerces/${CHAIN.id}/card-cta/${second.id}`, { headers: A, data: { label: 'Prendre rendez-vous', url: '' } });
});

test('the home at 390 px: black card, gold photo, the button set, networks partly set', async ({ page, request }) => {
  const made = await joinStore(request, 'cafe-lumiere', ((await (await request.get('/api/join/cafe-lumiere/page')).json()).stores || [])[0]?.slug, 'Camille Noire');
  const bc = made.barcode_id;
  const gold = '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600" viewBox="0 0 800 600">'
    + '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#E9C46A"/><stop offset="1" stop-color="#A67C2E"/></linearGradient></defs>'
    + '<rect width="800" height="600" fill="url(#g)"/><circle cx="560" cy="250" r="150" fill="#F6E2A8" opacity=".7"/></svg>';
  await page.route('**/e2e-assets/gold.svg', (r) => r.fulfill({ contentType: 'image/svg+xml', body: gold }));
  await page.route((u) => u.pathname === `/api/card/${bc}`, async (route) => {
    if (route.request().method() !== 'GET') return route.fallback();
    const res = await route.fetch();
    const body = await res.json();
    body.card = { ...body.card, programme: 'stamps', programme_kind: 'stamps', reward_threshold: 10, reward_description: 'Un café offert',
      card_bg_color: '#111111', brand_color: null, primary_color: null, accent_color: '#C9A04A',
      hero_photo_url: '/e2e-assets/gold.svg', tagline: 'Torréfacteur depuis 1998',
      socials: [{ network: 'instagram', url: 'https://www.instagram.com/cafelumiere' }, { network: 'tiktok', url: 'https://www.tiktok.com/@cafelumiere' }],
      cta: { label: 'Prendre rendez-vous', url: 'https://www.planity.com/cafe-lumiere' } };
    body.customer = { ...body.customer, first_name: 'Camille', cycle_visits: 6, visits: 6 };
    await route.fulfill({ response: res, json: body });
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/card/${bc}?k=${made.card_key}`);
  await expect(page.getByRole('heading', { name: 'Bonjour, Camille !' })).toBeVisible(SETTLE);
  await expect(page.getByTestId('card-cta')).toHaveAttribute('href', 'https://www.planity.com/cafe-lumiere');
  await expect(page.getByTestId('follow-us').getByRole('link')).toHaveCount(3);       // Nous rejoindre + 2 networks
  await expect(page.getByTestId('follow-us').getByRole('button')).toHaveCount(2);     // Facebook, Snapchat
  await page.waitForTimeout(600);                                                      // the photo's colours
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
  if (SHOTS) {
    await page.screenshot({ path: `${SHOTS}/card-home-black-gold-390-top.png` });
    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
    await page.screenshot({ path: `${SHOTS}/card-home-black-gold-390-bottom.png` });
  }
});
