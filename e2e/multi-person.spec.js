/**
 * « Plusieurs personnes » at the till (user, 2026-10-30): a mother pays for
 * herself and her children — staff switches « Plusieurs personnes » on, picks
 * how many, then the services as usual; the card gets each one's tampons, the
 * visit counts once. Local server only.
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
  const before = (await (await request.get('/api/owner/card/settings', { headers: SH })).json()).programme;
  expect((await request.put('/api/owner/card/settings', { headers: SH, data: {
    programme: 'stamps', reward_threshold_stamps: 10, multi_person: true, multi_person_max: 4 } })).ok()).toBeTruthy();
  const pub = await (await request.get(`/api/join/${SLUG}/page`)).json();
  const storeSlug = (pub.stores || []).find((s) => s.id === store)?.slug || (pub.stores || [])[0]?.slug;
  const stamp = String(Date.now()).slice(-7);
  const joined = await (await request.post(`/api/join/${SLUG}`, { data: {
    name: `Maman ${stamp}`, phone: `07${stamp}1`, postal_code: '37000', birthday: '01/02/1990', consent: true,
    ...(storeSlug ? { store: storeSlug } : {}) } })).json();
  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
    try { sessionStorage.removeItem('ft_pick_store'); } catch (_e) { /* ignore */ }
  }, [login.access_token, store]);
  const restore = async () => request.put('/api/owner/card/settings', { headers: SH, data: {
    programme: before.type, reward_threshold_stamps: before.reward_threshold_stamps,
    multi_person: before.multi_person.enabled, multi_person_max: before.multi_person.max } });
  return { SH, barcode: joined.barcode_id, restore };
}

test.describe('Plusieurs personnes', () => {
  test.use({ viewport: { width: 1536, height: 960 } });

  test('3 people → +3 tampons, one visit; the most is kept; the setting is on the card page', async ({ page, request }) => {
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    const { SH, barcode, restore } = await setup(page, request);
    try {
      await page.goto('/dashboard/scan');
      await page.getByRole('button', { name: 'Saisir le code' }).click();
      await page.getByLabel('Code de la carte').fill(barcode);
      const box = page.getByTestId('multi-person');
      await expect(box).toBeVisible({ timeout: 10_000 });
      await box.getByRole('switch', { name: 'Plusieurs personnes' }).click();
      await expect(box.getByTestId('persons-count')).toHaveText('2');
      await box.getByRole('button', { name: 'Une personne de plus' }).click();
      await expect(box.getByTestId('persons-count')).toHaveText('3');
      await expect(box).toContainText('tampons de 3 visites');
      // the most (4): « + » stops there
      await box.getByRole('button', { name: 'Une personne de plus' }).click();
      await expect(box.getByRole('button', { name: 'Une personne de plus' })).toBeDisabled();
      await box.getByRole('button', { name: 'Une personne de moins' }).click();
      await expect(box.getByTestId('persons-count')).toHaveText('3');

      await page.getByTestId('visit-items').getByRole('button', { name: /Suivant/ }).click();
      await expect(page.getByTestId('review-persons')).toContainText('3 personnes');
      await page.getByRole('button', { name: /Enregistrer la visite/ }).first().click();
      const summary = page.getByTestId('visit-summary');
      await expect(summary).toContainText('+3 tampons · 3 personnes', { timeout: 15_000 });

      const card = await (await request.get(`/api/owner/scan/card?barcode=${barcode}`, { headers: SH })).json();
      expect(card.balance.value, 'three tampons on the card').toBe(3);
      expect(card.customer.visits, 'one visit').toBe(1);

      // the owner's setting, on the card page
      await page.goto('/dashboard/card');
      await page.getByRole('button', { name: /Paramètres/ }).first().click();
      const setting = page.getByTestId('multi-person-setting');
      await expect(setting).toBeVisible({ timeout: 15_000 });
      await expect(setting).toContainText('Visite à plusieurs personnes');
      await expect(setting).toContainText('4 personnes');
      expect(errors).toEqual([]);
    } finally {
      await restore();
    }
  });
});

test.describe('Plusieurs personnes on a phone', () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

  test('2 people from the phone till: +2 tampons', async ({ page, request }) => {
    const { SH, barcode, restore } = await setup(page, request);
    try {
      await page.goto('/dashboard/scan');
      await page.getByRole('button', { name: 'Saisir le code' }).click();
      await page.getByLabel('Code de la carte').fill(barcode);
      const box = page.getByTestId('multi-person');
      await expect(box).toBeVisible({ timeout: 10_000 });
      await box.getByRole('switch', { name: 'Plusieurs personnes' }).tap();
      await expect(box.getByTestId('persons-count')).toHaveText('2');
      const bar = page.getByTestId('phone-action-bar');
      await bar.getByRole('button', { name: /Suivant/ }).click();
      await expect(page.getByTestId('review-persons')).toContainText('2 personnes');
      await bar.getByRole('button', { name: /Enregistrer/ }).click();
      await expect(page.getByTestId('visit-summary')).toContainText('+2 tampons · 2 personnes', { timeout: 15_000 });
      const card = await (await request.get(`/api/owner/scan/card?barcode=${barcode}`, { headers: SH })).json();
      expect(card.balance.value).toBe(2);
    } finally {
      await restore();
    }
  });
});
