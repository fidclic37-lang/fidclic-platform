/**
 * Getting a card back (/carte/recuperer/<token>, the shop's QR or e-mail) —
 * user, 2026-11-26: after « Récupérer ma carte » the client landed on the card
 * home, which has no Wallet button any more. As before: the « Ajouter à Apple
 * Wallet / Google Wallet » screen of THAT card (components/WalletButtons, as on
 * the signup's « Félicitations » and the add page of #521), with its owner key,
 * and a link to open the card page under it.
 *
 * The local server has no Apple / Google keys: /api/wallet/config is answered
 * here. Local server and demo data only.
 *   npx vite build && E2E_PORT=8811 npx playwright test e2e/card-readd-wallet.spec.js
 */
import { test, expect } from '@playwright/test';

const SLUG = 'cafe-lumiere';
const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
const phone = () => `06${String(Math.floor(Math.random() * 1e8)).padStart(8, '0')}`;

async function readdLink(request, name) {
  const pub = await (await request.get(`/api/join/${SLUG}/page`)).json();
  const store = (pub.stores || [])[0]?.slug;
  const made = await (await request.post(`/api/join/${SLUG}`, { data: {
    name, phone: phone(), postal_code: '37000', birthday: '03/04/1992', consent: true, ...(store ? { store } : {}) } })).json();
  expect(made.barcode_id, JSON.stringify(made).slice(0, 200)).toBeTruthy();
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const auth = { Authorization: `Bearer ${login.access_token}` };
  const list = await (await request.get(`/api/owner/clients/list?search=${made.barcode_id}`, { headers: auth })).json();
  const id = (list.rows || []).find((r) => r.barcode_id === made.barcode_id)?.id;
  expect(id, 'the shop finds its client').toBeTruthy();
  const link = await (await request.post(`/api/owner/clients/${id}/card/readd`, { headers: auth, data: { channel: 'qr' } })).json();
  return { bc: made.barcode_id, path: new URL(link.url).pathname };
}

test('QR / readd link → « Récupérer ma carte » → the Wallet add screen of THAT card', async ({ browser, request }) => {
  const { bc, path } = await readdLink(request, 'Inès Readd');
  const ctx = await browser.newContext();                      // the client's phone, fresh: no card on it
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const asked = [];
  page.on('request', (r) => { const u = new URL(r.url()); if (u.pathname.startsWith('/api/')) asked.push(`${r.method()} ${u.pathname}${u.search}`); });
  await page.route('**/api/wallet/config**', (r) => r.fulfill({ json: { apple: true, google: true } }));
  await page.route('**/wallet-prepare**', (r) => r.fulfill({ json: { apple: true, google_url: null } }));

  await page.goto(path);
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Récupérez votre carte');
  await page.getByRole('button', { name: 'Récupérer ma carte' }).click();

  // the add screen, on the same page — not the card home
  await expect(page.getByTestId('readd-wallet')).toBeVisible();
  await expect(page).toHaveURL(new RegExp('/carte/recuperer/'));
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Votre carte est de retour');
  const apple = page.getByRole('link', { name: /Ajouter à Apple Wallet/ });
  await expect(apple).toBeVisible();
  await expect(page.getByRole('button', { name: /Ajouter à Google Wallet/ })).toBeVisible();
  // THAT card's pass, with its owner key (Safari could not add it without)
  const href = await apple.getAttribute('href');
  expect(href).toMatch(new RegExp(`^/api/card/${bc}/apple-wallet\\.pkpass\\?k=.+`));
  // the phone now holds the card with its key (lib/myCards)
  const mine = await page.evaluate(() => window.localStorage.getItem('fidclic:my_cards') || '');
  expect(mine, 'the card is this phone\'s now').toContain(bc);
  // the Wallets are got ready for THAT card
  expect(asked.some((a) => a.startsWith(`POST /api/card/${bc}/wallet-prepare`))).toBe(true);

  // under it: open the card page (with the key, the gate keeps it on the phone)
  const open = page.getByRole('link', { name: /Ouvrir ma carte/ });
  await expect(open).toHaveAttribute('href', new RegExp(`^/card/${bc}\\?k=`));
  await open.click();
  await expect(page).toHaveURL(new RegExp(`/card/${bc}$`));
  await expect(page.getByTestId('card-page')).toBeVisible();
  expect(errors).toEqual([]);

  // the link is spent: a second phone gets the refusal, never the card
  const other = await browser.newContext();
  const p2 = await other.newPage();
  await p2.goto(path);
  await expect(p2.locator('body')).toContainText('déjà été utilisé');
  await expect(p2.getByTestId('readd-wallet')).toHaveCount(0);
  await other.close();
  await ctx.close();
});

test('the add screen survives a reload on the phone that took the card back', async ({ browser, request }) => {
  const { bc, path } = await readdLink(request, 'Noé Reload');
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  await page.route('**/api/wallet/config**', (r) => r.fulfill({ json: { apple: true, google: true } }));
  await page.route('**/wallet-prepare**', (r) => r.fulfill({ json: { apple: true, google_url: null } }));
  await page.goto(path);
  await page.getByRole('button', { name: 'Récupérer ma carte' }).click();
  await expect(page.getByTestId('readd-wallet')).toBeVisible();
  await page.reload();
  await expect(page.getByTestId('readd-wallet')).toBeVisible();
  await expect(page.getByRole('link', { name: /Ajouter à Apple Wallet/ })).toHaveAttribute('href', new RegExp(`/api/card/${bc}/apple-wallet`));
  await ctx.close();
});
