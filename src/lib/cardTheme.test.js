// Run: node --test src/lib/cardTheme.test.js
// « Ma carte en ligne » takes its colours from the shop's own card (user,
// 2026-11-25): calm page tint, the card's dark colour under the photo, and
// text that always reads (WCAG 4.5:1 body, 3:1 large). Garbage in → neutral.
import test from 'node:test';
import assert from 'node:assert/strict';
import { themeFromCard, themeVars, parseColor, contrast } from './cardTheme.js';

const HEX = /^#[0-9a-f]{6}$/i;
const TEXT_ON = [
  // [foreground token, background token, minimum ratio]
  ['ink', 'page', 4.5], ['ink', 'sheet', 4.5], ['muted', 'page', 4.5], ['muted', 'sheet', 4.5],
  ['faint', 'sheet', 4.5], ['brandInk', 'sheet', 4.5], ['brandInk', 'page', 4.5],
  ['accentInk', 'sheet', 4.5], ['accentInk', 'accentSoft', 4.5], ['btnInk', 'btn', 4.5],
  ['bannerInk', 'banner', 4.5], ['ok', 'sheet', 4.5], ['ok', 'okSoft', 4.5],
];
const hsl = (hex) => {
  const n = parseInt(hex.slice(1), 16);
  const r = ((n >> 16) & 255) / 255, g = ((n >> 8) & 255) / 255, b = (n & 255) / 255;
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2, d = mx - mn;
  if (!d) return { h: 0, s: 0, l };
  const s = d / (1 - Math.abs(2 * l - 1));
  let h = mx === r ? ((g - b) / d) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
  h *= 60; if (h < 0) h += 360;
  return { h, s, l };
};
const hueNear = (a, b, tol) => Math.min(Math.abs(a - b), 360 - Math.abs(a - b)) <= tol;

function assertReadable(t, why) {
  for (const k of ['page', 'sheet', 'ink', 'muted', 'faint', 'line', 'soft', 'brand', 'brandInk', 'accent',
    'accentSoft', 'accentInk', 'btn', 'btnInk', 'banner', 'bannerInk', 'heroFade', 'ok', 'okSoft']) {
    assert.match(t[k], HEX, `${why}: ${k} is a hex colour (${t[k]})`);
  }
  for (const [fg, bg, min] of TEXT_ON) {
    const r = contrast(t[fg], t[bg]);
    assert.ok(r >= min, `${why}: ${fg} on ${bg} = ${r.toFixed(2)} < ${min}`);
  }
  // big numbers (34px) use brandInk; the bell dot / bar are graphics ≥ 3:1 is not required for the dot
  assert.ok(contrast('#FFFFFF', t.heroFade) >= 4.5, `${why}: white greeting on heroFade`);
  // calm page: pale and not saturated
  const p = hsl(t.page);
  assert.ok(p.l >= 0.92, `${why}: page is light (${t.page})`);
  assert.ok(p.s <= 0.6, `${why}: page is not shouty (${t.page})`);
  assert.ok(hsl(t.heroFade).l <= 0.2, `${why}: heroFade is dark (${t.heroFade})`);
  assert.ok(typeof t.bar === 'string' && t.bar.startsWith('linear-gradient('), `${why}: bar gradient`);
}

test('parseColor reads #rrggbb, #rgb, bare hex, rgb()/rgba(), and refuses garbage', () => {
  assert.equal(parseColor('#1450B8'), '#1450b8');
  assert.equal(parseColor('1450b8'), '#1450b8');
  assert.equal(parseColor('  #FFF '), '#ffffff');
  assert.equal(parseColor('#abc'), '#aabbcc');
  assert.equal(parseColor('rgb(20, 80, 184)'), '#1450b8');
  assert.equal(parseColor('rgba(20,80,184,0.5)'), '#1450b8');
  assert.equal(parseColor('rgb(300, -4, 12)'), '#ff000c');
  for (const bad of [null, undefined, '', '#12', '#12345', '#ggg000', 'blue', 'rgb(1,2)', 12, {}, [], 'url(x)', 'transparent']) {
    assert.equal(parseColor(bad), null, `garbage ${JSON.stringify(bad)}`);
  }
});

test('missing card / empty card / garbage colours → the neutral default, readable', () => {
  const base = themeFromCard();
  assertReadable(base, 'no card');
  assert.deepEqual(themeFromCard(null), base);
  assert.deepEqual(themeFromCard({}), base);
  assert.deepEqual(themeFromCard({ brand_color: 'nope', card_bg_color: '#12', primary_color: 42, accent_color: 'rgb(a,b,c)' }), base);
  assert.equal(base.neutral, true);
});

test('FidClic blue + yellow comes out close to the approved palette', () => {
  const t = themeFromCard({ brand_color: '#1450B8', accent_color: '#F8B008' });
  assertReadable(t, 'fidclic');
  assert.equal(t.btn.toLowerCase(), '#1450b8');
  assert.equal(t.btnInk.toLowerCase(), '#ffffff');
  assert.equal(t.brandInk.toLowerCase(), '#1450b8');
  assert.equal(t.accent.toLowerCase(), '#f8b008');
  assert.ok(hueNear(hsl(t.page).h, 218, 12), `page is a blue tint (${t.page})`);
  assert.ok(hueNear(hsl(t.heroFade).h, 218, 12), `heroFade is a dark blue (${t.heroFade})`);
  assert.ok(hueNear(hsl(t.accentSoft).h, 42, 10), `accentSoft is a pale yellow (${t.accentSoft})`);
  assert.equal(t.neutral, false);
});

test('black + gold (Royal Trim): warm page, dark button with gold ink, near-black fade', () => {
  const t = themeFromCard({ card_bg_color: '#15120E', accent_color: '#C9A04A' });
  assertReadable(t, 'black+gold');
  assert.ok(hsl(t.btn).l < 0.15, `button stays black (${t.btn})`);
  assert.ok(hueNear(hsl(t.btnInk).h, 42, 14) && hsl(t.btnInk).s > 0.3, `button ink is gold (${t.btnInk})`);
  assert.ok(hueNear(hsl(t.page).h, 40, 15), `page tint comes from the gold (${t.page})`);
  assert.ok(hueNear(hsl(t.brandInk).h, 40, 15), `numbers in a dark gold (${t.brandInk})`);
  assert.ok(hsl(t.heroFade).l < 0.1);
});

test('graphite + bronze and olive + gold stay in their own hues', () => {
  const g = themeFromCard({ brand_color: '#1E1F22', poster_footer_color: '#8C7357', accent_color: '#B8946A' });
  assertReadable(g, 'graphite+bronze');
  assert.ok(hueNear(hsl(g.page).h, 32, 18), `bronze page (${g.page})`);
  const o = themeFromCard({ brand_color: '#6E7442', accent_color: '#BFA75F' });
  assertReadable(o, 'olive+gold');
  assert.ok(hueNear(hsl(o.page).h, 66, 15), `olive page (${o.page})`);
  assert.ok(hueNear(hsl(o.btn).h, 66, 15), `olive button (${o.btn})`);
});

test('a dark but coloured brand (dark olive + gold) writes in its gold, like black', () => {
  const t = themeFromCard({ brand_color: '#2A2E1E', accent_color: '#BFA75F' });
  assertReadable(t, 'dark olive+gold');
  assert.ok(hueNear(hsl(t.btnInk).h, 45, 15) && hsl(t.btnInk).s > 0.3, `gold button ink (${t.btnInk})`);
  assert.ok(hueNear(hsl(t.brandInk).h, 45, 15), `gold numbers (${t.brandInk})`);
  assert.ok(hueNear(hsl(t.page).h, 75, 15), `olive page (${t.page})`);
});

test('#fff and #000 cards: still a dark fade and readable text', () => {
  const w = themeFromCard({ brand_color: '#FFFFFF' });
  assertReadable(w, 'white');
  const w3 = themeFromCard({ card_bg_color: '#fff', accent_color: '#fff' });
  assertReadable(w3, 'white 3-digit');
  const b = themeFromCard({ brand_color: '#000000', accent_color: '#000' });
  assertReadable(b, 'black');
});

test('neon green is calmed down: pale page, darker button, readable ink', () => {
  const t = themeFromCard({ brand_color: '#39FF14' });
  assertReadable(t, 'neon');
  assert.ok(hsl(t.page).s <= 0.6);
  assert.ok(hsl(t.btn).l <= 0.45, `button darkened (${t.btn})`);
  assert.ok(hueNear(hsl(t.btn).h, 110, 12), `still green (${t.btn})`);
  const y = themeFromCard({ brand_color: '#FFFF00', accent_color: '#00FFFF' });
  assertReadable(y, 'neon yellow + cyan');
});

test('field priority: brand_color, then card_bg_color, then primary_color, then design', () => {
  const a = themeFromCard({ brand_color: '#1450B8', card_bg_color: '#C0392B' });
  assert.equal(a.btn.toLowerCase(), '#1450b8');
  const b = themeFromCard({ brand_color: 'nope', card_bg_color: '#1450B8', primary_color: '#C0392B' });
  assert.equal(b.btn.toLowerCase(), '#1450b8');
  const c = themeFromCard({ primary_color: '#1450B8' });
  assert.equal(c.btn.toLowerCase(), '#1450b8');
  const d = themeFromCard({ design: { primary_color: 'rgb(20,80,184)' } });
  assert.equal(d.btn.toLowerCase(), '#1450b8');
});

test('the card surface decides the fade under the photo', () => {
  const t = themeFromCard({ brand_color: '#1450B8', surface_color: '#2F2721' });
  assert.ok(hueNear(hsl(t.heroFade).h, 25, 15), `fade from the surface (${t.heroFade})`);
  const p = themeFromCard({ brand_color: '#1450B8', surface: 'noir' });
  assert.ok(hsl(p.heroFade).l < 0.12);
  const light = themeFromCard({ brand_color: '#1450B8', surface_color: '#F6EFE3' });
  assert.ok(hsl(light.heroFade).l <= 0.2, 'a cream surface is darkened for the fade');
});

test('themeVars turns tokens into CSS custom properties', () => {
  const v = themeVars(themeFromCard({ brand_color: '#1450B8' }));
  for (const k of ['--page', '--sheet', '--ink', '--muted', '--faint', '--line', '--soft', '--brand', '--brand-ink',
    '--accent', '--accent-soft', '--accent-ink', '--btn', '--btn-ink', '--banner', '--banner-2', '--banner-ink', '--bar',
    '--hero-fade', '--ok', '--ok-soft']) {
    assert.ok(typeof v[k] === 'string' && v[k].length > 0, `${k} set`);
  }
  assert.equal(v['--neutral'], undefined, 'no flags leak into CSS');
});
