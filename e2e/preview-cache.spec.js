// The card page keeps its last preview (user, 2026-10-13: « PREVIEW OF LOYALTY
// CARD KYUN LOAD N HO RHA »): opened again while the server is slow or fails,
// the phone shows the last card at once, never an empty « Aperçu indisponible ».
// Runs against the local server only (scripts/dev_local.py — demo data in memory).
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only

test.use({ viewport: { width: 1536, height: 960 } });

test('the last preview shows at once when the server fails', async ({ page, request }) => {
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const br = await (await request.get('/api/owner/branches', { headers: { Authorization: `Bearer ${login.access_token}` } })).json();
  const store = ((br && br.branches) || br || []).find((b) => b.status !== 'closed')?.id || '';
  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
  }, [login.access_token, store]);

  // a first visit: the server's preview, kept
  await page.goto('/dashboard/card');
  const phone = page.getByText('Aperçu de la carte sur iPhone');
  await expect(phone).toBeVisible();
  await expect.poll(() => page.evaluate(() => Object.keys(localStorage).filter((k) => k.startsWith('fidclic:pv:')).length),
    { timeout: 30_000 }).toBeGreaterThan(0);

  // the server now fails every preview
  await page.route('**/api/owner/wallet/preview', (r) => r.fulfill({ status: 504, body: 'timeout' }));
  await page.reload();
  await expect(phone).toBeVisible();
  await expect(page.getByText('Dernier aperçu — mise à jour au prochain changement')).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText('Aperçu indisponible')).toHaveCount(0);
  await expect(page.locator('[translate="no"]').filter({ hasText: /TAMPONS|POINTS/ }).first(), 'the card is on the phone').toBeVisible();
});
