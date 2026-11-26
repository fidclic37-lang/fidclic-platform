/**
 * cardTheme.js — the derivation engine behind the wallet-anatomy card.
 *
 * The old designer exposed ~17 colour pickers and merchants produced carnival
 * cards with them (blue band + red octagon stamps + cyan name + pink meter on
 * one card — the screenshot that triggered this redesign). The new contract:
 *
 *     merchant chooses   brand colour + surface (sombre | clair)
 *     this module derives everything else with contrast arithmetic
 *
 * so any input produces a professional card. Colour is maths here, not taste.
 *
 * Every derived value is WCAG-aware: ink on any surface resolves to the
 * highest-contrast option, and brand-on-surface falls back to a lightened or
 * darkened variant of the brand when the raw brand fails 3:1 against the
 * surface (a pastel brand on a light card would otherwise vanish).
 */

// ---------------------------------------------------------------- colour math

function hexToRgb(hex) {
  const h = (hex || '').replace('#', '').trim();
  const v = h.length === 3 ? h.split('').map((c) => c + c).join('') : h;
  const n = parseInt(v, 16);
  if (Number.isNaN(n) || v.length !== 6) return null;
  return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 };
}

function rgbToHex({ r, g, b }) {
  const c = (x) => Math.max(0, Math.min(255, Math.round(x))).toString(16).padStart(2, '0');
  return `#${c(r)}${c(g)}${c(b)}`;
}

/** Relative luminance per WCAG 2.x. */
function luminance(hex) {
  const rgb = hexToRgb(hex);
  if (!rgb) return 0;
  const f = (v) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * f(rgb.r) + 0.7152 * f(rgb.g) + 0.0722 * f(rgb.b);
}

/** WCAG contrast ratio between two hex colours (1..21). */
export function contrast(a, b) {
  const l1 = luminance(a);
  const l2 = luminance(b);
  const [hi, lo] = l1 >= l2 ? [l1, l2] : [l2, l1];
  return (hi + 0.05) / (lo + 0.05);
}

/** Mix `hex` toward pure white (amt>0) or pure black (amt<0), amt in 0..1. */
function shade(hex, amt) {
  const rgb = hexToRgb(hex);
  if (!rgb) return hex;
  const target = amt >= 0 ? 255 : 0;
  const t = Math.abs(amt);
  return rgbToHex({
    r: rgb.r + (target - rgb.r) * t,
    g: rgb.g + (target - rgb.g) * t,
    b: rgb.b + (target - rgb.b) * t,
  });
}

/** rgba() string from hex + alpha — for tracks and hairlines. */
function tint(hex, alpha) {
  const rgb = hexToRgb(hex) || { r: 0, g: 0, b: 0 };
  return `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, ${alpha})`;
}

/**
 * A variant of `brand` guaranteed to read against `surface` (≥3:1, the WCAG
 * threshold for graphical objects). Walks the brand toward white on dark
 * surfaces and toward black on light ones until it clears the bar.
 */
function legibleBrand(brand, surface) {
  if (contrast(brand, surface) >= 3) return brand;
  const towardWhite = luminance(surface) < 0.5;
  let candidate = brand;
  for (let step = 0.15; step <= 0.9; step += 0.15) {
    candidate = shade(brand, towardWhite ? step : -step);
    if (contrast(candidate, surface) >= 3) return candidate;
  }
  return towardWhite ? '#FFFFFF' : '#111111';
}

// ---------------------------------------------------------------- the engine

/**
 * Fixed metallic tier set. Deliberately NOT derived from the brand and NOT
 * merchant-editable: bronze/silver/gold/black-card mean the same thing on
 * every loyalty programme on earth, and that universality is the point.
 */
const TIER_CHIPS = {
  bronze: { bg: '#8C6239', ink: '#FFF6EC', label: 'Bronze' },
  silver: { bg: '#9BA3AD', ink: '#10151B', label: 'Argent' },
  gold:   { bg: '#C9A34E', ink: '#241B04', label: 'Or' },
  vip:    { bg: '#17181C', ink: '#E8D9A0', label: 'VIP' },
};

/**
 * Curated surface palette. Real brand identities are DUOS — black+gold,
 * navy+orange, crème+chocolat — so the surface is the second brand colour,
 * not a fixed constant. Curated names give safe defaults; `surface_color`
 * accepts any hex and runs through the same derivation, so even a custom
 * surface cannot produce unreadable text.
 */
export const SURFACE_PRESETS = {
  noir:       '#141519',
  anthracite: '#1C1D22',
  marine:     '#101B2E',
  foret:      '#12211A',
  espresso:   '#211711',
  blanc:      '#FDFCFA',
  creme:      '#F6EFE3',
  sable:      '#EFE9DD',
};

// Ink candidates for ANY surface — the engine picks whichever reads better.
const INK_LIGHT = '#F4F3F0';
const INK_DARK = '#17181C';

function resolveSurface(surface, surfaceColor) {
  const custom = hexToRgb(surfaceColor) ? surfaceColor : null;
  if (custom) return custom;
  if (SURFACE_PRESETS[surface]) return SURFACE_PRESETS[surface];
  return surface === 'clair' ? SURFACE_PRESETS.blanc : SURFACE_PRESETS.anthracite;
}

/**
 * deriveCardTheme({ brandColor, surface }) → every colour the card needs.
 *
 * Returned tokens are the ONLY colours WalletCard is allowed to paint with.
 * If a new element needs a colour, it gets a new derived token here — never
 * a new merchant-facing picker.
 */
export function deriveCardTheme({ brandColor, surface, surfaceColor } = {}) {
  const bg = resolveSurface(surface, surfaceColor);
  const brandRaw = hexToRgb(brandColor) ? brandColor : '#C73E2C';
  const brand = legibleBrand(brandRaw, bg);

  // Ink: whichever extreme reads better on THIS surface — works for any hex,
  // curated or custom, so a mid-tone custom surface still gets legible text.
  const ink = contrast(INK_LIGHT, bg) >= contrast(INK_DARK, bg) ? INK_LIGHT : INK_DARK;
  // Text on a solid brand fill (hero fallback, filled stamps).
  const onBrand = contrast('#FFFFFF', brand) >= contrast('#111111', brand) ? '#FFFFFF' : '#111111';

  return {
    surface: bg,
    ink,                              // primary values (names, numbers)
    inkSoft: tint(ink, 0.62),         // secondary text
    label: tint(ink, 0.45),           // uppercase micro-labels
    hairline: tint(ink, 0.14),        // separators
    brand,                            // accent: meter fill, stamp fill, offer border
    brandRaw,                         // untouched merchant colour (hero fallback fill)
    onBrand,                          // text/check marks on brand fills
    track: tint(ink, 0.12),           // meter track, empty stamps
    // The QR sits ON the card, not on a white plate: its background is the
    // card's own surface and its modules are the same ink every other value
    // uses, so it inherits the contrast the merchant already chose.
    //
    // Scanners: a QR needs a quiet zone of four modules, which the white plate
    // used to provide by being padded — the renderers now ask for it with
    // marginSize, in the card's own colour. On a dark surface the code comes
    // out light-on-dark; phone cameras read that, industrial laser readers
    // historically do not. FidClic scans with phones and tablets.
    codeBg: bg,
    codeInk: ink,
    chipBg: tint(ink, 0.08),          // offer chip surface
    tiers: TIER_CHIPS,
  };
}

/** Preset definitions the designer offers. Pure data — render reads the theme. */
export const CARD_PRESETS = [
  { key: 'signature', label: 'Signature', surface: 'sombre', hero: 'image' },
  { key: 'lumiere',   label: 'Lumière',   surface: 'clair',  hero: 'image' },
  { key: 'couleur',   label: 'Couleur',   surface: 'sombre', hero: 'brand' },
  { key: 'minimal',   label: 'Minimal',   surface: 'sombre', hero: 'none' },
];

// ================================================================ page theme
/*
 * themeFromCard(card) — the colours of « Ma carte en ligne » (MyWalletCardPage,
 * photo/tabs redesign 2026-11-25), read from the shop's own card, automatic and
 * CALM (user, 2026-11-25: « har card ka apna rang aur logo »):
 *
 *   · the page is a pale, desaturated tint of the card's colour — never shouty
 *   · a near-black card (black + gold, graphite + bronze) takes its tint from
 *     its accent, so the page is warm, not grey
 *   · heroFade is the card's own dark colour (darkened when too light): the
 *     photo melts into it, then into the page
 *   · every text colour is checked: ≥ 4.5:1 for text, the white greeting on
 *     the fade too — lightness is moved until it reads
 *   · a missing or broken colour falls back to a neutral slate
 *   · themeFromCard(card, photo): a card with no colour of its own (black /
 *     white / grey) takes its accent from its photo (lib/photoPalette), exactly
 *     as if the owner had set it; the photo's dark goes under the photo when
 *     the card has no dark colour. A chromatic card ignores the photo.
 *
 * Tests: node --test src/lib/cardTheme.test.js
 */

const clamp01 = (v) => Math.max(0, Math.min(1, v));
const toHex2 = (x) => Math.max(0, Math.min(255, Math.round(x))).toString(16).padStart(2, '0');

/** '#rrggbb' (lower case) from '#rgb', '#rrggbb', 'rrggbb', 'rgb()', 'rgba()' — else null. */
export function parseColor(v) {
  if (typeof v !== 'string') return null;
  const s = v.trim().toLowerCase();
  if (!s) return null;
  const m = s.match(/^rgba?\(\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*(?:,\s*-?\d*(?:\.\d+)?%?\s*)?\)$/);
  if (m) return `#${toHex2(+m[1])}${toHex2(+m[2])}${toHex2(+m[3])}`;
  const h = s.replace(/^#/, '');
  if (/^[0-9a-f]{3}$/.test(h)) return `#${h.split('').map((c) => c + c).join('')}`;
  if (/^[0-9a-f]{6}$/.test(h)) return `#${h}`;
  return null;
}

function toHsl(hex) {
  const { r: R, g: G, b: B } = hexToRgb(hex);
  const r = R / 255, g = G / 255, b = B / 255;
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b);
  const l = (mx + mn) / 2, d = mx - mn;
  if (!d) return { h: 0, s: 0, l };
  const s = d / (1 - Math.abs(2 * l - 1));
  let h = mx === r ? ((g - b) / d) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
  h *= 60;
  if (h < 0) h += 360;
  return { h, s, l };
}

function hsl(h, s, l) {
  s = clamp01(s); l = clamp01(l);
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = l - c / 2;
  const [r, g, b] = h < 60 ? [c, x, 0] : h < 120 ? [x, c, 0] : h < 180 ? [0, c, x]
    : h < 240 ? [0, x, c] : h < 300 ? [x, 0, c] : [c, 0, x];
  return `#${toHex2((r + m) * 255)}${toHex2((g + m) * 255)}${toHex2((b + m) * 255)}`;
}

/** Move `fg`'s lightness away from every `bgs` until each reads at `min`:1. */
function readable(fg, bgs, min = 4.5) {
  const ok = (c) => bgs.every((b) => contrast(c, b) >= min);
  if (ok(fg)) return fg;
  const { h, s, l } = toHsl(fg);
  const dark = bgs.every((b) => luminance(b) > 0.18);        // light backgrounds: go darker
  for (let i = 1; i <= 50; i += 1) {
    const c = hsl(h, s, dark ? l - i * 0.02 : l + i * 0.02);
    if (ok(c)) return c;
  }
  return dark ? '#000000' : '#ffffff';
}

const chromatic = (hex) => { const { s, l } = toHsl(hex); return s >= 0.2 && l >= 0.12 && l <= 0.9; };
const firstColor = (...vals) => { for (const v of vals) { const c = parseColor(v); if (c) return c; } return null; };

const NEUTRAL = { h: 220, s: 0.12, brand: '#273142', accent: '#3b6fd6' };
const OK_SOFT = '#e5f3eb';

function legacyTheme(card, photo) {
  const c = card && typeof card === 'object' ? card : {};
  const d = c.design && typeof c.design === 'object' ? c.design : {};
  const cardBrand = firstColor(c.brand_color, c.card_bg_color, c.primary_color, d.primary_color);
  const cardAccent = [c.accent_color, c.poster_footer_color, c.logo_text_color, d.accent_color, c.secondary_color]
    .map(parseColor).find((x) => x && chromatic(x)) || null;
  // the card's photo (lib/photoPalette): its colour only when the owner set none
  // (black / white / grey in Pass Designer — user, 2026-11-25, Royal Trim)
  const p = photo && typeof photo === 'object' ? photo : {};
  const photoAccent = typeof p.accent === 'string' && parseColor(p.accent) && chromatic(parseColor(p.accent)) ? parseColor(p.accent) : null;
  const photoDark = typeof p.dark === 'string' ? parseColor(p.dark) : null;
  const ownerColour = !!cardAccent || (!!cardBrand && chromatic(cardBrand));
  const fromPhoto = !ownerColour && !!photoAccent;
  const accentRaw = cardAccent || (fromPhoto ? photoAccent : null);
  // no colour at all + a coloured photo: a near-black card, the photo's dark if it is one
  const brandRaw = cardBrand || (fromPhoto ? (photoDark && toHsl(photoDark).l < 0.2 ? photoDark : INK_DARK.toLowerCase()) : null);
  const neutral = !brandRaw && !accentRaw;

  const brand = brandRaw || NEUTRAL.brand;
  const brandHsl = toHsl(brand);
  const brandChroma = chromatic(brand);
  const accent = accentRaw || (brandChroma && !neutral ? brand : NEUTRAL.accent);
  // a near-black card (black + gold, dark olive + gold) writes in its accent
  const useAccentInk = !!accentRaw && (!brandChroma || brandHsl.l < 0.2);
  const accentHsl = toHsl(accent);

  // the tint of the page: the brand when it has a colour, else its accent, else slate
  const tint = brandChroma ? { h: brandHsl.h, s: Math.min(brandHsl.s, 0.45) }
    : accentRaw ? { h: accentHsl.h, s: Math.min(accentHsl.s, 0.35) }
      : { h: NEUTRAL.h, s: NEUTRAL.s };
  const page = hsl(tint.h, tint.s, 0.955);
  const sheet = '#ffffff';
  const soft = hsl(tint.h, Math.min(tint.s * 1.4, 0.6), 0.92);
  const line = hsl(tint.h, Math.min(tint.s, 0.35), 0.89);
  const ink = readable(hsl(tint.h, Math.min(tint.s, 0.55), 0.12), [page, sheet]);
  const muted = readable(hsl(tint.h, Math.min(tint.s, 0.18), 0.4), [page, sheet, soft]);
  const faint = readable(hsl(tint.h, Math.min(tint.s, 0.14), 0.46), [page, sheet]);

  // numbers and links on the white sheet
  const brandInk = useAccentInk ? readable(accent, [sheet, page, soft])
    : brandChroma ? readable(brand, [sheet, page]) : ink;

  const accentSoft = hsl(accentHsl.h, Math.min(accentHsl.s, 0.9), 0.89);
  const accentInk = readable(accent, [sheet, accentSoft, page]);

  // the solid button: the card's colour (a neon one calmed), light ink on it
  let btn;
  if (brandChroma) {
    const base = brandHsl.s > 0.85 ? hsl(brandHsl.h, 0.85, brandHsl.l) : brand;
    btn = readable(base, ['#ffffff']);
  } else if (brandHsl.l <= 0.5) {
    btn = readable(brand, ['#ffffff']);
  } else {
    btn = accentRaw ? readable(accent, ['#ffffff']) : ink;
  }
  const goldInk = useAccentInk ? hsl(accentHsl.h, Math.min(accentHsl.s, 0.6), 0.76) : null;
  const btnInk = goldInk && contrast(goldInk, btn) >= 4.5 ? goldInk : readable('#ffffff', [btn]);
  const banner = btn;
  const btnHsl = toHsl(btn);
  const banner2 = hsl(btnHsl.h, btnHsl.s, btnHsl.l * 0.62);
  const goldBanner = goldInk ? hsl(accentHsl.h, Math.min(accentHsl.s, 0.6), 0.85) : null;
  const bannerInk = goldBanner && contrast(goldBanner, banner) >= 4.5 ? goldBanner : readable('#ffffff', [banner, banner2]);

  const bar = brandChroma && !useAccentInk
    ? `linear-gradient(90deg,${btn},${hsl(btnHsl.h, btnHsl.s, Math.min(0.62, btnHsl.l + 0.13))})`
    : useAccentInk
      ? `linear-gradient(90deg,${accentInk},${hsl(accentHsl.h, Math.min(accentHsl.s, 0.6), 0.69)})`
      : `linear-gradient(90deg,${btn},${NEUTRAL.accent})`;

  // under the photo: the card's own dark colour (its surface, else its brand)
  // — else the photo's dark (a white card, or no colour at all)
  let surface = firstColor(c.surface_color, SURFACE_PRESETS[c.surface], c.card_bg_color) || brandRaw || photoDark || brand;
  if (toHsl(surface).l > 0.6 && brandHsl.l <= 0.6) surface = brand;
  if (toHsl(surface).l > 0.6 && photoDark && toHsl(photoDark).l <= 0.6) surface = photoDark;
  const sHsl = toHsl(surface);
  const heroFade = readable(hsl(sHsl.h, Math.min(sHsl.s, 0.8), Math.min(sHsl.l, 0.16)), ['#ffffff']);

  const ctaBg = accentRaw ? accent : bannerInk;
  const ctaInk = accentRaw
    ? (contrast(heroFade, accent) >= 4.5 ? heroFade : readable('#111111', [accent]))
    : banner;
  const ok = readable('#16824f', [sheet, OK_SOFT]);
  const chipInk = contrast(accent, btn) >= 3 ? accent : btnInk;
  const accentOn = onColor(accent, [banner]);

  return {
    neutral, page, sheet, ink, muted, faint, line, soft, brand, brandInk, accent, accentSoft, accentInk,
    btn, btnInk, banner, banner2, bannerInk, bar, heroFade, heroInk: '#ffffff', chipInk, accentOn, ctaBg, ctaInk,
    ribbon: accent, ok, okSoft: OK_SOFT,
  };
}

/** The first of `prefer`, then white / black, that reads on `bg` at `min`:1 (one of white / black always does). */
function onColor(bg, prefer = [], min = 4.5) {
  for (const c of [...prefer, '#ffffff', '#000000']) if (c && contrast(c, bg) >= min) return c;
  return contrast('#ffffff', bg) >= contrast('#000000', bg) ? '#ffffff' : '#000000';
}

/*
 * themeFromCard(card, photo) — round 4 (user, 2026-11-26: « door door tak card
 * design se match nahi karta »): the page reads as the SAME object as the
 * shop's Wallet card. card.pass_colors (GET /api/card, features/card_page:
 * the colours of the Apple card the client holds, store-correct) and the
 * photo's palette (lib/photoPalette: accent, dark, band) decide:
 *
 *   band      the band under the card's fields: the owner's footer colour
 *             (pass_colors.footer, else card.poster_footer_color), else Apple's
 *             blur of the photo's bottom (photo.band); a storeCard (iOS 26,
 *             pass_colors.poster false) shows its background there instead
 *   heroFade  = band, exactly; the greeting on it in white or black, whichever reads
 *   page      a very light tint of the band's hue (the accent's when the band is grey)
 *   accent    the card's label / foreground colour when chromatic, else the shop
 *             name's colour (logo_text_color — the old designer's accent fields
 *             only when the Wallet colours are unknown), else the photo's dominant
 *             colour, else the band
 *             — numbers, links, the bar, the tile icons; made readable (4.5:1) for text
 *   btn       = band, its ink: the card's chromatic label, the photo's gold on a
 *             dark band, the card's foreground / label, else white / black
 *
 * No band known yet (no photo, the photo not read, a palette from before the
 * band): the 2026-11-25 theme (legacyTheme), with the card's label as accent.
 * Garbage in pass_colors is ignored: only parseColor's #rrggbb come out.
 */
export function themeFromCard(card, photo) {
  const c = card && typeof card === 'object' ? card : {};
  const d = c.design && typeof c.design === 'object' ? c.design : {};
  const pc = c.pass_colors && typeof c.pass_colors === 'object' && !Array.isArray(c.pass_colors) ? c.pass_colors : {};
  const pBg = parseColor(pc.background), pFg = parseColor(pc.foreground), pLabel = parseColor(pc.label);
  const poster = pc.poster !== false;
  const p = photo && typeof photo === 'object' ? photo : {};
  const pBand = typeof p.band === 'string' ? parseColor(p.band) : null;
  const ownerFooter = parseColor(pc.footer) || parseColor(c.poster_footer_color);
  const band = poster ? (ownerFooter || pBand) : pBg;
  const passAccent = [pLabel, pFg].find((x) => x && chromatic(x)) || null;
  if (!band) return legacyTheme(passAccent ? { ...c, accent_color: passAccent } : c, photo);

  const cardBrand = firstColor(c.brand_color, c.card_bg_color, c.primary_color, d.primary_color);
  // the card's own fields: with the Wallet card's colours known, only what that
  // card draws — the shop name's colour; the old designer's accent / secondary
  // colours are painted nowhere on it (round 4)
  const knowsPass = !!(pBg || pFg || pLabel);
  const cardAccent = (knowsPass ? [pc.name, c.logo_text_color] : [c.accent_color, c.logo_text_color, d.accent_color, c.secondary_color])
    .map(parseColor).find((x) => x && chromatic(x)) || null;
  const photoAccent = typeof p.accent === 'string' && parseColor(p.accent) && chromatic(parseColor(p.accent)) ? parseColor(p.accent) : null;
  const accentRaw = passAccent || cardAccent || photoAccent || (chromatic(band) ? band : null)
    || (cardBrand && chromatic(cardBrand) ? cardBrand : null);
  const accent = accentRaw || NEUTRAL.accent;
  const aH = toHsl(accent);
  const bH = toHsl(band);

  // the page: the band's hue, very light — the accent's when the band is grey / black / white
  const bandTinted = bH.s >= 0.12 && bH.l >= 0.08 && bH.l <= 0.94;
  const tint = bandTinted ? { h: bH.h, s: Math.min(bH.s, 0.45) }
    : accentRaw ? { h: aH.h, s: Math.min(aH.s, 0.35) } : { h: NEUTRAL.h, s: NEUTRAL.s };
  const page = hsl(tint.h, tint.s, 0.955);
  const sheet = '#ffffff';
  const soft = hsl(tint.h, Math.min(tint.s * 1.4, 0.6), 0.92);
  const line = hsl(tint.h, Math.min(tint.s, 0.35), 0.89);
  const ink = readable(hsl(tint.h, Math.min(tint.s, 0.55), 0.12), [page, sheet]);
  const muted = readable(hsl(tint.h, Math.min(tint.s, 0.18), 0.4), [page, sheet, soft]);
  const faint = readable(hsl(tint.h, Math.min(tint.s, 0.14), 0.46), [page, sheet]);

  const accentSoft = hsl(aH.h, Math.min(aH.s, 0.9), 0.89);
  const accentInk = readable(accent, [sheet, accentSoft, page]);
  const brandInk = accentRaw ? readable(accent, [sheet, page, soft]) : ink;

  // the solid button = the band; its ink from the card's own colours
  const darkBand = luminance(band) < 0.18;
  const goldInk = accentRaw && accentRaw !== passAccent && darkBand ? hsl(aH.h, Math.min(aH.s, 0.6), 0.76) : null;
  const btn = band;
  const btnInk = onColor(btn, [passAccent, goldInk, pFg, pLabel]);
  const banner = btn;
  const banner2 = hsl(bH.h, bH.s, bH.l > 0.5 ? bH.l - 0.06 : bH.l * 0.62);
  const bannerInk = [btnInk, '#ffffff', '#000000'].find((x) => contrast(x, banner) >= 4.5 && contrast(x, banner2) >= 4.5)
    || onColor(banner);
  const chipInk = contrast(accent, btn) >= 3 ? accent : btnInk;
  const ctaBg = accentRaw && contrast(accent, banner) >= 3 ? accent : bannerInk;
  const ctaInk = onColor(ctaBg, [banner]);
  const accentOn = onColor(accent, [banner]);
  const bar = `linear-gradient(90deg,${accentInk},${accent})`;
  const heroFade = band;
  const heroInk = onColor(heroFade, ['#ffffff']);
  const ok = readable('#16824f', [sheet, OK_SOFT]);

  return {
    neutral: false, page, sheet, ink, muted, faint, line, soft, brand: accentInk, brandInk, accent, accentSoft, accentInk,
    btn, btnInk, banner, banner2, bannerInk, bar, heroFade, heroInk, chipInk, accentOn, ctaBg, ctaInk,
    ribbon: accent, ok, okSoft: OK_SOFT,
  };
}

// ================================================================ colour distance
// CIE L*a*b* (sRGB, D65) and ΔE — how far the page's colours are from the
// card's (cardThemeMatch.test.js): CIEDE2000 (Sharma, Wu & Dalal 2005) and CIE76.

/** [L, a, b] of a colour parseColor reads, else null. */
export function hexToLab(v) {
  const hex = parseColor(v);
  if (!hex) return null;
  const { r, g, b } = hexToRgb(hex);
  const lin = (x) => { const s = x / 255; return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4; };
  const R = lin(r), G = lin(g), B = lin(b);
  const X = (0.4124564 * R + 0.3575761 * G + 0.1804375 * B) / 0.95047;
  const Y = (0.2126729 * R + 0.7151522 * G + 0.0721750 * B) / 1.0;
  const Z = (0.0193339 * R + 0.1191920 * G + 0.9503041 * B) / 1.08883;
  const f = (t) => (t > 216 / 24389 ? Math.cbrt(t) : (24389 / 27 * t + 16) / 116);
  const fx = f(X), fy = f(Y), fz = f(Z);
  return [116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)];
}

/** CIEDE2000 between two [L, a, b]. */
export function deltaE2000Lab([L1, a1, b1], [L2, a2, b2]) {
  const rad = Math.PI / 180;
  const C1 = Math.hypot(a1, b1), C2 = Math.hypot(a2, b2);
  const Cm = (C1 + C2) / 2;
  const G = 0.5 * (1 - Math.sqrt(Cm ** 7 / (Cm ** 7 + 25 ** 7)));
  const ap1 = a1 * (1 + G), ap2 = a2 * (1 + G);
  const Cp1 = Math.hypot(ap1, b1), Cp2 = Math.hypot(ap2, b2);
  const hp = (b, ap) => { if (b === 0 && ap === 0) return 0; const h = Math.atan2(b, ap) / rad; return h < 0 ? h + 360 : h; };
  const hp1 = hp(b1, ap1), hp2 = hp(b2, ap2);
  const dL = L2 - L1, dC = Cp2 - Cp1;
  let dh = 0;
  if (Cp1 * Cp2 !== 0) { dh = hp2 - hp1; if (dh > 180) dh -= 360; else if (dh < -180) dh += 360; }
  const dH = 2 * Math.sqrt(Cp1 * Cp2) * Math.sin((dh / 2) * rad);
  const Lm = (L1 + L2) / 2, Cpm = (Cp1 + Cp2) / 2;
  let hm = hp1 + hp2;
  if (Cp1 * Cp2 !== 0) {
    if (Math.abs(hp1 - hp2) > 180) hm = hp1 + hp2 < 360 ? (hp1 + hp2 + 360) / 2 : (hp1 + hp2 - 360) / 2;
    else hm = (hp1 + hp2) / 2;
  }
  const T = 1 - 0.17 * Math.cos((hm - 30) * rad) + 0.24 * Math.cos(2 * hm * rad)
    + 0.32 * Math.cos((3 * hm + 6) * rad) - 0.2 * Math.cos((4 * hm - 63) * rad);
  const dTheta = 30 * Math.exp(-(((hm - 275) / 25) ** 2));
  const Rc = 2 * Math.sqrt(Cpm ** 7 / (Cpm ** 7 + 25 ** 7));
  const Sl = 1 + (0.015 * (Lm - 50) ** 2) / Math.sqrt(20 + (Lm - 50) ** 2);
  const Sc = 1 + 0.045 * Cpm, Sh = 1 + 0.015 * Cpm * T;
  const Rt = -Math.sin(2 * dTheta * rad) * Rc;
  return Math.sqrt((dL / Sl) ** 2 + (dC / Sc) ** 2 + (dH / Sh) ** 2 + Rt * (dC / Sc) * (dH / Sh));
}

/** CIEDE2000 between two colours; Infinity when either is not a colour. */
export function deltaE2000(a, b) {
  const A = hexToLab(a), B = hexToLab(b);
  return A && B ? deltaE2000Lab(A, B) : Infinity;
}

/** CIE76 (plain Lab distance) between two colours; Infinity when either is not a colour. */
export function deltaE76(a, b) {
  const A = hexToLab(a), B = hexToLab(b);
  return A && B ? Math.hypot(A[0] - B[0], A[1] - B[1], A[2] - B[2]) : Infinity;
}

/** The theme as CSS custom properties for a `style` prop: brandInk → --brand-ink. */
export function themeVars(theme) {
  const out = {};
  for (const [k, v] of Object.entries(theme || {})) {
    if (typeof v !== 'string') continue;
    out[`--${k.replace(/([A-Z0-9])/g, '-$1').toLowerCase()}`] = v;
  }
  return out;
}
