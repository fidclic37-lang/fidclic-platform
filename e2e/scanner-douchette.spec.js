/**
 * A USB / Bluetooth scanner (douchette) at the till (user, 2026-10-14): scan
 * the card's QR and the client opens, with no field to click first — then the
 * products, the total, the reward, « Enregistrer la visite », as with the camera.
 *
 * A scanner is a keyboard typing very fast. Set to a US keyboard on a French
 * (AZERTY) computer, « FT-AB12CD34 » arrives as « FT)QB&éCD"' »: the page reads
 * the physical keys too. Local server only (scripts/dev_local.py).
 */
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only

async function asOwner(page, request) {
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const br = await (await request.get('/api/owner/branches', { headers: { Authorization: `Bearer ${login.access_token}` } })).json();
  const store = ((br && br.branches) || br || []).find((b) => b.status !== 'closed')?.id || '';
  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
    try { sessionStorage.removeItem('ft_pick_store'); } catch (_e) { /* ignore */ }
  }, [login.access_token, store]);
  return login.access_token;
}

// What a US-set scanner sends for each character: the US key, and the
// character that key makes on a French AZERTY keyboard (or on a US one).
function strokes(text, layout) {
  const AZ_DIGIT = { 1: '&', 2: 'é', 3: '"', 4: "'", 5: '(', 6: '-', 7: 'è', 8: '_', 9: 'ç', 0: 'à' };
  const AZ_LETTER = { A: 'q', Q: 'a', W: 'z', Z: 'w', M: ',' };
  return [...text].map((ch) => {
    if (/[a-z]/i.test(ch)) {
      const U = ch.toUpperCase(); const shift = ch !== ch.toLowerCase();
      const base = layout === 'azerty' ? (AZ_LETTER[U] || U.toLowerCase()) : U.toLowerCase();
      return { code: `Key${U}`, shift, key: shift ? (base === ',' ? '?' : base.toUpperCase()) : base };
    }
    if (/\d/.test(ch)) return { code: `Digit${ch}`, shift: false, key: layout === 'azerty' ? AZ_DIGIT[ch] : ch };
    const US = { '-': ['Minus', false, ')'], '/': ['Slash', false, '!'], ':': ['Semicolon', true, 'M'], '.': ['Period', false, ';'] }[ch];
    return { code: US[0], shift: US[1], key: layout === 'azerty' ? US[2] : ch };
  });
}

async function douchette(page, text, layout = 'us') {
  const keys = [...strokes(text, layout), { code: 'Enter', shift: false, key: 'Enter' }];
  await page.evaluate((ks) => {
    const target = document.activeElement || document.body;
    for (const k of ks) {
      target.dispatchEvent(new KeyboardEvent('keydown', { key: k.key, code: k.code, shiftKey: k.shift, bubbles: true, cancelable: true }));
    }
  }, keys);
}

test.describe.serial('a scanner at the till', () => {
  test.use({ viewport: { width: 1536, height: 960 } });
  let H; let card; let url;

  test('a catalogue and a client', async ({ page, request }) => {
    H = { Authorization: `Bearer ${await asOwner(page, request)}` };
    expect((await request.put('/api/owner/catalog', { headers: H, data: { items: [
      { name: 'Coupe femme', price: 45, category: 'Coupe' }, { name: 'Brushing', price: 25, category: 'Brushing' },
    ] } })).status()).toBe(200);
    const clients = await (await request.get('/api/owner/clients/list?per_page=5', { headers: H })).json();
    card = (clients.rows || [])[0]?.barcode_id;
    expect(card).toMatch(/^FT-[A-Z0-9]{8}$/);
    url = `https://app.fidclic.com/card/${card}`;          // what the card's QR holds
    expect(strokes(url, 'azerty').map((k) => k.key).join(''), 'AZERTY garbles the code').not.toContain(card);
  });

  test('scan → products → reward step → visit recorded, nothing clicked first', async ({ page, request }) => {
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await asOwner(page, request);
    await page.goto('/dashboard/scan');
    await expect(page.getByRole('heading', { name: 'Enregistrer une visite' })).toBeVisible();
    await page.evaluate(() => document.activeElement?.blur());
    await douchette(page, url, 'azerty');
    await expect(page.getByText('Client scanné')).toBeVisible({ timeout: 10_000 });

    await page.getByRole('button', { name: /Choisir un (service|produit)/ }).click();
    const drawer = page.getByRole('dialog');
    await drawer.getByRole('button', { name: 'Plus Coupe femme' }).click();
    await drawer.getByRole('button', { name: 'Plus Brushing' }).click();
    await drawer.getByRole('button', { name: /Ajouter 70,00/ }).click();
    await expect(page.getByPlaceholder('0,00')).toHaveValue(/^70[.,]00$/);

    // a stray scan in the middle of a visit throws nothing away
    await douchette(page, url, 'us');
    await expect(page.getByText(/Une visite est en cours/)).toBeVisible();
    await expect(page.getByPlaceholder('0,00')).toHaveValue(/^70[.,]00$/);

    await page.getByRole('button', { name: /Suivant/ }).click();
    await expect(page.getByTestId('visit-review').getByText('Offre / Récompense')).toBeVisible();
    await page.getByRole('button', { name: 'Enregistrer la visite' }).click();
    await expect(page.getByTestId('visit-summary')).toContainText('70,00', { timeout: 15_000 });

    // the next client: just scan — a new visit from step 1
    await douchette(page, url, 'us');
    await expect(page.getByTestId('visit-items')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId('visit-summary')).toHaveCount(0);
    await expect(page.getByPlaceholder('0,00')).toHaveValue('');
    expect(errors).toEqual([]);
  });

  test('a person typing the code by hand is left alone', async ({ page, request }) => {
    await asOwner(page, request);
    await page.goto('/dashboard/scan');
    // typed by hand into the field, slowly: no Enter magic, the field works as before
    await page.getByRole('button', { name: 'Saisir le code' }).click();
    await page.getByLabel('Code de la carte').pressSequentially(card, { delay: 90 });
    await expect(page.getByText('Client scanné')).toBeVisible({ timeout: 10_000 });
  });
});
