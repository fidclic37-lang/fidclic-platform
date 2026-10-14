// What a customer actually does, in a real browser on a phone-sized screen
// (2026-10-09). #176 made the card's data answer only to the card's owner
// key; the API tests passed, yet every Wallet « Offres » tile opened « Carte
// introuvable » — the page behind the link never sent the key. This walk
// opens every customer entry point the server hands out (signup, the card,
// the Wallet tiles, a friend scanning the QR, a card given back) and fails
// on any error screen or JavaScript error.
//
// Runs against the local server only (scripts/dev_local.py — demo data in
// memory). Never point it at production.
import { test, expect } from '@playwright/test';

const SLUG = 'cafe-lumiere';
const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
const BROKEN = /Carte introuvable|Not enough permissions|Une erreur est survenue|Something went wrong|Erreur inattendue/i;

const phone = () => `06${String(Math.floor(Math.random() * 1e8)).padStart(8, '0')}`;

// Fail on any uncaught error in the page, and on any « broken » screen.
function watch(page) {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  return {
    async clean(where) {
      await expect(page.locator('body'), `${where}: an error screen`).not.toContainText(BROKEN);
      expect(errors, `${where}: JavaScript errors`).toEqual([]);
    },
  };
}

async function signup(page, { name, tel, path = `/join/${SLUG}` }) {
  if (path) await page.goto(path);
  const form = page.locator('#join-form');
  await expect(form).toBeVisible();
  // several establishments and the account's own link: « Votre établissement » (2026-10-12)
  const store = form.getByLabel('Votre établissement');
  if (await store.count()) await store.selectOption({ index: 1 });
  await form.locator('input[type="text"]').first().fill(name);
  await page.locator('#join-phone').fill(tel);
  await page.locator('input[name="postal-code"]').fill('37000');
  const bday = page.locator('input[name="bday"]');                         // typed as digits, masked JJ/MM/AAAA
  await bday.pressSequentially('01');
  await expect(bday, 'the « / » comes right after the day').toHaveValue('01/');
  await bday.pressSequentially('02');
  await expect(bday).toHaveValue('01/02/');
  await bday.pressSequentially('1990');
  await expect(bday).toHaveValue('01/02/1990');
  await form.locator('input[type="checkbox"][required]').check();
  await page.getByRole('button', { name: /Rejoindre le programme/ }).click();
  // « Félicitations ! » with the shop's own card (2026-10-09 redesign)
  await expect(page.getByText('Félicitations', { exact: false }).first()).toBeVisible();
  await expect(page.getByText('Votre carte de fidélité est prête')).toBeVisible();
  await page.getByRole('link', { name: /Voir ma carte/ }).click();
  await expect(page).toHaveURL(/\/card\/FT-[A-Z0-9]+/);
  await expect(page.locator('body')).toContainText(name.split(' ')[0]);
  const barcode = page.url().match(/\/card\/(FT-[A-Z0-9]+)/)[1];
  const key = await page.evaluate((bc) => JSON.parse(localStorage.getItem('fidclic:my_cards') || '{}')[bc], barcode);
  expect(key, 'the phone keeps the card owner key after signup').toBeTruthy();
  return { barcode, key };
}

test("each establishment's link signs up its own members", async ({ page, request }) => {
  const pub = await (await request.get(`/api/join/${SLUG}/page`)).json();
  const stores = pub.stores || [];
  test.skip(stores.length < 2, 'a one-shop demo');
  // the account's link asks which one
  await page.goto(`/join/${SLUG}`);
  await expect(page.getByLabel('Votre établissement')).toBeVisible();
  await page.locator('input[type="text"]').first().fill('Sans Choix');
  await page.locator('#join-phone').fill('0699887766');
  await page.locator('input[name="postal-code"]').fill('37000');
  await page.locator('input[name="bday"]').pressSequentially('01021990');
  await page.locator('input[type="checkbox"][required]').check();
  await page.getByRole('button', { name: /Rejoindre le programme/ }).click();
  await expect(page.getByText('Choisissez votre établissement.')).toBeVisible();
  // a store's own link names it, asks nothing, and makes its member
  const s2 = stores[1];
  await page.goto(`/join/${SLUG}/${s2.slug}/insta`);
  await expect(page.getByText(`Établissement : ${s2.name}`)).toBeVisible();
  await expect(page.getByLabel('Votre établissement')).toHaveCount(0);
  const tel = `07${String(Date.now()).slice(-8)}`;
  const res = await request.post(`/api/join/${SLUG}`, { data: { name: 'Lien Magasin', phone: tel, postal_code: '37000',
    birthday: '03/04/1992', consent: true, store: s2.slug, acquisition_source: 'instagram' } });
  expect(res.ok()).toBeTruthy();
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const auth = { Authorization: `Bearer ${login.access_token}` };
  const made = await res.json();
  const card = await (await request.get(`/api/card/${made.barcode_id}`, { headers: { 'X-Card-Key': made.card_key } })).json();
  const fiche = await (await request.get(`/api/owner/clients/${card.customer.id}/fiche`, { headers: auth })).json();
  expect(fiche.home_store.id, 'a member of the store whose link they used').toBe(s2.id);
});

test.describe.serial('a customer, end to end', () => {
  let me;                       // { barcode, key, name }

  test('signs up and the card opens on this phone', async ({ page }) => {
    const w = watch(page);
    me = { name: 'Camille Parcours', ...(await signup(page, { name: 'Camille Parcours', tel: phone() })) };
    await w.clean('card after signup');
  });

  test('the signup refuses an impossible date of birth, plainly', async ({ page }) => {
    await page.goto(`/join/${SLUG}`);
    await page.locator('#join-form input[type="text"]').first().fill('Date Fausse');
    await page.locator('#join-phone').fill(phone());
    await page.locator('input[name="postal-code"]').fill('37000');
    await page.locator('input[name="bday"]').fill('31041990');
    await page.locator('#join-form input[type="checkbox"][required]').check();
    await page.getByRole('button', { name: /Rejoindre le programme/ }).click();
    await expect(page.locator('#join-birth-error')).toContainText('n’existe pas');
  });

  test("the owner sees the customer's age in Clients", async ({ request }) => {
    const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
    const list = await (await request.get(`/api/owner/clients/list?search=${me.barcode}`,
      { headers: { Authorization: `Bearer ${login.access_token}` } })).json();
    const row = list.rows.find((r) => r.barcode_id === me.barcode);
    const today = new Date();
    const age = today.getFullYear() - 1990 - ((today.getMonth() + 1 < 2 || (today.getMonth() + 1 === 2 && today.getDate() < 1)) ? 1 : 0);
    expect(row.age).toBe(age);
  });

  test('the Wallet tiles open on a phone that never stored the key (Safari)', async ({ browser }) => {
    const ctx = await browser.newContext();                      // empty storage — what Wallet opens in
    const page = await ctx.newPage();
    const w = watch(page);
    await page.goto(`/card/${me.barcode}/offres?k=${me.key}`);  // featured action « Offres »
    await expect(page.locator('body')).toContainText('Vos offres');
    await w.clean('offres tile');
    await page.getByRole('link', { name: 'Voir ma carte' }).click();      // → the card (2026-10-10 redesign)
    await expect(page).toHaveURL(new RegExp(`/card/${me.barcode}$`));
    await expect(page.getByRole('navigation', { name: 'Ma carte' })).toBeVisible();
    await w.clean('card from the offers');
    await page.goto(`/card/${me.barcode}?onglet=programme&k=${me.key}`);   // « Programme »
    await expect(page).toHaveURL(new RegExp(`/card/${me.barcode}`));
    await expect(page.getByRole('dialog', { name: 'Le programme' })).toBeVisible();
    await expect(page.locator('body')).toContainText(me.name.split(' ')[0]);
    await w.clean('programme tile');
    await ctx.close();
  });

  test("the card's own QR on its own phone opens that card", async ({ page }) => {
    const w = watch(page);
    // each test is a fresh browser: first this phone opens its card from an
    // owner link (as Wallet does), and keeps the key…
    await page.goto(`/card/${me.barcode}?k=${me.key}`);
    await expect(page.locator('body')).toContainText(me.name.split(' ')[0]);
    await expect.poll(() => page.evaluate((bc) => JSON.parse(localStorage.getItem('fidclic:my_cards') || '{}')[bc], me.barcode))
      .toBe(me.key);
    // …then scans its own QR, which carries no key
    await page.goto(`/card/${me.barcode}`);
    await expect(page).toHaveURL(new RegExp(`/card/${me.barcode}`));
    await expect(page.locator('body')).toContainText(me.name.split(' ')[0]);
    await w.clean('own QR');
  });

  test("a friend scanning the QR gets the signup, with parrainage, then their own card", async ({ browser }) => {
    const ctx = await browser.newContext();
    const page = await ctx.newPage();
    const w = watch(page);
    await page.goto(`/card/${me.barcode}`);
    await expect(page).toHaveURL(new RegExp(`/join/${SLUG}\\?p=${me.barcode}`));
    const friend = await signup(page, { name: 'Lou Ami', tel: phone(), path: null });
    expect(friend.barcode).not.toBe(me.barcode);
    await w.clean("friend's new card");
    await ctx.close();
  });

  test('without any key, the offers page says how to open it', async ({ browser }) => {
    const ctx = await browser.newContext();
    const page = await ctx.newPage();
    await page.goto(`/card/${me.barcode}/offres`);
    await expect(page.locator('body')).toContainText('Ouvrez vos offres depuis votre carte');
    await ctx.close();
  });

  test("the till moves a paper card's stamps once, on top of today's visit", async ({ request }) => {
    const pub = await (await request.get(`/api/join/${SLUG}/page`)).json();
    const signed = await (await request.post(`/api/join/${SLUG}`, { data: {
      name: 'Paula Papier', phone: phone(), postal_code: '37000', birthday: '03/04/1992', consent: true,
      ...(pub.stores?.length ? { store: pub.stores[0].slug } : {}) } })).json();
    const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
    const auth = { Authorization: `Bearer ${login.access_token}` };
    const pre = await (await request.get(`/api/owner/scan/preview?barcode=${signed.barcode_id}`, { headers: auth })).json();
    expect(pre.paper_max, 'a new card can take a full paper card').toBe(pre.threshold);
    // a visit counts where it is scanned: with several establishments the till names one (2026-10-12)
    const br = await (await request.get('/api/owner/branches', { headers: auth })).json();
    const store = ((br && br.branches) || br || []).find((b) => b.status !== 'closed')?.id;
    const scan = await (await request.post('/api/owner/scan', { headers: auth,
      data: { barcode_id: signed.barcode_id, amount_paid: 4, paper_stamps: 4, branch_id: store } })).json();
    expect(scan.stamps_in_cycle, '4 paper stamps + today = 5').toBe(5);
    const card = await (await request.get(`/api/card/${signed.barcode_id}`, { headers: { 'X-Card-Key': signed.card_key } })).json();
    expect(card.customer.cycle_visits, 'the customer sees 5 on their card').toBe(5);
    expect(card.customer.visits, 'one real visit').toBe(1);
    const again = await request.post('/api/owner/scan', { headers: auth,
      data: { barcode_id: signed.barcode_id, amount_paid: 4, paper_stamps: 2, branch_id: store } });
    expect(again.status(), 'never twice').toBe(409);
  });

  test('a deleted card comes back with the shop’s one-time link', async ({ browser, request }) => {
    const del = await request.delete(`/api/card/${me.barcode}`, { headers: { 'X-Card-Key': me.key } });
    expect(del.ok(), 'the customer deletes their card').toBeTruthy();
    const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
    const auth = { Authorization: `Bearer ${login.access_token}` };
    const ids = await (await request.get('/api/owner/clients/ids?card=deleted', { headers: auth })).json();
    expect(ids.ids.length, 'the shop sees the deleted card').toBeGreaterThan(0);
    const found = await (await request.post('/api/owner/card-readd/find', { headers: auth, data: { phone: '' } })).status();
    expect(found).toBe(400);
    const list = await (await request.get(`/api/owner/clients/list?card=deleted&search=${me.barcode}`, { headers: auth })).json();
    const id = list.rows.find((r) => r.barcode_id === me.barcode).id;
    const link = await (await request.post(`/api/owner/clients/${id}/card/readd`, { headers: auth, data: { channel: 'qr' } })).json();
    const path = new URL(link.url).pathname;

    const ctx = await browser.newContext();                      // the customer's phone, fresh
    const page = await ctx.newPage();
    const w = watch(page);
    await page.goto(path);
    await page.getByRole('button', { name: 'Récupérer ma carte' }).click();
    await expect(page).toHaveURL(new RegExp(`/card/${me.barcode}`));
    await expect(page.locator('body')).toContainText(me.name.split(' ')[0]);
    await w.clean('card given back');
    await page.goto(path);                                       // the link is spent
    await expect(page.locator('body')).toContainText('déjà été utilisé');
    await ctx.close();
  });
});
