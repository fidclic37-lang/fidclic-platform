// One unit per programme, and parrainage rewards of any kind (user, 2026-10-13),
// in a real browser:
//   QA BUG-009 — a Tampons card's receipt showed « +10 points » AND « +1 tampon ».
//   Parrainage — the owner picks, for the parrain and the filleul separately,
//   points, tampons or an offer of their own.
//
// Runs against the local server only (scripts/dev_local.py — demo data in
// memory). Never point it at production.
import { test, expect } from '@playwright/test';

const SLUG = 'cafe-lumiere';
const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only

async function asOwner(page, request) {
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const store = ((br && br.branches) || br || []).find((b) => b.status !== 'closed');
  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
  }, [login.access_token, store?.id || '']);
  return { H: { ...H, ...(store ? { 'X-FidClic-Store': store.id } : {}) }, store };
}

test.describe.serial('programme units and parrainage rewards', () => {
  test.use({ viewport: { width: 1536, height: 960 } });

  test('BUG-009 — a Tampons card: the receipt shows tampons, never points', async ({ page, request }) => {
    const { H, store } = await asOwner(page, request);
    const s = await (await request.get('/api/owner/card/settings', { headers: H })).json();
    test.skip(s.programme?.programme && s.programme.programme !== 'stamps', 'the demo store is not a Tampons card');
    const pub = await (await request.get(`/api/join/${SLUG}/page`)).json();
    const slug = (pub.stores || []).find((x) => x.id === store?.id)?.slug || (pub.stores || [])[0]?.slug;
    const made = await (await request.post(`/api/join/${SLUG}`, { data: {
      name: 'Tampon Test', phone: `07${String(Date.now()).slice(-8)}`, postal_code: '37000', birthday: '03/04/1992',
      consent: true, ...(slug ? { store: slug } : {}) } })).json();

    await page.goto('/dashboard/scan');
    await page.getByRole('button', { name: 'Saisir le code' }).click();
    await page.locator('#scan-card-id').fill(made.barcode_id);
    await expect(page.getByText('Client scanné')).toBeVisible({ timeout: 10_000 });

    // the card counts in tampons, and says so — never in points
    await expect(page.getByText('tampons', { exact: true })).toBeVisible();
    await expect(page.getByText('points', { exact: true }), 'no points on a Tampons card').toHaveCount(0);

    await page.getByRole('button', { name: 'Enregistrer la visite' }).click();
    await expect(page.getByText(/Visite enregistrée/)).toBeVisible({ timeout: 15_000 });
    const card = await (await request.get(`/api/card/${made.barcode_id}`, { headers: { 'X-Card-Key': made.card_key } })).json();
    expect(card.customer.points, 'no points credited').toBe(0);
  });

  test('Parrainage — tampons for the parrain, an offer for the filleul', async ({ page, request }) => {
    const { H } = await asOwner(page, request);
    const before = await (await request.get('/api/owner/referrals/config', { headers: H })).json();
    await page.goto('/dashboard/referral');
    await page.getByRole('button', { name: /Paramètres du programme/ }).first().click();
    if (!before.enabled) await page.getByRole('button', { name: /Programme de parrainage/ }).click();
    await page.getByRole('group', { name: 'Récompense parrain' }).getByRole('button', { name: 'Tampons' }).click();
    await page.getByLabel('Nombre de tampons').fill('2');
    await page.getByRole('group', { name: 'Récompense filleul' }).getByRole('button', { name: 'Offre' }).click();
    await page.getByLabel('Offre filleul').fill('1 café offert');
    await page.getByRole('button', { name: 'Enregistrer' }).click();
    await expect.poll(async () => (await (await request.get('/api/owner/referrals/config', { headers: H })).json()).referrer_reward_kind)
      .toBe('stamps');
    const after = await (await request.get('/api/owner/referrals/config', { headers: H })).json();
    expect(after.referrer_reward_kind).toBe('stamps');
    expect(after.referrer_reward_stamps).toBe(2);
    expect(after.referee_reward_kind).toBe('offer');
    expect(after.referee_reward_offer).toBe('1 café offert');

    // back as it was
    await request.put('/api/owner/referrals/config', { headers: H, data: before });
  });
});
