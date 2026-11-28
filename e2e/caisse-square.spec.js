// Caisse connector, Square (api/features/pos_connectors.py): the owner's
// whole journey in the browser, against the real local server and a local
// stand-in for Square's sandbox (SQUARE_API_BASE, sandbox only):
//   Paramètres › API & Intégrations › Caisse › « Connecter Square » → Square's
//   page (stand-in) → back « connectée » → each Square location mapped to a
//   store → a scanned card on a Square sale arrives (signed webhook) → the
//   page counts it → a forged connect link is refused → Déconnecter.
// Run with: SQUARE_ENV=sandbox SQUARE_APPLICATION_ID=sandbox-e2e SQUARE_APPLICATION_SECRET=e2e-secret
//   SQUARE_WEBHOOK_SIGNATURE_KEY=e2e-key SQUARE_API_BASE=http://127.0.0.1:$E2E_SQUARE_PORT E2E_SQUARE_PORT=…
import { test, expect, request as pw } from '@playwright/test';
import http from 'node:http';
import crypto from 'node:crypto';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
const ADMIN = { email: 'admin@fidelitour.com', password: 'Fidelit0ur!Adm' };        // local seed only
const SQ_PORT = Number(process.env.E2E_SQUARE_PORT || 0);
const SIG_KEY = process.env.SQUARE_WEBHOOK_SIGNATURE_KEY || '';

let fake;
const refs = {};             // Square customer id → reference id (the card's code)

test.skip(!SQ_PORT || !SIG_KEY, 'needs the Square stand-in env (see the header)');

test.beforeAll(async () => {
  fake = http.createServer((req, res) => {
    let body = '';
    req.on('data', (c) => { body += c; });
    req.on('end', () => {
      const j = body ? JSON.parse(body) : {};
      const send = (code, obj) => { res.writeHead(code, { 'content-type': 'application/json' }); res.end(JSON.stringify(obj)); };
      const path = req.url.split('?')[0];
      if (path === '/oauth2/token') return send(200, { access_token: 'EAAA-e2e', refresh_token: 'EQAA-e2e', merchant_id: 'E2E-MERCH',
        expires_at: new Date(Date.now() + 30 * 86400e3).toISOString() });
      if (path === '/oauth2/revoke') return send(200, { success: true });
      if (path === '/v2/merchants/me') return send(200, { merchant: { id: 'E2E-MERCH', business_name: 'Démo Square' } });
      if (path === '/v2/locations') return send(200, { locations: [{ id: 'LOC-A', name: 'Comptoir', currency: 'EUR', status: 'ACTIVE' },
        { id: 'LOC-B', name: 'Terrasse', currency: 'EUR', status: 'ACTIVE' }] });
      if (path === '/v2/customers/bulk-create') {
        const out = {};
        for (const [k, v] of Object.entries(j.customers || {})) { refs[`SQ-${k}`] = v.reference_id; out[k] = { customer: { id: `SQ-${k}` } }; }
        return send(200, { responses: out });
      }
      if (path.startsWith('/v2/customers/')) {
        const id = path.split('/').pop();
        return refs[id] ? send(200, { customer: { id, reference_id: refs[id] } }) : send(404, { errors: [{ code: 'NOT_FOUND' }] });
      }
      if (path === '/v2/payments') return send(200, { payments: [] });
      if (path === '/v2/refunds') return send(200, { refunds: [] });
      return send(404, {});
    });
  });
  await new Promise((ok) => fake.listen(SQ_PORT, '127.0.0.1', ok));
});

test.afterAll(async () => {
  if (fake) await new Promise((ok) => fake.close(ok));
  const back = JSON.parse(process.env.E2E_POS_RESTORE || 'null');
  if (!back || !back.plan) return;
  const admin = await pw.newContext({ baseURL: test.info().project.use.baseURL });
  const adm = await (await admin.post('/api/auth/login', { data: ADMIN })).json();
  await admin.post(`/api/admin/commerces/${back.tid}/plan`, { headers: { Authorization: `Bearer ${adm.access_token}` }, data: { plan: back.plan } });
  await admin.dispose();
});

test('Square: connect, map the stores, a scanned sale arrives, disconnect', async ({ page, request, baseURL }) => {
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  // the caisse rides on « API & Intégrations »: the local seed's plan may not have it (local seed only)
  const locked = await request.get('/api/owner/pos', { headers: H });
  if (locked.status() === 403) {
    const admin = await pw.newContext({ baseURL });
    const adm = await (await admin.post('/api/auth/login', { data: ADMIN })).json();
    const A = { Authorization: `Bearer ${adm.access_token}` };
    const { plans } = await (await admin.get('/api/admin/plan-limits', { headers: A })).json();
    const detail = (await locked.json()).detail;
    const was = (plans || []).find((p) => p.label === detail.plan);
    const moved = await admin.post(`/api/admin/commerces/${login.tenant_id}/plan`, { headers: A, data: { plan: detail.upgrade.key } });
    expect(moved.status()).toBe(200);
    await admin.dispose();
    process.env.E2E_POS_RESTORE = JSON.stringify({ tid: login.tenant_id, plan: was ? was.key : null });
  }

  await page.setViewportSize({ width: 1536, height: 960 });
  await page.goto('/login');
  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const stores = ((br && br.branches) || br || []).filter((b) => b.status !== 'closed');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
  }, [login.access_token, stores[0] && stores[0].id]);

  // 1. the Caisse tab offers Square
  await page.goto('/dashboard/parametres/api?tab=caisse');
  const root = page.getByTestId('caisse-connectors');
  await expect(root).toBeVisible();
  const btn = root.getByRole('button', { name: /Connecter Square/ });
  await expect(btn).toBeEnabled();

  // 2. « Connecter Square » → Square's page (the stand-in) — we answer as Square would: back with a code
  let authorize = '';
  await page.route(`http://127.0.0.1:${SQ_PORT}/oauth2/authorize**`, async (route) => {
    authorize = route.request().url();
    const state = new URL(authorize).searchParams.get('state');
    await route.fulfill({ status: 302, headers: { location: `${baseURL}/api/pos/square/callback?code=e2e-code&state=${encodeURIComponent(state)}` } });
  });
  await btn.click();
  // the page was already on Paramètres: wait for the round trip through « Square », not for the URL
  await expect(page.getByRole('status')).toContainText('Caisse connectée');
  expect(new URL(authorize).searchParams.get('client_id')).toBe(process.env.SQUARE_APPLICATION_ID);
  await expect(page, 'the ?caisse= note leaves the URL once read').not.toHaveURL(/caisse=/);
  const card = page.getByTestId('caisse-square');
  await expect(card).toContainText('Connectée');
  await expect(card).toContainText('Démo Square');
  await expect(card, 'never a token on the page').not.toContainText('EAAA');

  // 3. each Square location → a FidClic store
  const target = stores[1] || stores[0];
  if (target) {
    await card.getByLabel('Établissement pour Terrasse').selectOption(target.id);
    await expect(page.getByRole('status')).toContainText('Établissement enregistré');
  }

  // 4. the cards go to Square (the tick's job; « Vérifier maintenant » does it at once)
  await card.getByRole('button', { name: /Vérifier maintenant/ }).click();
  await expect(page.getByRole('status')).toContainText('Vérification faite');
  const sqCustomer = Object.keys(refs)[0];
  expect(sqCustomer, 'at least one card pushed to Square').toBeTruthy();
  expect(refs[sqCustomer], 'the reference id is the card code').toMatch(/FT-/i);

  // 5. Square rings: a finished sale with that customer, at the Terrasse
  const payId = `E2E-PAY-${Date.now()}`;
  const event = JSON.stringify({ merchant_id: 'E2E-MERCH', type: 'payment.updated', event_id: `ev-${payId}`, created_at: new Date().toISOString(),
    data: { type: 'payment', id: payId, object: { payment: { id: payId, status: 'COMPLETED', amount_money: { amount: 1490, currency: 'EUR' },
      location_id: 'LOC-B', customer_id: sqCustomer, created_at: new Date().toISOString() } } } });
  const url = process.env.SQUARE_WEBHOOK_URL || `${baseURL}/api/pos/square/webhook`;
  const sig = crypto.createHmac('sha256', SIG_KEY).update(url + event).digest('base64');
  const forged = await request.post('/api/pos/square/webhook', { data: event, headers: { 'content-type': 'application/json', 'x-square-hmacsha256-signature': 'AAAA' } });
  expect(forged.status(), 'a forged signature is refused').toBe(401);
  const rang = await request.post('/api/pos/square/webhook', { data: event, headers: { 'content-type': 'application/json', 'x-square-hmacsha256-signature': sig } });
  expect(rang.status(), await rang.text()).toBe(200);
  await request.post('/api/pos/square/webhook', { data: event, headers: { 'content-type': 'application/json', 'x-square-hmacsha256-signature': sig } });

  await page.reload();
  await page.getByRole('button', { name: 'Caisse' }).click();
  const tiles = page.getByTestId('caisse-square');
  await expect(tiles.getByText('Tickets aujourd’hui').locator('..')).toContainText('1');
  await expect(tiles.getByText('Avec une carte FidClic').locator('..')).toContainText('1');

  // 6. a forged connect link is refused, with a plain sentence
  await page.goto('/api/pos/square/callback?code=x&state=forged');
  await expect(page).toHaveURL(/\/dashboard\/parametres\/api/);
  await expect(page.getByRole('status')).toContainText('expiré');

  // 7. Déconnecter
  page.once('dialog', (d) => d.accept());
  await page.getByTestId('caisse-square').getByRole('button', { name: /Déconnecter/ }).click();
  await expect(page.getByRole('status')).toContainText('déconnectée');
  await expect(page.getByTestId('caisse-square')).toHaveCount(0);
  await expect(page.getByTestId('caisse-connectors').getByRole('button', { name: /Connecter Square/ })).toBeVisible();
});
