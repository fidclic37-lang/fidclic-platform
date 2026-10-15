/**
 * « Importer depuis une photo du menu » (2026-10-15): a phone photo is
 * 3–5 MB, over Vercel's 4.5 MB body once in base64 — the page sends it at
 * 1600 px as JPEG. Local server only; the vision call itself is stubbed.
 */
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only
test.use({ viewport: { width: 1536, height: 960 } });

test('a big phone photo leaves the page small, as JPEG, and its products come back', async ({ page, request }) => {
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const br = await (await request.get('/api/owner/branches', { headers: { Authorization: `Bearer ${login.access_token}` } })).json();
  const store = ((br && br.branches) || br || []).find((x) => x.status !== 'closed')?.id || '';
  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
    try { sessionStorage.removeItem('ft_pick_store'); } catch (_e) { /* ignore */ }
  }, [login.access_token, store]);

  let sent = null;
  await page.route('**/api/owner/catalog/parse-menu', async (route) => {
    sent = route.request().postDataJSON();
    await route.fulfill({ json: { items: [{ name: 'Coupe + barbe+ coiffage', price: 29, category: 'Coupe / Coiffage / Barbe' }] } });
  });

  await page.goto('/dashboard/catalogue');
  await page.getByRole('button', { name: /Ajouter un produit/ }).first().click();
  await page.getByRole('button', { name: /Vous avez une carte ou une liste de prix/ }).click();

  // a 4032 × 3024 photo, as a phone takes it
  const b64 = await page.evaluate(async () => {
    const c = document.createElement('canvas'); c.width = 4032; c.height = 3024;
    const x = c.getContext('2d');
    for (let i = 0; i < 4000; i += 1) { x.fillStyle = `hsl(${i % 360},70%,${30 + (i % 50)}%)`; x.fillRect((i * 97) % 4032, (i * 53) % 3024, 120, 90); }
    return c.toDataURL('image/jpeg', 0.98).split(',')[1];
  });
  const buffer = Buffer.from(b64, 'base64');
  await page.locator('input[type="file"][accept="image/*"]').last().setInputFiles({ name: 'IMG_0001.jpg', mimeType: 'image/jpeg', buffer });

  await expect.poll(() => page.locator('input').evaluateAll((els) => els.some((e) => e.value === 'Coupe + barbe+ coiffage')), { timeout: 10_000 }).toBe(true);
  expect(sent.mime).toBe('image/jpeg');
  const body = Buffer.from(sent.image_base64.split(',').pop(), 'base64');
  expect(body.length, `sent ${body.length} bytes for a ${buffer.length}-byte photo`).toBeLessThan(Math.min(buffer.length / 2, 1_500_000));
});
