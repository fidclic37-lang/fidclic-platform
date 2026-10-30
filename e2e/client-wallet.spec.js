/**
 * Clients › a client's « Carte Wallet » (user, 2026-10-30, ROYAL TRIM
 * LIBÉRTÉ: « 80 % des clients doivent rafraîchir leur carte »): where the card
 * is, its iPhones, its last pushes and every registration event with its
 * reason. Local server only.
 */
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
test.use({ viewport: { width: 1536, height: 960 } });

test('Carte Wallet: a card on no iPhone, and a refused registration in its history', async ({ page, request }) => {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const store = ((br && br.branches) || br || []).find((x) => x.status !== 'closed')?.id || '';
  const stamp = String(Date.now()).slice(-6);
  const pub = await (await request.get('/api/join/cafe-lumiere/page')).json();
  const signup = await (await request.post('/api/join/cafe-lumiere', { data: {
    name: `Wallet ${stamp}`, phone: `07${String(Date.now()).slice(-8)}`, postal_code: '37000', birthday: '01/02/1990', consent: true,
    ...((pub.stores || []).length ? { store: pub.stores[0].slug } : {}) } })).json();
  // an iPhone that tries to register with a wrong key — Apple's real callback path
  const reg = await request.post(`/api/passes/v1/devices/E2EDEVICE${stamp}000/registrations/pass.com.fidclic.test/${signup.barcode_id}`, {
    headers: { Authorization: 'ApplePass wrong-key-wrong-key-wrong-key' }, data: { pushToken: `tok${stamp}` } });
  expect(reg.status()).toBe(401);

  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
    try { sessionStorage.removeItem('ft_pick_store'); } catch (_e) { /* ignore */ }
  }, [login.access_token, store]);
  await page.goto('/dashboard/customers');
  await page.getByPlaceholder('Rechercher un client (nom, email, téléphone…)').fill(`Wallet ${stamp}`);
  await page.getByRole('button', { name: `Wallet ${stamp}`, exact: true }).click();
  await expect(page.getByRole('dialog', { name: 'Profil client' })).toBeVisible();
  await page.getByRole('tab', { name: 'Carte Wallet' }).click();
  const panel = page.getByRole('dialog', { name: 'Carte Wallet' });
  await expect(panel.getByTestId('client-wallet')).toBeVisible({ timeout: 10_000 });
  await expect(panel.getByTestId('wallet-state')).toHaveAttribute('data-state', 'none');
  await expect(panel).toContainText('Aucun iPhone inscrit');
  await expect(panel.getByTestId('wallet-event').first()).toContainText("Inscription de l'iPhone refusée");
  await expect(panel.getByTestId('wallet-event').first()).toContainText('clé de la carte invalide');
  await expect(panel).not.toContainText(`E2EDEVICE${stamp}000`);       // device ids shortened
  await page.screenshot({ path: 'test-results/client-wallet.png' });
  expect(errors).toEqual([]);
});
