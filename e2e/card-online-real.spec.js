// « Ma carte en ligne » redesign (2026-11-25), the whole path with nothing
// reshaped in the browser: a real signup, real scans at the till, the owner's
// real TikTok / Instagram save in Paramètres › Établissement, then the card page
// reads GET /card/{bc} and GET /card/{bc}/activity from the server itself.
// Local server only (scripts/dev_local.py — demo data in memory).
import { test, expect } from '@playwright/test';

const SLUG = 'cafe-lumiere';
const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only

test('signup, two scans and the owner’s networks show on the new card page', async ({ page, request }) => {
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };

  const pub = await (await request.get(`/api/join/${SLUG}/page`)).json();
  const store = (pub.stores || [])[0]?.slug;
  const made = await (await request.post(`/api/join/${SLUG}`, { data: {
    name: 'Réelle Testeuse', phone: `06${String(Date.now()).slice(-8)}`, postal_code: '37000', birthday: '03/04/1991',
    consent: true, ...(store ? { store } : {}) } })).json();
  expect(made.barcode_id, JSON.stringify(made).slice(0, 200)).toBeTruthy();

  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const branches = Array.isArray(br) ? br : (br.branches || br.items || []);
  const branch_id = (branches.find((b) => b.slug === store) || branches[0] || {}).id;
  for (const amount of [12, 8]) {
    const r = await request.post('/api/owner/scan', { headers: H, data: { barcode_id: made.barcode_id, amount_paid: amount, branch_id } });
    expect(r.ok(), await r.text()).toBeTruthy();
  }

  // networks are kept per établissement: save them on the card's own store, named
  // explicitly — the owner's « current store » is whatever an earlier spec left
  const card0 = await (await request.get(`/api/card/${made.barcode_id}`, { headers: { 'X-Card-Key': made.card_key } })).json();
  const HS = { ...H, ...(card0.store_id ? { 'X-FidClic-Store': card0.store_id } : {}) };

  // the owner types a handle and a full link; the server keeps only safe https links
  const save = await request.put('/api/owner/etablissement', { headers: HS,
    data: { business: { socials: { instagram: '@cafelumiere', tiktok: 'https://www.tiktok.com/@cafelumiere', facebook: '', snapchat: '' } } } });
  expect(save.ok(), await save.text()).toBeTruthy();

  try {
    const card = await (await request.get(`/api/card/${made.barcode_id}`, { headers: { 'X-Card-Key': made.card_key } })).json();
    expect(card.customer.first_name).toBe('Réelle');
    expect(card.card.socials.map((s) => s.network)).toEqual(['instagram', 'tiktok']);

    // paging with the server's own opaque cursor, one row a page: each scan exactly once
    // (the two scans can share a timestamp — the case the cursor exists for)
    const seen = [];
    let before = null;
    for (let i = 0; i < 5; i += 1) {
      const page1 = await (await request.get(`/api/card/${made.barcode_id}/activity`, {
        headers: { 'X-Card-Key': made.card_key }, params: { limit: 1, ...(before ? { before } : {}) } })).json();
      seen.push(...page1.items);
      before = page1.next;
      if (!before) break;
    }
    expect(seen.map((it) => it.kind)).toEqual(['visit', 'visit']);
    expect(seen.map((it) => it.amount).sort()).toEqual([12, 8].sort());

    await page.goto(`/card/${made.barcode_id}?k=${made.card_key}`);
    await expect(page.getByText('Bonjour, Réelle !')).toBeVisible();

    const acts = page.getByTestId('activity-list').getByRole('listitem');
    await expect(acts).toHaveCount(2);                       // the two scans, newest first

    const insta = page.getByRole('link', { name: /instagram/i });
    await expect(insta).toHaveAttribute('href', 'https://www.instagram.com/cafelumiere');
    await expect(insta).toHaveAttribute('rel', /noopener/);
    await expect(page.getByRole('link', { name: /tiktok/i })).toHaveAttribute('href', 'https://www.tiktok.com/@cafelumiere');
    await expect(page.getByRole('link', { name: /snapchat/i })).toHaveCount(0);

    // nothing wider than the phone
    const wide = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(wide).toBeLessThanOrEqual(0);
  } finally {
    // the demo store is shared by the other specs
    await request.put('/api/owner/etablissement', { headers: HS,
      data: { business: { socials: { instagram: '', tiktok: '', facebook: '', snapchat: '' } } } });
  }
});
