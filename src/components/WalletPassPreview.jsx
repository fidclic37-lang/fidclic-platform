import React from 'react';
import { QRCodeSVG } from 'qrcode.react';
import Code128Barcode from './Code128Barcode';
import { deriveCardTheme } from '../lib/cardTheme';

/**
 * WalletPassPreview — a pkpass-FAITHFUL render of the merchant's card, shown
 * inside the designer's iPhone frame.
 *
 * This is deliberately NOT the PWA card (WalletCard.jsx). The merchant is
 * going to launch with real Apple Wallet passes, so what they see while
 * designing must be what PassKit will actually render — same geometry, same
 * constraints, none of the PWA-only liberties. Concretely:
 *
 *   - storeCard anatomy: logo row (logo capped at Apple's 160×50pt box) +
 *     organization name, ONE header field top-right as label/value TEXT
 *     (Wallet renders no coloured chips)
 *   - strip: edge-to-edge, Apple's exact 375:144 ratio. The stamps are
 *     composited INTO the strip, because that is how they will really ship —
 *     PassKit has no stamp element, so the server generates a strip.png per
 *     customer state (the Loopy Loyalty technique)
 *   - fields: secondary row (≤4 per Apple), auxiliary row for reward progress
 *     as TEXT — a real pass cannot draw a progress bar
 *   - barcode: exactly ONE (Wallet never shows two), centred on a white
 *     rounded block with altText beneath — code_type 'both' collapses to QR
 *   - colours: backgroundColor / foregroundColor / labelColor semantics via
 *     deriveCardTheme — the same three knobs pass.json actually has
 *
 * Scaled to `width` px for a 375pt-wide pass, so proportions stay exact.
 */
export default function WalletPassPreview({ customer, tenant, card = {}, width = 292 }) {
  const t = deriveCardTheme({
    brandColor: card.brand_color || card.card_bg_color || card.primary_color,
    surface: card.surface,
    surfaceColor: card.surface_color,
  });

  const s = width / 375; // 1pt at design scale → px
  const px = (v) => Math.round(v * s * 10) / 10;

  // ---- front-photo blend: merge the subject INTO the bg photo -------------
  // ---- data (same derived-from-visits maths as everywhere else) ----------
  const firstName = (customer?.first_name || customer?.name || '').split(' ')[0] || 'Client';
  const displayName = card.use_full_name ? (customer?.name || firstName) : firstName;
  const visits = parseInt(customer?.visits, 10) || 0;
  const threshold = Math.max(1, parseInt(customer?.reward_threshold, 10)
    || parseInt(card.reward_threshold_stamps, 10) || 10);
  const pointsPerVisit = parseInt(card.points_per_visit, 10) || 10;
  const visitsPerStamp = Math.max(1, parseInt(card.visits_per_stamp, 10) || 1);
  const stamps = Math.min(threshold, Math.floor(visits / visitsPerStamp));
  const remaining = threshold - stamps;
  const meterMax = threshold * visitsPerStamp * pointsPerVisit;
  const earned = Math.min(visits * pointsPerVisit, meterMax);
  const tierKey = (customer?.tier || 'bronze').toLowerCase();
  const tierLabels = { bronze: 'Bronze', silver: 'Argent', gold: 'Or', vip: 'VIP' };
  const barcodeId = customer?.barcode_id || '';

  const memberLabel = (card.greeting_label || 'Membre').toUpperCase();
  const pointsLabel = (card.points_label || 'Points').toUpperCase();
  const visitsLabel = (card.visits_label || 'Visites').toUpperCase();

  const showTier = card.show_tier_badge !== false && card.show_tier !== false;
  const showPoints = card.show_points !== false;
  const showVisits = card.show_visits !== false;
  const showStamps = card.show_stamps !== false && threshold > 0;
  const showMeter = card.show_meter !== false;
  const offerText = card.offer_box_text || '';
  const showOffer = card.show_offer_box !== false && !!offerText;

  // ONE barcode — a real pass never shows two. 'both' collapses to QR.
  const wantsBarcode = card.code_type === 'barcode'
    || (!card.code_type && card.show_qr === false && card.show_barcode !== false);
  const heroMode = card.hero_mode || (card.hero_image_url ? 'image' : 'brand');

  // Native PassKit typographic rhythm: labels are quiet, values shout.
  const label = {
    fontSize: px(9), fontWeight: 600, letterSpacing: '0.07em',
    color: t.label, textTransform: 'uppercase', lineHeight: 1.3,
  };
  // The strip's "on brand" text (over the hero) needs its own contrast.
  const stripLabel = { ...label, color: 'rgba(255,255,255,0.72)' };

  // Cleaner short code for the human-readable line: FT-RT0184 → RT0184.
  const shortCode = barcodeId.replace(/^FT-?/i, '') || barcodeId;

  return (
    <div
      data-testid="wallet-pass-preview"
      style={{
        width, background: t.surface, borderRadius: px(12), overflow: 'hidden',
        fontFamily: "-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Segoe UI', Roboto, sans-serif",
        boxShadow: '0 10px 30px rgba(0,0,0,0.35)',
      }}
    >
      {/* ── header row: logo + org name (left) · ONE header field (right).
             Native stack: quiet label above, bold value below. This is the
             ONLY thing visible when the pass is collapsed in the stack, so it
             carries the single most glanceable status — the tier. ── */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    padding: `${px(11)}px ${px(14)}px ${px(9)}px`, gap: px(10) }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: px(8), minWidth: 0 }}>
          {card.logo_url ? (
            <img src={card.logo_url} alt=""
              style={{ maxHeight: px(28), maxWidth: px(88), borderRadius: px(4), objectFit: 'contain' }} />
          ) : null}
          <span style={{ fontSize: px(13.5), fontWeight: 600, color: t.ink,
                         whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {tenant?.name || 'Votre commerce'}
          </span>
        </div>
        {showTier && (
          <div style={{ textAlign: 'right', flexShrink: 0 }}>
            <div style={label}>Statut</div>
            <div style={{ fontSize: px(15), fontWeight: 700, color: t.brand, lineHeight: 1.15 }}>
              {tierLabels[tierKey] || 'Bronze'}
            </div>
          </div>
        )}
      </div>

      {/* ── strip: ALWAYS the fixed 375×144 band (a real pass can't resize).
             image → ONE photo FILLING the band completely (cover), exactly
             like a real Apple Wallet strip — no empty space, ever. A
             landscape photo fits whole; a taller photo loses a little top
             and bottom, which is how every real pass behaves.
             logo  → the merchant's mark centred on the brand field
             brand → flat brand colour ── */}
      {heroMode !== 'none' && (
        <div style={{
          position: 'relative', width: '100%', aspectRatio: '375 / 144', overflow: 'hidden',
          background: t.brandRaw,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          {(heroMode === 'image' || heroMode === 'composite') && card.hero_image_url && (
            <img src={card.hero_image_url} alt=""
              style={{ position: 'absolute', inset: 0, width: '100%', height: '100%',
                       objectFit: 'cover', objectPosition: 'center' }} />
          )}
          {heroMode === 'logo' && card.logo_url && (
            <img src={card.logo_url} alt=""
              style={{ position: 'relative', maxHeight: '78%', maxWidth: '78%',
                       objectFit: 'contain' }} />
          )}
        </div>
      )}

      {/* ── stamps row: its OWN slim band flush under the strip — in flow, not
             an overlay, so the hero image is NEVER covered. Themed to the
             surface so it adapts to light and dark cards alike. ── */}
      {showStamps && (
        <div style={{
          padding: `${px(8)}px ${px(14)}px`, background: t.chipBg,
          borderBottom: `1px solid ${t.hairline}`,
          display: 'flex', flexDirection: 'column', gap: px(5),
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
            <span style={label}>{(card.stamps_label || 'Tampons').toUpperCase()}</span>
            <span style={{ fontSize: px(10.5), fontWeight: 700, color: t.ink }}>
              {stamps}<span style={{ opacity: 0.55 }}> / {threshold}</span>
            </span>
          </div>
          <div style={{ display: 'flex', gap: px(4.5), alignItems: 'center' }}>
            {Array.from({ length: threshold }).map((_, i) => (
              <span key={i} style={{
                flex: 1, height: px(9), borderRadius: px(5),
                background: i < stamps ? t.brand : t.track,
              }} />
            ))}
          </div>
        </div>
      )}

      {/* ── PRIMARY field: the one number the customer glances for. Big.
             The stamps row above already carries the visual count, so the
             primary shows points — no duplicated 6/10. ── */}
      <div style={{ padding: `${px(12)}px ${px(14)}px 0` }}>
        <div style={label}>{showStamps || showPoints ? pointsLabel
                                                      : (card.stamps_label || 'Tampons').toUpperCase()}</div>
        <div style={{ fontSize: px(30), fontWeight: 700, color: t.ink, lineHeight: 1.05,
                      letterSpacing: '-0.02em', fontVariantNumeric: 'tabular-nums' }}>
          {showStamps || showPoints ? earned : `${stamps} / ${threshold}`}
        </div>
      </div>

      {/* ── AUXILIARY field: next reward, in plain words. One line. ── */}
      <div style={{ padding: `${px(10)}px ${px(14)}px 0` }}>
        <div style={label}>{(card.meter_label || 'Prochaine récompense').toUpperCase()}</div>
        <div style={{ fontSize: px(13.5), fontWeight: 500, color: t.ink, lineHeight: 1.3 }}>
          {remaining > 0
            ? `Encore ${remaining} ${showStamps ? (remaining > 1 ? 'tampons' : 'tampon')
                                                 : (remaining > 1 ? 'visites' : 'visite')} · ${card.reward_description || 'récompense'}`
            : (card.reward_description || 'Récompense débloquée !')}
        </div>
      </div>

      {/* ── barcode block: ONE code, white block, tight altText. Everything
             else — member name, visits, offer terms, address — lives on the
             back (the "…" flip in real Wallet), off the glanceable face. ── */}
      {barcodeId && (
        <div style={{ display: 'flex', justifyContent: 'center',
                      padding: `${px(16)}px 0 ${px(16)}px` }}>
          <div style={{ background: '#FFFFFF', borderRadius: px(10),
                        padding: `${px(9)}px ${px(11)}px ${px(7)}px`,
                        display: 'flex', flexDirection: 'column',
                        alignItems: 'center', gap: px(5) }}>
            {wantsBarcode ? (
              <Code128Barcode value={barcodeId} height={px(40)} />
            ) : (
              <QRCodeSVG value={barcodeId} size={px(88)} bgColor="#FFFFFF"
                         fgColor="#111111" level="M" />
            )}
            <div style={{ fontSize: px(8.5), letterSpacing: '0.14em', color: '#8A8D92',
                          fontVariantNumeric: 'tabular-nums', fontWeight: 600 }}>
              {shortCode}
            </div>
          </div>
        </div>
      )}

      {/* ── back-of-card strip: a thin footer note standing in for the real
             pass back (member, visits, offer, terms). Keeps the FACE clean
             while signalling where the rest of the info lives. ── */}
      <div style={{ borderTop: `1px solid ${t.hairline}`,
                    padding: `${px(8)}px ${px(14)}px ${px(10)}px`,
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: px(8) }}>
        <span style={{ fontSize: px(10), color: t.inkSoft, whiteSpace: 'nowrap',
                       overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {displayName}{showVisits ? ` · ${visits} ${visitsLabel.toLowerCase()}` : ''}
        </span>
        <span style={{ fontSize: px(9.5), color: t.label, whiteSpace: 'nowrap' }}>
          Détails au dos ›
        </span>
      </div>
    </div>
  );
}
