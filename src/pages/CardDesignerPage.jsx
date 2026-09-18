import React, { useState, useEffect } from 'react';
import { Save, Send, CheckCircle, AlertCircle, Palette, Coins, Award, ImagePlus, X } from 'lucide-react';
import { ownerAPI } from '../lib/api';
import NumberInput from '../components/NumberInput';
import { PageHeader, C as C_PS } from '../components/PageShell';
import PremiumLoyaltyCard from '../components/PremiumLoyaltyCard';
import WalletPassPreview from '../components/WalletPassPreview';

// Crop viewport for the band photo — exactly the strip's 375:144 ratio.
const CROP_W = 500;
const CROP_H = 192;

// Defaults for the loyalty rules — kept in sync with the backend CardTemplate model.
const DEFAULT_RULES = {
  points_per_visit: 10,
  visits_per_stamp: 1,
  reward_threshold_stamps: 10,
  reward_description: 'Un café gratuit',
  notify_before_reward: 1,   // Push fires when this-many visits remain
};

// Brand defaults for the premium card. EVERY visible field on
// PremiumLoyaltyCard is editable here so the owner can match their brand
// down to the last detail without touching code.
const DEFAULT_BRAND = {
  // Colours
  primary_color:    '#B85C38',
  secondary_color:  '#9C4427',
  accent_color:     '#F4D8A8',
  text_on_brand:    '#FFFFFF',   // text colour on the hero block
  back_link_color:  '#F4D8A8',   // "Au dos →" colour
  // Images
  logo_url:         '',
  hero_image_url:   '',
  hero_front_url:   '',
  // Where the logo sits on the card. 'top_left' is the Apple-Wallet default
  // (matches Maison 123, FNAC, GÉMO). 'middle_overlay' puts it centred over
  // the middle band, 'top_center' centres it on the top strip.
  logo_position:    'top_left',  // 'top_left' | 'top_center' | 'middle_overlay'
  // Text content
  title_label:      'Ta carte fidélité',
  points_label:     'Points',
  greeting_label:   'Bonjour',
  back_label:       'Détails récompenses',
  back_value:       'Au dos →',
  // Typography
  title_font:       'Cormorant Garamond',  // serif by default
  title_italic:     true,
  title_bold:       true,
  title_underline:  false,
  // Visibility toggles (show/hide each element)
  show_tier:        true,   // "MEMBRE GOLD" under brand name
  show_points:      true,   // points block top-right
  show_title:       true,   // "Ta carte fidélité" editorial title
  show_greeting:    true,   // "Bonjour Marie" row
  show_back_link:   true,   // "Au dos →" right side
  show_card_number: true,   // "N° CARTE 4E62" footer
  show_barcode:     true,   // Code 128 strip

  // ── Wallet-anatomy design (layout_style: 'wallet') ───────────────
  // The redesigned card (FidClic-Card-Redesign-Spec). Duo-tone contract:
  // the merchant picks a surface (card body) + a brand colour (accent);
  // cardTheme.js derives every other colour with contrast arithmetic.
  // These keys ride brand_fields into the customer payload automatically.
  layout_style:     '',          // '' = legacy render · 'wallet' = new anatomy
  surface:          'anthracite',// curated: noir|anthracite|marine|foret|espresso|blanc|creme|sable
  surface_color:    '',          // optional custom hex — overrides `surface`
  brand_color:      '#B85C38',   // THE accent (stamps, meter, offer chip, tier ring)
  code_type:        'qr',        // 'qr' | 'barcode' | 'both' — QR default: Apple
                                 // notes Code128 is unsupported on watchOS and
                                 // square codes scan better on small screens
  hero_mode:        'image',     // 'image' | 'brand' | 'none'

  // ── Layout selector + Wallet-pass-specific fields ────────────────
  // Two ways to render the card:
  //   - 'hero': full brand-coloured hero with logo + name + image
  //     overlay (the existing premium layout, KFC-inspired).
  //   - 'wallet_pass': 3-band Apple-Wallet style — light top strip,
  //     promotional middle band (image OR colour with text + optional
  //     CTA box), light bottom strip with member fields + barcode.
  //     Matches GÉMO, Maison 123, FNAC adhérent, etc.
  // Default to the 3-band wallet-pass layout (FNAC / Maison 123 / GÉMO style)
  // since this is what most owners want out of the box. They can flip to
  // 'hero' from the layout picker if they prefer the brand-coloured full-bleed.
  layout_style:        'wallet_pass',
  // Card surface colour — shared by the top strip + bottom strip
  // in 'wallet_pass' layout. Default white.
  card_bg_color:       '#FFFFFF',
  card_ink_color:      '#171412',   // text colour on top + bottom strips
  // Middle band — solid colour OR image
  strip_type:          'color',     // 'color' | 'image'
  strip_color:         '#7AA070',   // sage by default (GÉMO is mint green)
  strip_text_color:    '#FFFFFF',   // text overlaid on the strip
  strip_title:         'Avantage exclusif fidélité',
  strip_subtitle:      'Réservé aux membres du programme',
  // Optional callout box inside the strip (like GÉMO's "10€ cagnottés")
  show_offer_box:      true,
  offer_box_text:      '10€ cagnottés*',
  offer_box_subtext:   'Dès 3 articles achetés',
  offer_box_color:     '#FFFFFF',   // box fill colour (often white-on-strip)
  offer_box_ink_color: '#4A6740',   // text inside the box
  // Top-right link (GÉMO has "PLUS D'INFOS ↗ Florian MARTINEZ")
  top_right_label:     'Plus d\'infos',
  top_right_value:     '',          // owner can set a URL or leave empty
  show_top_right:      true,
  // Member identifier line shown on the bottom strip
  show_member_id:      true,
  member_id_label:     'Membre',    // shown above the name
  use_full_name:       false,       // false = "Marie", true = "Marie LEFÈVRE"
  // Stats row on the bottom strip — "MON COMPTEUR FID 1/3" + "MES OFFRES DISPONIBLES 0"
  show_counter:        true,
  counter_label:       'Mon compteur fid',
  show_offers_count:   true,
  offers_count_label:  'Mes offres disponibles',

  // ── Stamps grid + progress meter (bottom band) ───────────────────
  // The user wants the classic punch-card-style stamp grid AND a
  // points meter on the bottom band of the wallet-pass layout.
  show_stamps_grid:    true,
  // Shape of each individual stamp slot. 'custom' uses stamp_custom_url
  // for both filled and empty states (filled = full colour, empty = faded).
  stamp_shape:         'circle',         // 'circle' | 'hexagon' | 'octagon' | 'square' | 'custom'
  stamp_custom_url:    '',               // data URL when stamp_shape === 'custom'
  stamp_fill_color:    '#B85C38',        // colour of a collected stamp
  stamp_empty_color:   '#E9E5E0',        // colour of an unfilled slot
  stamp_ink_color:     '#FFFFFF',        // colour of the icon/check inside a filled stamp
  stamp_size:          28,               // pixel size of each slot
  stamps_label:        'Vos tampons',    // small caption above the stamps row

  // Progress meter — slim horizontal bar that mirrors the stamps fill
  show_meter:          true,
  meter_fill_color:    '#B85C38',
  meter_track_color:   '#F2EDE3',
  meter_label:         'Points',         // caption above the points meter

  // ── Apple-Wallet-style bottom band layout ──────────────────────────
  // Top-right corner of the card — small "+ D'INFOS / N pts" stack
  show_points_top_right: true,
  points_top_right_label: '+ D\'INFOS',
  // Greeting on the bottom band (Maison 123: "VICTOIRE / Utku")
  bottom_greeting_label: 'Bienvenue',
  // QR code + barcode controls — owner picks one or both, and the size
  show_qr:              true,
  show_barcode:         true,           // re-declared for clarity (matches above)
  qr_size:              90,             // px on the card surface
  // Birthday display
  show_birthday:        false,
  birthday_label:       'Anniversaire',
  // Tier badge on the top strip
  show_tier_badge:      true,
  tier_badge_bronze:    '#B26344',
  tier_badge_silver:    '#9AA6B3',
  tier_badge_gold:      '#E8A53B',
  tier_badge_vip:       '#9A6DBF',
};

// Font options for the title.
const TITLE_FONTS = [
  // Serif — boutique / luxury
  'Cormorant Garamond',
  'Playfair Display',
  'DM Serif Display',
  'Abril Fatface',
  'Libre Caslon Text',
  'EB Garamond',
  // Sans — modern SaaS
  'Inter',
  'Montserrat',
  'Poppins',
  'Work Sans',
  'DM Sans',
  // Display — bold, sporty, brand
  'Bebas Neue',
  'Anton',
  'Oswald',
  'Archivo Black',
  // Script — handwritten
  'Pacifico',
  'Dancing Script',
  'Great Vibes',
  // Monospace — tech / editorial
  'JetBrains Mono',
  'IBM Plex Mono',
];

// Convert an image File into a base64 data URL. We keep file size in check
// (max 800KB after re-encode) so the card_template doc stays under Mongo's
// 4MB cap even with a hero photograph attached.
function compressImage(file, maxDim = 1200, quality = 0.82) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      const img = new Image();
      img.onload = () => {
        const scale = Math.min(1, maxDim / Math.max(img.width, img.height));
        const w = Math.round(img.width * scale);
        const h = Math.round(img.height * scale);
        const canvas = document.createElement('canvas');
        canvas.width = w; canvas.height = h;
        canvas.getContext('2d').drawImage(img, 0, 0, w, h);
        resolve(canvas.toDataURL('image/jpeg', quality));
      };
      img.onerror = reject;
      img.src = e.target.result;
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

export default function CardDesignerPage() {
  // Loyalty rules — owner-configurable. Stored on the card_template doc itself.
  const [rules, setRules] = useState(DEFAULT_RULES);
  // Brand fields for the premium card surface (logo, hero image, colours).
  const [brand, setBrand] = useState(DEFAULT_BRAND);
  // Hold the full server-side template so we don't drop fields on save.
  const [serverTemplate, setServerTemplate] = useState(null);
  const [tenant, setTenant] = useState(null);
  const [saving, setSaving] = useState(false);
  const [pushing, setPushing] = useState(false);
  const [ok, setOk] = useState('');
  const [err, setErr] = useState('');
  // Crop step for the band photo: {src, imgW, imgH, scale, minScale, x, y}.
  // The merchant frames their photo in the band's exact 375:144 ratio, so the
  // strip is ALWAYS full — no empty space — and THEY choose what's in frame.
  const [cropper, setCropper] = useState(null);
  const cropDrag = React.useRef(null);

  const clampCrop = (c) => ({
    ...c,
    x: Math.min(0, Math.max(CROP_W - c.imgW * c.scale, c.x)),
    y: Math.min(0, Math.max(CROP_H - c.imgH * c.scale, c.y)),
  });

  const confirmCrop = () => {
    if (!cropper) return;
    const img = new Image();
    img.onload = () => {
      const cv = document.createElement('canvas');
      cv.width = 1125; cv.height = 432;                 // Apple @3x strip
      const ctx = cv.getContext('2d');
      ctx.drawImage(img,
        -cropper.x / cropper.scale, -cropper.y / cropper.scale,
        CROP_W / cropper.scale, CROP_H / cropper.scale,
        0, 0, 1125, 432);
      setBrand((b) => ({ ...b, hero_image_url: cv.toDataURL('image/jpeg', 0.85),
                          hero_mode: 'image' }));
      setCropper(null);
    };
    img.src = cropper.src;
  };

  useEffect(() => {
    (async () => {
      try {
        const [t, tpl] = await Promise.all([ownerAPI.getTenant(), ownerAPI.getCardTemplate()]);
        setTenant(t.data || null);
        const tplData = tpl?.data || {};
        setServerTemplate(tplData);
        // Pull rules from the top-level card_template fields
        setRules({
          points_per_visit: tplData.points_per_visit ?? DEFAULT_RULES.points_per_visit,
          visits_per_stamp: tplData.visits_per_stamp ?? DEFAULT_RULES.visits_per_stamp,
          reward_threshold_stamps: tplData.reward_threshold_stamps ?? DEFAULT_RULES.reward_threshold_stamps,
          reward_description: tplData.reward_description ?? DEFAULT_RULES.reward_description,
          notify_before_reward: tplData.notify_before_reward ?? DEFAULT_RULES.notify_before_reward,
        });
        // Pull ALL brand fields from the saved template. Spread defaults
        // first so any new field added later picks up sensibly.
        setBrand({
          ...DEFAULT_BRAND,
          ...(tplData.brand_fields || {}),
          // Legacy field names — keep reading these for old docs
          primary_color: tplData.primary_color || DEFAULT_BRAND.primary_color,
          secondary_color: tplData.secondary_color || DEFAULT_BRAND.secondary_color,
          accent_color: tplData.accent_color || DEFAULT_BRAND.accent_color,
          logo_url: tplData.logo_url || '',
          hero_image_url: tplData.hero_image_url || '',
          hero_front_url: tplData.hero_front_url || '',
          title_label: tplData.title_label || DEFAULT_BRAND.title_label,
          points_label: tplData.points_label || DEFAULT_BRAND.points_label,
          // Wallet-anatomy keys may exist only at top level (set via API
          // before this UI existed — the demo tenant, for one). Seed them
          // from there so opening the designer and hitting Save doesn't
          // silently flip a live wallet card back to the legacy render.
          layout_style: tplData.layout_style ?? tplData.brand_fields?.layout_style ?? '',
          surface: tplData.surface ?? tplData.brand_fields?.surface ?? DEFAULT_BRAND.surface,
          surface_color: tplData.surface_color ?? tplData.brand_fields?.surface_color ?? '',
          brand_color: tplData.brand_color ?? tplData.brand_fields?.brand_color ?? DEFAULT_BRAND.brand_color,
          code_type: (() => { const v = tplData.code_type ?? tplData.brand_fields?.code_type ?? DEFAULT_BRAND.code_type;
            return v === 'both' ? 'qr' : v; })(),
          hero_mode: tplData.hero_mode ?? tplData.brand_fields?.hero_mode ?? DEFAULT_BRAND.hero_mode,
        });
        // Legacy auchan_layout is preserved on save but no longer edited.
      } catch (e) {
        /* defaults are fine */
      }
    })();
  }, []);

  const updateRule = (key, val) => {
    setRules((r) => ({ ...r, [key]: val }));
  };

  const flash = (type, msg) => {
    if (type === 'ok') { setOk(msg); setErr(''); }
    else { setErr(msg); setOk(''); }
    setTimeout(() => { setOk(''); setErr(''); }, 3000);
  };

  // Convert any backend error into a readable string (objects/arrays were
  // showing as "[object Object]").
  const errMsg = (e) => {
    const d = e?.response?.data?.detail;
    if (typeof d === 'string') return d;
    if (Array.isArray(d)) return d.map((x) => x?.msg || JSON.stringify(x)).join('; ');
    if (d && typeof d === 'object') return JSON.stringify(d);
    if (e?.response?.status === 413) return 'Payload too large — your image is over the upload limit. Try a smaller banner.';
    if (e?.response?.statusText) return `${e.response.status} ${e.response.statusText}`;
    return e?.message || 'Unknown error';
  };

  const save = async () => {
    setSaving(true);
    try {
      // Build the full card_template payload: server-side fields + the
      // owner-edited layout + the owner-edited rules. We start from the
      // existing serverTemplate so we never drop an admin-set field.
      const payload = {
        ...(serverTemplate || {}),
        // The premium card is the single source of truth. Legacy
        // auchan_layout in the existing doc is preserved (it spreads
        // through `...serverTemplate`) but no longer edited from the UI.
        points_per_visit: Math.max(0, parseInt(rules.points_per_visit, 10) || 0),
        visits_per_stamp: Math.max(1, parseInt(rules.visits_per_stamp, 10) || 1),
        reward_threshold_stamps: Math.max(1, Math.min(15, parseInt(rules.reward_threshold_stamps, 10) || 1)),
        reward_description: (rules.reward_description || '').trim() || 'Reward',
        notify_before_reward: Math.max(0, parseInt(rules.notify_before_reward, 10) || 0),
        // Brand fields drive the PremiumLoyaltyCard surface. We persist
        // both the top-level keys (for backward-compat with older readers)
        // AND a single brand_fields object (for forward-looking growth —
        // any new toggle landed in DEFAULT_BRAND auto-persists).
        brand_fields: brand,
        primary_color: brand.primary_color || DEFAULT_BRAND.primary_color,
        secondary_color: brand.secondary_color || DEFAULT_BRAND.secondary_color,
        accent_color: brand.accent_color || DEFAULT_BRAND.accent_color,
        logo_url: brand.logo_url || '',
        hero_image_url: brand.hero_image_url || '',
        hero_front_url: brand.hero_front_url || '',
        title_label: (brand.title_label || '').trim() || DEFAULT_BRAND.title_label,
        points_label: (brand.points_label || '').trim() || DEFAULT_BRAND.points_label,
        // Wallet-anatomy keys mirrored at top level: the customer payload
        // reads these via tpl.get(...), which would override the brand_fields
        // spread with None if they only lived inside brand_fields.
        layout_style: brand.layout_style || '',
        surface: brand.surface || 'anthracite',
        surface_color: brand.surface_color || '',
        brand_color: brand.brand_color || DEFAULT_BRAND.brand_color,
        code_type: brand.code_type || 'qr',
        hero_mode: brand.hero_mode || 'image',
      };
      delete payload._id; // mongo internal field — never round-trip
      const payloadSize = JSON.stringify(payload).length;
      if (payloadSize > 4_000_000) {
        flash('err', `Your card design is ${(payloadSize / 1_048_576).toFixed(1)} MB — too large to save (limit ~4 MB). Use a smaller / more compressed image.`);
        setSaving(false);
        return;
      }
      const res = await ownerAPI.saveCardTemplate(payload);
      // Re-anchor the server template so subsequent saves keep working
      if (res?.data) setServerTemplate(res.data);
      flash('ok', 'Card design + loyalty rules saved.');
    } catch (e) {
      flash('err', 'Save failed: ' + errMsg(e));
    } finally {
      setSaving(false);
    }
  };

  // Live, human-readable summary of how the rules combine.
  const totalVisitsForReward = Math.max(1, parseInt(rules.visits_per_stamp, 10) || 1) *
    Math.max(1, parseInt(rules.reward_threshold_stamps, 10) || 1);
  const pointsPerReward = Math.max(0, parseInt(rules.points_per_visit, 10) || 0) * totalVisitsForReward;

  const sendPush = async () => {
    setPushing(true);
    try {
      await ownerAPI.sendCardNotification({
        type: 'offer',
        title: tenant?.business_name || tenant?.name || 'Nouvelle offre',
        body: `${rules.reward_description ? rules.reward_description + ' ' : ''}vous attend !`,
      });
      flash('ok', 'Push sent to all your customers.');
    } catch (e) {
      flash('err', 'Push failed: ' + (e?.response?.data?.detail || e.message));
    } finally {
      setPushing(false);
    }
  };

  const ctx = {
    first_name: 'Sophie',
    name: 'Sophie Dupont',
    points: '3.4',
    loyalty_number: '049130960',
    business_name: tenant?.business_name || 'Mon commerce',
  };

  return (
    <div className="max-w-6xl mx-auto space-y-6 card-designer-page">
      <PageHeader
        eyebrow="Visual Design"
        title="Card Designer"
        description="Edit every text, font, color, and placement on the wallet card. Save to push the new look to all customers."
        role="business_owner"
        actions={
          <div className="flex gap-2">
            <button
              onClick={sendPush}
              disabled={pushing}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-full text-sm font-semibold transition-all hover:-translate-y-0.5 disabled:opacity-50"
              style={{ background: 'var(--flc-card, #FFFFFF)', border: `1px solid ${C_PS.terracotta}`, color: C_PS.terracotta }}
            >
              <Send size={14} /> {pushing ? 'Sending…' : 'Send push'}
            </button>
            <button
              onClick={save}
              disabled={saving}
              className="inline-flex items-center gap-2 px-5 py-2 rounded-full text-sm font-semibold text-white transition-all shadow-md hover:-translate-y-0.5 disabled:opacity-50"
              style={{ background: `linear-gradient(135deg, ${C_PS.ochre}, ${C_PS.terracotta})` }}
            >
              <Save size={14} /> {saving ? 'Saving…' : 'Save design'}
            </button>
          </div>
        }
      />

      {/* Floating save — the header button scrolls away and the phone preview
          hides it on small screens; this one is ALWAYS on screen. */}
      <button
        onClick={save}
        disabled={saving}
        className="fixed bottom-5 right-5 z-50 inline-flex items-center gap-2 px-6 py-3 rounded-full text-sm font-bold text-white shadow-xl transition-all hover:-translate-y-0.5 disabled:opacity-50"
        style={{ background: `linear-gradient(135deg, ${C_PS.ochre}, ${C_PS.terracotta})`,
                 boxShadow: '0 10px 30px rgba(0,0,0,0.35)' }}
      >
        <Save size={16} /> {saving ? 'Enregistrement…' : 'Enregistrer'}
      </button>

      {/* ── Crop step: frame the photo in the band's exact ratio ── */}
      {cropper && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center p-4"
             style={{ background: 'rgba(15,14,12,0.72)' }}>
          <div className="bg-white rounded-2xl p-5 shadow-2xl" style={{ maxWidth: CROP_W + 40 }}>
            <p className="text-sm font-bold text-[#171412] mb-1">Cadrez votre photo</p>
            <p className="text-[11px] text-[#8D857D] mb-3">
              Glissez pour déplacer, zoomez avec le curseur. Ce que vous voyez ici est
              exactement ce qui remplira le bandeau — aucun espace vide, aucun recadrage surprise.
            </p>
            <div
              style={{ width: CROP_W, height: CROP_H, overflow: 'hidden', borderRadius: 10,
                       position: 'relative', cursor: 'grab', touchAction: 'none',
                       background: '#111', maxWidth: '100%' }}
              onPointerDown={(e) => {
                e.currentTarget.setPointerCapture(e.pointerId);
                cropDrag.current = { sx: e.clientX, sy: e.clientY, x: cropper.x, y: cropper.y };
              }}
              onPointerMove={(e) => {
                if (!cropDrag.current) return;
                const d = cropDrag.current;
                setCropper((c) => c && clampCrop({ ...c,
                  x: d.x + (e.clientX - d.sx), y: d.y + (e.clientY - d.sy) }));
              }}
              onPointerUp={() => { cropDrag.current = null; }}
            >
              <img src={cropper.src} alt="" draggable={false}
                style={{ position: 'absolute', left: cropper.x, top: cropper.y,
                         width: cropper.imgW * cropper.scale,
                         height: cropper.imgH * cropper.scale,
                         maxWidth: 'none', userSelect: 'none', pointerEvents: 'none' }} />
            </div>
            <input
              type="range" className="w-full mt-3"
              min={cropper.minScale} max={cropper.minScale * 3} step={0.001}
              value={cropper.scale}
              onChange={(e) => {
                const ns = parseFloat(e.target.value);
                setCropper((c) => {
                  if (!c) return c;
                  // zoom about the viewport centre
                  const cx = (CROP_W / 2 - c.x) / c.scale;
                  const cy = (CROP_H / 2 - c.y) / c.scale;
                  return clampCrop({ ...c, scale: ns,
                    x: CROP_W / 2 - cx * ns, y: CROP_H / 2 - cy * ns });
                });
              }}
            />
            <div className="flex justify-end gap-2 mt-3">
              <button onClick={() => setCropper(null)}
                className="px-4 py-2 rounded-full text-sm font-medium border border-[#E9E5E0] text-[#57504A]">
                Annuler
              </button>
              <button onClick={confirmCrop}
                className="px-5 py-2 rounded-full text-sm font-bold text-white"
                style={{ background: `linear-gradient(135deg, ${C_PS.ochre}, ${C_PS.terracotta})` }}>
                Valider le cadrage
              </button>
            </div>
          </div>
        </div>
      )}

      {ok && (
        <div className="rounded-lg bg-green-50 border border-green-200 text-green-800 px-4 py-2 text-sm flex items-center gap-2">
          <CheckCircle size={15} /> {ok}
        </div>
      )}
      {err && (
        <div className="rounded-lg bg-red-50 border border-red-200 text-red-800 px-4 py-2 text-sm flex items-center gap-2">
          <AlertCircle size={15} /> {err}
        </div>
      )}

      {/* Loyalty Rules — these drive the actual scan + reward logic. They're
          separate from the visual design so owners can change "10 visits = 1
          free coffee" → "8 visits = 1 free pastry" in seconds without touching
          the layout. The visual stamps_target auto-syncs with reward_threshold_stamps. */}
      <div className="rounded-xl border-2 border-[#E3A869] bg-[#F6E9E2] p-5 space-y-4">
        <div className="flex items-center gap-2">
          <Coins size={20} className="text-[#96431F]" />
          <h2 className="text-lg font-bold text-[#96431F]">
            Loyalty Rules — what your customers earn
          </h2>
        </div>
        <p className="text-xs text-[#96431F]/80 -mt-2">
          These numbers control your scan flow and reward unlocks. Change them and every customer's
          card and progression updates. The visual stamp count below auto-syncs with the reward threshold.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="text-xs font-bold text-[#96431F] uppercase tracking-wider mb-1 block">
              Points awarded per visit
            </label>
            <p className="text-[11px] text-[#96431F]/80 mb-2">
              How many points each customer gets when staff scans their visit. Default: 10.
            </p>
            <NumberInput
              min={0}
              max={1000}
              emptyValue={10}
              value={rules.points_per_visit}
              onChange={(n) => updateRule('points_per_visit', n)}
              className="w-full px-3 py-2 rounded-lg border border-[#E3A869]/60 bg-white text-lg font-bold text-[#171412]"
            />
          </div>

          <div>
            <label className="text-xs font-bold text-[#96431F] uppercase tracking-wider mb-1 block">
              Visits required per stamp
            </label>
            <p className="text-[11px] text-[#96431F]/80 mb-2">
              Usually 1 (every visit = 1 stamp). Set to 2 if you want stamps to feel rarer.
            </p>
            <NumberInput
              min={1}
              max={20}
              emptyValue={1}
              value={rules.visits_per_stamp}
              onChange={(n) => updateRule('visits_per_stamp', n)}
              className="w-full px-3 py-2 rounded-lg border border-[#E3A869]/60 bg-white text-lg font-bold text-[#171412]"
            />
          </div>

          <div>
            <label className="text-xs font-bold text-[#96431F] uppercase tracking-wider mb-1 block">
              Stamps to unlock the reward
            </label>
            <p className="text-[11px] text-[#96431F]/80 mb-2">
              How many stamps to fill the card. Default: 10 (the classic café punch card).
            </p>
            <NumberInput
              min={1}
              max={15}
              emptyValue={10}
              value={rules.reward_threshold_stamps}
              onChange={(n) => updateRule('reward_threshold_stamps', n)}
              className="w-full px-3 py-2 rounded-lg border border-[#E3A869]/60 bg-white text-lg font-bold text-[#171412]"
            />
          </div>

          <div>
            <label className="text-xs font-bold text-[#96431F] uppercase tracking-wider mb-1 block">
              Reward description
            </label>
            <p className="text-[11px] text-[#96431F]/80 mb-2">
              What customers see they'll earn. Shown on the card and in the unlock notification.
            </p>
            <input
              type="text"
              maxLength={120}
              value={rules.reward_description}
              onChange={(e) => updateRule('reward_description', e.target.value)}
              placeholder="e.g. Un café gratuit"
              className="w-full px-3 py-2 rounded-lg border border-[#E3A869]/60 bg-white text-lg font-semibold text-[#171412]"
            />
          </div>

          <div className="md:col-span-2">
            <label className="text-xs font-bold text-[#96431F] uppercase tracking-wider mb-1 block">
              🔔 Send "almost there" push when N visits remain
            </label>
            <p className="text-[11px] text-[#96431F]/80 mb-2">
              When a customer is this many visits away from unlocking the reward, an automatic push
              fires once. Set to <b>1</b> for the classic "one more visit and you get a free coffee!"
              nudge. Set to <b>0</b> to disable.
            </p>
            <div className="flex items-center gap-3">
              <NumberInput
                min={0}
                max={10}
                emptyValue={0}
                value={rules.notify_before_reward}
                onChange={(n) => updateRule('notify_before_reward', n)}
                className="w-24 px-3 py-2 rounded-lg border border-[#E3A869]/60 bg-white text-lg font-bold text-[#171412]"
              />
              <div className="flex items-center gap-2 text-xs text-[#96431F]">
                {[0, 1, 2, 3].map((preset) => {
                  const active = parseInt(rules.notify_before_reward, 10) === preset;
                  return (
                    <button
                      key={preset}
                      type="button"
                      onClick={() => updateRule('notify_before_reward', preset)}
                      className={`px-2.5 py-1 rounded-full text-xs font-bold transition ${
                        active
                          ? 'bg-[#B85C38] text-white'
                          : 'bg-white border border-[#E3A869]/60 hover:bg-[#F6E9E2]'
                      }`}
                    >
                      {preset === 0 ? 'Off' : `${preset} visit${preset > 1 ? 's' : ''} away`}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
        </div>

        {/* Live, plain-English summary */}
        <div className="rounded-lg bg-[#96431F] text-white p-4 flex items-start gap-3">
          <Award size={18} className="shrink-0 mt-0.5" />
          <div className="text-sm">
            <p className="font-bold">In plain English:</p>
            <p className="opacity-95">
              Customers earn <b>{rules.points_per_visit} points</b> per visit.
              {' '}After <b>{totalVisitsForReward} visit{totalVisitsForReward === 1 ? '' : 's'}</b>
              {' '}({rules.reward_threshold_stamps} stamp{rules.reward_threshold_stamps === 1 ? '' : 's'} ·
              {' '}{rules.visits_per_stamp} visit{rules.visits_per_stamp === 1 ? '' : 's'} per stamp)
              {' '}they unlock <b>"{rules.reward_description}"</b> — having earned <b>{pointsPerReward} points</b> along the way.
              {parseInt(rules.notify_before_reward, 10) > 0 && (
                <>
                  {' '}🔔 When they're <b>{rules.notify_before_reward} visit{parseInt(rules.notify_before_reward, 10) === 1 ? '' : 's'}</b> away,
                  {' '}an automatic "almost there!" push lands on their phone.
                </>
              )}
            </p>
          </div>
        </div>
      </div>

      {/* ── Nouveau design Wallet — the wallet-anatomy card ──────────────
          Duo-tone contract: surface + brand colour, everything else derived.
          Four curated presets follow the PassKit research: template-led with
          premium constraints, never a freeform canvas. */}
      <div className="rounded-xl border border-[#E9E5E0] bg-white p-5 space-y-4">
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <h2 className="text-lg font-bold text-[#171412]">
            Nouveau design Wallet
            <span className="ml-2 text-[10px] font-bold uppercase tracking-wider align-middle px-2 py-0.5 rounded-full"
              style={{ background: brand.layout_style === 'wallet' ? '#DCF0E4' : '#F2F2F2',
                       color: brand.layout_style === 'wallet' ? '#0F6B45' : '#8D857D' }}>
              {brand.layout_style === 'wallet' ? 'Actif' : 'Inactif'}
            </span>
          </h2>
          <button
            type="button"
            onClick={() => setBrand((b) => ({ ...b, layout_style: b.layout_style === 'wallet' ? '' : 'wallet' }))}
            className="text-xs font-bold px-3 py-1.5 rounded-lg border"
            style={brand.layout_style === 'wallet'
              ? { borderColor: '#E9E5E0', color: '#57504A', background: '#FAFAF8' }
              : { borderColor: '#171412', color: '#FFFFFF', background: '#171412' }}
          >
            {brand.layout_style === 'wallet' ? 'Revenir à l’ancien design' : 'Activer le nouveau design'}
          </button>
        </div>
        <p className="text-xs text-[#57504A] -mt-2 max-w-xl">
          Style « carte Apple Wallet » : vous choisissez la couleur de la carte, la couleur
          d’accent, le logo et la photo — la lisibilité (contrastes, tailles, typographie)
          est garantie automatiquement. Vos anciennes cartes ne changent pas tant que vous
          n’activez pas ce design.
        </p>

        {brand.layout_style === 'wallet' && (
          <div className="space-y-5">
            {/* Duo-tone pickers */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <p className="text-[11px] font-bold uppercase tracking-wider text-[#57504A] mb-2">Couleur de la carte (fond)</p>
                <div className="flex flex-wrap gap-1.5 mb-2">
                  {[['noir','#141519'],['anthracite','#1C1D22'],['marine','#101B2E'],['foret','#12211A'],
                    ['espresso','#211711'],['blanc','#FDFCFA'],['creme','#F6EFE3'],['sable','#EFE9DD']].map(([k, hex]) => (
                    <button key={k} type="button" title={k}
                      onClick={() => setBrand((b) => ({ ...b, surface: k, surface_color: '' }))}
                      className="w-8 h-8 rounded-lg border-2"
                      style={{ background: hex,
                               borderColor: (brand.surface === k && !brand.surface_color) ? '#171412' : '#E9E5E0' }} />
                  ))}
                  <label className="w-8 h-8 rounded-lg border-2 overflow-hidden cursor-pointer grid place-items-center text-[10px] font-bold"
                    style={{ borderColor: brand.surface_color ? '#171412' : '#E9E5E0',
                             background: brand.surface_color || '#FFFFFF', color: '#8D857D' }}
                    title="Couleur personnalisée">
                    {!brand.surface_color && '+'}
                    <input type="color" className="sr-only"
                      value={brand.surface_color || '#1C1D22'}
                      onChange={(e) => setBrand((b) => ({ ...b, surface_color: e.target.value }))} />
                  </label>
                </div>
                <p className="text-[10px] text-[#8D857D]">Le texte s’adapte automatiquement — même une couleur personnalisée reste lisible.</p>
              </div>
              <div>
                <p className="text-[11px] font-bold uppercase tracking-wider text-[#57504A] mb-2">Couleur d’accent (marque)</p>
                <div className="flex items-center gap-2">
                  <input type="color"
                    value={brand.brand_color || '#B85C38'}
                    onChange={(e) => setBrand((b) => ({ ...b, brand_color: e.target.value }))}
                    className="w-10 h-10 rounded-lg border border-[#E9E5E0] cursor-pointer" />
                  <div className="text-[11px] text-[#57504A]">
                    Tampons, jauge, offre, accents.<br />
                    <span className="text-[#8D857D]">Duo gagnant : noir + or, marine + orange…</span>
                  </div>
                </div>
              </div>
            </div>

            {/* Hero + code */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <p className="text-[11px] font-bold uppercase tracking-wider text-[#57504A] mb-2">Bandeau (haut de carte)</p>
                <div className="flex gap-1.5">
                  {[['image','Photo'],['logo','Logo'],['brand','Couleur'],['none','Aucun']].map(([v, lbl]) => (
                    <button key={v} type="button"
                      onClick={() => setBrand((b) => ({ ...b, hero_mode: v }))}
                      className="text-xs px-3 py-1.5 rounded-lg border font-medium"
                      style={brand.hero_mode === v
                        ? { background: '#171412', color: '#FFF', borderColor: '#171412' }
                        : { background: '#FFF', color: '#57504A', borderColor: '#E9E5E0' }}>
                      {lbl}
                    </button>
                  ))}
                </div>
                <p className="text-[10px] text-[#8D857D] mt-1.5">
                  <b>Photo</b> : votre photo remplit tout le bandeau, sans espace vide — comme sur une vraie carte Apple Wallet. Une photo paysage (large) s'affiche en entier ; une photo carrée ou verticale est légèrement rognée en haut et en bas. <b>Logo</b> : votre logo seul sur la couleur de la carte. Le bandeau garde toujours la même taille.
                </p>
              </div>
              <div>
                <p className="text-[11px] font-bold uppercase tracking-wider text-[#57504A] mb-2">Code scanné en caisse</p>
                <div className="flex gap-1.5">
                  {/* ONE code only — a real Apple Wallet pass can't carry two,
                      so offering "Les deux" was a lie. Legacy 'both' → QR. */}
                  {[['qr','QR'],['barcode','Code-barres']].map(([v, lbl]) => (
                    <button key={v} type="button"
                      onClick={() => setBrand((b) => ({ ...b, code_type: v }))}
                      className="text-xs px-3 py-1.5 rounded-lg border font-medium"
                      style={brand.code_type === v
                        ? { background: '#171412', color: '#FFF', borderColor: '#171412' }
                        : { background: '#FFF', color: '#57504A', borderColor: '#E9E5E0' }}>
                      {lbl}
                    </button>
                  ))}
                </div>
                <p className="text-[10px] text-[#8D857D] mt-1.5">
                  QR recommandé : lisible sur petit écran, et le Code128 n’est pas supporté
                  sur Apple Watch.
                </p>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Premium brand block — drives the new wallet card surface
          (logo, hero image, brand colours, title + points labels). The Auchan
          editor below is for fine-tuning the back-of-card / legacy layout. */}
      <div className="rounded-xl border border-[#E9E5E0] bg-white p-5 space-y-4">
        <div className="flex items-center gap-2">
          <Palette size={20} className="text-[#B85C38]" />
          <h2 className="text-lg font-bold text-[#171412]">
            Design premium — logo, image, couleurs
          </h2>
        </div>
        <p className="text-xs text-[#57504A] -mt-2">
          Ces éléments forment la première impression du client quand il ouvre sa carte.
          Un logo net + une belle photo de votre produit + la bonne couleur de marque suffisent à
          faire passer la carte de "site web" à "Apple Wallet".
        </p>

        <div className="grid grid-cols-1 lg:grid-cols-[1fr,300px] gap-6">
          {/* Editor column */}
          <div className="space-y-5">
            {/* Logo */}
            <div>
              <label className="block text-xs font-bold uppercase tracking-wider text-[#57504A] mb-1">
                Logo (carré, 200×200 idéal)
              </label>
              <div className="flex items-center gap-3">
                {brand.logo_url ? (
                  <div className="relative">
                    <div className="w-36 h-36 rounded-xl border border-[#E9E5E0] bg-white p-2 flex items-center justify-center overflow-hidden">
                      <img src={brand.logo_url} alt="" className="max-w-full max-h-full object-contain" />
                    </div>
                    <button
                      type="button"
                      onClick={() => setBrand((b) => ({ ...b, logo_url: '' }))}
                      className="absolute -top-2 -right-2 w-7 h-7 rounded-full bg-[#171412] text-white flex items-center justify-center shadow-md"
                      aria-label="Supprimer le logo"
                    >
                      <X size={14} />
                    </button>
                  </div>
                ) : (
                  <div className="w-36 h-36 rounded-xl bg-[#FAFAF8] border border-dashed border-[#D6D3D1] flex items-center justify-center text-[#8D857D]">
                    <ImagePlus size={36} />
                  </div>
                )}
                <label className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-[#E9E5E0] text-sm font-medium text-[#171412] cursor-pointer hover:bg-[#FAFAF8]">
                  <ImagePlus size={14} />
                  {brand.logo_url ? 'Changer le logo' : 'Téléverser un logo'}
                  <input
                    type="file"
                    accept="image/*"
                    className="hidden"
                    onChange={async (e) => {
                      const f = e.target.files?.[0];
                      if (!f) return;
                      try {
                        const dataUrl = await compressImage(f, 400, 0.9);
                        setBrand((b) => ({ ...b, logo_url: dataUrl }));
                      } catch (_e) { flash('err', 'Impossible de lire l\'image.'); }
                      e.target.value = '';
                    }}
                  />
                </label>
              </div>
            </div>

            {/* Hero image — the single photo shown on the card's band */}
            <div>
              <label className="block text-xs font-bold uppercase tracking-wider text-[#57504A] mb-1">
                Photo de la carte (votre salon, boutique, produit)
              </label>
              <p className="text-[11px] text-[#8D857D] mb-2">
                À l'envoi, un cadreur s'ouvre : glissez et zoomez votre photo dans le format
                exact du bandeau. Résultat : bandeau toujours plein, cadrage choisi par vous.
              </p>
              <div className="flex items-center gap-3">
                {brand.hero_image_url ? (
                  <div className="relative">
                    <img src={brand.hero_image_url} alt="" className="w-28 h-16 rounded-lg object-cover border border-[#E9E5E0]" />
                    <button
                      type="button"
                      onClick={() => setBrand((b) => ({ ...b, hero_image_url: '' }))}
                      className="absolute -top-1 -right-1 w-5 h-5 rounded-full bg-[#171412] text-white flex items-center justify-center"
                      aria-label="Supprimer l'image"
                    >
                      <X size={11} />
                    </button>
                  </div>
                ) : (
                  <div className="w-28 h-16 rounded-lg bg-[#FAFAF8] border border-dashed border-[#D6D3D1] flex items-center justify-center text-[#8D857D]">
                    <ImagePlus size={22} />
                  </div>
                )}
                <label className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-[#E9E5E0] text-sm font-medium text-[#171412] cursor-pointer hover:bg-[#FAFAF8]">
                  <ImagePlus size={14} />
                  {brand.hero_image_url ? 'Changer l\'image' : 'Téléverser une image'}
                  <input
                    type="file"
                    accept="image/*"
                    className="hidden"
                    onChange={async (e) => {
                      const f = e.target.files?.[0];
                      if (!f) return;
                      try {
                        // Open the crop step instead of setting directly: the
                        // merchant frames their photo in the band's exact
                        // ratio, so the strip is always FULL with THEIR crop.
                        const dataUrl = await compressImage(f, 2000, 0.9);
                        const img = new Image();
                        img.onload = () => {
                          const minScale = Math.max(CROP_W / img.width, CROP_H / img.height);
                          setCropper({ src: dataUrl, imgW: img.width, imgH: img.height,
                                       scale: minScale, minScale,
                                       x: (CROP_W - img.width * minScale) / 2,
                                       y: (CROP_H - img.height * minScale) / 2 });
                        };
                        img.src = dataUrl;
                      } catch (_e) { flash('err', 'Impossible de lire l\'image.'); }
                      e.target.value = '';
                    }}
                  />
                </label>
              </div>
            </div>

            {/* Éléments visibles — ONLY what the wallet pass actually renders.
                Everything else (palette, typography, 3-band layout, stamp
                shapes) belonged to the retired legacy card and was noise. */}
            <div>
              <p className="text-[11px] font-bold uppercase tracking-wider text-[#57504A] mb-2">Éléments visibles</p>
              <div className="grid grid-cols-2 gap-2">
                {[
                  { key: 'show_tier',   label: 'Statut (Or, VIP…)' },
                  { key: 'show_points', label: 'Points' },
                  { key: 'show_visits', label: 'Visites' },
                  { key: 'show_stamps', label: 'Tampons' },
                ].map(({ key, label }) => (
                  <label key={key} className="flex items-center gap-2 text-[12px] text-[#171412] cursor-pointer py-1 px-2 rounded hover:bg-[#FAFAF8]">
                    <input
                      type="checkbox"
                      checked={brand[key] !== false}
                      onChange={(e) => setBrand((b) => ({ ...b, [key]: e.target.checked }))}
                    />
                    {label}
                  </label>
                ))}
              </div>
            </div>
          </div>

          {/* Live preview column — the card renders standalone (no PhoneFrame,
              no Safari URL bar) so it reads as if it's already sitting inside
              the Apple Wallet app. Sticky so the owner can scroll through the
              editor on the left and never lose sight of the live result.
              Underneath the card we render an annotated map that names each
              of the 3 patches and which controls live there. */}
          <div
            className="card-designer-preview-pane self-start"
          >
            {/* Hyper-realistic iPhone 15 Pro frame. Titanium-edged body,
                Dynamic Island, real status bar (time / signal / Wi-Fi /
                battery), Apple Wallet's "Done / ⋯" detail-view top bar,
                home indicator at the bottom. Card lives inside this. */}
            <div
              className="mx-auto"
              style={{
                position: 'relative',
                width: 312,
                height: 640,
                borderRadius: 50,
                background: 'linear-gradient(155deg, #5C5A57 0%, #2A2826 26%, #181615 60%, #2E2C2A 100%)',
                padding: 6,
                boxShadow: '0 36px 70px -28px rgba(0,0,0,0.60), 0 14px 28px -10px rgba(0,0,0,0.32)',
              }}
            >
              {/* Inner black bezel ring */}
              <div style={{ position: 'absolute', inset: 4, borderRadius: 46, background: '#000', boxShadow: 'inset 0 0 0 1px rgba(255,255,255,0.04)' }} />
              {/* Screen. Wallet mode shows Apple Wallet's LIGHT detail view
                  (#F2F2F7) — a dark pass on a dark screen just disappears,
                  and the reference passes all sit on this light ground. */}
              {(() => {
                const light = brand?.layout_style === 'wallet';
                const screenBg = light ? '#F2F2F7' : '#000000';
                const inkP = light ? '#111111' : '#FFFFFF';
                return (
              <div style={{ position: 'absolute', inset: 8, borderRadius: 42, overflow: 'hidden', background: screenBg }}>
                {/* Status bar */}
                <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 44, display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 24px 0', color: inkP, fontFamily: 'system-ui, -apple-system, sans-serif' }}>
                  <span style={{ fontSize: 14, fontWeight: 600, letterSpacing: '-0.01em' }}>9:41</span>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                    <svg width="16" height="10" viewBox="0 0 16 10" aria-hidden="true">
                      <rect x="0"  y="6" width="3" height="4"  rx="0.6" fill={inkP} />
                      <rect x="4"  y="4" width="3" height="6"  rx="0.6" fill={inkP} />
                      <rect x="8"  y="2" width="3" height="8"  rx="0.6" fill={inkP} />
                      <rect x="12" y="0" width="3" height="10" rx="0.6" fill={inkP} />
                    </svg>
                    <svg width="14" height="10" viewBox="0 0 15 11" aria-hidden="true">
                      <path d="M7.5 10.2a1.1 1.1 0 100-2.2 1.1 1.1 0 000 2.2zM7.5 6.6a3.3 3.3 0 012.35.97l1.05-1.05a4.8 4.8 0 00-6.8 0L5.15 7.57A3.3 3.3 0 017.5 6.6zm0-3.6a6.9 6.9 0 014.93 2.05l1.05-1.05A8.4 8.4 0 007.5 1.4 8.4 8.4 0 001.52 4l1.05 1.05A6.9 6.9 0 017.5 3z" fill={inkP}/>
                    </svg>
                    <svg width="26" height="11" viewBox="0 0 26 11" aria-hidden="true">
                      <rect x="0.5" y="0.5" width="21" height="10" rx="2.4" fill="none" stroke={inkP} strokeOpacity="0.55" />
                      <rect x="2.2" y="2.2" width="15.6" height="6.6" rx="1.2" fill={inkP} />
                      <rect x="22.5" y="3.5" width="2" height="4" rx="0.6" fill={inkP} fillOpacity="0.55" />
                    </svg>
                  </div>
                </div>
                {/* Dynamic Island */}
                <div style={{ position: 'absolute', top: 11, left: '50%', transform: 'translateX(-50%)', width: 96, height: 28, borderRadius: 999, background: '#000000', border: '1px solid #1A1A1A' }} />
                {/* Apple Wallet detail-view top bar — two translucent circular
                    controls, back-chevron left + more right, like the real
                    pass detail screen (not a bare "OK / …" text row). */}
                <div style={{ position: 'absolute', top: 52, left: 0, right: 0, display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 16px' }}>
                  {[('back'), ('more')].map((k) => (
                    <div key={k} style={{ width: 30, height: 30, borderRadius: 15,
                      background: light ? 'rgba(120,120,128,0.16)' : 'rgba(255,255,255,0.18)',
                      backdropFilter: 'blur(8px)', display: 'grid', placeItems: 'center' }}>
                      {k === 'back' ? (
                        <svg width="9" height="15" viewBox="0 0 9 15" aria-hidden="true">
                          <path d="M7.5 1L1.5 7.5L7.5 14" fill="none" stroke={light ? '#007AFF' : '#FFFFFF'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                      ) : (
                        <svg width="16" height="4" viewBox="0 0 16 4" aria-hidden="true">
                          {[2, 8, 14].map((cx) => <circle key={cx} cx={cx} cy="2" r="1.6" fill={light ? '#007AFF' : '#FFFFFF'} />)}
                        </svg>
                      )}
                    </div>
                  ))}
                </div>
                {/* Card surface — full pass width, centred, so the strip runs
                    edge-to-edge INSIDE the phone (a real pass never bleeds
                    past the screen). Width is computed to fit the screen. */}
                <div style={{ position: 'absolute', top: 96, left: 0, right: 0, bottom: 26, overflowY: 'auto', display: 'flex', justifyContent: 'center', padding: '0 14px' }}>
                  <div className="relative" style={{ width: '100%', maxWidth: 268 }}>
                {(() => {
                  // Wallet mode previews the pkpass-FAITHFUL render — the
                  // merchant launches with real Apple Wallet passes, so the
                  // phone frame must show exactly what PassKit will draw
                  // (stamps in the strip, one barcode, text-only fields).
                  // Legacy mode keeps previewing the customer-page component.
                  const CardPreview = brand?.layout_style === 'wallet' ? WalletPassPreview : PremiumLoyaltyCard;
                  return (
                    <CardPreview
                      customer={{
                        name: 'Marie Lefèvre',
                        first_name: 'Marie',
                        tier: 'Gold',
                        barcode_id: 'FT-1DFC4E62',
                        // Sample customer at 60% of one reward cycle so the
                        // owner sees a half-filled card. Visits are EXPRESSED
                        // as raw visits (not stamps), so we multiply by
                        // visits_per_stamp to get the correct underlying count.
                        visits: Math.floor((parseInt(rules.reward_threshold_stamps, 10) || 10) * 0.6) * (Math.max(1, parseInt(rules.visits_per_stamp, 10) || 1)),
                        reward_threshold: parseInt(rules.reward_threshold_stamps, 10) || 10,
                        offers_count: 1,
                        birthday: '12/05',
                      }}
                      tenant={{ name: tenant?.name || tenant?.business_name || 'Mon commerce' }}
                      card={{
                        ...brand,
                        // Merge loyalty rules so the points meter on the preview
                        // reflects the owner's current points-per-visit setting.
                        points_per_visit: parseInt(rules.points_per_visit, 10) || 10,
                        visits_per_stamp: parseInt(rules.visits_per_stamp, 10) || 1,
                      }}
                      width={268}
                      compact
                    />
                  );
                })()}
                {/* Numbered band tags — legacy-layout anchors only. The wallet
                    preview follows pkpass anatomy, not the 3-band editor map. */}
                {brand?.layout_style !== 'wallet' && (
                  <>
                    <span className="absolute -left-1 top-[8%] text-[9px] font-bold uppercase px-1.5 py-0.5 rounded" style={{ background: '#3FA9D9', color: '#FFFFFF', letterSpacing: '0.10em' }}>1</span>
                    <span className="absolute -left-1 top-[40%] text-[9px] font-bold uppercase px-1.5 py-0.5 rounded" style={{ background: '#E8A53B', color: '#FFFFFF', letterSpacing: '0.10em' }}>2</span>
                    <span className="absolute -left-1 top-[74%] text-[9px] font-bold uppercase px-1.5 py-0.5 rounded" style={{ background: '#20714C', color: '#FFFFFF', letterSpacing: '0.10em' }}>3</span>
                  </>
                )}
                  </div>
                </div>
                {/* Home indicator bar */}
                <div aria-hidden="true" style={{ position: 'absolute', bottom: 8, left: '50%', transform: 'translateX(-50%)', width: 110, height: 5, background: light ? '#111111' : 'var(--flc-card, #FFFFFF)', borderRadius: 3, opacity: 0.9 }} />
              </div>
                );
              })()}
            </div>

            {/* (Legacy 3-band legend removed — it described the retired card
                anatomy and its dead knobs, pure noise next to the wallet
                preview.) */}
          </div>
        </div>
      </div>

    </div>
  );
}
