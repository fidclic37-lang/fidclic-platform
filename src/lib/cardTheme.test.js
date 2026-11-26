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

function assertReadable(t, why, { band = false } = {}) {
  for (const k of ['page', 'sheet', 'ink', 'muted', 'faint', 'line', 'soft', 'brand', 'brandInk', 'accent',
    'accentSoft', 'accentInk', 'btn', 'btnInk', 'banner', 'bannerInk', 'heroFade', 'ok', 'okSoft']) {
    assert.match(t[k], HEX, `${why}: ${k} is a hex colour (${t[k]})`);
  }
  for (const [fg, bg, min] of TEXT_ON) {
    const r = contrast(t[fg], t[bg]);
    assert.ok(r >= min, `${why}: ${fg} on ${bg} = ${r.toFixed(2)} < ${min}`);
  }
  // big numbers (34px) use brandInk; the bell dot / bar are graphics ≥ 3:1 is not required for the dot
  // the greeting: white on the dark fade (2026-11-25); on a card's own band (round 4) whichever reads
  assert.ok(contrast(t.heroInk, t.heroFade) >= 4.5, `${why}: greeting ${t.heroInk} on heroFade ${t.heroFade}`);
  if (!band) assert.equal(t.heroInk, '#ffffff', `${why}: white greeting on the dark fade`);
  // calm page: pale and not saturated
  const p = hsl(t.page);
  assert.ok(p.l >= 0.92, `${why}: page is light (${t.page})`);
  assert.ok(p.s <= 0.6, `${why}: page is not shouty (${t.page})`);
  if (!band) assert.ok(hsl(t.heroFade).l <= 0.2, `${why}: heroFade is dark (${t.heroFade})`);
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
  // round 4: the owner's footer colour IS the band under the photo (cardThemeMatch.test.js)
  const g = themeFromCard({ brand_color: '#1E1F22', poster_footer_color: '#8C7357', accent_color: '#B8946A' });
  assertReadable(g, 'graphite+bronze', { band: true });
  assert.equal(g.heroFade, '#8c7357');
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

// ---------------------------------------------------------------- the photo's colours
// user, 2026-11-25: Royal Trim's cards are black / white / grey in Pass Designer,
// their look is the photo (Liberté black + gold, Palissy graphite + bronze,
// PL-Monstre olive + gold) — lib/photoPalette reads it, themeFromCard(card, photo) uses it.
const GOLD = { accent: '#c9a04a', dark: '#0f0d0b' };
const OLIVE = { accent: '#6a7040', dark: '#15170e' };
const BRONZE = { accent: '#97693f', dark: '#26272a' };

test('black card + gold photo comes out exactly like the approved black + gold card', () => {
  const t = themeFromCard({ card_bg_color: '#15120E' }, GOLD);
  assertReadable(t, 'black card, gold photo');
  assert.deepEqual(t, themeFromCard({ card_bg_color: '#15120E', accent_color: '#C9A04A' }));
  assert.ok(hueNear(hsl(t.page).h, 40, 15) && hsl(t.page).s > 0.1, `warm light page (${t.page})`);
  assert.ok(hsl(t.btn).l < 0.15, `dark button (${t.btn})`);
  assert.ok(hueNear(hsl(t.btnInk).h, 42, 14) && hsl(t.btnInk).s > 0.3, `gold ink on it (${t.btnInk})`);
  assert.match(t.bar, /linear-gradient/);
  assert.ok(t.bar.includes(t.accentInk), `gold bar (${t.bar})`);
  assert.equal(t.neutral, false);
});

test('no colour at all + a gold photo: gold accent, dark from the photo', () => {
  const t = themeFromCard({}, GOLD);
  assertReadable(t, 'no colour, gold photo');
  assert.equal(t.neutral, false);
  assert.ok(hueNear(hsl(t.page).h, 40, 15), `warm page (${t.page})`);
  assert.ok(hueNear(hsl(t.btnInk).h, 42, 14) && hsl(t.btnInk).s > 0.3, `gold button ink (${t.btnInk})`);
  assert.ok(hsl(t.btn).l < 0.15, `dark button (${t.btn})`);
  assert.ok(hsl(t.heroFade).l < 0.1, `the photo's dark under it (${t.heroFade})`);
});

test('graphite card + bronze photo, black card + olive photo: their own hues', () => {
  const g = themeFromCard({ brand_color: '#1E1F22', accent_color: '#9a9a9a' }, BRONZE);
  assertReadable(g, 'graphite, bronze photo');
  assert.ok(hueNear(hsl(g.page).h, 29, 15), `bronze page (${g.page})`);
  assert.ok(hueNear(hsl(g.btnInk).h, 29, 15), `bronze button ink (${g.btnInk})`);
  const o = themeFromCard({ card_bg_color: '#000000', logo_text_color: '#FFFFFF' }, OLIVE);
  assertReadable(o, 'black, olive photo');
  assert.ok(hueNear(hsl(o.page).h, 67, 15) && hsl(o.page).s > 0.1, `olive page (${o.page})`);
  assert.ok(hueNear(hsl(o.brandInk).h, 67, 15), `olive numbers (${o.brandInk})`);
});

test('white / grey cards take the photo too, and its dark under the photo', () => {
  const w = themeFromCard({ brand_color: '#FFFFFF', surface: 'blanc' }, GOLD);
  assertReadable(w, 'white card, gold photo');
  assert.ok(hueNear(hsl(w.page).h, 40, 15), `warm page (${w.page})`);
  assert.ok(hueNear(hsl(w.heroFade).h, hsl(GOLD.dark).h, 20) && hsl(w.heroFade).l < 0.12, `photo's dark fade (${w.heroFade})`);
  const g = themeFromCard({ brand_color: '#8A8A8A' }, OLIVE);
  assertReadable(g, 'grey card, olive photo');
  assert.ok(hueNear(hsl(g.page).h, 67, 15), `olive page (${g.page})`);
});

test('a chromatic card ignores the photo', () => {
  const card = { brand_color: '#1450B8', accent_color: '#F8B008' };
  assert.deepEqual(themeFromCard(card, GOLD), themeFromCard(card));
  const accentOnly = { card_bg_color: '#15120E', accent_color: '#B03A2E' };   // a red the owner set
  assert.deepEqual(themeFromCard(accentOnly, OLIVE), themeFromCard(accentOnly));
  const olive = { brand_color: '#6E7442' };
  assert.deepEqual(themeFromCard(olive, GOLD), themeFromCard(olive));
});

test('no photo, a grey photo, or garbage → today\'s theme', () => {
  const black = { card_bg_color: '#15120E' };
  for (const p of [undefined, null, {}, { accent: null, dark: null }, { accent: '#808080' }, { accent: 'nope', dark: 42 }, 'gold', 7]) {
    assert.deepEqual(themeFromCard(black, p), themeFromCard(black), `photo ${JSON.stringify(p)}`);
    assert.deepEqual(themeFromCard({}, p), themeFromCard(), `no colour, photo ${JSON.stringify(p)}`);
  }
  assert.equal(themeFromCard({}, { accent: null, dark: null }).neutral, true);
});

test('only the photo\'s dark: neutral colours, the photo\'s dark under it', () => {
  const t = themeFromCard({}, { accent: null, dark: '#1b140c' });
  assertReadable(t, 'photo dark only');
  assert.equal(t.neutral, true);
  assert.equal(t.page, themeFromCard().page);
  assert.ok(hueNear(hsl(t.heroFade).h, 33, 15), `warm fade (${t.heroFade})`);
  // the card's own dark colour still wins over the photo's
  const c = themeFromCard({ card_bg_color: '#101B2E' }, { accent: '#c9a04a', dark: '#2a1a0a' });
  assert.ok(hueNear(hsl(c.heroFade).h, 218, 15), `the card's navy fade (${c.heroFade})`);
});

test('every photo colour keeps the contrast guarantees', () => {
  const photos = ['#c9a04a', '#6a7040', '#97693f', '#ff0000', '#00ffd5', '#f5e663', '#3a1bd1', '#e85d9a', '#7a2a2a']
    .map((accent) => ({ accent, dark: '#0d0d0d' }));
  const cards = [{}, { card_bg_color: '#000' }, { brand_color: '#fff' }, { brand_color: '#777777' }, { card_bg_color: '#1E1F22', surface: 'creme' }];
  for (const p of photos) for (const c of cards) assertReadable(themeFromCard(c, p), `${JSON.stringify(c)} + ${p.accent}`);
});
