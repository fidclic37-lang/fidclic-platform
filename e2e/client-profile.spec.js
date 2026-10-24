/**
 * FidClic IA « Profil client » (user, 2026-10-24): what a client's visits say —
 * what they usually take, their basket, whether their rhythm is known yet —
 * the one offer worth sending, which opens the composer pre-filled, and the
 * line the till shows the staff. Local server only.
 */
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
test.use({ viewport: { width: 1536, height: 960 } });

async function setup(page, request) {
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const store = ((br && br.branches) || br || []).find((x) => x.status !== 'closed')?.id || '';
  const SH = { ...H, 'X-FidClic-Store': store };
  const stamp = String(Date.now()).slice(-6);
  const product = `Coupe IA ${stamp}`;
  const made = await (await request.post('/api/owner/catalogue/products', { headers: SH, data: { name: product, price: 22, category: '' } })).json();
  const pub = await (await request.get('/api/join/cafe-lumiere/page')).json();
  const join = async (name, i) => (await request.post('/api/join/cafe-lumiere', { data: {
    name, phone: `07${String(Date.now() + i).slice(-8)}`, postal_code: '37000', birthday: '01/02/1990', consent: true,
    ...((pub.stores || []).length ? { store: pub.stores[0].slug } : {}) } })).json();
  const regular = await join(`Habitude ${stamp}`, 1);
  const once = await join(`Une fois ${stamp}`, 2);
  const scan = async (c) => {
    const r = await request.post('/api/owner/scan', { headers: SH, data: {
      barcode_id: c.barcode_id, items: [{ item_id: made.id, qty: 1 }], branch_id: store || undefined } });
    expect(r.ok(), await r.text()).toBeTruthy();
  };
  for (let i = 0; i < 3; i += 1) await scan(regular);      // three visits today: habits, no rhythm yet
  await scan(once);
  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
    try { sessionStorage.removeItem('ft_pick_store'); } catch (_e) { /* ignore */ }
  }, [login.access_token, store]);
  return { stamp, product, regular, once };
}

async function openProfile(page, name) {
  await page.goto('/dashboard/customers');
  await page.getByPlaceholder('Rechercher un client (nom, email, téléphone…)').fill(name);
  await page.getByRole('button', { name, exact: true }).click();
  const panel = page.getByRole('dialog', { name: 'Profil client' });
  await expect(panel.getByTestId('client-profile')).toBeVisible({ timeout: 10_000 });
  return panel;
}

test('the profile says what the visits say, and the till shows the habit', async ({ page, request }) => {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const { stamp, product, regular } = await setup(page, request);

  const panel = await openProfile(page, `Habitude ${stamp}`);
  await expect(panel.getByTestId('profile-habits')).toContainText(product);
  await expect(panel.getByTestId('profile-habits')).toContainText('3 fois sur 3');
  await expect(panel.getByTestId('profile-basket')).toContainText('22');
  // three scans on one day are not a rhythm: said plainly, no invented date
  await expect(panel.getByTestId('profile-next')).toContainText('venu 1 jour différent');
  await expect(panel.getByTestId('profile-status')).toContainText('Trop tôt pour savoir');
  await expect(panel.getByTestId('profile-kind')).toContainText('Nouveau client');
  await expect(panel.getByTestId('profile-offer')).toContainText('Rien à envoyer');
  await expect(panel.getByTestId('profile-offer-cta')).toHaveCount(0);
  await expect(panel).toContainText(`D'habitude : ${product}`);
  await page.screenshot({ path: 'test-results/client-profile.png' });

  // the till: the same line for the staff, as soon as the card is read
  await page.goto('/dashboard/scan');
  await page.getByRole('button', { name: 'Saisir le code' }).click();
  await page.getByLabel('Code de la carte').fill(regular.barcode_id);
  await expect(page.getByText('Client scanné')).toBeVisible({ timeout: 10_000 });
  await expect(page.getByTestId('client-habit')).toContainText(`D'habitude : ${product} · ~22 €`);
  expect(errors).toEqual([]);
});

test('« Préparer le message » opens the composer with the suggested words, for that client only', async ({ page, request }) => {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const { stamp } = await setup(page, request);

  const panel = await openProfile(page, `Une fois ${stamp}`);
  await expect(panel.getByTestId('profile-kind')).toContainText('Nouveau client');
  await expect(panel.getByTestId('profile-offer')).toContainText('Offre de deuxième visite');
  await expect(panel.getByTestId('profile-offer')).toContainText('Pourquoi ?');
  await panel.getByTestId('profile-offer-cta').click();
  await expect(page).toHaveURL(/\/dashboard\/campaigns/);
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText(/Merci pour votre première visite/).first()).toBeVisible();   // the client's words
  await dialog.getByRole('button', { name: /^Suivant/ }).click();                 // message → destinataires
  await expect(dialog.getByText('1 client choisi')).toBeVisible({ timeout: 20_000 });
  expect(errors).toEqual([]);
});
