import React from 'react';
import { QRCodeSVG } from 'qrcode.react';
import Code128Barcode from './Code128Barcode';
import { cycleVisits } from '../lib/cardCycle';

/**
 * What the QR on the card encodes: the card's own public URL, not the bare
 * id. A phone camera can do something with a URL and nothing at all with
 * "FT-AB12CD34" — and that is what turns a customer's own card into an
 * invitation: a stranger who scans it lands on the signup page, already
 * attributed to them. The till reads the same QR and pulls the id back out
 * of it, so there is still only one code on the card.
 */
export const cardUrl = (barcodeId) => {
  const id = (barcodeId || '').trim();
  if (!id) return '';
  const origin = typeof window !== 'undefined' && window.location ? window.location.origin : '';
  return `${origin}/card/${id.toUpperCase()}`;
};

/**
 * PremiumLoyaltyCard — KFC-grade wallet card.
 *
 * What this looks like:
 *   - Brand-colored full-bleed hero block with the business logo top-left,
 *     points badge top-right ("PTS 725"), and a big editorial title
 *     ("TA CARTE FIDÉLITÉ") set in serif.
 *   - Hero photography fills the right half of the brand block (optional —
 *     falls back to a gradient if no hero_image_url is set).
 *   - "BONJOUR {first_name}" greeting + "DÉTAILS DES RÉCOMPENSES Au dos →"
 *     affordance, exactly like the KFC reference.
 *   - Centered big QR (the modern scan path) on a white surface inside the
 *     brand panel — high contrast, easy for any phone camera.
 *   - Below the brand block: a clean white section with the Code 128 strip
 *     and a formatted "N° Carte: A618" identifier, the parts old POS lasers
 *     need.
 *
 * Designed to:
 *   - Look premium on first glance, even before the patron customises a logo
 *     (brand-coloured + serif title = "expensive" feel by default).
 *   - Stay responsive — the card lives inside MyWalletCardPage's two-column
 *     layout on desktop and stacks naturally on mobile.
 *   - Be theme-driven: every colour is read from `card` so the Card Designer
 *     in Settings continues to control the look without code changes.
 *
 * Props:
 *   - customer: { name, barcode_id, points, tier, first_name? }
 *   - tenant:   { name }
 *   - card:     { primary_color, secondary_color, accent_color,
 *                 logo_url?, hero_image_url?, title_label?, points_label? }
 *
 * The component is deliberately self-contained (no state, no effects) so it
 * can be embedded inside HeroPhoneShowcase for the landing-page demo as well.
 */
export default function PremiumLoyaltyCard({ customer, tenant, card = {}, compact = false }) {
  // Colour palette — every key has a sensible fallback so a half-configured
  // card never crashes.
  const primary = card.primary_color || '#B85C38';
  const secondary = card.secondary_color || '#9C4427';
  const accent = card.accent_color || '#F4D8A8';
  const textOnBrand = card.text_on_brand || '#FFFFFF';
  const backLinkColor = card.back_link_color || accent;
  const muted = 'rgba(255,255,255,0.78)';

  // Text content — every visible label is owner-editable in Card Designer.
  const titleText    = card.title_label    || 'Ta carte fidélité';
  const pointsLabel  = card.points_label   || 'Points';
  const greetingLbl  = card.greeting_label || 'Bonjour';
  const backLabel    = card.back_label     || 'Détails récompenses';
  const backValue    = card.back_value     || 'Au dos →';

  // Typography
  const titleFont    = card.title_font || 'Cormorant Garamond';
  const titleItalic  = card.title_italic !== false;   // default true

  // Visibility toggles — each element can be hidden by the owner.
  // Default everything to TRUE so existing cards (without these flags
  // in the doc) keep showing all elements.
  const showTier        = card.show_tier        !== false;
  const showPoints      = card.show_points      !== false;
  const showTitle       = card.show_title       !== false;
  const showGreeting    = card.show_greeting    !== false;
  const showBackLink    = card.show_back_link   !== false;
  const showCardNumber  = card.show_card_number !== false;
  const showBarcode     = card.show_barcode     !== false;

  // Hero image fully opaque — opacity feature removed at owner request.
  const heroOpacity = 1;

  // First name only — feels personal, matches the KFC pattern ("Bonjour Julie")
  const firstName = (customer?.first_name || customer?.name || '').split(' ')[0] || 'Client';

  // Format the barcode_id as an elegant card number. "FT-1DFC4E62" → "A618"-style
  // short suffix, plus a long-form line for completeness.
  const cardSuffix = (() => {
    const raw = (customer?.barcode_id || '').replace(/[^A-Z0-9]/gi, '').toUpperCase();
    if (!raw) return '----';
    return raw.slice(-4);
  })();

  const points = customer?.points ?? 0;

  // ── 3-band Apple Wallet layout — the ONLY supported design ─────────
  // TOP STRIP:    business logo + name (top-left), "+ D'INFOS / N pts"
  //               (top-right), tier badge (optional). Uses card_bg_color.
  // MIDDLE STRIP: brand-coloured or image promo band, optionally with
  //               business logo overlaid centre. Independent strip_color.
  // BOTTOM STRIP: greeting + name (left), action prompt (right), then
  //               stamps grid, points meter, smaller QR code with
  //               customer ID + barcode + birthday. Same card_bg_color
  //               as the top so they read as one continuous surface.
  // (The legacy "hero" layout has been removed — one design, strictly
  // following the 3-patch rule.)
  {
    const cardBg     = card.card_bg_color   || '#FFFFFF';
    const cardInk    = card.card_ink_color  || '#1F1B1A';
    const stripType  = card.strip_type      || 'color';
    const stripColor = card.strip_color     || primary;
    const stripInk   = card.strip_text_color || '#FFFFFF';
    const stripTitle = card.strip_title     || titleText;
    const stripSub   = card.strip_subtitle  || '';
    const showOffer  = card.show_offer_box !== false;
    const offerText  = card.offer_box_text  || '';
    const offerSub   = card.offer_box_subtext || '';
    const offerBg    = card.offer_box_color || '#FFFFFF';
    const offerInk   = card.offer_box_ink_color || stripColor;
    const logoPos    = card.logo_position || 'top_left';
    const showPtsTR  = card.show_points_top_right !== false;
    const ptsTRLbl   = card.points_top_right_label || '+ D\'INFOS';
    const greetLbl   = (card.bottom_greeting_label || 'Bienvenue').toUpperCase();
    // Points + visits + stamps maths — single source of truth derived
    // from the owner's loyalty rules, NEVER from stored customer.points
    // (which can drift if the rules change after a customer accumulated).
    //
    //   stampsFilled = floor(visits / visits_per_stamp)   capped at cycle
    //   earnedPoints = visits × points_per_visit
    //   maxPoints    = cycle × visits_per_stamp × points_per_visit
    //
    // Example: visits_per_stamp=2, points_per_visit=10, reward=10 stamps.
    //   6 stamps filled  →  12 visits  →  120 pts earned / 200 pts max.
    // Declare cycle + visits FIRST — they're inputs to the maths below.
    const visits         = parseInt(customer?.visits, 10) || 0;
    const cycle          = parseInt(customer?.reward_threshold, 10) || 10;
    const pointsPerVisit = parseInt(card.points_per_visit, 10) || 10;
    const visitsPerStamp = Math.max(1, parseInt(card.visits_per_stamp, 10) || 1);
    const totalVisits    = visits;
    // the meter reads THIS card (lib/cardCycle); « visites » stays lifetime
    const onCard         = cycleVisits(customer);
    const stampsFilled   = Math.min(cycle, Math.floor(onCard / visitsPerStamp));
    const earnedPoints   = onCard * pointsPerVisit;
    const maxPoints      = cycle * visitsPerStamp * pointsPerVisit;
    const pointsFillPct  = maxPoints > 0 ? Math.min(100, (earnedPoints / maxPoints) * 100) : 0;
    const showQr         = card.show_qr !== false;
    const qrSize         = Math.max(48, Math.min(140, parseInt(card.qr_size, 10) || 90));
    const showBday       = !!card.show_birthday;
    const bdayLbl        = card.birthday_label || 'Anniversaire';
    const showTier       = card.show_tier_badge !== false;
    const tierKey        = (customer?.tier || 'bronze').toLowerCase();
    const tierColor      = ({
      bronze: card.tier_badge_bronze || '#B26344',
      silver: card.tier_badge_silver || '#9AA6B3',
      gold:   card.tier_badge_gold   || '#E8A53B',
      vip:    card.tier_badge_vip    || '#9A6DBF',
    })[tierKey] || (card.tier_badge_bronze || '#B26344');
    const fullName       = card.use_full_name
      ? (customer?.name || firstName).toUpperCase()
      : firstName;

    return (
      <div
        className="rounded-2xl overflow-hidden shadow-xl relative isolate"
        style={{ background: cardBg, maxWidth: 380, margin: '0 auto' }}
      >
        {/* ── TOP STRIP ────────────────────────────────────────── */}
        <div className="px-5 pt-4 pb-3 flex items-start justify-between gap-2" style={{ color: cardInk, background: cardBg }}>
          {/* Logo + tenant name top-left (unless logo_position overrides it) */}
          {logoPos !== 'middle_overlay' && (
            <div className={`flex items-center gap-2 min-w-0 ${logoPos === 'top_center' ? 'mx-auto' : ''}`}>
              {card.logo_url ? (
                <img src={card.logo_url} alt="" className="w-auto object-contain" style={{ height: 44, maxWidth: 160 }} />
              ) : (
                <span className="text-[17px] font-semibold" style={{ color: cardInk, letterSpacing: '-0.01em' }}>
                  {tenant?.name || 'FidClic'}
                </span>
              )}
              {showTier && (
                <span
                  className="text-[9px] uppercase tracking-[0.14em] font-bold px-1.5 py-0.5 rounded"
                  style={{ background: tierColor, color: '#FFFFFF', letterSpacing: '0.12em' }}
                >
                  {tierKey}
                </span>
              )}
            </div>
          )}
          {/* Top-right: "+ D'INFOS / N pts" */}
          {showPtsTR && (
            <div className="text-right leading-tight shrink-0">
              <p className="text-[10px] uppercase tracking-[0.14em]" style={{ color: cardInk, opacity: 0.55 }}>
                {ptsTRLbl}
                <span className="ml-1">↗</span>
              </p>
              <p className="text-[14px] mt-0.5 font-semibold" style={{ color: cardInk }}>
                {points} pts
              </p>
            </div>
          )}
        </div>

        {/* ── MIDDLE STRIP — image OR colour with optional overlay ── */}
        <div
          className="relative"
          style={{
            background: stripType === 'image' && card.hero_image_url
              ? `url(${card.hero_image_url}) center/cover no-repeat`
              : stripColor,
            color: stripInk,
            minHeight: 130,
          }}
        >
          {/* Readability scrim when image is used */}
          {stripType === 'image' && card.hero_image_url && (
            <div
              aria-hidden="true"
              className="absolute inset-0"
              style={{ background: 'linear-gradient(180deg, rgba(0,0,0,0.10) 0%, rgba(0,0,0,0.35) 100%)' }}
            />
          )}
          {/* Middle-overlay logo option */}
          {logoPos === 'middle_overlay' && card.logo_url && (
            <div className="absolute top-4 left-1/2 -translate-x-1/2 z-10">
              <img src={card.logo_url} alt="" className="w-auto object-contain" style={{ height: 56, maxWidth: 180, filter: 'drop-shadow(0 1px 3px rgba(0,0,0,0.35))' }} />
            </div>
          )}
          <div className="relative z-10 px-5 py-5 text-center flex flex-col items-center justify-center" style={{ minHeight: 130 }}>
            {stripTitle && (
              <p
                className="uppercase"
                style={{
                  color: stripInk,
                  fontFamily: `'${titleFont}', Georgia, serif`,
                  fontStyle: titleItalic ? 'italic' : 'normal',
                  fontWeight: card.title_bold !== false ? 700 : 400,
                  textDecoration: card.title_underline ? 'underline' : 'none',
                  fontSize: 22,
                  letterSpacing: '0.06em',
                  textShadow: stripType === 'image' ? '0 1px 3px rgba(0,0,0,0.45)' : 'none',
                }}
              >
                {stripTitle}
              </p>
            )}
            {stripSub && (
              <p className="text-[11.5px] mt-1" style={{ color: stripInk, opacity: 0.92 }}>
                {stripSub}
              </p>
            )}
            {showOffer && offerText && (
              <div
                className="inline-block mt-3 px-4 py-2"
                style={{ background: offerBg, color: offerInk }}
              >
                <p className="text-[15px] font-bold uppercase" style={{ letterSpacing: '0.04em' }}>
                  {offerText}
                </p>
                {offerSub && (
                  <p className="text-[9.5px] mt-0.5 uppercase" style={{ letterSpacing: '0.12em', opacity: 0.8 }}>
                    {offerSub}
                  </p>
                )}
              </div>
            )}
          </div>
        </div>

        {/* ── BOTTOM STRIP — greeting + action prompt + stamps + meter + QR + barcode ── */}
        <div className="px-5 pt-4 pb-5" style={{ color: cardInk, background: cardBg }}>
          {/* Greeting (left) + Total visits (right) */}
          <div className="flex items-start justify-between gap-3 mb-4">
            <div className="min-w-0">
              <p className="text-[9px] uppercase tracking-[0.16em]" style={{ color: cardInk, opacity: 0.55 }}>
                {greetLbl}
              </p>
              <p className="text-[18px] font-semibold mt-0.5 truncate" style={{ color: cardInk }}>
                {fullName}
              </p>
            </div>
            <div className="text-right min-w-0">
              <p className="text-[9px] uppercase tracking-[0.16em]" style={{ color: cardInk, opacity: 0.55 }}>
                Total visites
              </p>
              <p className="text-[22px] font-semibold mt-0.5" style={{ color: cardInk, fontVariantNumeric: 'tabular-nums' }}>
                {totalVisits}
              </p>
            </div>
          </div>

          {/* Stamps grid — count = cycle target, filled = stampsFilled
              (visits ÷ visits_per_stamp, capped at cycle). */}
          {card.show_stamps_grid !== false && (
            <StampGrid
              count={cycle}
              filled={stampsFilled}
              shape={card.stamp_shape || 'circle'}
              fillColor={card.stamp_fill_color || primary}
              emptyColor={card.stamp_empty_color || '#E7E5E4'}
              inkColor={card.stamp_ink_color || '#FFFFFF'}
              customUrl={card.stamp_custom_url || ''}
              size={card.stamp_size || 26}
              label={card.stamps_label || ''}
              ink={cardInk}
            />
          )}

          {/* Points meter — earned vs maxPoints (one full reward cycle).
              earned = visits × points_per_visit
              max    = cycle × visits_per_stamp × points_per_visit */}
          {card.show_meter !== false && maxPoints > 0 && (
            <div className="mt-3 mb-4">
              <div className="flex items-center justify-between mb-1">
                <p className="text-[9px] uppercase tracking-[0.14em]" style={{ color: cardInk, opacity: 0.55 }}>
                  {card.meter_label || 'Points'}
                </p>
                <p className="text-[10px] font-semibold" style={{ color: cardInk, fontVariantNumeric: 'tabular-nums' }}>
                  {Math.min(earnedPoints, maxPoints)} / {maxPoints} pts
                </p>
              </div>
              <div className="h-2 rounded-full overflow-hidden" style={{ background: card.meter_track_color || '#F2EDE3' }}>
                <div
                  className="h-full rounded-full transition-all"
                  style={{
                    width: `${pointsFillPct}%`,
                    background: card.meter_fill_color || primary,
                  }}
                />
              </div>
            </div>
          )}

          {/* Birthday line */}
          {showBday && customer?.birthday && (
            <div className="mt-3 flex items-center justify-between border-t pt-3" style={{ borderColor: 'rgba(0,0,0,0.08)' }}>
              <p className="text-[9px] uppercase tracking-[0.14em]" style={{ color: cardInk, opacity: 0.55 }}>
                {bdayLbl}
              </p>
              <p className="text-[12px] font-medium" style={{ color: cardInk }}>
                {customer.birthday}
              </p>
            </div>
          )}

          {/* QR code (smaller) — only when enabled */}
          {/* The QR sits ON the card, not on a white plate: the background is
              the card's own surface and the modules are its ink, the same pair
              every other element on the card uses, so the contrast is whatever
              the merchant already chose for their text.

              `marginSize` is not decoration — a QR needs a quiet zone of four
              modules around it to be read at all. The white plate used to
              provide it; now the card's own colour does. */}
          {showQr && (
            <div className="mt-3 flex flex-col items-center">
              <QRCodeSVG
                value={cardUrl(customer?.barcode_id)}
                size={qrSize}
                level="M"
                marginSize={4}
                bgColor={cardBg}
                fgColor={cardInk}
              />
            </div>
          )}

          {/* Barcode at the bottom — DISABLED per owner spec (Nov 2026).
              The 1D Code 128 strip is hidden everywhere on the platform
              for now; only the QR above is rendered. To restore, replace
              the `false` below with the original `showBarcode` prop. */}
          {false && showBarcode && (
            <div className="mt-3 flex flex-col items-center">
              <Code128Barcode
                value={customer?.barcode_id || ''}
                height={compact ? 40 : 48}
                barWidth={2}
                fontSize={11}
              />
            </div>
          )}
          {showCardNumber && !showBarcode && !showQr && (
            <div className="mt-2 text-center font-mono text-[12px]" style={{ color: cardInk }}>
              {customer?.barcode_id}
            </div>
          )}
        </div>
      </div>
    );
  }
}

/**
 * StampGrid — the classic punch-card visual.
 * Renders `count` slots; the first `filled` are marked "collected".
 * Owner-configurable: shape (circle, hexagon, octagon, square, custom image),
 * fill colour, empty colour, glyph colour, size, and an optional caption.
 *
 * The grid wraps automatically; for the typical 10-stamp cycle this means
 * one row of 10 on a wide card and two rows of 5 on a narrow one.
 */
function StampGrid({ count = 10, filled = 0, shape = 'circle', fillColor = '#B85C38', emptyColor = '#E7E5E4', inkColor = '#FFFFFF', customUrl = '', size = 28, label = '', ink = '#1F1B1A' }) {
  const slots = Array.from({ length: Math.max(1, count) }, (_, i) => i < filled);
  const clipPathFor = (s) => {
    switch (s) {
      case 'hexagon': return 'polygon(25% 5%, 75% 5%, 100% 50%, 75% 95%, 25% 95%, 0% 50%)';
      case 'octagon': return 'polygon(30% 0%, 70% 0%, 100% 30%, 100% 70%, 70% 100%, 30% 100%, 0% 70%, 0% 30%)';
      case 'square':  return 'none';
      default:        return 'none';
    }
  };
  const isCircle = shape === 'circle';
  const isCustom = shape === 'custom' && !!customUrl;
  return (
    <div className="mt-2">
      {label && (
        <p className="text-[9px] uppercase tracking-[0.14em] mb-2" style={{ color: ink, opacity: 0.55 }}>
          {label}
        </p>
      )}
      <div className="flex flex-wrap gap-1.5">
        {slots.map((isFilled, i) => {
          if (isCustom) {
            return (
              <div
                key={i}
                style={{
                  width: size,
                  height: size,
                  backgroundImage: `url(${customUrl})`,
                  backgroundSize: 'cover',
                  backgroundPosition: 'center',
                  opacity: isFilled ? 1 : 0.25,
                  filter: isFilled ? 'none' : 'grayscale(0.6)',
                  borderRadius: 4,
                }}
                aria-label={isFilled ? 'Tampon collecté' : 'Tampon vide'}
              />
            );
          }
          const baseStyle = {
            width: size,
            height: size,
            background: isFilled ? fillColor : emptyColor,
            display: 'grid',
            placeItems: 'center',
            color: inkColor,
            borderRadius: isCircle ? '50%' : (shape === 'square' ? 4 : 0),
            clipPath: isCircle || shape === 'square' ? 'none' : clipPathFor(shape),
            transition: 'background 200ms',
          };
          return (
            <div key={i} style={baseStyle} aria-label={isFilled ? 'Tampon collecté' : 'Tampon vide'}>
              {isFilled && (
                <svg width={Math.round(size * 0.5)} height={Math.round(size * 0.5)} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
