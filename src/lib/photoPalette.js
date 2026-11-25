/**
 * photoPalette.js — the colours of the card's photo (user, 2026-11-25).
 *
 * Shops like Royal Trim design their card in Pass Designer with black, white
 * and grey only; their real look lives in the photo (Liberté = black + gold,
 * Palissy = graphite + bronze, PL-Monstre = olive + gold). « Ma carte en
 * ligne » was colourless for them. This module reads the photo:
 *
 *   accent  the dominant chromatic hue: a hue histogram (36 bins of 10°) of the
 *           reasonably saturated, mid-light pixels, weighted by saturation and
 *           by how close to mid-lightness they are; the winning bin (smoothed
 *           with its neighbours) gives the average colour of those three bins.
 *           null when under 3 % of the visible pixels have a colour (a grey photo).
 *   dark    the average of the photo's dark pixels (l < 0.2), or null.
 *
 * Transparent pixels (alpha < 128) never vote. Pure maths, no DOM: the thin
 * browser loader photoPalette(url) draws the photo the hero already loaded into
 * a 64×64 canvas, and caches the answer per URL (memory + sessionStorage).
 *
 * Tests: node --test src/lib/photoPalette.test.js
 */

const EMPTY = Object.freeze({ accent: null, dark: null });
const BINS = 36;
const MIN_SHARE = 0.03;

const hex2 = (x) => Math.max(0, Math.min(255, Math.round(x))).toString(16).padStart(2, '0');
const toHex = (r, g, b) => `#${hex2(r)}${hex2(g)}${hex2(b)}`;

/** { accent, dark } of an RGBA pixel buffer (Uint8ClampedArray or Array). */
export function paletteFromPixels(rgba, { width, height } = {}) {
  if (!rgba || typeof rgba !== 'object' || typeof rgba.length !== 'number') return { ...EMPTY };
  let n = Math.floor(rgba.length / 4);
  const w = Number(width), h = Number(height);
  if (Number.isFinite(w) && Number.isFinite(h) && w > 0 && h > 0) n = Math.min(n, Math.floor(w) * Math.floor(h));
  if (n <= 0) return { ...EMPTY };

  const binW = new Float64Array(BINS), binR = new Float64Array(BINS), binG = new Float64Array(BINS), binB = new Float64Array(BINS);
  let opaque = 0, chroma = 0, darkN = 0, dR = 0, dG = 0, dB = 0;
  for (let i = 0; i < n; i += 1) {
    const o = i * 4;
    const a = Number(rgba[o + 3]);
    if (!(a >= 128)) continue;
    const r = Number(rgba[o]) || 0, g = Number(rgba[o + 1]) || 0, b = Number(rgba[o + 2]) || 0;
    opaque += 1;
    const mx = Math.max(r, g, b) / 255, mn = Math.min(r, g, b) / 255;
    const l = (mx + mn) / 2, d = mx - mn;
    if (l < 0.2) { darkN += 1; dR += r; dG += g; dB += b; }
    if (!d) continue;
    const s = d / (1 - Math.abs(2 * l - 1));
    if (s < 0.2 || d < 0.08 || l < 0.18 || l > 0.85) continue;
    const R = r / 255, G = g / 255, B = b / 255;
    let hue = mx === R ? ((G - B) / d) % 6 : mx === G ? (B - R) / d + 2 : (R - G) / d + 4;
    hue *= 60;
    if (hue < 0) hue += 360;
    const weight = Math.min(1, s) * (1 - Math.abs(l - 0.5) * 1.4);
    const bin = Math.floor(hue / (360 / BINS)) % BINS;
    chroma += 1;
    binW[bin] += weight; binR[bin] += r * weight; binG[bin] += g * weight; binB[bin] += b * weight;
  }
  if (!opaque) return { ...EMPTY };

  let accent = null;
  if (chroma / opaque >= MIN_SHARE) {
    const at = (i) => (i + BINS) % BINS;
    let best = -1, score = -1;
    for (let i = 0; i < BINS; i += 1) {
      const sc = binW[i] + 0.5 * (binW[at(i - 1)] + binW[at(i + 1)]);
      if (sc > score) { score = sc; best = i; }
    }
    let W = 0, R = 0, G = 0, B = 0;
    for (const j of [at(best - 1), best, at(best + 1)]) { W += binW[j]; R += binR[j]; G += binG[j]; B += binB[j]; }
    if (W > 0) accent = toHex(R / W, G / W, B / W);
  }
  const dark = darkN / opaque >= MIN_SHARE ? toHex(dR / darkN, dG / darkN, dB / darkN) : null;
  return { accent, dark };
}

// ---------------------------------------------------------------- browser loader

const SIZE = 64;
const TIMEOUT_MS = 8000;
const KEY = 'fidclic:photo-palette:';
const mem = new Map();
const HEX = /^#[0-9a-f]{6}$/;
const clean = (v) => ({
  accent: typeof v?.accent === 'string' && HEX.test(v.accent) ? v.accent : null,
  dark: typeof v?.dark === 'string' && HEX.test(v.dark) ? v.dark : null,
});

/** Draw `src` into a small canvas: { ok, palette }. Never rejects. */
function read(src) {
  return new Promise((resolve) => {
    let done = false;
    const end = (v) => { if (!done) { done = true; resolve(v); } };
    const fail = () => end({ ok: false, palette: { ...EMPTY } });
    try {
      const img = new Image();
      img.crossOrigin = 'anonymous';          // a canvas fed without CORS is « tainted » and cannot be read
      img.decoding = 'async';
      img.onload = () => {
        try {
          const canvas = document.createElement('canvas');
          canvas.width = SIZE; canvas.height = SIZE;
          const ctx = canvas.getContext('2d', { willReadFrequently: true });
          ctx.drawImage(img, 0, 0, SIZE, SIZE);
          const px = ctx.getImageData(0, 0, SIZE, SIZE);
          end({ ok: true, palette: paletteFromPixels(px.data, { width: SIZE, height: SIZE }) });
        } catch (_e) { fail(); }             // tainted canvas, no 2d context
      };
      img.onerror = fail;
      setTimeout(fail, TIMEOUT_MS);
      img.src = src;
    } catch (_e) { fail(); }
  });
}

/**
 * The palette of the photo at `url` — Promise of { accent, dark }, never
 * rejects; { accent: null, dark: null } outside a browser or when the photo
 * cannot be read. A « /api/media/<id> » that Vercel Blob answers without CORS
 * is read once more from our own origin (?raw=1); the answer is kept for the
 * session, so a photo costs that at most once per visit.
 */
export function photoPalette(url) {
  const src = typeof url === 'string' ? url.trim() : '';
  if (!src || typeof window === 'undefined' || typeof document === 'undefined' || typeof Image === 'undefined') {
    return Promise.resolve({ ...EMPTY });
  }
  if (mem.has(src)) return mem.get(src);
  try {
    const saved = JSON.parse(window.sessionStorage.getItem(KEY + src) || 'null');
    if (saved && typeof saved === 'object') {
      const p = Promise.resolve(clean(saved));
      mem.set(src, p);
      return p;
    }
  } catch (_e) { /* private mode, blocked storage */ }

  const raw = /^\/api\/media\/[^?#]+$/.test(src) ? `${src}?raw=1` : null;
  const p = read(src)
    .then((first) => (first.ok || !raw ? first : read(raw)))
    .then(({ ok, palette }) => {
      const v = clean(palette);
      if (ok) { try { window.sessionStorage.setItem(KEY + src, JSON.stringify(v)); } catch (_e) { /* full, blocked */ } }
      return v;
    });
  mem.set(src, p);
  return p;
}
