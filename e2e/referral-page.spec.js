/**
 * Parrainage page (user, 2026-10-28):
 *  1. « Top parrains › Voir tous » downloaded a CSV — it opens the list of
 *     every parrain (search, pages), no file;
 *  2. « Derniers parrainages › Récompense » is both sides together
 *     (« 4 tampons »), each side shown on hover or tap.
 * Local server only.
 */
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
const SLUG = 'cafe-lumiere';

async function setup(page, request) {
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const store = ((br && br.branches) || br || []).find((x) => x.status !== 'closed')?.id || '';
  const SH = { ...H, ...(store ? { 'X-FidClic-Store': store } : {}) };
  expect((await request.put('/api/owner/referrals/config', { headers: SH, data: {
    enabled: true, minimum_visits_to_earn: 1, reward_mode: 'once',
    referrer_reward_kind: 'stamps', referee_reward_kind: 'stamps', referrer_reward_stamps: 2, referee_reward_stamps: 2,
  } })).ok()).toBeTruthy();
  const pub = await (await request.get(`/api/join/${SLUG}/page`)).json();
  const storeSlug = (pub.stores || []).find((s) => s.id === store)?.slug || (pub.stores || [])[0]?.slug;
  const stamp = String(Date.now()).slice(-6);
  let n = 0;
  const join = async (name, parrain) => (await (await request.post(`/api/join/${SLUG}`, { data: {
    name, phone: `07${stamp}${String(n++).padStart(2, '0')}`, postal_code: '37000', birthday: '01/02/1990', consent: true,
    ...(storeSlug ? { store: storeSlug } : {}), ...(parrain ? { parrain_barcode: parrain } : {}) } })).json()).barcode_id;
  const parrains = [];
  for (let i = 0; i < 7; i += 1) {
    const p = await join(`Parrain${'ABCDEFG'[i]}${stamp}`);         // one word each: a search finds exactly one
    parrains.push(p);
    const f = await join(`Filleul${stamp} ${i}`, p);
    const r = await request.post('/api/owner/scan', { headers: SH, data: { barcode_id: f, amount_paid: 10, ...(store ? { branch_id: store } : {}) } });
    expect(r.ok(), await r.text()).toBeTruthy();
  }
  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
    try { sessionStorage.removeItem('ft_pick_store'); } catch (_e) { /* ignore */ }
  }, [login.access_token, store]);
  return { stamp };
}

test.describe('parrainage page', () => {
  test.use({ viewport: { width: 1536, height: 960 } });

  test('Top parrains › Voir tous opens every parrain, no download; the reward is both sides', async ({ page, request }) => {
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    const downloads = [];
    page.on('download', (d) => downloads.push(d.suggestedFilename()));
    const { stamp } = await setup(page, request);
    await page.goto('/dashboard/referral');

    // 1. the list, not a file
    const top = page.getByTestId('top-parrains');
    await top.getByRole('button', { name: /Voir tous/ }).click();
    const dlg = page.getByRole('dialog', { name: 'Tous les parrains' });
    await expect(dlg).toBeVisible();
    await expect(dlg.getByTestId('parrain-row').first()).toBeVisible();
    expect(await dlg.getByTestId('parrain-row').count()).toBeGreaterThanOrEqual(7);
    await dlg.getByPlaceholder(/Rechercher un parrain/).fill(`ParrainD${stamp}`);
    await expect(dlg.getByTestId('parrain-row')).toHaveCount(1);
    await expect(dlg.getByTestId('parrain-row')).toContainText('2 tampons');
    expect(downloads, 'no CSV downloaded').toEqual([]);
    await dlg.getByRole('button', { name: 'Fermer' }).click();
    await expect(dlg).toHaveCount(0);

    // 2. the table: total of both sides, each side on hover
    const cell = page.getByTestId('reward-cell').first();
    await expect(cell).toContainText('4 tampons');
    await cell.hover();
    const tip = page.getByRole('tooltip');
    await expect(tip).toContainText('Parrain');
    await expect(tip).toContainText('Filleul');
    await expect(tip).toContainText('2 tampons');
    expect(errors).toEqual([]);
  });
});

// the tooltip is fully on screen — never cut by the table (user, 2026-10-28:
// on the first row it was hidden under the header)
async function fullyVisible(page) {
  const tip = page.getByRole('tooltip');
  await expect(tip).toBeVisible();
  const box = await tip.boundingBox();
  const vp = page.viewportSize();
  expect(box.x, 'left edge on screen').toBeGreaterThanOrEqual(0);
  expect(box.y, 'top edge on screen').toBeGreaterThanOrEqual(0);
  expect(box.x + box.width, 'right edge on screen').toBeLessThanOrEqual(vp.width);
  expect(box.y + box.height, 'bottom edge on screen').toBeLessThanOrEqual(vp.height);
  // nothing covers it: its four corners and centre are the tooltip itself
  // (it ignores the mouse — pointer-events: none — so hit-testing is switched
  // on just for this check; what is painted on top does not change)
  await tip.evaluate((el) => { el.style.pointerEvents = 'auto'; });
  const pts = [[box.x + 4, box.y + 4], [box.x + box.width - 4, box.y + 4], [box.x + 4, box.y + box.height - 4],
    [box.x + box.width - 4, box.y + box.height - 4], [box.x + box.width / 2, box.y + box.height / 2]];
  for (const [x, y] of pts) {
    const inside = await page.evaluate(([px, py]) => !!document.elementFromPoint(px, py)?.closest('[role="tooltip"]'), [x, y]);
    expect(inside, `tooltip not covered at ${Math.round(x)},${Math.round(y)}`).toBe(true);
  }
  await expect(tip).toContainText('Parrain');
  await expect(tip).toContainText('Filleul');
  await expect(tip).toContainText('Total');
}

test.describe('the reward tooltip is never cut', () => {
  test.use({ viewport: { width: 1536, height: 960 } });
  test('first row, scrolled so the row sits right under the screen top, and last row at the bottom', async ({ page, request }) => {
    await setup(page, request);
    await page.goto('/dashboard/referral');
    const cells = page.getByTestId('reward-cell');
    const first = cells.first();
    // the first row near the top of the window: no room above
    await first.evaluate((el) => { el.scrollIntoView({ block: 'start' }); window.scrollBy(0, -20); });
    await first.hover();
    await fullyVisible(page);
    await page.mouse.move(5, 5);
    await expect(page.getByRole('tooltip')).toHaveCount(0);
    // the last row near the bottom of the window
    const last = cells.last();
    await last.evaluate((el) => el.scrollIntoView({ block: 'end' }));
    await last.hover();
    await fullyVisible(page);
  });
});

test('phone: tapping the reward shows both sides', async ({ page, request }) => {
  await setup(page, request);
  await page.goto('/dashboard/referral');
  const cell = page.getByTestId('reward-cell').first();
  await cell.scrollIntoViewIfNeeded();
  await cell.click();
  await expect(page.getByRole('tooltip')).toContainText('Filleul');
  await fullyVisible(page);
});

// « Étudiants » is gone (user, 2026-10-30: « students waali category hata di
// thi pehle hi, toh hatao students ko full power »)
test('Répartition des parrainages: three slices, no Étudiants', async ({ page, request }) => {
  await setup(page, request);
  await page.goto('/dashboard/referral');
  const card = page.locator('section, div').filter({ has: page.getByText('Répartition des parrainages', { exact: true }) }).last();
  await expect(card.getByText('Clients réguliers')).toBeVisible();
  await expect(card.getByText('Nouveaux clients')).toBeVisible();
  await expect(card.getByText('Autres', { exact: true })).toBeVisible();
  await expect(page.getByText(/Étudiant/)).toHaveCount(0);
});
