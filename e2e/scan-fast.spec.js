/**
 * The till opens the client at once after a scan (user, 2026-11-20: « page
 * ekdm smooth and fast load ho, slow load n ho »).
 *
 *   · a whole code (camera, douchette) asks for the client at once — no
 *     250 ms wait meant for a code typed by hand
 *   · while the client loads, the till says so (« Chargement du client… »
 *     with the code), never the empty « Saisir le code » form
 *   · the QR reader (jsQR) comes from our own site, ready before the camera
 *     opens; the CDN down changes nothing
 *   · the open till keeps the server awake: a light ping, no database,
 *     only while the page is on screen
 *
 * Local server and demo data only (scripts/dev_local.py).
 */
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only

async function asOwner(page, request) {
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const store = ((br && br.branches) || br || []).find((b) => b.status !== 'closed')?.id || '';
  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
    try { sessionStorage.removeItem('ft_pick_store'); } catch (_e) { /* ignore */ }
  }, [login.access_token, store]);
  const clients = await (await request.get('/api/owner/clients/list?per_page=5', { headers: H })).json();
  return (clients.rows || [])[0]?.barcode_id;
}

// a douchette: a keyboard typing the card's URL very fast, then Enter
async function douchette(page, text) {
  await page.evaluate((t) => {
    const target = document.activeElement || document.body;
    for (const ch of [...t, 'Enter']) {
      const key = ch;
      const code = ch === 'Enter' ? 'Enter' : /\d/.test(ch) ? `Digit${ch}` : /[a-z]/i.test(ch) ? `Key${ch.toUpperCase()}` : ({ '-': 'Minus', '/': 'Slash', ':': 'Semicolon', '.': 'Period' }[ch] || '');
      target.dispatchEvent(new KeyboardEvent('keydown', { key, code, shiftKey: /[A-Z:]/.test(ch), bubbles: true, cancelable: true }));
    }
  }, text);
}

test.use({ viewport: { width: 1536, height: 960 } });

test('a scanned code asks for the client at once, and the till says it is loading', async ({ page, request }) => {
  const card = await asOwner(page, request);
  expect(card).toMatch(/^FT-[A-Z0-9]{8}$/);
  await page.goto('/dashboard/scan');
  await expect(page.getByRole('heading', { name: 'Enregistrer une visite' })).toBeVisible();

  // the client's answer is held 1.5 s, as on a slow phone network
  let asked = 0;
  await page.route('**/api/owner/scan/card?**', async (route) => {
    asked = Date.now();
    await new Promise((r) => setTimeout(r, 1500));
    await route.continue();
  });
  await page.evaluate(() => document.activeElement?.blur());
  const sent = Date.now();
  await douchette(page, `https://app.fidclic.com/card/${card}`);

  await expect.poll(() => asked, { timeout: 5000 }).toBeGreaterThan(0);
  expect(asked - sent, 'asked at once, not after a typing pause').toBeLessThan(200);

  const loading = page.getByTestId('scan-loading');
  await expect(loading).toBeVisible();
  await expect(loading).toContainText('Chargement du client');
  await expect(loading).toContainText(card);
  await expect(page.getByLabel('Code de la carte')).toHaveCount(0);        // not the empty form

  await expect(page.getByText('Client scanné')).toBeVisible({ timeout: 10_000 });
  await expect(loading).toHaveCount(0);
});

test('a code typed by hand still waits for the end of the typing', async ({ page, request }) => {
  const card = await asOwner(page, request);
  await page.goto('/dashboard/scan');
  const asks = [];
  page.on('request', (r) => { if (r.url().includes('/api/owner/scan/card?')) asks.push(r.url()); });
  await page.getByRole('button', { name: 'Saisir le code' }).click();
  await page.getByLabel('Code de la carte').pressSequentially(card, { delay: 90 });
  await expect(page.getByText('Client scanné')).toBeVisible({ timeout: 10_000 });
  expect(asks.length, `one request for the whole code, not one per key (${asks.length})`).toBeLessThanOrEqual(2);
});

test('the QR reader comes from our own site, the CDN down changes nothing', async ({ page, request }) => {
  await asOwner(page, request);
  const cdn = [];
  await page.route('https://cdn.jsdelivr.net/**', (route) => { cdn.push(route.request().url()); return route.abort(); });
  const ours = [];
  page.on('request', (r) => { if (/\/vendor\/jsqr-[\d.]+\.js$/.test(r.url())) ours.push(r.url()); });
  await page.goto('/dashboard/scan');
  await expect(page.getByRole('heading', { name: 'Enregistrer une visite' })).toBeVisible();
  // ready before the camera opens
  await expect.poll(() => page.evaluate(() => typeof window.jsQR), { timeout: 10_000 }).toBe('function');
  expect(ours.length).toBeGreaterThan(0);
  expect(cdn).toEqual([]);
  const r = await request.get(ours[0].replace(/^https?:\/\/[^/]+/, ''));
  expect(r.status()).toBe(200);
});

test('the open till keeps the server awake, without the database, only on screen', async ({ page, request }) => {
  await page.clock.install();
  await asOwner(page, request);
  const pings = [];
  page.on('request', (r) => { if (r.url().endsWith('/api/warm')) pings.push(Date.now()); });
  await page.goto('/dashboard/scan');
  await expect(page.getByRole('heading', { name: 'Enregistrer une visite' })).toBeVisible();
  await page.clock.runFor(4 * 60_000 + 1000);
  await expect.poll(() => pings.length).toBeGreaterThanOrEqual(1);
  const before = pings.length;
  // hidden (another tab, the screen off): no ping
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => true });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await page.clock.runFor(9 * 60_000);
  expect(pings.length).toBe(before);

  const w = await request.get('/api/warm');
  expect(w.status()).toBe(204);
  expect(await w.text()).toBe('');
});
