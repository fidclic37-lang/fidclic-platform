/**
 * Super admin › Mes paramètres (user, 2026-11-11): profile, 2FA on and off
 * with a real code, sessions, alerts. Local server only; everything is put
 * back (2FA off, names, alerts) so the other specs still sign in.
 */
import { test, expect } from '@playwright/test';
import crypto from 'node:crypto';

const ADMIN = { email: 'admin@fidelitour.com', password: 'Fidelit0ur!Adm' };   // local seed only
test.use({ viewport: { width: 1536, height: 960 } });
test.setTimeout(240_000);

function totp(secret) {
  const A = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
  let bits = '';
  for (const ch of secret.replace(/=+$/, '').toUpperCase()) bits += A.indexOf(ch).toString(2).padStart(5, '0');
  const key = Buffer.from(bits.match(/.{8}/g).map((b) => parseInt(b, 2)));
  const ctr = Buffer.alloc(8);
  ctr.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30000)));
  const h = crypto.createHmac('sha1', key).update(ctr).digest();
  const o = h[h.length - 1] & 15;
  return String(((h.readUInt32BE(o) & 0x7fffffff) % 1e6)).padStart(6, '0');
}

test('a team member edits their profile, turns 2FA on and off, picks their alerts', async ({ page, request }) => {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const login = await (await request.post('/api/auth/login', { data: ADMIN })).json();
  const A = { Authorization: `Bearer ${login.access_token}` };
  const before = await (await request.get('/api/admin/me', { headers: A })).json();
  let secret = null;
  try {
    await page.goto('/login');
    await page.evaluate((t) => localStorage.setItem('fidelitour_access_token', t), login.access_token);
    await page.goto('/admin');
    await page.getByRole('link', { name: 'Mes paramètres' }).first().click();
    await expect(page.getByTestId('my-account')).toBeVisible({ timeout: 60_000 });

    // profile
    await page.locator('#me-ln').fill('Testeur');
    await page.getByTestId('profile-save').click();
    await expect(page.getByText('Profil enregistré.')).toBeVisible();

    // 2FA on with a real code, backup codes shown once
    await page.getByTestId('totp-start').click();
    secret = (await page.getByTestId('totp-secret').innerText()).trim();
    await page.getByLabel('Code à 6 chiffres').fill(totp(secret));
    await page.getByTestId('totp-confirm').click();
    await expect(page.getByTestId('totp-state')).toContainText('Activée', { timeout: 30_000 });
    await expect(page.getByText('Codes de secours — notez-les', { exact: false })).toBeVisible();

    // an alert by e-mail
    const row = page.locator('[data-alert="support"]');
    await row.getByRole('radio', { name: 'Cloche + email' }).click();
    await expect(row.getByRole('radio', { name: 'Cloche + email' })).toHaveAttribute('aria-checked', 'true');
    await page.screenshot({ path: 'test-results/admin-my-account.png', fullPage: true });

    // 2FA off again (password + a fresh code)
    await page.getByLabel('Mot de passe pour désactiver').fill(ADMIN.password);
    await page.getByLabel('Code pour désactiver').fill(totp(secret));
    await page.getByRole('button', { name: 'Désactiver' }).click();
    await expect(page.getByTestId('totp-state')).toHaveText('Désactivée', { timeout: 30_000 });
  } finally {
    // never leave the seed admin behind a 2FA: the other specs sign in with its password
    const now = await (await request.get('/api/admin/me', { headers: A })).json();
    if (now.security?.totp && secret) {
      await request.post('/api/security/2fa/disable', { headers: A, data: { password: ADMIN.password, code: totp(secret) } });
    }
    await request.put('/api/admin/me/profile', { headers: A, data: { last_name: before.profile.last_name || '' } });
    await request.put('/api/admin/me/alerts', { headers: A, data: Object.fromEntries(before.alerts.map((a) => [a.key, a.value])) });
    const back = await (await request.get('/api/admin/me', { headers: A })).json();
    expect(back.security.totp).toBe(false);
    const again = await request.post('/api/auth/login', { data: ADMIN });
    expect((await again.json()).access_token).toBeTruthy();
  }
  expect(errors).toEqual([]);
});
