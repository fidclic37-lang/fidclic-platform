/**
 * « Aaj visit hui, next visit pr reward: scan pr show hona chahiye » (user,
 * 2026-11-05). Real till, real server, local seed only: the receipt says it on a
 * tampon card and on a points card, on a phone too, says nothing on an ordinary
 * visit, and what it said is what the next visit hands over.
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
    try { sessionStorage.removeItem('ft_pick_store'); } catch (_e) { /* ignore */ }
  }, [login.access_token, store]);
  return { H: { ...H, 'X-FidClic-Store': store || 'all' }, store };
}

const newClient = (request, H, store) => async () => {
  const list = await (await request.get('/api/owner/clients/list?per_page=50', { headers: H })).json();
  for (const c of list.rows || []) {
    if (!c.barcode_id) continue;
    const card = await (await request.get(`/api/owner/scan/card?barcode=${c.barcode_id}`, { headers: H })).json();
    if (card.reward_ahead) return { card: c.barcode_id, ahead: card.reward_ahead };
  }
  throw new Error(`no client short of a reward in ${store}`);
};

async function typeVisit(page, card, amount = '5') {
  await page.goto('/dashboard/scan');
  await page.getByRole('button', { name: 'Saisir le code' }).click();
  await page.getByLabel('Code de la carte').fill(card);
  await expect(page.getByPlaceholder('0,00')).toBeVisible({ timeout: 15_000 });
  await page.getByPlaceholder('0,00').fill(amount);
  await page.getByRole('button', { name: /Suivant/ }).click();
  await expect(page.getByTestId('visit-review')).toBeVisible();
}

const record = async (page) => {
  // the page's button, or the bar stuck to the bottom of a phone
  await page.getByRole('button', { name: /^Enregistrer( la visite)?$/ }).locator('visible=true').first().click();
  await expect(page.getByTestId('visit-summary')).toBeVisible({ timeout: 15_000 });
};

const noOverflow = async (page) => {
  const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(over).toBeLessThanOrEqual(1);
};

async function bringShort(request, H, store, card, left) {
  for (let i = 0; i < 80; i += 1) {
    const c = await (await request.get(`/api/owner/scan/card?barcode=${card}`, { headers: H })).json();
    if (c.reward_ahead?.need_visits != null && c.reward_ahead.need_visits <= left) return c.reward_ahead;
    if (c.reward_ahead?.need_points != null && c.reward_ahead.need_points <= left) return c.reward_ahead;
    const r = await request.post('/api/owner/scan', { headers: H, data: { barcode_id: card, amount_paid: 1, branch_id: store || undefined } });
    expect(r.status(), await r.text()).toBe(200);
  }
  throw new Error('never got short');
}

for (const [label, viewport] of [['desktop', { width: 1536, height: 960 }], ['phone', { width: 375, height: 812 }]]) {
  test.describe(label, () => {
    test.use({ viewport });

    test('tampons: an ordinary visit says nothing, the one that fills says it, the next one hands it over', async ({ page, request }) => {
      test.setTimeout(150_000);
      const { H, store } = await asOwner(page, request);
      const s = await (await request.get('/api/owner/card/settings', { headers: H })).json();
      test.skip((s.programme?.type || 'stamps') !== 'stamps', 'the demo store is not a Tampons card');
      const { card, ahead } = await newClient(request, H, store)();
      const perStamp = ahead.per_stamp || 1;
      await bringShort(request, H, store, card, 2 * perStamp);

      // still short after today: nothing promised
      const before = await (await request.get(`/api/owner/scan/card?barcode=${card}`, { headers: H })).json();
      if (before.reward_ahead.need_visits > 1) {
        await typeVisit(page, card);
        await expect(page.getByTestId('reward-after-this-visit')).toHaveCount(0);
        await record(page);
        await expect(page.getByTestId('next-visit-reward')).toHaveCount(0);
      }
      await bringShort(request, H, store, card, 1);

      // this visit fills it
      await typeVisit(page, card);
      await record(page);
      const said = page.getByTestId('next-visit-reward');
      await expect(said).toContainText('À la prochaine visite');
      await expect(said).toContainText(ahead.title);
      await noOverflow(page);
      await page.screenshot({ path: `test-results/next-visit-reward-${label}.png` });

      // the next visit: what was said is there to pick
      await typeVisit(page, card);
      const row = page.getByTestId('visit-review').getByRole('button', { name: new RegExp(ahead.title.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) });
      await expect(row).toBeEnabled();
      await row.click();
      await record(page);
      await expect(page.getByTestId('next-visit-reward')).toHaveCount(0);
    });
  });
}

test('points: the till warns before the visit, the receipt says it after', async ({ page, request }) => {
  test.setTimeout(150_000);
  const { H, store } = await asOwner(page, request);
  const was = await (await request.get('/api/owner/card/settings', { headers: H })).json();
  const put = (data) => request.put('/api/owner/card/settings', { headers: H, data });
  const back = { programme: was.programme?.type || 'stamps', reward_threshold_stamps: Number(was.programme?.reward_threshold_stamps) || 10 };
  try {
    const r = await put({ programme: 'points_visit', points_per_visit: 10, reward_points: 100000, reward_description: 'Dessert offert' });
    expect(r.status(), await r.text()).toBe(200);
    const { card } = await newClient(request, H, store)();
    const now = await (await request.get(`/api/owner/scan/card?barcode=${card}`, { headers: H })).json();
    const balance = now.balance.value;

    // the reward just above this client's balance: one visit away
    await put({ reward_points: balance + 10 });
    await typeVisit(page, card);
    await expect(page.getByTestId('reward-after-this-visit')).toContainText('Dessert offert');
    await expect(page.getByTestId('reward-after-this-visit')).toContainText('disponible à la prochaine visite');
    await record(page);
    await expect(page.getByTestId('next-visit-reward')).toContainText('Dessert offert');
  } finally {
    await put(back);
  }
});
