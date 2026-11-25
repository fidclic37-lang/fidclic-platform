// « Donner mon avis » in Mon compte (2026-11-25): the page opens it for 14 days
// after the client's last visit, but GET /card/{bc} never sent that visit — so
// the section never showed. Nothing reshaped in the browser: a real signup,
// a real scan at the till, the card page reads the server's own answer.
// Local server only (scripts/dev_local.py — demo data in memory).
//   npx vite build && E2E_PORT=8811 npx playwright test e2e/card-review-real.spec.js
import { test, expect } from '@playwright/test';

const SLUG = 'cafe-lumiere';
const SHOTS = process.env.CARD_SHOT_DIR || '';
const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only

test('no visit → no « Donner mon avis »; after a scan → it shows and the review lands on that visit', async ({ page, request }) => {
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };

  const pub = await (await request.get(`/api/join/${SLUG}/page`)).json();
  const store = (pub.stores || [])[0]?.slug;
  const made = await (await request.post(`/api/join/${SLUG}`, { data: {
    name: 'Avis Testeuse', phone: `06${String(Date.now()).slice(-8)}`, postal_code: '37000', birthday: '05/06/1990',
    consent: true, ...(store ? { store } : {}) } })).json();
  expect(made.barcode_id, JSON.stringify(made).slice(0, 200)).toBeTruthy();
  const K = { 'X-Card-Key': made.card_key };
  const url = `/card/${made.barcode_id}?k=${made.card_key}&onglet=compte`;

  // 1. signed up, never scanned: the server says so, the page hides the section
  const before = await (await request.get(`/api/card/${made.barcode_id}`, { headers: K })).json();
  expect(before.customer.last_visit_date ?? null).toBeNull();
  await page.goto(url);
  await expect(page.getByText('Supprimer mes données personnelles').first()).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Donner mon avis' })).toHaveCount(0);
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/avis-1-sans-visite.png`, fullPage: true });

  // 2. one real scan at the till
  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const branches = Array.isArray(br) ? br : (br.branches || br.items || []);
  const branch_id = (branches.find((b) => b.slug === store) || branches[0] || {}).id;
  const scan = await request.post('/api/owner/scan', { headers: H, data: { barcode_id: made.barcode_id, amount_paid: 14, branch_id } });
  expect(scan.ok(), await scan.text()).toBeTruthy();

  const after = await (await request.get(`/api/card/${made.barcode_id}`, { headers: K })).json();
  expect(after.customer.last_visit_id, JSON.stringify(after.customer)).toBeTruthy();
  expect(after.customer.last_visit_date).toMatch(/Z$/);
  expect(Date.now() - Date.parse(after.customer.last_visit_date)).toBeLessThan(10 * 60_000);

  // 3. the page now opens « Donner mon avis »
  await page.goto(url);
  await expect(page.getByRole('heading', { name: 'Donner mon avis' })).toBeVisible();
  if (SHOTS) {
    await page.getByRole('heading', { name: 'Donner mon avis' }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${SHOTS}/avis-2-apres-visite.png` });
  }

  // 4. the review is sent with that visit — a second one for the same visit is refused
  const sent = page.waitForRequest((r) => r.url().endsWith('/api/public/reviews') && r.method() === 'POST');
  await page.getByLabel('Note sur 10').fill('9');
  await page.getByRole('button', { name: 'Envoyer mon avis' }).click();
  expect((await sent).postDataJSON().visit_id).toBe(after.customer.last_visit_id);
  await expect(page.getByText('Merci pour votre avis !')).toBeVisible();
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/avis-3-merci.png` });
  const again = await request.post('/api/public/reviews', { headers: K,
    data: { barcode_id: made.barcode_id, rating: 5, visit_id: after.customer.last_visit_id } });
  expect(again.status()).toBe(409);
});
