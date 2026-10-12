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

// « Couleur » labels two different toggles on this page — the colour of the
// shop's name beside the logo, and the colour of the band under the QR. Each
// segmented control carries its own aria-label group; this is the band's.
const band = (page) => page.getByRole('group', { name: 'Bande du bas (sous le QR code)' });

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
    await expect(phone).toContainText('● ● ● ○ ○ ○ ○ ○ ○ ○');   // a space between the tampons

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

    // the band: a colour. « Couleur » is also the name-colour option above,
    // so always ask the band's own group for it.
    await band(page).getByRole('button', { name: 'Couleur', exact: true }).click();
    // the shape: ★
    await page.getByRole('button', { name: /Étoile/ }).click();
    await expect(phone).toContainText('★ ★ ★ ☆ ☆ ☆ ☆ ☆ ☆ ☆');

    // the preview's pass.json carries the footer colour
    const pv = page.waitForResponse((r) => r.url().includes('/api/owner/wallet/preview') && r.status() === 200);
    await page.getByRole('button', { name: /Losange/ }).click();
    const preview = await (await pv).json();
    expect(preview.pass_json.footerBackgroundColor).toMatch(/^rgb\(/);
    await expect(phone).toContainText('◆ ◆ ◆ ◇');

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
    expect(row.balance.string).toBe('◆ ◆ ◆ ◇ ◇ ◇ ◇ ◇ ◇ ◇');

    expect(errors).toEqual([]);
  });

  test('with a Pass Designer design: the photo, the band and the tampons reach iOS 27 too', async ({ page, request }) => {
    // 2026-10-12: with a design, iOS 27 drew the design's own background and
    // no tampons — « ios27 chhod k sab mein changes barabar dikh rhe hai »
    const token = await asOwner(page, request);
    const H = { Authorization: `Bearer ${token}` };
    const st = await (await request.get('/api/owner/card/pass-designer/starter', { headers: H })).json();
    st.pass.posterGeneric.primaryFields = [{ key: 'name', value: '{prenom}' }, { key: 'loves', label: 'LOVES', value: 'ROLLS ROYCE' }];
    st.pass.footerBackgroundColor = 'rgb(105,27,27)';
    expect((await request.put('/api/owner/card/pass-designer', { headers: H,
      data: { name: 'Royal', pass_json: JSON.stringify(st.pass), images: st.image_data || {}, source: 'editor' } })).status()).toBe(200);

    await page.goto('/dashboard/card');
    const phone = page.locator('[translate="no"]').filter({ hasText: 'ROLLS ROYCE' }).first();
    // the jauge, under the QR (in whichever shape the card has: the test before saved ◆)
    await expect(phone).toContainText(/TAMPONS · 3\/10/);
    await expect(phone).toContainText(/([●◆★♥■]\uFE0E? ){3}([○◇☆♡□] ){6}[○◇☆♡□]/);
    await expect(band(page).getByRole('button', { name: 'Couleur', exact: true })).toHaveAttribute('aria-pressed', 'true');

    const bytes = await landscape(page);
    const field = page.getByText('Image de fond (optionnelle)', { exact: true }).locator('..');
    await field.locator('input[type="file"]').setInputFiles({ name: 'royal.jpg', mimeType: 'image/jpeg', buffer: Buffer.from(bytes) });
    await expect(page.getByText(/Votre design \(onglets/)).toBeVisible();
    await page.getByRole('button', { name: 'Flou Apple' }).click();
    await page.getByRole('button', { name: /Enregistrer les modifications/ }).click();
    await expect(page.getByText(/Modifications non enregistrées/)).toHaveCount(0, { timeout: 15_000 });

    const d = await (await request.get('/api/owner/card/pass-designer?full=1', { headers: H })).json();
    expect(d.pass.footerBackgroundColor || '').toBe('');
    // the pass the server builds draws the design with Identité's photo (2026-10-12)
    const pv = await (await request.post('/api/owner/wallet/preview', { headers: H, data: { card: {}, visits: 3, design: {} } })).json();
    const px = await page.evaluate(async (src) => {
      const im = new Image(); im.src = src; await im.decode();
      const c = document.createElement('canvas'); c.width = im.naturalWidth; c.height = im.naturalHeight;
      const x = c.getContext('2d'); x.drawImage(im, 0, 0);
      return [c.width, c.height, ...x.getImageData(Math.round(c.width / 2), Math.round(c.height / 2), 1, 1).data.slice(0, 3)];
    }, pv.images.background);
    expect(px.slice(0, 2)).toEqual([690, 1010]);                         // the poster's @2x is the new photo,
    expect(px[2]).toBeLessThan(100); expect(px[4]).toBeGreaterThan(180); // centred: its blue middle

    // the Images tab no longer offers the logo or the photo: they live in Identité
    await page.getByRole('button', { name: 'Images', exact: true }).click();
    await expect(page.getByText('Le logo et l’image de fond (avec « Ajuster »)')).toBeVisible();
    await expect(page.getByText('Logo principal (sur le poster)')).toHaveCount(0);
    await expect(page.getByText('Image de fond', { exact: true })).toHaveCount(0);
    // « Ajuster » sits on the photo itself
    await page.getByRole('button', { name: 'Identité', exact: true }).last().click();   // the note's link
    await expect(field.getByRole('button', { name: 'Ajuster' })).toBeVisible();
    await request.delete('/api/owner/card/pass-designer', { headers: H });
  });

  test('the Récompense box: shown or not, under the QR or on the back — and no points on a tampons card', async ({ page, request }) => {
    // 2026-10-12: « points and tampons dono kyun hai », and a « Récompense »
    // that added itself to the card
    const token = await asOwner(page, request);
    const H = { Authorization: `Bearer ${token}` };
    await page.goto('/dashboard/card');
    await page.getByRole('button', { name: 'Étape suivante : Paramètres' }).click();
    await expect(page.getByText('Sur la carte : les tampons, sous le QR code (pas de points)')).toBeVisible();
    await expect(page.getByText('Afficher le solde de points')).toHaveCount(0);
    await expect(page.getByText('Paliers (optionnel)')).toBeVisible();
    await expect(page.getByText('Comment le palier d\'un client est décidé')).toHaveCount(0);   // folded

    const phone = page.locator('[translate="no"]').filter({ hasText: 'TAMPONS' }).first();
    await expect(phone).not.toContainText('POINTS');
    await page.getByPlaceholder('Une coupe offerte').fill('Une coupe offerte');
    await page.getByRole('button', { name: /Sous le QR code/ }).click();
    await expect(phone).toContainText('RÉCOMPENSE');
    await page.getByRole('button', { name: /Enregistrer les modifications/ }).click();
    await expect(page.getByText(/Modifications non enregistrées/)).toHaveCount(0, { timeout: 15_000 });
    const s1 = await (await request.get('/api/owner/card/settings', { headers: H })).json();
    expect(s1.advanced.reward_place).toBe('front');
    expect(s1.programme.reward_description).toBe('Une coupe offerte');

    await page.getByRole('button', { name: 'Non', exact: true }).click();
    await expect(phone).not.toContainText('RÉCOMPENSE');
    await page.getByRole('button', { name: /Enregistrer les modifications/ }).click();
    await expect(page.getByText(/Modifications non enregistrées/)).toHaveCount(0, { timeout: 15_000 });
    const s2 = await (await request.get('/api/owner/card/settings', { headers: H })).json();
    expect(s2.advanced.reward_on_card).toBe(false);
    await page.getByRole('button', { name: 'Oui', exact: true }).click();
    await page.getByRole('button', { name: /Au dos de la carte\s*Dans/ }).click();
    await page.getByRole('button', { name: /Enregistrer les modifications/ }).click();
    await expect(page.getByText(/Modifications non enregistrées/)).toHaveCount(0, { timeout: 15_000 });
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
