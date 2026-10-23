/**
 * « 🎁 Partagez la carte » from the back of the Wallet card (user, 2026-10-23):
 * a page with the card's QR — the public address a friend scans to sign up as
 * a filleul — and the apps to send the link. Local server only.
 */
import { test, expect } from '@playwright/test';

test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

test('the share page: QR of the public card link, apps, copy', async ({ page, request }) => {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const pub = await (await request.get('/api/join/cafe-lumiere/page')).json();
  const made = await (await request.post('/api/join/cafe-lumiere', { data: {
    name: 'Léa Partage', phone: `07${String(Date.now()).slice(-8)}`, postal_code: '37000', birthday: '01/02/1990', consent: true,
    ...((pub.stores || []).length ? { store: pub.stores[0].slug } : {}) } })).json();
  const bc = made.barcode_id;
  await page.goto(`/card/${bc}/partager`);
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Léa');
  await expect(page.getByRole('heading', { level: 1 })).toContainText('partagez votre carte');
  await expect(page.getByTestId('share-qr').locator('svg')).toBeVisible();
  const url = `${new URL(page.url()).origin}/card/${bc}`;
  await expect(page.getByText(url, { exact: true })).toBeVisible();
  const wa = await page.getByRole('link', { name: 'Partager sur WhatsApp' }).getAttribute('href');
  expect(decodeURIComponent(wa)).toContain(url);
  expect(wa, 'never the owner key').not.toContain(made.card_key);
  for (const name of ['Messenger', 'Facebook', 'X', 'Telegram']) {
    await expect(page.getByRole('link', { name: `Partager sur ${name}` })).toBeVisible();
  }
  await expect(page.getByRole('link', { name: 'Partager par SMS' })).toBeVisible();
  await page.screenshot({ path: 'test-results/card-share.png' });
  // the QR's link, opened by a friend's phone: the signup, as a filleul
  const ctx = await page.context().browser().newContext();
  const friend = await ctx.newPage();
  await friend.goto(url);
  await expect(friend).toHaveURL(new RegExp(`/join/.*\\?p=${bc}`));
  await ctx.close();
  expect(errors).toEqual([]);
});
