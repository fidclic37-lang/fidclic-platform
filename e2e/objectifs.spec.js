/**
 * « Objectifs et récompenses » — the owner writes a milestone, a client
 * reaches it at the till, and the reward is there to hand over.
 */
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only

async function asOwner(page, request) {
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const store = ((br && br.branches) || br || []).find((b) => b.status !== 'closed')?.id || '';
  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
    // the store gate waits for a choice; these tests have made it already
    try { sessionStorage.removeItem('ft_pick_store'); } catch (_e) { /* ignore */ }
  }, [login.access_token, store]);
  return { H, store };
}

test.describe.serial('objectifs the shop sets for itself', () => {
  test.use({ viewport: { width: 1536, height: 960 } });

  test('the tab is in Paramètres and saves an objectif', async ({ page, request }) => {
    const { H } = await asOwner(page, request);
    await page.goto('/dashboard/parametres/objectifs');
    await expect(page.getByRole('heading', { name: 'Objectifs et récompenses' })).toBeVisible();
    await expect(page.getByText('Aucun objectif pour le moment')).toBeVisible();

    await page.getByRole('button', { name: 'Ajouter un objectif' }).click();
    await page.getByLabel('Récompense').fill('Café offert e2e');
    await page.getByLabel('À partir de').fill('3');
    await page.getByRole('button', { name: 'Enregistrer' }).click();
    await expect(page.getByText('Objectifs enregistrés.')).toBeVisible({ timeout: 10_000 });

    // the server really kept it
    const saved = await (await request.get('/api/owner/milestones', { headers: H })).json();
    const mine = (saved.items || []).find((i) => i.label === 'Café offert e2e');
    expect(mine, 'the objectif is stored').toBeTruthy();
    expect(mine.unit).toBe('visits');
    expect(mine.threshold).toBe(3);
    expect(mine.repeat).toBe(false);
  });

  test('a client reaching it gets the reward waiting at the till', async ({ page, request }) => {
    const { H, store } = await asOwner(page, request);
    const pub = await (await request.get('/api/join/cafe-lumiere/page')).json();
    const slug = (pub.stores || [])[0]?.slug;
    const made = await (await request.post('/api/join/cafe-lumiere', { data: {
      name: 'Objectif Test', phone: `07${String(Date.now()).slice(-8)}`, postal_code: '37000',
      birthday: '03/04/1992', consent: true, ...(slug ? { store: slug } : {}) } })).json();
    expect(made.barcode_id).toBeTruthy();

    // the till always says where the visit happened (2026-10-12)
    const scan = () => request.post('/api/owner/scan', { headers: H,
      data: { barcode_id: made.barcode_id, branch_id: store || undefined } });
    const r1 = await (await scan()).json();
    const r2 = await (await scan()).json();
    expect(r1.objectifs_won, 'not yet at one visit').toEqual([]);
    expect(r2.objectifs_won, 'not yet at two').toEqual([]);

    const r3 = await (await scan()).json();
    expect(r3.objectifs_won.map((w) => w.reward)).toContain('Café offert e2e');

    // and the till offers it on the very next scan
    const card = await (await request.get(`/api/owner/scan/card?barcode=${made.barcode_id}`, { headers: H })).json();
    expect(card.applicables.some((a) => a.title === 'Café offert e2e'), 'waiting at the till').toBeTruthy();

    // once is once
    const r4 = await (await scan()).json();
    expect(r4.objectifs_won, 'not handed out twice').toEqual([]);
  });

  test('the paliers moved here, and saving one really saves it', async ({ page, request }) => {
    const { H: base, store } = await asOwner(page, request);
    // The ladder is per establishment (multi-store): the browser sends the
    // chosen one on every call, so a check that does not would read another's.
    const H = { ...base, 'X-FidClic-Store': store || 'all' };
    const before = await (await request.get('/api/owner/card/settings', { headers: H })).json();
    const rung = (before.tiers || [])[2];                 // « Or », the third
    expect(rung, 'the shop has a ladder').toBeTruthy();

    await page.goto('/dashboard/parametres/objectifs');
    await expect(page.getByRole('heading', { name: 'Paliers' })).toBeVisible();
    await expect(page.getByText("Comment le palier d'un client est décidé")).toBeVisible();

    await page.getByRole('button', { name: 'Gérer les paliers' }).click();
    const ceiling = page.getByLabel(`Plafond du palier ${before.tiers[1].label}`);
    const target = String(Number(rung.min) + 7);
    await ceiling.fill(target);
    await page.getByRole('button', { name: 'Enregistrer' }).first().click();
    await page.waitForTimeout(1500);
    // the server kept it, not just the screen
    await expect.poll(async () => {
      const now = await (await request.get('/api/owner/card/settings', { headers: H })).json();
      return String((now.tiers || [])[2]?.min);
    }, { timeout: 15_000 }).toBe(target);

    // put it back the way it was
    await request.put('/api/owner/card/rewards', { headers: H, data: {
      tiers: before.tiers.map((t) => ({ key: t.key, min: t.min, reward: t.reward })),
      vip_shortcut: before.vip_shortcut } });
  });

  test('cleanup: the objectif is removed again', async ({ page, request }) => {
    const { H } = await asOwner(page, request);
    const now = await (await request.get('/api/owner/milestones', { headers: H })).json();
    const left = (now.items || []).filter((i) => i.label !== 'Café offert e2e');
    const put = await request.put('/api/owner/milestones', { headers: H, data: { items: left } });
    expect(put.ok()).toBeTruthy();
  });
});
