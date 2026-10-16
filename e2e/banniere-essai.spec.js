/**
 * « Masquer » on the trial banner (user, 2026-10-16: the cross hid it, then a
 * refresh brought it straight back).
 *
 * The browser's half: the cross tells the server, and a page that loads with
 * banner_hidden draws no banner. The server's half — that it is kept on the
 * account, that the reminder and the expired banner ignore it, and who may
 * hide it — is api/tests/test_trial_banner.py.
 */
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
const QUIET = {
  is_in_trial: true, is_expired: false, subscription_status: 'trialing',
  days_left: 25, hours_left: 600, trial_ends_at: '2026-11-10T12:00:00+00:00',
  trial_duration_days: 30, reminder_window: false, reminder_days_before: 1,
  plan: 'vip', plan_price: 108, available_plans: [], banner_hidden: false,
};

test.use({ viewport: { width: 1536, height: 960 } });

test('the cross hides it, and a refresh does not bring it back', async ({ page, request }) => {
  // the shop of the seed pays; this test needs a shop on its trial
  let hidden = false;
  const posts = [];
  await page.route('**/api/owner/trial-status', (r) => r.fulfill({
    contentType: 'application/json', body: JSON.stringify({ ...QUIET, banner_hidden: hidden }),
  }));
  await page.route('**/api/owner/trial-status/hide-banner', (r) => {
    posts.push(r.request().method());
    hidden = true;
    return r.fulfill({ contentType: 'application/json', body: JSON.stringify({ ...QUIET, banner_hidden: true }) });
  });

  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  await page.goto('/login');
  await page.evaluate((t) => {
    localStorage.setItem('fidelitour_access_token', t);
    try { sessionStorage.removeItem('ft_pick_store'); } catch (_e) { /* ignore */ }
  }, login.access_token);

  await page.goto('/dashboard');
  const banner = page.getByText(/jours? d'essai gratuit/);
  await expect(banner.first()).toBeVisible({ timeout: 20000 });

  await page.getByRole('button', { name: 'Masquer' }).click();
  await expect(banner).toHaveCount(0);
  await expect.poll(() => posts.length, { message: 'the account is told' }).toBe(1);
  expect(posts[0]).toBe('POST');

  await page.reload();
  await expect(page.getByRole('heading').first()).toBeVisible({ timeout: 20000 });
  await expect(banner, 'it stays away after a refresh').toHaveCount(0);
});
