// « Mes offres · 2 en cours » on the card, « Pas d'offre en ce moment » once
// opened (user, 2026-11-25). The count on the card and the list behind it are
// now the same list: what is live for THIS customer.
// Runs against the local server only (scripts/dev_local.py — demo data in memory).
import { test, expect } from '@playwright/test';

const SLUG = 'cafe-lumiere';
const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
const iso = (d) => d.toISOString().slice(0, 10);

test('the card counts exactly the offers its « Mes offres » page lists', async ({ page, request }) => {
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const store = ((br && br.branches) || br || []).find((b) => b.status !== 'closed')?.id || '';
  const SH = { ...H, ...(store ? { 'X-FidClic-Store': store } : {}) };
  const pub = await (await request.get(`/api/join/${SLUG}/page`)).json();
  const slug = (pub.stores || []).find((x) => x.id === store)?.slug;
  const name = `Compte Offres ${Date.now() % 100000}`;
  const made = await (await request.post(`/api/join/${SLUG}`, { data: {
    name, phone: `07${String(Date.now()).slice(-8)}`, postal_code: '37000', birthday: '03/04/1992',
    consent: true, ...(slug ? { store: slug } : {}) } })).json();
  let id = made.customer_id || made.id;
  if (!id) {
    const rows = (await (await request.get(`/api/owner/clients/list?per_page=20&search=${encodeURIComponent(name)}`, { headers: SH })).json()).rows || [];
    id = rows.find((c) => c.name === name)?.id;
  }
  expect(id, 'a new client of this establishment').toBeTruthy();

  // a défi: it is sent to the client but has its own « Défi en cours », it is no offer
  const end = new Date(Date.now() + 5 * 864e5);
  const defi = await request.post('/api/owner/campaigns/compose', { headers: SH, data: {
    kind: 'defi', title: `Défi ${name}`, message: '3 visites = 1 café', customer_ids: [id],
    defi: { target: 3, end_date: iso(end), count_mode: 'per_scan', reward: 'Un café', reward_valid_days: 7 } } });
  expect(defi.ok(), await defi.text()).toBeTruthy();

  await page.goto('/login');
  await page.evaluate(([bc, k]) => localStorage.setItem('fidclic:my_cards', JSON.stringify({ [bc]: k })),
    [made.barcode_id, made.card_key]);

  // round 4: the tile opens the Récompenses tab of the card page (no other page)
  const offers = page.getByRole('button', { name: /Mes offres/ });
  await page.goto(`/card/${made.barcode_id}`);
  await expect(offers).toBeVisible();
  await expect(offers, 'a défi is not « en cours » in Mes offres').not.toContainText('en cours');
  // the tile (redesign 2026-11-25) shows « N en cours » only when there are offers
  await expect(offers).toContainText('Mes offres exclusives');
  await offers.click();
  await expect(page.getByText('Pas d’offre en ce moment')).toBeVisible();

  // a real offer: one on the card, one on the page
  const title = `Offre ${name}`;
  const sent = await request.post('/api/owner/campaigns/compose', { headers: SH,
    data: { title, message: 'Bonjour {prénom} !', customer_ids: [id] } });
  expect(sent.ok(), await sent.text()).toBeTruthy();
  await page.goto(`/card/${made.barcode_id}`);
  await expect(offers).toContainText('1 en cours');
  await offers.click();
  await expect(page.getByText(title)).toBeVisible();
  await expect(page.getByText('Pas d’offre en ce moment')).toHaveCount(0);
});
