/**
 * The card page asks the server only what it needs, once (user, 2026-11-21,
 * PR A: a client's iPhone registration was lost while the server was busy).
 * The page opened right after « Rejoindre » asked « notification status »
 * twice — once before the card had arrived, once after.
 *
 *   · each card question goes out once per page load
 *   · the card itself is asked once
 *
 * Local server and demo shop only.
 */
import { test, expect } from '@playwright/test';

const SLUG = 'cafe-lumiere';
const SAFARI = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1';

test.use({ userAgent: SAFARI, viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

test('the card page asks each question once', async ({ page }) => {
  await page.goto(`/join/${SLUG}`);
  await expect(page.getByLabel('Nom complet')).toBeVisible();
  const store = page.getByLabel('Votre établissement');
  if (await store.count()) await store.selectOption({ index: 1 });
  await page.getByLabel('Nom complet').fill('Requêtes Test');
  await page.locator('#join-phone').fill(`06${String(Date.now()).slice(-8)}`);
  await page.getByLabel('Code postal').fill('37000');
  await page.getByLabel(/Date de naissance/).fill('03041992');
  await page.locator('#join-form input[type="checkbox"]').check();
  await page.getByRole('button', { name: /Rejoindre/ }).click();
  await expect(page.getByText('Félicitations !')).toBeVisible();
  const href = await page.getByRole('link', { name: /Ajouter à Apple Wallet|Voir ma carte/ }).first().getAttribute('href').catch(() => null);
  const card = (page.url().match(/FT-[A-Z0-9]+/) || (href || '').match(/FT-[A-Z0-9]+/) || [])[0];
  expect(card, 'the new card number').toBeTruthy();

  const asked = [];
  page.on('request', (r) => {
    const u = new URL(r.url());
    if (u.pathname.startsWith('/api/card/')) asked.push(`${r.method()} ${u.pathname}`);
  });
  await page.goto(`/card/${card}`);
  await expect(page.getByText(/Requêtes Test|Requêtes/).first()).toBeVisible({ timeout: 15_000 });
  await page.waitForTimeout(2500);                       // whatever the page asks after it shows

  const count = (p) => asked.filter((a) => a === p).length;
  expect(count(`GET /api/card/${card}/notification-status`), asked.join('\n')).toBe(1);
  expect(count(`GET /api/card/${card}`), asked.join('\n')).toBe(1);
  const dup = asked.filter((a, i) => asked.indexOf(a) !== i && !a.startsWith('POST'));
  expect(dup, 'no question asked twice').toEqual([]);
});
