/**
 * « Mes parrainages » on « Ma carte en ligne » (user, 2026-11-26), in a real
 * browser on the local server (scripts/dev_local.py — demo data in memory):
 *   • the Parrainage view: « Le plaisir se partage », « notre programme », what
 *     each side gets in the shop's own kind (tampons / points / offer), the
 *     friends this card invited — « Récompensé » once the friend came (a real
 *     till scan), « En attente » before — first names only;
 *   • the Récompenses tab (the Wallet's rewards button) sums it up and opens
 *     the Parrainage view in the same page, the bottom bar still there;
 *   • FidClic colours (blue #1450B8) whatever the card's theme.
 */
import { test, expect } from '@playwright/test';
import fs from 'node:fs';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
let phone = Number(String(Date.now()).slice(-8));
const SHOTS = process.env.SHOTS_DIR || '';

async function owner(request) {
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const store = ((br && br.branches) || br || []).find((b) => b.status !== 'closed')?.id || '';
  return { H, store };
}

async function settings(request, H, extra) {
  const r = await request.put('/api/owner/referrals/config', {
    headers: H,
    data: {
      enabled: true, minimum_visits_to_earn: 1, reward_mode: 'once',
      referrer_reward_kind: 'stamps', referee_reward_kind: 'stamps',
      referrer_reward_stamps: 2, referee_reward_stamps: 2, ...extra,
    },
  });
  expect(r.status()).toBe(200);
}

async function join(request, name, parrain) {
  const pub = await (await request.get('/api/join/cafe-lumiere/page')).json();
  phone += 1;
  const r = await request.post('/api/join/cafe-lumiere', {
    data: {
      name, phone: `07${String(phone).padStart(8, '0').slice(-8)}`, postal_code: '37000', birthday: '1990-05-04',
      accepted_terms: true, consent: true, ...((pub.stores || []).length ? { store: pub.stores[0].slug } : {}),
      ...(parrain ? { parrain_barcode: parrain } : {}),
    },
  });
  expect(r.status()).toBeLessThan(300);
  return r.json();
}

async function scan(request, H, store, bc) {
  const r = await request.post('/api/owner/scan', {
    headers: { ...H, 'X-FidClic-Store': store }, data: { barcode_id: bc, amount_paid: 12, branch_id: store || undefined } });
  expect(r.ok(), await r.text()).toBeTruthy();
}

async function shot(page, name) {
  if (!SHOTS) return;
  fs.mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });
}

const noSideScroll = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

test.describe.serial('mes parrainages sur la carte', () => {
  let saved = null;
  test.beforeAll(async ({ request }) => {
    const { H } = await owner(request);
    const v = await (await request.get('/api/owner/referrals/overview', { headers: H })).json();
    saved = { ...v.config, enabled: v.enabled };
  });
  test.afterAll(async ({ request }) => {
    if (!saved) return;
    const { H } = await owner(request);
    await request.put('/api/owner/referrals/config', { headers: H, data: saved });
  });

  test('the Parrainage view: rewards, friends, Récompensé / En attente — then the Récompenses summary', async ({ page, request }) => {
    const { H, store } = await owner(request);
    await settings(request, H, {});
    const parrain = await join(request, 'Marie Parrain');
    const thomas = await join(request, 'Thomas Filleul', parrain.barcode_id);
    await join(request, 'Sarah Attente', parrain.barcode_id);
    await scan(request, H, store, thomas.barcode_id);              // Thomas came: both paid

    const bc = parrain.barcode_id;
    await page.goto(`/card/${bc}?k=${parrain.card_key}`);
    await page.getByRole('button', { name: /Parrainer un proche/ }).click();
    const box = page.getByTestId('parrainage');
    await expect(box).toBeVisible();
    await expect(box).toContainText('Le plaisir se partage.');
    await expect(box).toContainText('Invitez un ami à rejoindre notre programme de fidélité');
    await expect(box).not.toContainText('votre programme');
    await expect(page.getByTestId('parrainage-me')).toHaveText('+2 tampons');
    await expect(page.getByTestId('parrainage-friend')).toHaveText('+2 tampons');
    await expect(page.getByTestId('parrainage-invited')).toHaveText('2');
    await expect(page.getByTestId('parrainage-earned')).toHaveText('2');
    await expect(box).toContainText('Tampons gagnés');

    const rows = page.getByTestId('parrainage-row');
    await expect(rows).toHaveCount(2);
    const t = rows.filter({ hasText: 'Thomas' });
    const s = rows.filter({ hasText: 'Sarah' });
    await expect(t).toHaveAttribute('data-status', 'rewarded');
    await expect(t).toContainText('Récompensé');
    await expect(t).toContainText('2 tampons pour vous');
    await expect(s).toHaveAttribute('data-status', 'pending');
    await expect(s).toContainText('En attente');
    await expect(s).toContainText('1re visite à faire');
    await expect(box, 'a first name only').not.toContainText('Filleul');
    await expect(box).not.toContainText('Attente ');

    // FidClic blue on every shop's page, the bottom bar still there, the QR below
    const blue = await page.getByTestId('parrainage-invite').evaluate((el) => getComputedStyle(el).backgroundColor);
    expect(blue).toBe('rgb(20, 80, 184)');
    await expect(page.getByRole('navigation', { name: 'Ma carte en ligne' })).toBeVisible();
    await expect(page.getByTestId('share-qr').locator('svg')).toBeVisible();
    expect(await noSideScroll(page)).toBeLessThanOrEqual(0);
    await shot(page, 'parrainage-view');

    // « Inviter un ami » with no share sheet: the QR comes into view
    await page.evaluate(() => { try { Object.defineProperty(navigator, 'share', { value: undefined, configurable: true }); } catch (_e) { /* */ } });
    await page.getByTestId('parrainage-invite').click();
    await expect(page.getByTestId('share-qr')).toBeInViewport();

    // the Récompenses tab — where the Wallet's rewards button lands
    await page.getByRole('tab', { name: 'Récompenses' }).click();
    const mini = page.getByTestId('parrainage-mini');
    await expect(mini).toBeVisible();
    await expect(mini).toContainText('+2 tampons');
    await expect(mini).toContainText('2Amis invités');
    await expect(mini).toContainText('2Tampons gagnés');
    await expect(mini).toContainText('1En attente');
    await shot(page, 'recompenses-tab');
    await mini.getByRole('button', { name: /Parrainage/ }).click();
    await expect(page).toHaveURL(new RegExp(`/card/${bc}\\?onglet=parrainage$`));
    await expect(page.getByTestId('parrainage')).toBeVisible();
    await expect(page.getByTestId('card-page')).toBeVisible();
  });

  test('points for the parrain, an offer for the friend, paid from the 2nd visit', async ({ page, request }) => {
    const { H, store } = await owner(request);
    await settings(request, H, {
      minimum_visits_to_earn: 2, referrer_reward_kind: 'points', referrer_reward_points: 50,
      referee_reward_kind: 'offer', referee_reward_offer: 'Un café offert',
    });
    const parrain = await join(request, 'Paul Points');
    const lea = await join(request, 'Léa Deux', parrain.barcode_id);
    await scan(request, H, store, lea.barcode_id);                 // 1 visit of 2: still pending

    await page.goto(`/card/${parrain.barcode_id}?k=${parrain.card_key}&onglet=parrainage`);
    await expect(page.getByTestId('parrainage-me')).toHaveText('+50 points');
    await expect(page.getByTestId('parrainage-friend')).toHaveText('Un café offert');
    await expect(page.getByTestId('parrainage')).toContainText('quand votre ami vient 2 fois');
    await expect(page.getByTestId('parrainage')).toContainText('à sa 2e visite');
    const row = page.getByTestId('parrainage-row').filter({ hasText: 'Léa' });
    await expect(row).toHaveAttribute('data-status', 'pending');
    await expect(row).toContainText('1 visite sur 2');
    await expect(page.getByTestId('parrainage-earned')).toHaveText('0');
    await expect(page.getByTestId('parrainage')).toContainText('Points gagnés');
    await shot(page, 'parrainage-points-pending');

    await scan(request, H, store, lea.barcode_id);                 // the 2nd visit: paid
    await page.reload();
    await expect(row).toHaveAttribute('data-status', 'rewarded');
    await expect(row).toContainText('50 points pour vous');
    await expect(page.getByTestId('parrainage-earned')).toHaveText('50');
  });

  test('nobody invited yet: an empty list that says what to do', async ({ page, request }) => {
    const { H } = await owner(request);
    await settings(request, H, {});
    const solo = await join(request, 'Solo Personne');
    await page.goto(`/card/${solo.barcode_id}?k=${solo.card_key}&onglet=parrainage`);
    await expect(page.getByTestId('parrainage-invited')).toHaveText('0');
    await expect(page.getByTestId('parrainage-list')).toContainText('Aucun ami invité');
    await shot(page, 'parrainage-empty');
  });
});
