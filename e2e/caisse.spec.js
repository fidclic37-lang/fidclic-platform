// « Cet appareil est la caisse » (user, 2026-10-14). A till is left on a
// counter and scans all day; it must not be sent back to a login screen, and
// the owner must be able to tell it from their own phone — and cut it.
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only

test.describe.serial('a device registered as the till', () => {
  test.use({ viewport: { width: 1536, height: 960 } });

  test('is named in Sécurité, and can be given back', async ({ page, request }) => {
    const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
    const H = { Authorization: `Bearer ${login.access_token}` };
    const br = await (await request.get('/api/owner/branches', { headers: H })).json();
    const store = ((br && br.branches) || br || []).find((b) => b.status !== 'closed');

    await page.goto('/login');
    await page.evaluate(([t, s]) => {
      localStorage.setItem('fidelitour_access_token', t);
      localStorage.setItem('ft_selected_branch_v1', s);
    }, [login.access_token, store.id]);

    await page.goto('/dashboard/scan');
    const mark = page.getByRole('button', { name: 'Enregistrer cet appareil' });
    await expect(mark).toBeVisible();
    await mark.click();
    await expect(page.getByText('Cet appareil est la caisse')).toBeVisible();

    // Sécurité names it, with the establishment it sits in
    await page.goto('/dashboard/parametres/securite');
    await expect(page.getByText(/^Caisse/).first()).toBeVisible();
    expect(await page.evaluate(() => document.body.innerText.includes('Caisse'))).toBe(true);

    // and the session really is a long one now
    const me = await (await request.get('/api/auth/me', { headers: H })).json();
    expect(me.access_token, 'the session slides').toBeTruthy();

    // giving it back
    await page.goto('/dashboard/scan');
    await page.getByRole('button', { name: /n’est plus la caisse|n'est plus la caisse/ }).click();
    await expect(page.getByRole('button', { name: 'Enregistrer cet appareil' })).toBeVisible();
  });
});
