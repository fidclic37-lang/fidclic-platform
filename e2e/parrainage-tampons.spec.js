/**
 * Parrainage in tampons (user, 2026-10-27: the settings said Tampons, the
 * page said « 0 points » while the friends had their tampons in Wallet), in a
 * real browser on the local server:
 *   • a shop in tampons sees « Tampons offerts », « 2 tampons » on the row and
 *     beside the parrain — never « 0 points »;
 *   • a pending parrainage shows its promise in tampons;
 *   • a shop with its own offer sees the offer's words.
 */
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
const PAGE = '/dashboard/referral';
const uniq = String(Date.now()).slice(-6);
let phone = Number(String(Date.now()).slice(-8));

async function asOwner(page, request) {
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const store = ((br && br.branches) || br || []).find((b) => b.status !== 'closed')?.id || '';
  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
    try { sessionStorage.removeItem('ft_pick_store'); } catch (_e) { /* ignore */ }
  }, [login.access_token, store]);
  return { H, store };
}

async function settings(request, H, extra) {
  const r = await request.put('/api/owner/referrals/config', {
    headers: H,
    data: {
      enabled: true, minimum_visits_to_earn: 1, reward_mode: 'once',
      referrer_reward_kind: 'stamps', referee_reward_kind: 'stamps',
      referrer_reward_stamps: 2, referee_reward_stamps: 2,
      referrer_reward_points: 50, referee_reward_points: 25, ...extra,
    },
  });
  expect(r.status()).toBe(200);
}

async function join(request, name, parrain) {
  const pub = await (await request.get('/api/join/cafe-lumiere/page')).json();
  phone += 1;
  const r = await request.post('/api/join/cafe-lumiere', {
    data: {
      name, phone: `07${String(phone).padStart(8, '0').slice(-8)}`, postal_code: '37000', birthday: '1990-05-04',
      accepted_terms: true, consent: true, ...((pub.stores || []).length ? { store: pub.stores[0].slug } : {}),
      ...(parrain ? { parrain_barcode: parrain } : {}),
    },
  });
  expect(r.status()).toBeLessThan(300);
  return (await r.json()).barcode_id;
}

async function scan(request, H, store, bc) {
  const r = await request.post('/api/owner/scan', {
    headers: { ...H, 'X-FidClic-Store': store }, data: { barcode_id: bc, amount_paid: 12, branch_id: store || undefined } });
  expect(r.ok(), await r.text()).toBeTruthy();
}

test.describe.serial('parrainage en tampons', () => {
  test.use({ viewport: { width: 1536, height: 960 } });

  test('les tampons donnés se lisent en tampons, jamais « 0 points »', async ({ page, request }) => {
    const { H, store } = await asOwner(page, request);
    await settings(request, H, {});
    const parrain = await join(request, `Ahmed Parrain${uniq}`);
    const filleul = await join(request, `Ingrid Filleule${uniq}`, parrain);
    await scan(request, H, store, filleul);
    await join(request, `Adams Attente${uniq}`, parrain);       // pending: no visit yet

    await page.goto(PAGE);
    await expect(page.getByText('Tampons offerts')).toBeVisible({ timeout: 20000 });
    const paid = page.getByRole('row').filter({ hasText: 'Ingrid' }).filter({ hasText: 'Validé' });
    await expect(paid.first()).toContainText('2 tampons');
    const pending = page.getByRole('row').filter({ hasText: 'Adams' });
    await expect(pending.first()).toContainText('2 tampons');
    await expect(pending.first()).toContainText('En attente');
    await expect(page.locator('li').filter({ hasText: 'Ahmed' }).first()).toContainText('2 tampons');
    await expect(page.getByText(/^0 points$/)).toHaveCount(0);
  });

  test("une offre du commerce se lit dans ses propres mots", async ({ page, request }) => {
    const { H, store } = await asOwner(page, request);
    await settings(request, H, { referrer_reward_kind: 'offer', referrer_reward_offer: '1 coupe offerte' });
    const parrain = await join(request, `Paul Offre${uniq}`);
    const filleul = await join(request, `Lina Offre${uniq}`, parrain);
    await scan(request, H, store, filleul);

    await page.goto(PAGE);
    await expect(page.getByText('Offres offertes')).toBeVisible({ timeout: 20000 });
    await expect(page.getByRole('row').filter({ hasText: 'Lina' }).first()).toContainText('1 coupe offerte');
  });
});
