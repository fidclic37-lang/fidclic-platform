// Run: node --test src/lib/photoPalette.test.js
// « Ma carte en ligne » had no colour for shops whose Pass Designer card is
// black / white / grey only (user, 2026-11-25: Royal Trim) — their real look is
// the card's photo. paletteFromPixels reads it: the dominant chromatic hue as
// the accent, the photo's dark tone for the fade. Grey photo → no accent.
import test from 'node:test';
import assert from 'node:assert/strict';
import { paletteFromPixels, photoPalette } from './photoPalette.js';

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

// a seeded random, so « noise » is the same on every run
function rng(seed) { let s = seed >>> 0; return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 2 ** 32; }; }

/** A 64×64 photo: [hex, share] parts in order (noise = seeded random); alpha 255 unless given. */
function photo(parts, { size = 64, alpha = 255, seed = 7 } = {}) {
  const n = size * size;
  const px = [];
  for (const [hex, share] of parts) {
    const k = Math.round(n * share);
    const [r, g, b] = hex === 'noise' ? [0, 0, 0] : rgbOf(hex);
    for (let i = 0; i < k; i += 1) px.push(hex === 'noise' ? null : [r, g, b]);
  }
  while (px.length < n) px.push(px[px.length - 1] || [0, 0, 0]);
  const rand = rng(seed);
  const out = new Uint8ClampedArray(n * 4);
  px.slice(0, n).forEach((p, i) => {
    const c = p || [rand() * 255, rand() * 255, rand() * 255];
    out.set([c[0], c[1], c[2], alpha], i * 4);
  });
  return { data: out, width: size, height: size };
}
const run = ({ data, width, height }) => paletteFromPixels(data, { width, height });

test('a dark barber photo with gold (Liberté): gold accent, near-black dark', () => {
  const p = run(photo([['#0e0c0a', 0.55], ['#1d1915', 0.15], ['#c9a04a', 0.12], ['#a8823a', 0.08], ['#e0c27a', 0.04], ['#8a8580', 0.06]]));
  assert.match(p.accent, HEX);
  assert.ok(hueNear(hsl(p.accent).h, 40, 10), `gold hue (${p.accent})`);
  assert.ok(hsl(p.accent).s >= 0.35, `saturated enough (${p.accent})`);
  assert.match(p.dark, HEX);
  assert.ok(hsl(p.dark).l < 0.12, `near-black (${p.dark})`);
});

test('olive + gold (PL-Monstre): the olive wins when it covers more', () => {
  const p = run(photo([['#5f6638', 0.4], ['#6e7442', 0.2], ['#bfa75f', 0.08], ['#1a1c12', 0.3], ['#d8d8d0', 0.02]]));
  assert.ok(hueNear(hsl(p.accent).h, 68, 12), `olive hue (${p.accent})`);
  assert.ok(hsl(p.dark).l < 0.15);
});

test('graphite + bronze (Palissy): a bronze accent', () => {
  const p = run(photo([['#2a2b2e', 0.5], ['#3a3b3f', 0.2], ['#8c6239', 0.12], ['#a77a4d', 0.08], ['#777777', 0.1]]));
  assert.ok(hueNear(hsl(p.accent).h, 30, 10), `bronze hue (${p.accent})`);
});

test('a grey photo has no accent, still a dark tone', () => {
  const p = run(photo([['#101010', 0.4], ['#444444', 0.2], ['#888888', 0.2], ['#dddddd', 0.2]]));
  assert.equal(p.accent, null);
  assert.match(p.dark, HEX);
  // a hair of colour (under 3 %) is still grey
  const q = run(photo([['#111111', 0.6], ['#999999', 0.38], ['#c9a04a', 0.02]]));
  assert.equal(q.accent, null, `2 % gold is not a colour (${q.accent})`);
});

test('fully transparent, empty, missing → nothing', () => {
  const t = run(photo([['#c9a04a', 1]], { alpha: 0 }));
  assert.deepEqual(t, { accent: null, dark: null, band: null });
  for (const bad of [new Uint8ClampedArray(0), [], null, undefined, 'abc', 42, {}]) {
    assert.deepEqual(paletteFromPixels(bad, { width: 0, height: 0 }), { accent: null, dark: null, band: null }, `bad ${JSON.stringify(bad)}`);
  }
  assert.deepEqual(paletteFromPixels([201, 160, 74], {}), { accent: null, dark: null, band: null }, 'not even one whole pixel');
});

test('transparent pixels do not vote: a gold logo on a transparent square', () => {
  const { data, width, height } = photo([['#c9a04a', 0.1], ['#3060d0', 0.9]]);
  for (let i = Math.round(width * height * 0.1); i < width * height; i += 1) data[i * 4 + 3] = 0;   // blue is see-through
  const p = paletteFromPixels(data, { width, height });
  assert.ok(hueNear(hsl(p.accent).h, 41, 8), `gold, not the hidden blue (${p.accent})`);
  assert.equal(p.dark, null, 'no dark pixel at all');
});

test('one pixel, and a plain Array', () => {
  const p = paletteFromPixels([201, 160, 74, 255], { width: 1, height: 1 });
  assert.ok(hueNear(hsl(p.accent).h, 41, 3), p.accent);
  assert.equal(p.dark, null);
  const d = paletteFromPixels([10, 9, 8, 255], { width: 1, height: 1 });
  assert.equal(d.accent, null);
  assert.match(d.dark, HEX);
  // width × height smaller than the array: only that many pixels are read
  const cut = paletteFromPixels([10, 9, 8, 255, 201, 160, 74, 255], { width: 1, height: 1 });
  assert.equal(cut.accent, null);
});

test('noise: gold under 30 % random pixels is still gold; pure noise is a hex or null, never a crash', () => {
  const p = run(photo([['#0e0c0a', 0.5], ['#c9a04a', 0.2], ['noise', 0.3]]));
  assert.ok(hueNear(hsl(p.accent).h, 40, 12), `gold through the noise (${p.accent})`);
  const n = run(photo([['noise', 1]], { seed: 99 }));
  assert.ok(n.accent === null || HEX.test(n.accent), String(n.accent));
  assert.ok(n.dark === null || HEX.test(n.dark), String(n.dark));
  assert.deepEqual(run(photo([['noise', 1]], { seed: 99 })), n, 'same pixels, same answer');
});

test('neon and pastel pixels do not drown a real mid colour', () => {
  // a small white-ish wash (l > 0.9) and a near-black olive tint are not the accent
  const p = run(photo([['#f7f3ea', 0.5], ['#141608', 0.3], ['#b8946a', 0.2]]));
  assert.ok(hueNear(hsl(p.accent).h, 33, 10), `the bronze (${p.accent})`);
});

test('photoPalette outside a browser: nothing, without throwing', async () => {
  assert.deepEqual(await photoPalette('/api/media/abc'), { accent: null, dark: null, band: null });
  assert.deepEqual(await photoPalette(''), { accent: null, dark: null, band: null });
  assert.deepEqual(await photoPalette(null), { accent: null, dark: null, band: null });
});

// ---------------------------------------------------------------- the band (2026-11-26)
// iOS 27 poster cards: with no footer colour of the owner's, Wallet draws the
// band under the fields as a blur of the photo's bottom. `band` = the average
// colour of the photo's bottom quarter (opaque pixels only).
const rows = (w, h, paint) => {
  const out = new Uint8ClampedArray(w * h * 4);
  for (let y = 0; y < h; y += 1) for (let x = 0; x < w; x += 1) out.set([...paint(x, y), 255], (y * w + x) * 4);
  return { data: out, width: w, height: h };
};

test('band: the bottom quarter only, averaged', () => {
  // graphite top, warm bronze bottom quarter (Palissy)
  const p = run(rows(64, 64, (x, y) => (y >= 48 ? rgbOf('#8c6a48') : rgbOf('#3a3b3f'))));
  assert.equal(p.band, '#8c6a48');
  // a 50/50 bottom: the mean of the two
  const q = run(rows(64, 64, (x, y) => (y < 48 ? rgbOf('#ffffff') : x % 2 ? rgbOf('#000000') : rgbOf('#c8a050'))));
  assert.equal(q.band, '#645028');
});

test('band: a black photo lit with gold at the top stays dark at the bottom', () => {
  const p = run(rows(64, 64, (x, y) => (y < 20 && x > 10 && x < 50 ? rgbOf('#c9a04a') : rgbOf('#15110c'))));
  assert.equal(p.band, '#15110c');
  assert.ok(hueNear(hsl(p.accent).h, 41, 6), `the gold is still the accent (${p.accent})`);
});

test('band: transparent pixels in the bottom do not count; all transparent → null', () => {
  const { data, width, height } = rows(8, 8, (x, y) => (y >= 6 ? (x < 4 ? rgbOf('#6e7442') : rgbOf('#ffffff')) : rgbOf('#101010')));
  for (let y = 6; y < 8; y += 1) for (let x = 4; x < 8; x += 1) data[(y * 8 + x) * 4 + 3] = 0;
  assert.equal(paletteFromPixels(data, { width, height }).band, '#6e7442');
  for (let i = 48; i < 64; i += 1) data[i * 4 + 3] = 0;
  assert.equal(paletteFromPixels(data, { width, height }).band, null);
});

test('band: one pixel, a tiny photo, no size given', () => {
  assert.equal(paletteFromPixels([20, 80, 184, 255], { width: 1, height: 1 }).band, '#1450b8');
  // 1×3: the bottom quarter rounds up to the last row
  assert.equal(paletteFromPixels([0, 0, 0, 255, 0, 0, 0, 255, 248, 176, 8, 255], { width: 1, height: 3 }).band, '#f8b008');
  // no size: the last quarter of the pixels (row order)
  const flat = [...Array(12)].flatMap((_, i) => (i >= 9 ? [140, 106, 72, 255] : [0, 0, 0, 255]));
  assert.equal(paletteFromPixels(flat, {}).band, '#8c6a48');
});
