/**
 * « Ma carte en ligne » must read as the SAME object as the shop's Wallet card
 * (user, 2026-11-26: « door door tak card design se match nahi karta »).
 * Four synthetic cards (never a real shop's data or photo), each with a
 * generated photo, through the real page in a real browser:
 *   (a) black card + gold-lit photo, no footer colour (Apple's blur of the photo)
 *   (b) graphite photo with a warm bronze bottom
 *   (c) olive photo + a gold label
 *   (d) FidClic blue #1450B8 + yellow #F8B008, the owner's blue footer
 * Measured (CIEDE2000): the fade under the photo vs the card's band < 6, the
 * accent vs the card's accent < 12. Side-by-side 390 px pictures (a Wallet-like
 * drawing of the card | the themed home) go to ROUND4_SHOT_DIR when set.
 *   npx vite build && E2E_PORT=8811 ROUND4_SHOT_DIR=… npx playwright test e2e/card-theme-match.spec.js
 */
import { test, expect } from '@playwright/test';
import zlib from 'node:zlib';
import { deltaE2000 } from '../src/lib/cardTheme.js';

const SLUG = 'cafe-lumiere';
const SHOTS = process.env.ROUND4_SHOT_DIR || '';

// ---- a tiny PNG encoder (RGB, no filter) ---------------------------------
const CRC = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n += 1) { let c = n; for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; }
  return (buf) => { let c = 0xffffffff; for (const b of buf) c = t[(c ^ b) & 255] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };
})();
function chunk(type, data) {
  const len = Buffer.alloc(4); len.writeUInt32BE(data.length);
  const td = Buffer.concat([Buffer.from(type, 'ascii'), data]);
  const crc = Buffer.alloc(4); crc.writeUInt32BE(CRC(td));
  return Buffer.concat([len, td, crc]);
}
const rgb = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
const W = 400, H = 300;
function png(paint) {
  const raw = Buffer.alloc((W * 3 + 1) * H);
  for (let y = 0; y < H; y += 1) {
    raw[y * (W * 3 + 1)] = 0;
    for (let x = 0; x < W; x += 1) raw.set(rgb(paint(x, y)), y * (W * 3 + 1) + 1 + x * 3);
  }
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(W, 0); ihdr.writeUInt32BE(H, 4); ihdr[8] = 8; ihdr[9] = 2;
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', ihdr),
    chunk('IDAT', zlib.deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]);
}
/** The mean colour of the photo's bottom quarter — what Apple blurs into the band. */
function bottomMean(paint) {
  const s = [0, 0, 0]; let n = 0;
  for (let y = Math.floor(H * 0.75); y < H; y += 1) for (let x = 0; x < W; x += 1) { const c = rgb(paint(x, y)); s[0] += c[0]; s[1] += c[1]; s[2] += c[2]; n += 1; }
  return `#${s.map((v) => Math.round(v / n).toString(16).padStart(2, '0')).join('')}`;
}

const FIX = [
  { key: 'a-black-gold', title: '(a) black card + gold-lit photo, no footer colour', shop: 'MAISON NOIRE',
    paint: (x, y) => (y > 20 && y < 130 && x > 60 && x < 340 ? '#c9a04a' : y >= 225 && x % 40 < 5 ? '#c9a04a' : '#14100b'),
    card: { card_bg_color: '#000000', brand_color: null, accent_color: null, poster_footer_color: null, logo_text_color: '#FFFFFF',
      pass_colors: { background: '#000000', foreground: '#ffffff', label: '#ffffff', footer: null, name: '#ffffff', poster: true } },
    accent: '#c9a04a' },
  { key: 'b-graphite-bronze', title: '(b) graphite photo with a warm bronze bottom', shop: 'ATELIER GRAPHITE',
    paint: (x, y) => (y >= 225 ? '#8c6a48' : (Math.floor(x / 20) + Math.floor(y / 20)) % 2 ? '#3a3b3f' : '#2a2b2e'),
    card: { brand_color: '#1E1F22', accent_color: null, poster_footer_color: null, logo_text_color: null,
      pass_colors: { background: '#1e1f22', foreground: '#ffffff', label: '#b4b4b4', footer: null, name: null, poster: true } },
    accent: '#8c6a48' },
  { key: 'c-olive-gold', title: '(c) olive + gold', shop: 'OLIVE & OR',
    paint: (x, y) => (y >= 225 ? '#4a4f2b' : y < 60 && x > 260 ? '#c8a752' : '#6e7442'),
    card: { brand_color: '#2B2F1C', accent_color: null, poster_footer_color: null, logo_text_color: '#C8A752',
      pass_colors: { background: '#2b2f1c', foreground: '#ffffff', label: '#c8a752', footer: null, name: '#c8a752', poster: true } },
    accent: '#c8a752' },
  { key: 'd-fidclic-blue-yellow', title: '(d) FidClic blue + yellow', shop: 'CAFÉ BLEU',
    paint: (x, y) => (y >= 180 ? '#6b4a2f' : '#d9c2a3'),
    card: { brand_color: '#1450B8', accent_color: '#F8B008', poster_footer_color: '#1450B8', logo_text_color: '#F8B008',
      pass_colors: { background: '#1450b8', foreground: '#ffffff', label: '#f8b008', footer: '#1450b8', name: '#f8b008', poster: true } },
    band: '#1450b8', accent: '#f8b008' },
];
for (const f of FIX) { f.png = png(f.paint); if (!f.band) f.band = bottomMean(f.paint); }

async function newCard(request, name) {
  const pub = await (await request.get(`/api/join/${SLUG}/page`)).json();
  const store = (pub.stores || [])[0]?.slug;
  const made = await (await request.post(`/api/join/${SLUG}`, { data: {
    name, phone: `07${String(Date.now()).slice(-8)}`, postal_code: '37000', birthday: '03/04/1992',
    consent: true, ...(store ? { store } : {}) } })).json();
  expect(made.barcode_id, JSON.stringify(made).slice(0, 200)).toBeTruthy();
  return made;
}

/** A Wallet-like drawing of the card: the photo full-bleed, the band (the owner's colour or Apple's blur), the labels. */
function passHtml(f, photo) {
  const pc = f.card.pass_colors;
  const band = pc.footer ? `background:${pc.footer}` : 'backdrop-filter:blur(22px) saturate(1.1);-webkit-backdrop-filter:blur(22px);background:rgba(0,0,0,.08)';
  return `<!doctype html><meta charset="utf-8"><body style="margin:0;width:390px;height:844px;background:#e9e9ee;font:500 14px -apple-system,Helvetica,Arial">
  <p style="margin:0;padding:26px 0 10px;text-align:center;color:#555;font-size:13px">Apple Wallet (iOS 27 poster), drawn from card.pass_colors</p>
  <div style="margin:0 auto;width:344px;height:560px;border-radius:20px;overflow:hidden;position:relative;background:url(${photo}) center/cover;box-shadow:0 18px 40px -20px rgba(0,0,0,.6)">
    <div style="position:absolute;top:16px;left:16px;display:flex;gap:8px;align-items:center;color:${pc.name || pc.foreground}">
      <span style="width:30px;height:30px;border-radius:8px;background:${pc.foreground};opacity:.9"></span><b style="letter-spacing:.04em">${f.shop}</b></div>
    <div style="position:absolute;left:0;right:0;bottom:0;height:38%;${band}">
      <div style="display:flex;justify-content:space-between;padding:16px 18px 0">
        <div><div style="font-size:11px;letter-spacing:.06em;color:${pc.label}">MEMBRE</div><div style="font-size:18px;color:${pc.foreground}">Camille</div></div>
        <div style="text-align:right"><div style="font-size:11px;letter-spacing:.06em;color:${pc.label}">TAMPONS · 4/10</div><div style="font-size:16px;color:${pc.foreground}">●●●●○○○○○○</div></div>
      </div>
      <div style="margin:14px auto 0;width:96px;height:96px;border-radius:10px;background:#fff"></div>
    </div>
  </div></body>`;
}

test.use({ viewport: { width: 390, height: 844 } });

const results = [];
for (const f of FIX) {
  test(`${f.title}: the page reads as the same card`, async ({ page, request }) => {
    const made = await newCard(request, `Camille ${f.key}`);
    const bc = made.barcode_id;
    await page.route(`**/e2e-assets/${f.key}.png`, (r) => r.fulfill({ contentType: 'image/png', body: f.png }));
    await page.route((u) => u.pathname === `/api/card/${bc}`, async (route) => {
      if (route.request().method() !== 'GET') return route.fallback();
      const res = await route.fetch();
      const body = await res.json();
      body.card = { ...body.card, ...f.card, hero_photo_url: `/e2e-assets/${f.key}.png`, logo_url: null, tagline: '' };
      body.tenant = { ...body.tenant, name: f.shop };
      await route.fulfill({ response: res, json: body });
    });
    await page.goto(`/card/${bc}?k=${made.card_key}`);
    await expect(page.getByRole('heading', { name: /Bonjour/ })).toBeVisible();
    const v = (n) => page.getByTestId('card-page').evaluate((el, k) => getComputedStyle(el).getPropertyValue(k).trim().toLowerCase(), n);
    // the photo is read (lib/photoPalette), then the page re-themes: wait for the band
    await expect.poll(async () => deltaE2000(await v('--hero-fade'), f.band), { timeout: 10_000 }).toBeLessThan(6);
    const fade = await v('--hero-fade');
    const accent = await v('--accent');
    const btn = await v('--btn');
    const dBand = deltaE2000(fade, f.band);
    const dAccent = deltaE2000(accent, f.accent);
    results.push(`${f.title}: fade ${fade} vs band ${f.band} ΔE00 ${dBand.toFixed(2)} · accent ${accent} vs ${f.accent} ΔE00 ${dAccent.toFixed(2)} · button ${btn}`);
    expect(dBand).toBeLessThan(6);
    expect(dAccent).toBeLessThan(12);
    // the greeting reads on the band, the brand sits top-left
    const hello = page.getByRole('heading', { name: /Bonjour/ });
    await expect(hello).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);

    if (SHOTS) {
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.waitForTimeout(250);
      const home = await page.screenshot();
      const pass = await page.context().newPage();
      await pass.setViewportSize({ width: 390, height: 844 });
      await pass.setContent(passHtml(f, `data:image/png;base64,${f.png.toString('base64')}`));
      const card = await pass.screenshot();
      await pass.setViewportSize({ width: 800, height: 900 });
      await pass.setContent(`<!doctype html><body style="margin:0;background:#fff;font:600 13px Helvetica,Arial">
        <div style="display:flex;gap:20px;padding:0">
          <img src="data:image/png;base64,${card.toString('base64')}" width="390" height="844">
          <img src="data:image/png;base64,${home.toString('base64')}" width="390" height="844"></div>
        <p style="margin:8px 12px;color:#333">${f.title} — fade ΔE00 ${dBand.toFixed(2)}, accent ΔE00 ${dAccent.toFixed(2)}</p></body>`);
      await pass.screenshot({ path: `${SHOTS}/round4-${f.key}.png`, fullPage: true });
      await pass.close();
    }
  });
}
test.afterAll(() => { for (const r of results) console.log(`ΔE ${r}`); });
