// Run: node --test src/lib/cardThemeMatch.test.js
// « Ma carte en ligne » must read as the SAME object as the shop's Wallet card
// (user, 2026-11-26: « door door tak card design se match nahi karta »):
//   · the fade under the photo = the card's footer band (the owner's colour,
//     else Apple's blur of the photo's bottom — photoPalette.band)
//   · the page = a very light tint of that band (or of the accent when the band is grey)
//   · the accent = the card's label / foreground when chromatic, else the photo's colour
//   · the solid buttons = the band, with an ink taken from the card's own colours
// Measured with CIEDE2000: fade vs band < 6, accent vs the card's accent < 12.
import test from 'node:test';
import assert from 'node:assert/strict';
import { themeFromCard, contrast, deltaE2000, deltaE2000Lab, deltaE76, hexToLab } from './cardTheme.js';
import { paletteFromPixels } from './photoPalette.js';

const HEX = /^#[0-9a-f]{6}$/;
const rgbOf = (hex) => { const n = parseInt(hex.slice(1), 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; };
const hsl = (hex) => {
  const [R, G, B] = rgbOf(hex).map((v) => v / 255);
  const mx = Math.max(R, G, B), mn = Math.min(R, G, B), l = (mx + mn) / 2, d = mx - mn;
  if (!d) return { h: 0, s: 0, l };
  const s = d / (1 - Math.abs(2 * l - 1));
  let h = mx === R ? ((G - B) / d) % 6 : mx === G ? (B - R) / d + 2 : (R - G) / d + 4;
  h *= 60; if (h < 0) h += 360;
  return { h, s, l };
};
const hueNear = (a, b, tol) => Math.min(Math.abs(a - b), 360 - Math.abs(a - b)) <= tol;
const mean = (...hexes) => `#${[0, 1, 2].map((i) => Math.round(hexes.reduce((s, h) => s + rgbOf(h)[i], 0) / hexes.length)
  .toString(16).padStart(2, '0')).join('')}`;

/** A 64×64 photo: paint(x, y) → hex. */
function photo(paint, w = 64, h = 64) {
  const out = new Uint8ClampedArray(w * h * 4);
  for (let y = 0; y < h; y += 1) for (let x = 0; x < w; x += 1) out.set([...rgbOf(paint(x, y)), 255], (y * w + x) * 4);
  return paletteFromPixels(out, { width: w, height: h });
}

// ---------------------------------------------------------------- ΔE helpers

test('hexToLab: white, black, sRGB red (D65)', () => {
  const near = (a, b, tol, why) => assert.ok(Math.abs(a - b) <= tol, `${why}: ${a} vs ${b}`);
  const w = hexToLab('#ffffff');
  near(w[0], 100, 0.01, 'white L'); near(w[1], 0, 0.01, 'white a'); near(w[2], 0, 0.01, 'white b');
  assert.deepEqual(hexToLab('#000000').map((v) => Math.round(v * 1000) / 1000), [0, 0, 0]);
  const r = hexToLab('#ff0000');
  near(r[0], 53.24, 0.05, 'red L'); near(r[1], 80.09, 0.05, 'red a'); near(r[2], 67.2, 0.05, 'red b');
  assert.equal(hexToLab('nope'), null);
  assert.equal(hexToLab(null), null);
});

test('deltaE2000 matches Sharma, Wu & Dalal (2005) reference pairs', () => {
  const pairs = [
    [[50, 2.6772, -79.7751], [50, 0, -82.7485], 2.0425],
    [[50, 3.1571, -77.2803], [50, 0, -82.7485], 2.8615],
    [[50, 2.8361, -74.02], [50, 0, -82.7485], 3.4412],
    [[50, -1.3802, -84.2814], [50, 0, -82.7485], 1.0],
    [[50, 0, 0], [50, -1, 2], 2.3669],
    [[50, 2.49, -0.001], [50, -2.49, 0.0009], 7.1792],
    [[50, 2.5, 0], [73, 25, -18], 27.1492],
    [[50, 2.5, 0], [61, -5, 29], 22.8977],
    [[60.2574, -34.0099, 36.2677], [60.4626, -34.1751, 39.4387], 1.2644],
    [[63.0109, -31.0961, -5.8663], [62.8187, -29.7946, -4.0864], 1.263],
    [[22.7233, 20.0904, -46.694], [23.0331, 14.973, -42.5619], 2.0373],
    [[90.9257, -0.5406, -0.9208], [88.6381, -0.8985, -0.7239], 1.5381],
    [[2.0776, 0.0795, -1.135], [0.9033, -0.0636, -0.5514], 0.9082],
  ];
  for (const [a, b, want] of pairs) {
    const got = deltaE2000Lab(a, b);
    assert.ok(Math.abs(got - want) < 1e-3, `${JSON.stringify(a)} / ${JSON.stringify(b)}: ${got} ≠ ${want}`);
    assert.ok(Math.abs(deltaE2000Lab(b, a) - want) < 1e-3, 'symmetric');
  }
});

test('deltaE2000 / deltaE76 on hex: zero, symmetry, order, garbage', () => {
  assert.equal(deltaE2000('#1450b8', '#1450B8'), 0);
  assert.equal(deltaE76('#c9a04a', '#c9a04a'), 0);
  assert.ok(Math.abs(deltaE2000('#000000', '#ffffff') - 100) < 0.01, 'black / white = 100');
  assert.ok(Math.abs(deltaE76('#000000', '#ffffff') - 100) < 0.01);
  assert.ok(deltaE2000('#c9a04a', '#caa14b') < 1, 'one step apart is invisible');
  assert.ok(deltaE2000('#c9a04a', '#1450b8') > 40, 'gold vs blue is far');
  assert.equal(deltaE2000('#c9a04a', 'nope'), Infinity);
  assert.equal(deltaE76(null, '#000'), Infinity);
});

// ---------------------------------------------------------------- the four fixtures

const FIXTURES = [
  {
    name: '(a) black card + gold-lit photo, no footer colour',
    card: { card_bg_color: '#000000', logo_text_color: '#FFFFFF',
      pass_colors: { background: '#000000', foreground: '#ffffff', label: '#ffffff', footer: null, name: '#ffffff', poster: true } },
    // a near-black salon, a gold-lit mirror at the top, gold glints in the dark bottom
    photo: (x, y) => (y < 30 && x > 10 && x < 54 ? '#c9a04a' : y >= 48 && x % 8 === 0 ? '#c9a04a' : '#14100b'),
    band: mean('#c9a04a', '#14100b', '#14100b', '#14100b', '#14100b', '#14100b', '#14100b', '#14100b'),
    accent: '#c9a04a',
  },
  {
    name: '(b) graphite photo with a warm bronze bottom',
    card: { brand_color: '#1E1F22',
      pass_colors: { background: '#1e1f22', foreground: '#ffffff', label: '#b4b4b4', footer: null, name: null, poster: true } },
    photo: (x, y) => (y >= 48 ? '#8c6a48' : (x + y) % 5 ? '#3a3b3f' : '#2a2b2e'),
    band: '#8c6a48',
    accent: '#8c6a48',
  },
  {
    name: '(c) olive + gold',
    card: { brand_color: '#2B2F1C', accent_color: null,
      pass_colors: { background: '#2b2f1c', foreground: '#ffffff', label: '#c8a752', footer: null, name: '#c8a752', poster: true } },
    photo: (x, y) => (y >= 48 ? '#4a4f2b' : y < 12 && x > 40 ? '#c8a752' : '#6e7442'),
    band: '#4a4f2b',
    accent: '#c8a752',
  },
  {
    name: '(d) FidClic blue #1450B8 + yellow #F8B008',
    card: { brand_color: '#1450B8', accent_color: '#F8B008', poster_footer_color: '#1450B8', logo_text_color: '#F8B008',
      pass_colors: { background: '#1450b8', foreground: '#ffffff', label: '#f8b008', footer: '#1450b8', name: '#f8b008', poster: true } },
    // a café photo: the owner's band wins over Apple's blur
    photo: (x, y) => (y >= 40 ? '#6b4a2f' : '#d9c2a3'),
    band: '#1450b8',
    accent: '#f8b008',
  },
];

function assertCalmAndReadable(t, why) {
  for (const k of ['page', 'sheet', 'ink', 'muted', 'faint', 'brandInk', 'accent', 'accentSoft', 'accentInk', 'btn',
    'btnInk', 'banner', 'bannerInk', 'heroFade', 'heroInk', 'chipInk', 'ctaBg', 'ctaInk']) {
    assert.match(t[k], HEX, `${why}: ${k} is a hex (${t[k]})`);
  }
  for (const [fg, bg, min] of [['ink', 'page', 4.5], ['ink', 'sheet', 4.5], ['muted', 'page', 4.5], ['muted', 'sheet', 4.5],
    ['faint', 'sheet', 4.5], ['brandInk', 'sheet', 4.5], ['brandInk', 'page', 4.5], ['accentInk', 'sheet', 4.5],
    ['accentInk', 'accentSoft', 4.5], ['btnInk', 'btn', 4.5], ['bannerInk', 'banner', 4.5], ['heroInk', 'heroFade', 4.5],
    ['ctaInk', 'ctaBg', 4.5], ['chipInk', 'btn', 3], ['ok', 'sheet', 4.5]]) {
    const r = contrast(t[fg], t[bg]);
    assert.ok(r >= min, `${why}: ${fg} on ${bg} = ${r.toFixed(2)} < ${min}`);
  }
  const p = hsl(t.page);
  assert.ok(p.l >= 0.92 && p.s <= 0.6, `${why}: calm light page (${t.page})`);
}

const report = [];
for (const f of FIXTURES) {
  test(`${f.name}: the page reads as the same card`, () => {
    const pal = photo(f.photo);
    const t = themeFromCard(f.card, pal);
    assertCalmAndReadable(t, f.name);
    const dBand = deltaE2000(t.heroFade, f.band);
    const dAccent = deltaE2000(t.accent, f.accent);
    report.push(`${f.name}: ΔE00 fade↔band ${dBand.toFixed(2)} · accent↔card ${dAccent.toFixed(2)} · btn↔band ${deltaE2000(t.btn, f.band).toFixed(2)}`
      + ` (fade ${t.heroFade}, band ${f.band}, accent ${t.accent}, btn ${t.btn}/${t.btnInk}, page ${t.page})`);
    assert.ok(dBand < 6, `${f.name}: fade ${t.heroFade} vs band ${f.band} ΔE ${dBand.toFixed(2)}`);
    assert.ok(dAccent < 12, `${f.name}: accent ${t.accent} vs ${f.accent} ΔE ${dAccent.toFixed(2)}`);
    // the button is the band itself whenever an ink of the card reads on it
    assert.ok(deltaE2000(t.btn, f.band) < 6, `${f.name}: button ${t.btn} is the band ${f.band}`);
    // numbers / links in the accent's own hue (made readable)
    assert.ok(hueNear(hsl(t.brandInk).h, hsl(f.accent).h, 14), `${f.name}: numbers in the accent's hue (${t.brandInk})`);
    // the page's tint: the band's hue when it has one, else the accent's
    const b = hsl(f.band);
    const tintHue = b.s >= 0.12 && b.l >= 0.08 && b.l <= 0.94 ? b.h : hsl(f.accent).h;
    assert.ok(hueNear(hsl(t.page).h, tintHue, 16), `${f.name}: page ${t.page} tinted ${Math.round(tintHue)}°`);
  });
}
test.after(() => { for (const line of report) console.log(`ΔE ${line}`); });

// ---------------------------------------------------------------- the rules, one by one

test('(a) black + gold: the button ink is gold (the photo\'s colour), the greeting white on the dark band', () => {
  const f = FIXTURES[0];
  const t = themeFromCard(f.card, photo(f.photo));
  assert.ok(hueNear(hsl(t.btnInk).h, 42, 14) && hsl(t.btnInk).s > 0.3, `gold ink (${t.btnInk})`);
  assert.equal(t.heroInk, '#ffffff');
  assert.ok(hueNear(hsl(t.chipInk).h, 42, 14), `gold tile icons (${t.chipInk})`);
});

test('(d) FidClic: white ink on the blue button (yellow does not read on it), yellow tile icons', () => {
  const f = FIXTURES[3];
  const t = themeFromCard(f.card, photo(f.photo));
  assert.equal(t.btn, '#1450b8');
  assert.equal(t.btnInk, '#ffffff');
  assert.equal(t.chipInk, '#f8b008');
  assert.ok(hueNear(hsl(t.page).h, 218, 12), `blue page (${t.page})`);
});

test('a light footer band (cream): dark greeting, dark button ink, still calm', () => {
  const t = themeFromCard({ pass_colors: { background: '#f6efe3', foreground: '#2a1d12', label: '#8a5a2b', footer: '#f6efe3', poster: true } },
    photo(() => '#d8c8b0'));
  assertCalmAndReadable(t, 'cream band');
  assert.ok(deltaE2000(t.heroFade, '#f6efe3') < 1, `fade = cream (${t.heroFade})`);
  assert.ok(contrast(t.heroInk, t.heroFade) >= 4.5 && hsl(t.heroInk).l < 0.3, `dark greeting (${t.heroInk})`);
  assert.ok(hueNear(hsl(t.accent).h, hsl('#8a5a2b').h, 6), `accent = the brown label (${t.accent})`);
});

test('a mid-grey band: whichever of white / black reads (one always clears 4.5:1)', () => {
  for (const g of ['#767676', '#777777', '#808080', '#5a5a5a', '#9a9a9a']) {
    const t = themeFromCard({ pass_colors: { background: '#000000', foreground: '#ffffff', label: '#ffffff', footer: g, poster: true } });
    assertCalmAndReadable(t, `grey ${g}`);
    assert.equal(t.heroFade, g);
  }
});

test('a storeCard (iOS 26, no poster): the band is the card\'s background', () => {
  const t = themeFromCard({ pass_colors: { background: '#7a2a2a', foreground: '#ffffff', label: '#f0c8a0', footer: '#00ff00', poster: false } },
    photo(() => '#203040'));
  assertCalmAndReadable(t, 'storeCard');
  assert.equal(t.heroFade, '#7a2a2a');
});

test('no pass_colors: the owner\'s poster_footer_color, else the photo\'s bottom', () => {
  const a = themeFromCard({ brand_color: '#1450B8', poster_footer_color: '#8C7357' }, photo(() => '#203040'));
  assertCalmAndReadable(a, 'owner footer');
  assert.equal(a.heroFade, '#8c7357');
  const b = themeFromCard({ brand_color: '#1450B8', accent_color: '#F8B008' }, photo((x, y) => (y >= 48 ? '#4a3020' : '#c0c0c0')));
  assertCalmAndReadable(b, 'photo band');
  assert.equal(b.heroFade, '#4a3020');
  assert.equal(b.accent, '#f8b008', 'the owner\'s accent stays');
});

test('accent order: chromatic label, then foreground, then the shop name\'s colour, then the photo', () => {
  const pal = photo((x, y) => (y >= 48 ? '#101010' : '#3060d0'));          // a blue photo
  const base = { background: '#000000', footer: null, poster: true };
  assert.equal(themeFromCard({ pass_colors: { ...base, foreground: '#ffffff', label: '#c8a752' } }, pal).accent, '#c8a752');
  assert.equal(themeFromCard({ pass_colors: { ...base, foreground: '#d04040', label: '#ffffff' } }, pal).accent, '#d04040');
  assert.equal(themeFromCard({ pass_colors: { ...base, foreground: '#fff', label: '#fff', name: '#22aa66' } }, pal).accent, '#22aa66');
  assert.equal(themeFromCard({ logo_text_color: '#22aa66', pass_colors: { ...base, foreground: '#fff', label: '#fff' } }, pal).accent, '#22aa66');
  // the old designer's accent / secondary colours are drawn nowhere on the Wallet card: the photo wins
  // (real demo card, e2e card-theme-match: a #d4a574 nobody sees stood in for the photo's bronze)
  const old = themeFromCard({ accent_color: '#d4a574', secondary_color: '#1c1917', design: { accent_color: '#d4a574' },
    pass_colors: { ...base, foreground: '#fff', label: '#fff' } }, pal);
  assert.ok(hueNear(hsl(old.accent).h, hsl('#3060d0').h, 8), `the photo, not the invisible #d4a574 (${old.accent})`);
  const p = themeFromCard({ pass_colors: { ...base, foreground: '#ffffff', label: '#9a9a9a' } }, pal);
  assert.ok(hueNear(hsl(p.accent).h, hsl('#3060d0').h, 8), `the photo's blue (${p.accent})`);
});

test('garbage pass_colors are ignored: same theme as without them', () => {
  const card = { card_bg_color: '#15120E' };
  const pal = photo((x, y) => (y >= 48 ? '#1a140c' : '#c9a04a'));
  const want = themeFromCard(card, pal);
  for (const pc of [null, 'red', 42, [], { background: 'url(x)', foreground: 'javascript:alert(1)', label: '</style>', footer: 'expression(1)' },
    { background: 12, label: {}, footer: [] }]) {
    assert.deepEqual(themeFromCard({ ...card, pass_colors: pc }, pal), want, `pass_colors ${JSON.stringify(pc)}`);
  }
});

test('every token is a plain colour or gradient: nothing typed reaches CSS', () => {
  const t = themeFromCard({ brand_color: '#1450B8', pass_colors: { background: '#1450b8', foreground: 'red;}body{x', label: '#f8b008', footer: '#1450b8', poster: true } },
    { accent: '#c9a04a;}', dark: 'x', band: 'url(javascript:1)' });
  for (const [k, v] of Object.entries(t)) {
    if (typeof v !== 'string') continue;
    assert.ok(HEX.test(v) || /^linear-gradient\(90deg,#[0-9a-f]{6},#[0-9a-f]{6}\)$/.test(v), `${k}: ${v}`);
  }
});

test('a photo palette from the past (no band) keeps today\'s theme', () => {
  const card = { card_bg_color: '#15120E' };
  assert.deepEqual(themeFromCard(card, { accent: '#c9a04a', dark: '#0f0d0b' }),
    themeFromCard(card, { accent: '#c9a04a', dark: '#0f0d0b', band: null }));
});
