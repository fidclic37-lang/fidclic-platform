/**
 * « The theme is not there at all, the page is colourless » (user, 2026-11-25,
 * production): Royal Trim's cards are black / white / grey in Pass Designer,
 * their real look is the card's photo. The page now reads the photo the hero
 * already shows (lib/photoPalette) and themes itself from it — no API request.
 *
 * Two generated PNGs (a dark photo with gold, one with olive) are served at
 * /e2e-assets/ on a black card. Local server and demo data only.
 *   npx vite build && E2E_PORT=8811 npx playwright test e2e/card-photo-theme.spec.js
 */
import { test, expect } from '@playwright/test';
import { deltaE2000 } from '../src/lib/cardTheme.js';
import zlib from 'node:zlib';

const SLUG = 'cafe-lumiere';
const SHOTS = process.env.CARD_SHOT_DIR || '';

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
/** w×h PNG: `paint(x, y)` → [r, g, b]. */
function png(w, h, paint) {
  const raw = Buffer.alloc((w * 3 + 1) * h);
  for (let y = 0; y < h; y += 1) {
    raw[y * (w * 3 + 1)] = 0;
    for (let x = 0; x < w; x += 1) raw.set(paint(x, y), y * (w * 3 + 1) + 1 + x * 3);
  }
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(w, 0); ihdr.writeUInt32BE(h, 4); ihdr[8] = 8; ihdr[9] = 2; ihdr[10] = 0; ihdr[11] = 0; ihdr[12] = 0;
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', ihdr),
    chunk('IDAT', zlib.deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]);
}
const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
/** A dark barber photo: a near-black room, a lit band of `tone` across it, a grey chair. */
const photo = (tone, deep) => png(400, 300, (x, y) => {
  if (y > 110 && y < 190 && x > 40 && x < 360) return hex(tone);
  if (x > 260 && y > 200) return hex('#7d7a76');
  return hex(deep);
});
const GOLD = photo('#c9a04a', '#0f0d0b');
const OLIVE = photo('#6e7442', '#14160e');

async function newCard(request, name) {
  const pub = await (await request.get(`/api/join/${SLUG}/page`)).json();
  const store = (pub.stores || [])[0]?.slug;
  const made = await (await request.post(`/api/join/${SLUG}`, { data: {
    name, phone: `07${String(Date.now()).slice(-8)}`, postal_code: '37000', birthday: '03/04/1992',
    consent: true, ...(store ? { store } : {}) } })).json();
  expect(made.barcode_id, JSON.stringify(made).slice(0, 200)).toBeTruthy();
  return made;
}

// a black card with no colour of its own: every colour field the page reads, blanked
const BLACK = { card_bg_color: '#15120E', brand_color: null, primary_color: null, accent_color: null,
  poster_footer_color: null, logo_text_color: '#FFFFFF', secondary_color: null, surface_color: null, surface: null, design: {},
  // the Wallet card itself (round 4, card.pass_colors): black / white, no footer colour — Apple blurs the photo
  pass_colors: { background: '#000000', foreground: '#ffffff', label: '#ffffff', footer: null, name: '#ffffff', poster: true } };
// the photo's bottom quarter (y ≥ 225): the grey chair on the right, the room's deep tone elsewhere
const bottomOf = (deep) => {
  const chair = hex('#7d7a76'), d = hex(deep), share = 139 / 400;     // x > 260
  return `#${[0, 1, 2].map((i) => Math.round(chair[i] * share + d[i] * (1 - share)).toString(16).padStart(2, '0')).join('')}`;
};

async function stage(page, bc, card) {
  const asked = [];
  page.on('request', (r) => {
    const u = new URL(r.url());
    if (u.pathname.startsWith('/api/')) asked.push(`${r.method()} ${u.pathname}`);
  });
  await page.route('**/e2e-assets/*', (route) => route.fulfill({ contentType: 'image/png',
    body: route.request().url().includes('olive') ? OLIVE : GOLD }));
  await page.route((u) => u.pathname === `/api/card/${bc}`, async (route) => {
    if (route.request().method() !== 'GET') return route.fallback();
    const res = await route.fetch();
    const body = await res.json();
    body.card = { ...body.card, ...card };
    await route.fulfill({ response: res, json: body });
  });
  return asked;
}

const vars = (page) => page.getByTestId('card-page').evaluate((el) => {
  const cs = getComputedStyle(el);
  return Object.fromEntries(['--page', '--btn', '--btn-ink', '--accent', '--brand-ink', '--hero-fade', '--bar']
    .map((k) => [k, cs.getPropertyValue(k).trim().toLowerCase()]));
});
const hsl = (h) => {
  const [r, g, b] = hex(h).map((v) => v / 255);
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2, d = mx - mn;
  if (!d) return { h: 0, s: 0, l };
  const s = d / (1 - Math.abs(2 * l - 1));
  let hh = mx === r ? ((g - b) / d) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
  hh *= 60; if (hh < 0) hh += 360;
  return { h: hh, s, l };
};
const hueNear = (a, b, tol) => Math.min(Math.abs(a - b), 360 - Math.abs(a - b)) <= tol;

test.use({ viewport: { width: 390, height: 844 } });

for (const [name, url, hue, deep] of [['gold', '/e2e-assets/gold.png', 41, '#0f0d0b'], ['olive', '/e2e-assets/olive.png', 66, '#14160e']]) {
  test(`a black card with a ${name} photo takes the photo's colour, without asking the server more`, async ({ page, request }) => {
    const made = await newCard(request, `Photo ${name}`);
    const bc = made.barcode_id;

    // the same black card with no photo: the neutral slate of before
    const none = await stage(page, bc, { ...BLACK, hero_photo_url: null });
    await page.goto(`/card/${bc}?k=${made.card_key}`);
    await expect(page.getByRole('heading', { name: /Bonjour/ })).toBeVisible();
    const slate = await vars(page);
    expect(none.length).toBeGreaterThan(0);
    await page.unrouteAll({ behavior: 'ignoreErrors' });

    const asked = await stage(page, bc, { ...BLACK, hero_photo_url: url });
    await page.goto(`/card/${bc}`);
    await expect(page.getByRole('heading', { name: /Bonjour/ })).toBeVisible();
    await expect.poll(async () => (await vars(page))['--page'], { message: 'the page re-themes from the photo' }).not.toBe(slate['--page']);
    const v = await vars(page);
    expect(hueNear(hsl(v['--page']).h, hue, 15) && hsl(v['--page']).s > 0.1, `--page from the ${name} (${v['--page']})`).toBe(true);
    expect(hueNear(hsl(v['--btn-ink']).h, hue, 15), `--btn-ink in the ${name} (${v['--btn-ink']})`).toBe(true);
    // round 4: under the photo and on the buttons, the band the Wallet card shows (Apple's blur of the photo's bottom)
    expect(deltaE2000(v['--hero-fade'], bottomOf(deep)), `fade = the photo's bottom (${v['--hero-fade']} vs ${bottomOf(deep)})`).toBeLessThan(6);
    expect(v['--btn']).toBe(v['--hero-fade']);
    expect(hsl(v['--btn']).l, `dark button (${v['--btn']})`).toBeLessThan(0.25);
    expect(v['--accent']).not.toBe(slate['--accent']);
    expect(v['--bar']).not.toBe(slate['--bar']);
    await expect(page.getByTestId('hero-photo')).toHaveCSS('background-size', 'cover');

    // no API request for it: each card question once, no /api/media read
    await page.waitForTimeout(1200);
    const card = asked.filter((a) => a === `GET /api/card/${bc}`);
    expect(card, asked.join('\n')).toHaveLength(1);
    expect(asked.filter((a) => a.includes('/api/media/')), asked.join('\n')).toEqual([]);
    const dup = asked.filter((a, i) => asked.indexOf(a) !== i && !a.startsWith('POST'));
    expect(dup, 'no question asked twice').toEqual([]);

    if (SHOTS) {
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({ path: `${SHOTS}/card-photo-${name}-390.png` });
    }
  });
}
