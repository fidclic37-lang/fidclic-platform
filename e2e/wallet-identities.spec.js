/**
 * Super Admin › Commerces says where each business's own Apple Wallet id
 * stands (user, 2026-10-30: one id per business, made by the platform). On
 * the local server App Store Connect is not set, so it says so — the cards
 * stay under the common id. Local server only.
 */
import { test, expect } from '@playwright/test';

const ADMIN = { email: 'admin@fidelitour.com', password: 'Fidelit0ur!Adm' };   // local seed only
test.use({ viewport: { width: 1536, height: 960 } });

test('Commerces: the Apple Wallet line, and no key in the answer', async ({ page, request }) => {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const login = await (await request.post('/api/auth/login', { data: ADMIN })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const api = await request.get('/api/admin/wallet-identities', { headers: H });
  expect(api.status()).toBe(200);
  const body = await api.text();
  expect(body).not.toContain('PRIVATE KEY');
  expect(JSON.parse(body).configured).toBe(false);

  await page.goto('/login');
  await page.evaluate((t) => localStorage.setItem('fidelitour_access_token', t), login.access_token);
  await page.goto('/admin/commerces');
  const line = page.getByTestId('wallet-identities');
  await expect(line).toBeVisible({ timeout: 15_000 });
  await expect(line).toContainText('App Store Connect');
  await page.screenshot({ path: 'test-results/wallet-identities.png' });
  expect(errors).toEqual([]);
});

test('a business owner cannot read it', async ({ request }) => {
  const login = await (await request.post('/api/auth/login', { data: { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' } })).json();
  const r = await request.get('/api/admin/wallet-identities', { headers: { Authorization: `Bearer ${login.access_token}` } });
  expect(r.status()).toBe(403);
});

test('Super Admin imports a certificate by hand: a refusal with its reason, then a valid one', async ({ page, request }) => {
  const { execSync } = await import('node:child_process');
  const fs = await import('node:fs');
  const os = await import('node:os');
  const path = await import('node:path');
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const login = await (await request.post('/api/auth/login', { data: ADMIN })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const list = await (await request.get('/api/admin/wallet-identities', { headers: H })).json();
  const biz = list.businesses.find((b) => !list.rows.some((r) => r.tenant_id === b.id)) || list.businesses[0];
  const ident = `pass.com.fidclic.e2e-${Date.now().toString(36)}`;
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'wid-'));
  execSync(`openssl req -x509 -newkey rsa:2048 -nodes -days 30 -subj "/UID=${ident}/CN=Pass Type ID: ${ident}" `
    + `-keyout ${dir}/k.pem -out ${dir}/c.pem`, { stdio: 'ignore' });
  const cert = fs.readFileSync(`${dir}/c.pem`, 'utf8');
  const key = fs.readFileSync(`${dir}/k.pem`, 'utf8');

  await page.goto('/login');
  await page.evaluate((t) => localStorage.setItem('fidelitour_access_token', t), login.access_token);
  await page.goto('/admin/commerces');
  const line = page.getByTestId('wallet-identities');
  await expect(line).toBeVisible({ timeout: 15_000 });
  await line.getByRole('button', { name: 'Importer un certificat' }).click();
  const form = page.getByTestId('wallet-identity-import');
  await form.getByRole('combobox', { name: 'Commerce' }).selectOption(biz.id);
  await form.getByLabel(/Identifiant/).fill(ident);
  await form.getByLabel('Certificat (PEM)').fill(cert);
  await form.getByLabel(/Clé privée/).fill('-----BEGIN PRIVATE KEY-----\nnope\n-----END PRIVATE KEY-----');
  await form.getByRole('button', { name: 'Importer' }).click();
  await expect(form.getByRole('status')).toContainText('Clé privée illisible');

  await form.getByLabel(/Clé privée/).fill(key);
  await form.getByRole('button', { name: 'Importer' }).click();
  await expect(form.getByRole('status')).toContainText(`Identifiant ${ident} prêt`);
  await expect(page.getByTestId('wallet-identities-manual')).toContainText('importé à la main');
  const after = await (await request.get('/api/admin/wallet-identities', { headers: H })).text();
  expect(after).not.toContain('PRIVATE KEY');
  expect(JSON.parse(after).rows.find((r) => r.tenant_id === biz.id)).toMatchObject({ identifier: ident, status: 'ready', source: 'manual' });
  await page.screenshot({ path: 'test-results/wallet-identity-import.png' });
  expect(errors).toEqual([]);
});

test('a business owner cannot import', async ({ request }) => {
  const login = await (await request.post('/api/auth/login', { data: { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' } })).json();
  const r = await request.post('/api/admin/wallet-identities/whatever/upload', {
    headers: { Authorization: `Bearer ${login.access_token}` }, data: { certificate_pem: 'x', key_pem: 'y' } });
  expect(r.status()).toBe(403);
});
