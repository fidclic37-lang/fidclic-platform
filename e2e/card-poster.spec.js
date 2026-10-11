// The owner's Carte de fidélité, iOS 27 (user, 2026-10-11), in a real browser:
// a landscape photo covers the whole poster, « Ajuster » frames it, the band
// under the fields is Apple's blur or a colour, and the tampons' shape shows
// on iOS 27 (under the QR), on the iOS 26 strip and on Google Wallet — on the
// preview, then on the saved card the server builds.
//
// Runs against the local server only (scripts/dev_local.py — demo data in
// memory). Never point it at production.
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only

async function asOwner(page, request) {
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  await page.goto('/login');
  await page.evaluate((t) => localStorage.setItem('fidelitour_access_token', t), login.access_token);
  return login.access_token;
}

// a 1600×1000 landscape photo, drawn in the page
async function landscape(page) {
  return page.evaluate(async () => {
    const c = document.createElement('canvas'); c.width = 1600; c.height = 1000;
    const x = c.getContext('2d');
    x.fillStyle = '#3c78dc'; x.fillRect(0, 0, 1600, 1000);
    x.fillStyle = '#c83c32'; x.fillRect(0, 0, 200, 1000);          // a red edge on the left
    const blob = await new Promise((r) => c.toBlob(r, 'image/jpeg', 0.9));
    return Array.from(new Uint8Array(await blob.arrayBuffer()));
  });
}

test.describe.serial('the owner designs the iOS 27 card', () => {
  test.use({ viewport: { width: 1536, height: 960 } });

  test('photo full bleed, Ajuster, footer colour and tampon shape — preview, then the saved pass', async ({ page, request }) => {
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    const token = await asOwner(page, request);
    await page.goto('/dashboard/card');
    await expect(page.getByText('Aperçu de la carte sur iPhone')).toBeVisible();

    // the jauge is under the QR by default: « TAMPONS · 3/10 » over ●●●○…
    const phone = page.locator('[translate="no"]').filter({ hasText: 'TAMPONS' }).first();
    await expect(phone).toContainText('●●●○○○○○○○');

    // a landscape « Image de fond »
    const bytes = await landscape(page);
    const field = page.getByText('Image de fond (optionnelle)', { exact: true }).locator('..');
    await field.locator('input[type="file"]').setInputFiles({ name: 'cafe.jpg', mimeType: 'image/jpeg', buffer: Buffer.from(bytes) });
    await expect(page.getByText('Photo centrée automatiquement')).toBeVisible();

    // « Ajuster »: the cropper opens on that photo, the frame is used
    await page.getByRole('button', { name: 'Ajuster', exact: true }).click();
    await expect(page.getByText('Ajuster la photo (iOS 27)')).toBeVisible();
    await page.getByRole('button', { name: 'Utiliser ce cadre' }).click();
    await expect(page.getByText('Cadrage personnalisé')).toBeVisible();

    // the band: a colour
    await page.getByRole('button', { name: 'Couleur', exact: true }).click();
    // the shape: ★
    await page.getByRole('button', { name: /Étoile/ }).click();
    await expect(phone).toContainText('★★★☆☆☆☆☆☆☆');

    // the preview's pass.json carries the footer colour
    const pv = page.waitForResponse((r) => r.url().includes('/api/owner/wallet/preview') && r.status() === 200);
    await page.getByRole('button', { name: /Losange/ }).click();
    const preview = await (await pv).json();
    expect(preview.pass_json.footerBackgroundColor).toMatch(/^rgb\(/);
    await expect(phone).toContainText('◆◆◆◇');

    // iOS 26: same card as before, the strip carries the jauge
    await page.getByRole('button', { name: 'iOS 26 et avant', exact: true }).click();
    await expect(page.locator('img[src^="data:image/jpeg"]').first()).toBeVisible();

    // save, then the real pass for a customer takes all of it
    await page.getByRole('button', { name: /Enregistrer les modifications/ }).click();
    await expect(page.getByText(/Modifications non enregistrées/)).toHaveCount(0, { timeout: 15_000 });
    const settings = await (await request.get('/api/owner/card/settings', { headers: { Authorization: `Bearer ${token}` } })).json();
    expect(settings.advanced.stamp_shape).toBe('losange');
    expect(settings.advanced.poster_footer_color).toMatch(/^#[0-9A-F]{6}$/i);
    expect(settings.advanced.poster_image_url).toMatch(/^data:image\/jpeg/);

    // Google: with no banner, the row is the jauge in the same shape
    const g = await (await request.post('/api/owner/wallet/google-preview', {
      headers: { Authorization: `Bearer ${token}` },
      data: { card: { google_design: { hero: 'none' } }, visits: 3 } })).json();
    const row = g.object.secondaryLoyaltyPoints || g.object.loyaltyPoints;
    expect(row.balance.string).toBe('◆◆◆◇◇◇◇◇◇◇');

    expect(errors).toEqual([]);
  });

  test('back to the defaults: Flou Apple, bars, automatic centring', async ({ page, request }) => {
    const token = await asOwner(page, request);
    await page.goto('/dashboard/card');
    await page.getByRole('button', { name: 'Flou Apple' }).click();
    await page.getByRole('button', { name: /Par défaut/ }).click();
    await page.getByRole('button', { name: 'Centrer automatiquement' }).click();
    await page.getByRole('button', { name: /Enregistrer les modifications/ }).click();
    await expect(page.getByText(/Modifications non enregistrées/)).toHaveCount(0, { timeout: 15_000 });
    const s = await (await request.get('/api/owner/card/settings', { headers: { Authorization: `Bearer ${token}` } })).json();
    expect(s.advanced.stamp_shape).toBe('');
    expect(s.advanced.poster_footer_color).toBe('');
    expect(s.advanced.poster_image_url || '').toBe('');
  });
});
