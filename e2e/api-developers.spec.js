// API v1 hardening (2026-11-09): the public developer docs, the « Site en
// ligne » key option, and a till / borne / website journey through the real
// server — a ticket counted once, a refund taken back, a reward held by a
// borne and refused to the till meanwhile.
import { test, expect, request as pw } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
const ADMIN = { email: 'admin@fidelitour.com', password: 'Fidelit0ur!Adm' };        // local seed only

test.afterAll(async () => {
  const back = JSON.parse(process.env.E2E_API_RESTORE || 'null');
  if (!back || !back.plan) return;
  const admin = await pw.newContext({ baseURL: test.info().project.use.baseURL });
  const adm = await (await admin.post('/api/auth/login', { data: ADMIN })).json();
  await admin.post(`/api/admin/commerces/${back.tid}/plan`, { headers: { Authorization: `Bearer ${adm.access_token}` }, data: { plan: back.plan } });
  await admin.dispose();
});

test.describe.serial('API & developers', () => {
  test('the developer docs are public and readable on a phone', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto('/developers');
    const root = page.getByTestId('dev-docs');
    await expect(root).toBeVisible();
    for (const word of ['Idempotence', 'Webhooks', 'rewards/hold', 'visits/{ref}/cancel', 'verification']) {
      await expect(root, `the docs explain ${word}`).toContainText(word);
    }
    const wide = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(wide, 'no sideways scroll at 375 px').toBeLessThanOrEqual(1);
    await expect(page, 'no login asked').toHaveURL(/\/developers/);
  });

  test('a till, a borne and a refund through the real API', async ({ page, request }) => {
    const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
    const H = { Authorization: `Bearer ${login.access_token}` };
    // the local seed's plan may not include the API: the super admin moves the demo shop to the plan that has it
    // (local seed only), and back afterwards — a plan's switch only reaches a shop at its renewal
    const locked = await request.get('/api/owner/integrations', { headers: H });
    if (locked.status() === 403) {
      const admin = await pw.newContext({ baseURL: test.info().project.use.baseURL });   // its own cookies
      const adm = await (await admin.post('/api/auth/login', { data: ADMIN })).json();
      const A = { Authorization: `Bearer ${adm.access_token}` };
      const { plans } = await (await admin.get('/api/admin/plan-limits', { headers: A })).json();
      const detail = (await locked.json()).detail;
      const was = (plans || []).find((p) => p.label === detail.plan);
      const target = detail.upgrade.key;
      const moved = await admin.post(`/api/admin/commerces/${login.tenant_id}/plan`, { headers: A, data: { plan: target } });
      expect(moved.status(), `plan change: ${await moved.text()} (tenant ${login.tenant_id}, plan ${target})`).toBe(200);
      await admin.dispose();
      process.env.E2E_API_RESTORE = JSON.stringify({ tid: login.tenant_id, plan: was ? was.key : null });
    }
    const opened = await request.get('/api/owner/integrations', { headers: H });
    expect(opened.status(), `the API page opens: ${(await opened.text()).slice(0, 200)}`).toBe(200);

    // the owner makes a website key in the page: « Site en ligne » is offered
    await page.setViewportSize({ width: 1536, height: 960 });
    await page.goto('/login');
    const br = await (await request.get('/api/owner/branches', { headers: H })).json();
    const store = ((br && br.branches) || br || []).find((b) => b.status !== 'closed');
    await page.evaluate(([t, s]) => {
      localStorage.setItem('fidelitour_access_token', t);
      if (s) localStorage.setItem('ft_selected_branch_v1', s);
    }, [login.access_token, store && store.id]);
    await page.goto('/dashboard/parametres/api');
    await page.getByRole('button', { name: /Créer une clé/ }).click();
    await page.getByPlaceholder('Ex. Caisse du comptoir').fill('Site e2e');
    await page.getByTestId('key-online').check();
    await page.getByRole('button', { name: 'Créer la clé' }).click();
    await expect(page.locator('code', { hasText: 'fc_live_' })).toBeVisible();
    await page.getByRole('button', { name: "J'ai copié la clé" }).click();
    await expect(page.getByText('Site en ligne · SMS').first()).toBeVisible();

    // a till key, by the owner's API
    const key = (await (await request.post('/api/owner/integrations/keys', { headers: H, data: { name: 'Caisse e2e', write: true } })).json()).key;
    const K = { Authorization: `Bearer ${key}` };
    const me = await (await request.get('/api/v1/me', { headers: K })).json();
    const branch = (me.business.branches || [])[0];
    const clients = await (await request.get('/api/v1/customers?per_page=5', { headers: K })).json();
    const card = clients.data[0].card_number;
    const ticket = `E2E-${Date.now()}`;
    const send = (amount) => request.post('/api/v1/visits', {
      headers: K, data: { customer: card, amount, external_id: ticket, ...(branch ? { branch_id: branch.id } : {}) } });

    const [a, b] = await Promise.all([send(9.5), send(9.5)]);
    const codes = [a.status(), b.status()].sort();
    expect(codes[0], 'one ticket sent twice at once: written once').toBe(201);
    expect([201, 409]).toContain(codes[1]);
    expect((await send(99)).status(), 'same ticket, another amount → 422').toBe(422);

    const before = await (await request.get(`/api/v1/customers/${card}`, { headers: K })).json();
    const cancel = await request.post(`/api/v1/visits/${ticket}/cancel`, { headers: K, data: { reason: 'e2e' } });
    expect(cancel.status()).toBe(200);
    const after = await (await request.get(`/api/v1/customers/${card}`, { headers: K })).json();
    expect(after.visits, 'the refund takes the visit back').toBe(before.visits - 1);
    expect(await (await request.post(`/api/v1/visits/${ticket}/cancel`, { headers: K, data: {} })).json(),
      'cancelling again changes nothing').toMatchObject({ duplicate: true });

    // a reward held by a borne cannot be taken at the till meanwhile
    // a new client fills a card: the reward is there from the visit after
    const phone = `07${String(Date.now()).slice(-8)}`;
    const fresh = await request.post('/api/v1/customers', { headers: K, data: { name: 'Borne E2E', phone, consent: true } });
    expect(fresh.status()).toBe(201);
    const holdable = await fresh.json();
    for (let i = 0; i <= me.card.reward_threshold; i += 1) {
      const r = await request.post('/api/v1/visits', { headers: K, data: { customer: holdable.card_number, amount: 2, ...(branch ? { branch_id: branch.id } : {}) } });
      expect(r.status()).toBe(201);
    }
    expect((await (await request.get(`/api/v1/customers/${phone}`, { headers: K })).json()).reward_available,
      'found by phone, a reward ready').toBe(true);
    const hold = await request.post('/api/v1/rewards/hold', { headers: K, data: { customer: holdable.card_number, ttl_seconds: 60 } });
    expect(hold.status()).toBe(201);
    const till = await request.post('/api/owner/rewards/redeem', { headers: H, data: { customer_id: holdable.id } });
    expect(till.status(), 'the till is told the reward is held').toBe(409);
    const { hold_id } = await hold.json();
    expect((await request.delete(`/api/v1/rewards/hold/${hold_id}`, { headers: K })).status()).toBe(200);
  });
});
