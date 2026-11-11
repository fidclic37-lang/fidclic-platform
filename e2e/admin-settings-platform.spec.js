/**
 * Super admin › Paramètres › Plateforme (user, 2026-11-11): sign-ups closed
 * show their message on /register; the maintenance banner shows on a shop's
 * dashboard. Local server only; everything is put back at the end.
 */
import { test, expect } from '@playwright/test';

const ADMIN = { email: 'admin@fidelitour.com', password: 'Fidelit0ur!Adm' };          // local seed only
const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };     // local seed only
test.use({ viewport: { width: 1536, height: 960 } });
test.setTimeout(240_000);

test('sign-ups closed and the maintenance banner, end to end', async ({ page, request, browser }, info) => {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const admin = await (await request.post('/api/auth/login', { data: ADMIN })).json();
  const A = { Authorization: `Bearer ${admin.access_token}` };
  try {
    await page.goto('/login');
    await page.evaluate((t) => localStorage.setItem('fidelitour_access_token', t), admin.access_token);
    await page.goto('/admin/parametres');
    await page.getByRole('tab', { name: 'Plateforme' }).click();
    await expect(page.getByTestId('signups-state')).toHaveText('Ouvertes', { timeout: 60_000 });

    // close sign-ups with a message
    await page.locator('#pf-sign').fill('Lancement le 1er décembre !');
    await page.getByRole('button', { name: 'Enregistrer' }).first().click();
    await page.getByTestId('signups-switch').click();
    await expect(page.getByTestId('signups-state')).toHaveText('Fermées');

    // the banner, no dates = shown now
    await page.locator('#pf-ban').fill('Maintenance e2e ce soir 22:00–22:30');
    await page.getByRole('radio', { name: 'Important' }).click();
    await page.getByTestId('banner-save').click();
    await expect(page.getByTestId('banner-state')).toHaveText('Affiché en ce moment.');
    await page.screenshot({ path: 'test-results/admin-settings-platform.png', fullPage: true });

    // a visitor on /register reads the message, no form
    const v = await browser.newContext({ baseURL: info.project.use.baseURL });
    const vp = await v.newPage();
    await vp.goto('/register');
    await expect(vp.getByTestId('signups-closed')).toHaveText('Lancement le 1er décembre !', { timeout: 30_000 });
    await expect(vp.locator('form')).toBeHidden();
    await v.close();

    // a shop's dashboard shows the banner
    const owner = await (await request.post('/api/auth/login', { data: OWNER })).json();
    expect(owner.access_token).toBeTruthy();                  // sign-in still works with sign-ups closed
    const OH = { Authorization: `Bearer ${owner.access_token}` };
    const br = await (await request.get('/api/owner/branches', { headers: OH })).json();
    const store = ((br && br.branches) || br || []).find((b) => b.status !== 'closed')?.id || '';
    const o = await browser.newContext({ baseURL: info.project.use.baseURL, viewport: { width: 1536, height: 960 } });
    const op = await o.newPage();
    op.on('pageerror', (e) => errors.push(e.message));
    await op.goto('/login');
    await op.evaluate(([t, s]) => { localStorage.setItem('fidelitour_access_token', t); if (s) localStorage.setItem('ft_selected_branch_v1', s); }, [owner.access_token, store]);
    await op.goto('/dashboard');
    await expect(op.getByTestId('platform-banner')).toContainText('Maintenance e2e', { timeout: 60_000 });
    await op.screenshot({ path: 'test-results/owner-platform-banner.png', fullPage: false });
    await op.getByRole('button', { name: 'Masquer le bandeau' }).click();
    await expect(op.getByTestId('platform-banner')).toHaveCount(0);
    await o.close();
  } finally {
    await request.put('/api/admin/settings/platform', { headers: A, data: { signups_open: true, banner: null, signups_message: null } });
  }
  expect(errors).toEqual([]);
});
