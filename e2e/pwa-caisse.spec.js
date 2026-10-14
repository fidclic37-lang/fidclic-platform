// Installed from the Scan page, the icon must open the scanner — not the
// dashboard home (user, 2026-10-14). That is what makes a till usable: one
// tap, scan, nothing else.
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only

test.describe('the scanner installs as its own app', () => {
  test.use({ viewport: { width: 1536, height: 960 } });

  test('the Scan page carries a manifest that opens on the scanner', async ({ page, request }) => {
    const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
    const br = await (await request.get('/api/owner/branches',
      { headers: { Authorization: `Bearer ${login.access_token}` } })).json();
    const store = ((br && br.branches) || br || []).find((b) => b.status !== 'closed');

    await page.goto('/login');
    await page.evaluate(([t, s]) => {
      localStorage.setItem('fidelitour_access_token', t);
      localStorage.setItem('ft_selected_branch_v1', s);
    }, [login.access_token, store.id]);

    await page.goto('/dashboard/scan');
    await expect(page.getByRole('heading', { name: 'Enregistrer une visite' })).toBeVisible();

    const href = await page.evaluate(() =>
      document.querySelector('link[rel="manifest"]')?.getAttribute('href') || '');
    expect(href, 'the Scan page asks for its own manifest').toBe('/manifest-scan.json');

    const m = await (await request.get(href)).json();
    expect(m.start_url, 'the icon opens the scanner').toBe('/dashboard/scan');
    expect(m.display).toBe('standalone');
    expect(m.id, 'its own app, beside the main one').toBe('/dashboard/scan');
    expect(m.icons.length, 'it has icons to install with').toBeGreaterThan(0);

    // …and the rest of the app keeps the site-wide one
    await page.goto('/dashboard');
    const other = await page.evaluate(() =>
      document.querySelector('link[rel="manifest"]')?.getAttribute('href') || '');
    expect(other, 'elsewhere, nothing changes').toBe('/manifest.json');
  });
});
