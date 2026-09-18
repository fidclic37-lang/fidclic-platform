import React from 'react';
import { QRCodeSVG } from 'qrcode.react';
import Code128Barcode from './Code128Barcode';
import { deriveCardTheme } from '../lib/cardTheme';

/**
 * WalletCard — the wallet-anatomy render (layout_style: "wallet").
 *
 * This is the redesigned card from FidClic-Card-Redesign-Spec.html. It follows
 * the anatomy of a real Apple/Google Wallet pass — logo row, hero strip,
 * fields row, stamps, meter, code block — because that anatomy is what reads
 * as "professional". The old PremiumLoyaltyCard stays untouched as the render
 * for every template that has not opted in, so no existing merchant's live
 * card changes underneath them.
 *
 * Colour contract: every painted colour comes from deriveCardTheme(). This
 * component contains NO hex literals for surfaces/text/accents — if an element
 * needs a colour, it gets a derived token in cardTheme.js, never a prop.
 *
 * What the merchant still controls (and why that is safe):
 *   content   — logo_url, hero_image_url, brand_color, surface, every
 *               show_* toggle, every *_label text, reward/offer text,
 *               code_type ("qr" | "barcode" | "both")
 *   never     — fonts, per-element colours, sizes. Those are the knobs that
 *               produced the carnival card this replaces.
 *
 * The per-segment offer overlay keeps working exactly as before: overrides
 * land on hero_image_url / offer text fields upstream (server-side whitelist),
 * so a targeted campaign can swap the hero image and offer chip on just the
 * filtered customers' cards — same feature, professional rendering.
 */
export default function WalletCard({ customer, tenant, card = {}, compact = false }) {
  const t = deriveCardTheme({
    brandColor: card.brand_color || card.card_bg_color || card.primary_color,
    surface: card.surface,
    surfaceColor: card.surface_color,   // duo-tone: the second brand colour
  });

  // ---- content -----------------------------------------------------------
  const firstName = (customer?.first_name || customer?.name || '').split(' ')[0] || 'Client';
  const fullName = customer?.name || firstName;
  const displayName = card.use_full_name ? fullName : firstName;
  const points = customer?.points ?? 0;
  const tierKey = (customer?.tier || 'bronze').toLowerCase();
  const tierChip = t.tiers[tierKey] || t.tiers.bronze;
  const barcodeId = customer?.barcode_id || '';

  const memberLabel = card.greeting_label || 'Membre';
  const pointsLabel = card.points_label || 'Points';
  const visitsLabel = card.visits_label || 'Visites';
  const stampsLabel = card.stamps_label || 'Vos tampons';

  // ---- visibility (content is the merchant's call) -----------------------
  const showTier = card.show_tier_badge !== false && card.show_tier !== false;
  const showPoints = card.show_points !== false;
  const showVisits = card.show_visits !== false;
  const showStamps = card.show_stamps !== false && (card.reward_threshold_stamps ?? 10) > 0;
  const showMeter = card.show_meter !== false;

  // QR / barcode: explicit code_type wins. Absent that, QR is the default —
  // Apple documents Code128 as unsupported on watchOS and square codes scan
  // better on small screens — with the legacy toggles honoured only when the
  // merchant explicitly turned QR off.
  const codeType = card.code_type
    || (card.show_qr === false && card.show_barcode !== false ? 'barcode' : 'qr');
  const showQr = codeType === 'qr' || codeType === 'both';
  const showBarcode = codeType === 'barcode' || codeType === 'both';

  // ---- stamps + meter ----------------------------------------------------
  // Same single-source-of-truth maths as PremiumLoyaltyCard: everything is
  // DERIVED from visits and the owner's loyalty rules, never read from stored
  // customer.points/stamps (those drift when the owner later changes rules).
  const visits = parseInt(customer?.visits, 10) || 0;
  const threshold = Math.max(1, parseInt(customer?.reward_threshold, 10)
    || parseInt(card.reward_threshold_stamps, 10) || 10);
  const pointsPerVisit = parseInt(card.points_per_visit, 10) || 10;
  const visitsPerStamp = Math.max(1, parseInt(card.visits_per_stamp, 10) || 1);
  const stamps = Math.min(threshold, Math.floor(visits / visitsPerStamp));
  const remaining = threshold - stamps;

  const meterMax = threshold * visitsPerStamp * pointsPerVisit;
  // Cap the DISPLAYED figure at the cycle max: a customer past the reward
  // threshold was rendering "180 / 100", which reads as a broken counter
  // rather than an overflowing one (caught on the live Café Lumière card).
  const earnedPoints = Math.min(visits * pointsPerVisit, meterMax);
  const meterPct = meterMax > 0 ? Math.max(0, Math.min(100, (earnedPoints / meterMax) * 100)) : 0;

  // ---- offer chip (the per-segment overlay's new, calmer home) -----------
  const offerText = card.offer_box_text || card.active_offer_text || '';
  const showOffer = card.show_offer_box !== false && !!offerText;

  // ---- hero --------------------------------------------------------------
  // "image" when a hero exists, brand fill otherwise; "none" collapses it.
  const heroMode = card.hero_mode || (card.hero_image_url ? 'image' : 'brand');

  const S = styles(t, compact);

  return (
    <div style={S.card} data-testid="wallet-card">
      {/* header row: logo · name · tier chip */}
      <div style={S.header}>
        <div style={S.identity}>
          {card.logo_url ? (
            <img src={card.logo_url} alt="" style={S.logo} />
          ) : (
            <div style={{ ...S.logo, ...S.logoFallback }}>
              {(tenant?.name || 'F').charAt(0)}
            </div>
          )}
          <span style={S.bizName}>{tenant?.name || 'Votre commerce'}</span>
        </div>
        {showTier && (
          <span style={{ ...S.tierChip, background: tierChip.bg, color: tierChip.ink }}>
            {tierChip.label}
          </span>
        )}
      </div>

      {/* hero strip: merchant photo, or flat brand colour */}
      {heroMode !== 'none' && (
        <div
          style={{
            ...S.hero,
            ...(heroMode === 'image' && card.hero_image_url
              ? { backgroundImage: `url(${card.hero_image_url})` }
              : { backgroundColor: t.brandRaw }),
          }}
          role="img"
          aria-label={card.hero_image_alt || ''}
        />
      )}

      {/* fields row — wallet pass typography: micro label above, value below */}
      <div style={S.fields}>
        <div style={S.field}>
          <div style={S.fieldLabel}>{memberLabel}</div>
          <div style={S.fieldValue}>{displayName}</div>
        </div>
        {showPoints && (
          <div style={S.field}>
            <div style={S.fieldLabel}>{pointsLabel}</div>
            <div style={S.fieldValue}>{points}</div>
          </div>
        )}
        {showVisits && customer?.visits != null && (
          <div style={S.field}>
            <div style={S.fieldLabel}>{visitsLabel}</div>
            <div style={S.fieldValue}>{customer.visits}</div>
          </div>
        )}
      </div>

      {/* stamps — small brand dots, never traffic signage */}
      {showStamps && (
        <div style={S.section}>
          <div style={S.fieldLabel}>
            {stampsLabel}
            {remaining > 0 && remaining <= 3 && (
              <span style={S.almostThere}> · plus que {remaining}</span>
            )}
          </div>
          <div style={S.stampRow}>
            {Array.from({ length: threshold }).map((_, i) => (
              <span
                key={i}
                style={i < stamps ? S.stampFull : S.stampEmpty}
                aria-hidden="true"
              />
            ))}
          </div>
        </div>
      )}

      {/* meter — thin is premium */}
      {showMeter && (
        <div style={S.section}>
          <div style={S.meterHead}>
            <span style={S.fieldLabel}>{card.meter_label || 'Progression'}</span>
            <span style={S.meterCount}>{earnedPoints} / {meterMax}</span>
          </div>
          <div style={S.meterTrack}>
            <div style={{ ...S.meterFill, width: `${meterPct}%` }} />
          </div>
        </div>
      )}

      {/* offer chip — one line, brand border, no shouting */}
      {showOffer && (
        <div style={S.offerChip}>
          <span style={S.offerText}>{offerText}</span>
          {card.offer_box_subtext ? (
            <span style={S.offerSub}>{card.offer_box_subtext}</span>
          ) : null}
        </div>
      )}

      {/* code block — always on white, scanners come first */}
      {(showQr || showBarcode) && barcodeId && (
        <div style={S.codeBlock}>
          {showQr && (
            <QRCodeSVG
              value={barcodeId}
              size={compact ? 72 : 92}
              bgColor={t.codeBg}
              fgColor={t.codeInk}
              level="M"
            />
          )}
          {showBarcode && (
            <div style={S.barcodeWrap}>
              <Code128Barcode value={barcodeId} height={compact ? 34 : 42} />
            </div>
          )}
          {card.show_card_number !== false && (
            <div style={S.cardNumber}>{barcodeId}</div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- styles
// One font stack (the platform's), two weights, sizes fixed by the layout.
// No style below reads a merchant-supplied colour directly — only theme tokens.

function styles(t, compact) {
  const pad = compact ? 16 : 22;
  return {
    card: {
      background: t.surface,
      color: t.ink,
      borderRadius: 18,
      padding: pad,
      maxWidth: 380,
      width: '100%',
      fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
      boxShadow: '0 8px 28px rgba(0,0,0,0.18)',
      display: 'flex',
      flexDirection: 'column',
      gap: compact ? 12 : 15,
    },
    header: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 },
    identity: { display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 },
    logo: { width: 34, height: 34, borderRadius: 8, objectFit: 'cover', flexShrink: 0 },
    logoFallback: {
      background: t.track, color: t.ink, display: 'grid', placeItems: 'center',
      fontWeight: 600, fontSize: 15,
    },
    bizName: {
      fontWeight: 600, fontSize: 15, letterSpacing: '-0.01em',
      whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
    },
    tierChip: {
      fontSize: 10, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase',
      padding: '3px 9px', borderRadius: 999, flexShrink: 0,
    },
    hero: {
      // Apple's store-card strip is 375×144pt — the same ratio here means a
      // merchant's strip artwork works unchanged if we later emit real
      // .pkpass files, and the PWA card previews exactly what Wallet shows.
      aspectRatio: '375 / 144', borderRadius: 10,
      backgroundSize: 'cover', backgroundPosition: 'center',
    },
    fields: { display: 'flex', gap: compact ? 18 : 26 },
    field: { minWidth: 0 },
    fieldLabel: {
      fontSize: 9.5, fontWeight: 600, letterSpacing: '0.09em', textTransform: 'uppercase',
      color: t.label,
    },
    fieldValue: { fontSize: compact ? 15 : 17, fontWeight: 600, marginTop: 2, color: t.ink },
    section: { display: 'flex', flexDirection: 'column', gap: 6 },
    almostThere: { color: t.brand, textTransform: 'none', letterSpacing: 0, fontWeight: 600 },
    stampRow: { display: 'flex', gap: 5, flexWrap: 'wrap' },
    stampFull: {
      width: 14, height: 14, borderRadius: '50%', background: t.brand, display: 'inline-block',
    },
    stampEmpty: {
      width: 14, height: 14, borderRadius: '50%', border: `1.5px solid ${t.track}`,
      boxSizing: 'border-box', display: 'inline-block',
    },
    meterHead: { display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' },
    meterCount: { fontSize: 11, color: t.inkSoft, fontVariantNumeric: 'tabular-nums' },
    meterTrack: { height: 4, borderRadius: 2, background: t.track, overflow: 'hidden' },
    meterFill: { height: '100%', background: t.brand, borderRadius: 2 },
    offerChip: {
      background: t.chipBg, borderLeft: `3px solid ${t.brand}`, borderRadius: '0 8px 8px 0',
      padding: '9px 12px', display: 'flex', flexDirection: 'column', gap: 2,
    },
    offerText: { fontSize: 12.5, fontWeight: 600, color: t.ink },
    offerSub: { fontSize: 11, color: t.inkSoft },
    codeBlock: {
      background: t.codeBg, borderRadius: 12, padding: 12,
      display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8,
    },
    barcodeWrap: { width: '100%', display: 'flex', justifyContent: 'center' },
    cardNumber: {
      fontSize: 10, letterSpacing: '0.12em', color: '#6b6f76',
      fontVariantNumeric: 'tabular-nums',
    },
  };
}
