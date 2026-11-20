/**
 * The camera reads a card QR « ekdm sataak se » (user, 2026-11-20: slower
 * since #506). A phone whose browser reads QR codes itself (Chrome on
 * Android: BarcodeDetector) gets the first seconds to itself — jsQR, ready
 * from the page's first second since #506, ran a heavy pass every 6th frame
 * from the first frame on and held the phone's screen 100–300 ms each time.
 *
 *   · native reader present: no jsQR pass in the first 2 seconds
 *   · a card in front of it: read at once
 *   · native reader that sees nothing: jsQR still comes in later, as a backup
 *
 * The browser's reader is stood in for (headless Chrome on a Mac has none
 * that reads); Chrome's fake camera gives the frames. Local server only.
 */
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only

test.use({
  viewport: { width: 1536, height: 960 },
  permissions: ['camera'],
  launchOptions: { args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] },
});

async function open(page, request, hitAfter) {
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const store = ((br && br.branches) || br || []).find((b) => b.status !== 'closed')?.id || '';
  const card = ((await (await request.get('/api/owner/clients/list?per_page=5', { headers: H })).json()).rows || [])[0]?.barcode_id;
  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
    try { sessionStorage.removeItem('ft_pick_store'); } catch (_e) { /* ignore */ }
  }, [login.access_token, store]);
  await page.addInitScript(([after, code]) => {
    window.__native = 0;
    window.__jsqr = 0;
    class FakeDetector {
      static async getSupportedFormats() { return ['qr_code', 'code_128', 'ean_13']; }
      constructor() {}
      async detect() {
        window.__native += 1;
        if (!window.__firstNative) window.__firstNative = Date.now();
        return after && window.__native >= after ? [{ rawValue: `https://app.fidclic.com/card/${code}` }] : [];
      }
    }
    window.BarcodeDetector = FakeDetector;
    let real;                                       // count every jsQR pass
    Object.defineProperty(window, 'jsQR', {
      configurable: true,
      get() { return real && ((...a) => { window.__jsqr += 1; return real(...a); }); },
      set(v) { real = typeof v === 'function' ? v : v && v.default; },
    });
  }, [hitAfter, card]);
  await page.goto('/dashboard/scan');
  // the camera opens by itself on the scan page; a browser that asks first gets the button
  const on = page.getByRole('button', { name: 'Activer la caméra' });
  if (await on.isVisible({ timeout: 1500 }).catch(() => false)) await on.click();
  return card;
}

test('a phone that reads QR itself: its reader alone at first, jsQR only later as a backup', async ({ page, request }) => {
  await open(page, request, 0);                    // the reader never sees a code
  await expect.poll(() => page.evaluate(() => window.__native), { timeout: 10_000 }).toBeGreaterThan(5);
  await expect.poll(() => page.evaluate(() => typeof window.jsQR), { timeout: 10_000 }).toBe('function');
  await page.waitForTimeout(1200);
  const early = await page.evaluate(() => ({ n: window.__native, j: window.__jsqr }));
  expect(early.j, `no jsQR pass in the first seconds (${JSON.stringify(early)})`).toBe(0);
  await page.waitForTimeout(3000);
  const later = await page.evaluate(() => ({ n: window.__native, j: window.__jsqr }));
  expect(later.j, `jsQR still comes in as a backup (${JSON.stringify(later)})`).toBeGreaterThan(0);
  expect(later.n, 'the phone\'s reader keeps reading').toBeGreaterThan(early.n);
});

test('a card in front of the camera: read at once, no jsQR pass', async ({ page, request }) => {
  let asked = 0;
  page.on('request', (r) => { if (!asked && r.url().includes('/api/owner/scan/card?')) asked = Date.now(); });
  await open(page, request, 3);
  await expect.poll(() => asked, { timeout: 10_000 }).toBeGreaterThan(0);
  const first = await page.evaluate(() => window.__firstNative || 0);
  expect(asked - first, `read within a moment of the camera's first frame (${asked - first} ms)`).toBeLessThan(800);
  expect(await page.evaluate(() => window.__jsqr)).toBe(0);
});
