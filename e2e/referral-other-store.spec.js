/**
 * A filleul whose card is one establishment's, scanned in another (user,
 * 2026-11-01 — Royal Trim PL-Monstre read 0 € with no word why):
 *  1. Analyses › Impact FidClic of the card's store says what its filleuls
 *     spent elsewhere, and that it is counted there;
 *  2. Parrainage › Derniers parrainages names the card store and the visits
 *     in the other store.
 * Local server only.
 */
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
const SLUG = 'cafe-lumiere';

test.describe('filleul in another store', () => {
  test.use({ viewport: { width: 1536, height: 960 } });

  test('Impact FidClic and Derniers parrainages explain a visit scanned elsewhere', async ({ page, request }) => {
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
    const H = { Authorization: `Bearer ${login.access_token}` };
    const br = await (await request.get('/api/owner/branches', { headers: H })).json();
    const open = ((br && br.branches) || br || []).filter((x) => x.status !== 'closed');
    expect(open.length, 'the demo shop has several stores').toBeGreaterThan(1);
    const [home, other] = open;
    expect((await request.put('/api/owner/referrals/config', { headers: { ...H, 'X-FidClic-Store': home.id }, data: {
      enabled: true, minimum_visits_to_earn: 1, reward_mode: 'once',
      referrer_reward_kind: 'stamps', referee_reward_kind: 'stamps', referrer_reward_stamps: 2, referee_reward_stamps: 2,
    } })).ok()).toBeTruthy();
    const pub = await (await request.get(`/api/join/${SLUG}/page`)).json();
    const homeSlug = (pub.stores || []).find((s) => s.id === home.id)?.slug;
    const stamp = String(Date.now()).slice(-6);
    let n = 0;
    const join = async (name, parrain) => (await (await request.post(`/api/join/${SLUG}`, { data: {
      name, phone: `06${stamp}${String(n++).padStart(2, '0')}`, postal_code: '37000', birthday: '01/02/1990', consent: true,
      ...(homeSlug ? { store: homeSlug } : {}), ...(parrain ? { parrain_barcode: parrain } : {}) } })).json()).barcode_id;
    const parrain = await join(`Parrain${stamp}`);
    const filleul = await join(`Ailleurs${stamp} Test`, parrain);
    // the filleul's visit is scanned at the OTHER store
    const r = await request.post('/api/owner/scan', { headers: { ...H, 'X-FidClic-Store': other.id },
      data: { barcode_id: filleul, amount_paid: 22, branch_id: other.id } });
    expect(r.ok(), await r.text()).toBeTruthy();

    await page.goto('/login');
    await page.evaluate(([t, s]) => {
      localStorage.setItem('fidelitour_access_token', t);
      localStorage.setItem('ft_selected_branch_v1', s);
      try { sessionStorage.removeItem('ft_pick_store'); } catch (_e) { /* ignore */ }
    }, [login.access_token, home.id]);

    // 1. Impact FidClic of the card's store
    await page.goto('/dashboard/analytics');
    const box = page.getByTestId('filleuls-ailleurs');
    await expect(box).toBeVisible({ timeout: 20000 });
    await expect(box).toContainText('Vos filleuls passés dans un autre établissement');
    await expect(box).toContainText(other.name);
    await expect(box).toContainText('pas ici');

    // 2. Derniers parrainages
    await page.goto('/dashboard/referral');
    const line = page.getByTestId('filleul-ailleurs').filter({ hasText: other.name }).first();
    await expect(line).toBeVisible({ timeout: 20000 });
    await expect(line).toContainText(`Carte : ${home.name}`);
    await expect(line).toContainText('1 visite (22 €)');

    // the other store counts it itself: no box about this filleul there
    await page.evaluate((s) => localStorage.setItem('ft_selected_branch_v1', s), other.id);
    await page.goto('/dashboard/analytics');
    await expect(page.locator('#impact')).toBeVisible({ timeout: 20000 });
    const there = page.getByTestId('filleuls-ailleurs');
    if (await there.count()) await expect(there).not.toContainText(other.name);
    expect(errors).toEqual([]);
  });
});
