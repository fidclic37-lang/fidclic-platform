/**
 * AuchanCard.jsx — shared loyalty-card layout + editor.
 *
 * Exports:
 *   - DEFAULT_LAYOUT
 *   - FONT_LIST
 *   - substitute(text, ctx)
 *   - AuchanPreview
 *   - AuchanEditor
 *   - LockScreenPushPreview
 */
import React, { useRef, useState } from 'react';
import { QRCodeSVG } from 'qrcode.react';
import AppleWalletFrame from './AppleWalletFrame';
import {
  Bold, Italic, Underline, AlignLeft, AlignCenter, AlignRight,
  Eye, EyeOff, RotateCcw, Hexagon, Upload, X,
} from 'lucide-react';

/* ------------------------------------------------------------------ */
/*  Local image → data URL helper                                     */
/*                                                                    */
/*  Lets the user pick a logo/banner from their device. We load it    */
/*  into a canvas, cap the longest side at maxSide pixels, and emit   */
/*  a JPEG/PNG data URL — small enough to stash directly on the       */
/*  card template document without needing a separate file host.      */
/* ------------------------------------------------------------------ */
function readImageFileAsDataURL(file, { maxSide = 1200, quality = 0.85 } = {}) {
  return new Promise((resolve, reject) => {
    if (!file) return reject(new Error('No file'));
    if (!file.type?.startsWith('image/')) return reject(new Error('Not an image'));
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error || new Error('Read failed'));
    reader.onload = () => {
      const img = new Image();
      img.onerror = () => reject(new Error('Image decode failed'));
      img.onload = () => {
        // Always re-encode through canvas to control output size — even small
        // images get a quality pass. The previous "small images: emit directly"
        // shortcut meant a 3 MB JPEG could pass through unchanged.
        const longest = Math.max(img.width, img.height);
        const scale = longest > maxSide ? maxSide / longest : 1;
        const w = Math.round(img.width * scale);
        const h = Math.round(img.height * scale);
        const canvas = document.createElement('canvas');
        canvas.width = w; canvas.height = h;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(img, 0, 0, w, h);
        // PNG only when the source was PNG AND likely contains transparency.
        // For photos (jpeg / heic / webp) we always emit JPEG — much smaller.
        const mime = file.type === 'image/png' ? 'image/png' : 'image/jpeg';
        try {
          let dataUrl = canvas.toDataURL(mime, quality);
          // Adaptive size cap: if we're still over 1.5 MB, re-encode at lower
          // quality. Keep going down to 0.5 if needed. This guarantees the
          // serverless function never receives a payload that 413's.
          let q = quality;
          while (dataUrl.length > 1_500_000 && q > 0.5 && mime === 'image/jpeg') {
            q -= 0.1;
            dataUrl = canvas.toDataURL(mime, q);
          }
          resolve(dataUrl);
        } catch (e) {
          reject(e);
        }
      };
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
  });
}

/**
 * Small "Upload from device" button paired with the existing URL text input.
 *  - label: ignored (caller keeps their own label)
 *  - onLoaded(dataUrl): called once the image is read + compressed
 *  - onClear: optional callback to clear the current value
 *  - hasValue: whether a current value exists, to show the clear button
 *  - maxSide: pixel cap on the longest edge (default 1200)
 */
function LocalImageUploader({ onLoaded, onClear, hasValue, maxSide = 1200 }) {
  const inputRef = useRef(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const pick = () => { setErr(''); inputRef.current?.click(); };
  const handle = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = '';  // allow re-selecting the same file
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) {
      setErr('File is over 5 MB. Please pick a smaller image.');
      return;
    }
    try {
      setBusy(true);
      const dataUrl = await readImageFileAsDataURL(file, { maxSide });
      onLoaded?.(dataUrl);
    } catch (ex) {
      setErr(ex?.message || 'Upload failed');
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="flex items-center gap-2 mt-1">
      <button
        type="button"
        onClick={pick}
        disabled={busy}
        className="inline-flex items-center gap-1.5 px-2.5 py-1 border border-[#B85C38] text-[#B85C38] rounded text-xs font-semibold hover:bg-[#FEF2F0] disabled:opacity-50"
      >
        <Upload size={12} />
        {busy ? 'Uploading…' : 'Upload from device'}
      </button>
      {hasValue && onClear && (
        <button
          type="button"
          onClick={onClear}
          className="inline-flex items-center gap-1 px-2 py-1 text-xs text-[#8B8680] hover:text-red-600"
          title="Clear image"
        >
          <X size={12} /> Clear
        </button>
      )}
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        onChange={handle}
        className="hidden"
      />
      {err && <span className="text-xs text-red-600">{err}</span>}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Font catalogue                                                    */
/* ------------------------------------------------------------------ */
export const FONT_LIST = [
  'Inter', 'Roboto', 'Open Sans', 'Lato', 'Montserrat', 'Poppins', 'Raleway',
  'Oswald', 'Bebas Neue', 'Playfair Display', 'Merriweather', 'PT Serif',
  'Lora', 'Cormorant Garamond', 'Libre Baskerville', 'Nunito', 'Quicksand',
  'Work Sans', 'Rubik', 'DM Serif Display', 'Abril Fatface', 'Pacifico',
  'Dancing Script', 'Caveat', 'Shadows Into Light', 'Special Elite',
  'Press Start 2P', 'Geist Variable', 'Times New Roman', 'Arial', 'Georgia',
];

const STAMP_STYLES = [
  { id: 'none',    label: 'No stamps' },
  { id: 'hexagon', label: 'Hexagon' },
  { id: 'dots',    label: 'Dots' },
  { id: 'circles', label: 'Circles' },
  { id: 'squares', label: 'Squares' },
  { id: 'stars',   label: 'Stars' },
];

/* ------------------------------------------------------------------ */
/*  Default layout                                                    */
/* ------------------------------------------------------------------ */
const defaultSlot = (over = {}) => ({
  visible: true,
  text: '',
  font: 'Inter',
  size: 14,
  color: '#1C1917',
  bold: false,
  italic: false,
  underline: false,
  align: 'left',
  ...over,
});

// ---------------------------------------------------------------------
// Elegant default palette — "Champagne & Midnight"
//   card_bg     : warm cream (luxury hotel feel)
//   banner_bg   : deep midnight navy (refined, never red)
//   accent      : antique gold (replaces previous terracotta on stamps + meter)
//   ink_deep    : graphite black for text on cream
// Existing merchants' saved layouts are unaffected — only NEW signups (or
// merchants who hit "reset to default") get these refined defaults.
// ---------------------------------------------------------------------
const ELEGANT = {
  cream:        '#FAF5E9',
  cream_deep:   '#F1E9D2',
  midnight:     '#15233D',
  midnight_2:   '#1F2F4F',
  gold:         '#C9A961',
  gold_deep:    '#A88947',
  charcoal:     '#1C1917',
  inkSoft:      '#3A3A3A',
  inkMute:      '#6E6557',
};

export const DEFAULT_LAYOUT = {
  card_bg_color: ELEGANT.cream,
  banner_bg_color: ELEGANT.midnight,
  banner_image_url: '',         // small circular image inside the textual banner
  banner_full_image_url: '',    // full custom banner image — REPLACES the textual banner when set
  banner_height_px: 124,        // a touch taller for breathing room
  banner_object_position: 'center center',  // CSS object-position for the full banner crop
  logo_url: '',
  // stamps — refined antique-gold finish
  stamp_style: 'hexagon',
  stamps_target: 10,
  stamps_color_empty: '#E8DFC9',
  stamps_color_filled: ELEGANT.gold,
  // meter — gold rather than the vivid green
  meter: {
    enabled: true,
    color_empty: '#E8DFC9',
    color_filled: ELEGANT.gold,
    label: '{stamps_earned} / {stamps_target} visits',
    label_color: ELEGANT.inkMute,
    label_size: 10,
  },
  slots: {
    plus_dinfos: defaultSlot({
      text: 'PLUS D’INFOS sur ...',
      size: 10, color: ELEGANT.inkMute, align: 'right', bold: true,
    }),
    banner_eyebrow: defaultSlot({
      text: 'Programme fidélité',
      size: 10, color: ELEGANT.gold, align: 'center', bold: true,
    }),
    banner_subtitle: defaultSlot({
      text: 'Une expérience pensée pour vous',
      size: 11, color: '#E8DFC9', align: 'center',
      font: 'Cormorant Garamond', italic: true,
    }),
    banner_title: defaultSlot({
      text: 'Récompense exclusive',
      size: 26, color: '#FFFFFF', bold: true, align: 'center',
      font: 'Cormorant Garamond',
    }),
    banner_tag: defaultSlot({
      text: 'pour nos membres',
      size: 9, color: ELEGANT.midnight, bold: true, align: 'center',
    }),
    greeting_label: defaultSlot({
      text: 'BIENVENUE', size: 9, color: ELEGANT.gold_deep, bold: true,
    }),
    greeting_name: defaultSlot({
      text: '{first_name}', size: 26, color: ELEGANT.charcoal, bold: true,
      font: 'Cormorant Garamond',
    }),
    points_label: defaultSlot({
      text: 'MES POINTS', size: 9, color: ELEGANT.gold_deep, bold: true, align: 'right',
    }),
    // Points are visit-based integers (e.g. 70 pts for 7 visits at 10 pts/visit).
    // No more "€" suffix — that conflated points with currency.
    points_value: defaultSlot({
      text: '{points} pts', size: 24, color: ELEGANT.charcoal, bold: true, align: 'right',
      font: 'Cormorant Garamond',
    }),
    // New slots
    business_name: defaultSlot({
      text: '{business_name}', size: 12, color: ELEGANT.charcoal, bold: true, align: 'left',
      font: 'Cormorant Garamond',
    }),
    customer_name: defaultSlot({
      text: '{name}', size: 11, color: ELEGANT.inkMute, align: 'left',
    }),
    birthday: defaultSlot({
      text: '🎂 {birthday}', size: 11, color: ELEGANT.inkMute, align: 'right',
    }),
    points: defaultSlot({
      text: '⭐ {points} pts', size: 11, color: ELEGANT.gold_deep, bold: true, align: 'right',
    }),
  },
  push: {
    title: '',
    body: 'Une attention pour vous chez {business_name} — tournez votre carte pour la révéler.',
  },
};

/* ------------------------------------------------------------------ */
/*  Template substitution                                             */
/* ------------------------------------------------------------------ */
export function substitute(text, ctx = {}) {
  if (!text) return '';
  const vars = {
    first_name: ctx.first_name || ctx.name?.split(' ')?.[0] || 'Sophie',
    name: ctx.name || 'Sophie Dupont',
    points: ctx.points ?? '70',
    tier: ctx.tier || 'Bronze',
    birthday: ctx.birthday || '12 Mai',
    business_name: ctx.business_name || 'Mon commerce',
    loyalty_number: ctx.loyalty_number || '049130960',
    amount: ctx.amount ?? ctx.points ?? '70',
    stamps_earned: ctx.stamps_earned ?? 7,
    stamps_target: ctx.stamps_target ?? 10,
  };
  return text.replace(/\{(\w+)\}/g, (_, k) => (vars[k] !== undefined ? String(vars[k]) : `{${k}}`));
}

/* ------------------------------------------------------------------ */
/*  Slot renderer                                                     */
/* ------------------------------------------------------------------ */
function SlotText({ slot, ctx, className = '', style: extraStyle = {} }) {
  if (!slot || slot.visible === false) return null;
  const style = {
    fontFamily: `'${slot.font}', sans-serif`,
    fontSize: `${slot.size}px`,
    color: slot.color,
    fontWeight: slot.bold ? 700 : 400,
    fontStyle: slot.italic ? 'italic' : 'normal',
    textDecoration: slot.underline ? 'underline' : 'none',
    textAlign: slot.align || 'left',
    lineHeight: 1.15,
    ...extraStyle,
  };
  return <div className={className} style={style}>{substitute(slot.text, ctx)}</div>;
}

/* ------------------------------------------------------------------ */
/*  Stamps                                                            */
/* ------------------------------------------------------------------ */
function Stamp({ style, filled, size, colorEmpty, colorFilled }) {
  const color = filled ? colorFilled : colorEmpty;
  switch (style) {
    case 'hexagon':
      return (
        <svg width={size} height={size} viewBox="0 0 100 100">
          <polygon
            points="50,5 93.3,27.5 93.3,72.5 50,95 6.7,72.5 6.7,27.5"
            fill={filled ? color : 'none'}
            stroke={color}
            strokeWidth="6"
          />
        </svg>
      );
    case 'dots':
    case 'circles':
      return (
        <svg width={size} height={size} viewBox="0 0 100 100">
          <circle cx="50" cy="50" r="40"
            fill={filled ? color : 'none'}
            stroke={color}
            strokeWidth={style === 'dots' ? 0 : 6} />
        </svg>
      );
    case 'squares':
      return (
        <svg width={size} height={size} viewBox="0 0 100 100">
          <rect x="10" y="10" width="80" height="80" rx="10"
            fill={filled ? color : 'none'}
            stroke={color}
            strokeWidth="6" />
        </svg>
      );
    case 'stars':
      return (
        <svg width={size} height={size} viewBox="0 0 100 100">
          <polygon
            points="50,8 62,38 94,38 68,58 78,90 50,72 22,90 32,58 6,38 38,38"
            fill={filled ? color : 'none'}
            stroke={color}
            strokeWidth="4"
          />
        </svg>
      );
    default:
      return null;
  }
}

function StampsRow({ layout, ctx }) {
  if (!layout.stamp_style || layout.stamp_style === 'none') return null;
  const target = Math.max(1, Math.min(14, layout.stamps_target || 10));
  const earned = Math.max(0, Math.min(target, Number(ctx.stamps_earned ?? 7)));
  const size = target > 10 ? 22 : target > 8 ? 26 : 30;
  return (
    <div className="px-4 pt-2 pb-1 flex items-center justify-center gap-1.5 flex-wrap">
      {Array.from({ length: target }).map((_, i) => (
        <Stamp
          key={i}
          style={layout.stamp_style}
          filled={i < earned}
          size={size}
          colorEmpty={layout.stamps_color_empty}
          colorFilled={layout.stamps_color_filled}
        />
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Meter                                                             */
/* ------------------------------------------------------------------ */
function MeterBar({ layout, ctx }) {
  const m = layout.meter || {};
  if (!m.enabled) return null;
  const target = Math.max(1, layout.stamps_target || 10);
  const earned = Math.max(0, Math.min(target, Number(ctx.stamps_earned ?? 7)));
  const pct = Math.round((earned / target) * 100);
  const labelText = substitute(m.label || '', { ...ctx, stamps_earned: earned, stamps_target: target });
  return (
    <div className="px-4 pt-1 pb-2">
      <div className="h-2 rounded-full overflow-hidden" style={{ backgroundColor: m.color_empty || '#E5E7EB' }}>
        <div
          className="h-full rounded-full transition-all"
          style={{ width: `${pct}%`, backgroundColor: m.color_filled || '#22C55E' }}
        />
      </div>
      {labelText && (
        <div
          className="text-center mt-1"
          style={{ color: m.label_color || '#6B7280', fontSize: `${m.label_size || 10}px` }}
        >
          {labelText}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Barcode                                                           */
/* ------------------------------------------------------------------ */
function Barcode({ value = '049130960' }) {
  const bars = [];
  let seed = 0;
  for (let i = 0; i < value.length; i++) seed += value.charCodeAt(i);
  for (let i = 0; i < 110; i++) {
    seed = (seed * 9301 + 49297) % 233280;
    bars.push(1 + (seed % 3));
  }
  let x = 0;
  return (
    <svg viewBox="0 0 220 44" width="100%" height="44" preserveAspectRatio="none">
      {bars.map((w, i) => {
        const r = <rect key={i} x={x} y={0} width={w} height={44} fill="#111827" />;
        x += w + 1;
        return r;
      })}
    </svg>
  );
}

/* ------------------------------------------------------------------ */
/*  AuchanPreview — also imported by AppleWalletFrame in the editor below */
/* ------------------------------------------------------------------ */
export function AuchanPreview({ layout = DEFAULT_LAYOUT, ctx = {}, width = 380 }) {
  const L = {
    ...DEFAULT_LAYOUT,
    ...layout,
    meter: { ...DEFAULT_LAYOUT.meter, ...(layout.meter || {}) },
    slots: { ...DEFAULT_LAYOUT.slots, ...(layout.slots || {}) },
  };
  return (
    <div
      className="rounded-[22px] shadow-xl overflow-hidden relative"
      style={{ width: `${width}px`, backgroundColor: L.card_bg_color, fontFamily: "'Inter', sans-serif" }}
    >
      {/* HEADER */}
      <div className="flex items-center justify-between p-4">
        <div className="rounded-md bg-gray-100 flex items-center justify-center overflow-hidden" style={{ width: 78, height: 38 }}>
          {L.logo_url
            ? <img src={L.logo_url} alt="logo" className="w-full h-full object-contain" />
            : <span className="text-[10px] text-gray-400">logo</span>}
        </div>
        <div style={{ maxWidth: '55%' }}>
          <SlotText slot={L.slots.plus_dinfos} ctx={ctx} />
        </div>
      </div>

      {/* PROMO BANNER */}
      {L.banner_full_image_url ? (
        /* Full custom banner — uploaded by the owner. The image is cropped
           to fill a strict height, controlled by `banner_height_px`. The
           visible portion of the image is set via `banner_object_position`,
           letting the owner pick which part of their image shows. */
        <div
          className="mx-3 rounded-lg overflow-hidden"
          style={{
            height: `${L.banner_height_px || 116}px`,
            backgroundColor: L.banner_bg_color,
          }}
        >
          <img
            src={L.banner_full_image_url}
            alt="banner"
            className="w-full h-full"
            style={{
              display: 'block',
              objectFit: 'cover',
              objectPosition: L.banner_object_position || 'center center',
            }}
          />
        </div>
      ) : (
        <div className="mx-3 rounded-lg relative overflow-hidden flex items-center" style={{ backgroundColor: L.banner_bg_color, minHeight: 116 }}>
          <div className="flex-1 px-3 py-2 space-y-1 relative">
            <SlotText slot={L.slots.banner_eyebrow} ctx={ctx} />
            <SlotText slot={L.slots.banner_subtitle} ctx={ctx} />
            <div className="flex items-center justify-center gap-1 mt-1">
              <div className="flex flex-col items-center">
                <SlotText slot={L.slots.banner_title} ctx={ctx} />
                <div className="bg-white rounded-full px-2 py-0.5 -mt-1">
                  <SlotText slot={L.slots.banner_tag} ctx={ctx} />
                </div>
              </div>
            </div>
          </div>
          {L.banner_image_url && (
            <div className="rounded-full bg-white overflow-hidden flex-shrink-0 mr-2 border-2 border-white shadow" style={{ width: 78, height: 78 }}>
              <img src={L.banner_image_url} alt="promo" className="w-full h-full object-cover" />
            </div>
          )}
        </div>
      )}

      {/* GREETING + POINTS */}
      <div className="flex justify-between items-end px-4 pt-3 pb-1">
        <div>
          <SlotText slot={L.slots.greeting_label} ctx={ctx} />
          <SlotText slot={L.slots.greeting_name} ctx={ctx} />
        </div>
        <div>
          <SlotText slot={L.slots.points_label} ctx={ctx} />
          <SlotText slot={L.slots.points_value} ctx={ctx} />
        </div>
      </div>

      {/* EXTRA INFO ROW */}
      <div className="flex justify-between items-center gap-2 px-4 pt-1 pb-2">
        <div className="flex flex-col flex-1 min-w-0">
          <SlotText slot={L.slots.business_name} ctx={ctx} />
          <SlotText slot={L.slots.customer_name} ctx={ctx} />
        </div>
        <div className="flex flex-col items-end flex-1 min-w-0">
          <SlotText slot={L.slots.birthday} ctx={ctx} />
          <SlotText slot={L.slots.points} ctx={ctx} />
        </div>
      </div>

      {/* STAMPS */}
      <StampsRow layout={L} ctx={ctx} />

      {/* METER */}
      <MeterBar layout={L} ctx={ctx} />

      {/* QR CODE
          Customer-facing scan code at the bottom of the card. The old
          Code 128 barcode used to live here too — removed for now per
          owner spec; modern POS phones/tablets read QR fine and the
          one-code design is much cleaner visually. If a 1D barcode is
          ever needed again, render <Barcode/> alongside this block. */}
      <div className="px-6 py-3 pb-5 flex justify-center">
        <QRCodeSVG
          value={substitute('{loyalty_number}', ctx) || 'FT-PREVIEW'}
          size={120}
          level="M"
          marginSize={4}
          bgColor={L.card_bg_color}
          fgColor={L.card_text_color || '#0F0F0F'}
        />
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  LockScreenPushPreview                                             */
/* ------------------------------------------------------------------ */
export function LockScreenPushPreview({ title, body, businessName = 'Mon commerce' }) {
  const t = title || businessName;
  return (
    <div className="relative mx-auto" style={{ width: 260 }}>
      <div className="rounded-[40px] p-3 shadow-2xl" style={{ background: 'linear-gradient(180deg,#1e3a8a 0%,#0f172a 100%)', minHeight: 480 }}>
        <div className="text-center text-white pt-8">
          <div className="text-xs opacity-80">jeudi 30 mars</div>
          <div className="text-6xl font-light tracking-tight">11:52</div>
        </div>
        <div className="mt-64">
          <div className="bg-white/15 backdrop-blur rounded-2xl p-3 text-white text-[11px] leading-tight">
            <div className="flex items-center justify-between">
              <div className="font-semibold">{t}</div>
              <div className="opacity-70">now</div>
            </div>
            <div className="mt-1 whitespace-pre-wrap break-words">{body || 'Your push body…'}</div>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Slot editor                                                       */
/* ------------------------------------------------------------------ */
const SLOT_LABELS = {
  plus_dinfos:     'Top-right link (PLUS D’INFOS)',
  banner_eyebrow:  'Banner · date / eyebrow',
  banner_subtitle: 'Banner · subtitle',
  banner_title:    'Banner · main headline',
  banner_tag:      'Banner · highlight tag',
  greeting_label:  'Greeting label (BONJOUR)',
  greeting_name:   'Customer first name (greeting)',
  points_label:    'Points label (MA CAGNOTTE)',
  points_value:    'Points value (headline)',
  business_name:   'Business name',
  customer_name:   'Customer full name',
  birthday:        'Customer birthday',
  points:          'Points (secondary)',
};

function SlotEditor({ slotKey, slot, onChange }) {
  const update = (patch) => onChange({ ...slot, ...patch });
  const labelCls = 'text-[11px] font-bold text-gray-500 uppercase tracking-wider';
  const btn = (active) =>
    `p-1.5 rounded border ${active ? 'bg-[#B85C38] text-white border-[#B85C38]' : 'bg-white border-gray-200 text-gray-600'}`;

  return (
    <div className="rounded-lg border border-gray-200 p-3 bg-white space-y-2">
      <div className="flex items-center justify-between">
        <div className="text-sm font-semibold text-[#1C1917]">{SLOT_LABELS[slotKey] || slotKey}</div>
        <button
          type="button"
          onClick={() => update({ visible: !slot.visible })}
          className={`text-xs flex items-center gap-1 ${slot.visible ? 'text-green-600' : 'text-gray-400'}`}
        >
          {slot.visible ? <Eye size={12} /> : <EyeOff size={12} />}
          {slot.visible ? 'visible' : 'hidden'}
        </button>
      </div>
      <input
        type="text"
        value={slot.text}
        onChange={(e) => update({ text: e.target.value })}
        placeholder="Text — use {first_name}, {name}, {points}, {birthday}, {business_name}"
        className="w-full text-sm border border-gray-200 rounded px-2 py-1.5"
      />
      <div className="grid grid-cols-2 gap-2">
        <div>
          <div className={labelCls}>Font</div>
          <select value={slot.font} onChange={(e) => update({ font: e.target.value })} className="w-full text-sm border border-gray-200 rounded px-2 py-1">
            {FONT_LIST.map((f) => (
              <option key={f} value={f} style={{ fontFamily: `'${f}', sans-serif` }}>{f}</option>
            ))}
          </select>
        </div>
        <div>
          <div className={labelCls}>Size · {slot.size}px</div>
          <input type="range" min="8" max="48" value={slot.size} onChange={(e) => update({ size: parseInt(e.target.value, 10) })} className="w-full" />
        </div>
      </div>
      <div className="flex items-center gap-2">
        <div>
          <div className={labelCls}>Color</div>
          <input type="color" value={slot.color} onChange={(e) => update({ color: e.target.value })} className="w-9 h-8 border border-gray-200 rounded cursor-pointer" />
        </div>
        <div className="flex items-center gap-1">
          <button type="button" className={btn(slot.bold)} onClick={() => update({ bold: !slot.bold })}><Bold size={12} /></button>
          <button type="button" className={btn(slot.italic)} onClick={() => update({ italic: !slot.italic })}><Italic size={12} /></button>
          <button type="button" className={btn(slot.underline)} onClick={() => update({ underline: !slot.underline })}><Underline size={12} /></button>
        </div>
        <div className="flex items-center gap-1 ml-auto">
          <button type="button" className={btn(slot.align === 'left')} onClick={() => update({ align: 'left' })}><AlignLeft size={12} /></button>
          <button type="button" className={btn(slot.align === 'center')} onClick={() => update({ align: 'center' })}><AlignCenter size={12} /></button>
          <button type="button" className={btn(slot.align === 'right')} onClick={() => update({ align: 'right' })}><AlignRight size={12} /></button>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  AuchanEditor                                                      */
/* ------------------------------------------------------------------ */
export function AuchanEditor({ layout, onChange, ctx = {}, businessName }) {
  const [activeTab, setActiveTab] = useState('card');
  const L = {
    ...DEFAULT_LAYOUT,
    ...layout,
    meter: { ...DEFAULT_LAYOUT.meter, ...(layout?.meter || {}) },
    slots: { ...DEFAULT_LAYOUT.slots, ...(layout?.slots || {}) },
    push: { ...DEFAULT_LAYOUT.push, ...(layout?.push || {}) },
  };

  const setSlot  = (key, nextSlot) => onChange({ ...L, slots: { ...L.slots, [key]: nextSlot } });
  const setField = (key, val) => onChange({ ...L, [key]: val });
  const setPush  = (key, val) => onChange({ ...L, push: { ...L.push, [key]: val } });
  const setMeter = (patch)      => onChange({ ...L, meter: { ...L.meter, ...patch } });

  const resetSlot = (key) => setSlot(key, DEFAULT_LAYOUT.slots[key]);

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[1fr,460px] gap-6">
      {/* ---------- Controls ---------- */}
      <div className="space-y-4">
        <div className="flex gap-2 border-b border-gray-200 flex-wrap">
          {[
            ['card',   'Card elements'],
            ['stamps', 'Stamps & meter'],
            ['style',  'Colors & images'],
            ['push',   'Lock-screen push'],
          ].map(([k, label]) => (
            <button
              key={k}
              onClick={() => setActiveTab(k)}
              className={`px-3 py-2 text-sm font-medium border-b-2 -mb-px ${activeTab === k ? 'border-[#B85C38] text-[#B85C38]' : 'border-transparent text-gray-500 hover:text-gray-700'}`}
            >
              {label}
            </button>
          ))}
        </div>

        {activeTab === 'card' && (
          <div className="space-y-3">
            <p className="text-xs text-gray-500">
              Layout is fixed (logo · banner · greeting + points · extra info · stamps · meter · barcode). Every text slot is fully editable.
            </p>
            {Object.keys(SLOT_LABELS).map((key) => (
              <div key={key} className="relative">
                <SlotEditor slotKey={key} slot={L.slots[key]} onChange={(s) => setSlot(key, s)} />
                <button
                  type="button"
                  onClick={() => resetSlot(key)}
                  className="absolute -top-1 -right-1 bg-white border border-gray-200 rounded-full p-1 text-gray-400 hover:text-[#B85C38]"
                  title="Reset to default"
                >
                  <RotateCcw size={11} />
                </button>
              </div>
            ))}
          </div>
        )}

        {activeTab === 'stamps' && (
          <div className="space-y-4">
            {/* Stamps */}
            <div className="rounded-lg border border-gray-200 p-3 bg-white space-y-3">
              <div className="flex items-center gap-2 text-sm font-semibold text-[#1C1917]">
                <Hexagon size={14} /> Stamps
              </div>
              <div>
                <label className="text-xs font-bold text-gray-500 uppercase">Style</label>
                <div className="grid grid-cols-3 gap-1 mt-1">
                  {STAMP_STYLES.map((s) => (
                    <button
                      key={s.id}
                      type="button"
                      onClick={() => setField('stamp_style', s.id)}
                      className={`px-2 py-1.5 text-xs rounded border ${L.stamp_style === s.id ? 'bg-[#B85C38] text-white border-[#B85C38]' : 'bg-white text-gray-700 border-gray-200'}`}
                    >
                      {s.label}
                    </button>
                  ))}
                </div>
              </div>
              <div className="grid grid-cols-3 gap-2">
                <div>
                  <label className="text-xs font-bold text-gray-500 uppercase">Target · {L.stamps_target}</label>
                  <input type="range" min="3" max="14" value={L.stamps_target} onChange={(e) => setField('stamps_target', parseInt(e.target.value, 10))} className="w-full" />
                </div>
                <div>
                  <label className="text-xs font-bold text-gray-500 uppercase">Empty color</label>
                  <input type="color" value={L.stamps_color_empty} onChange={(e) => setField('stamps_color_empty', e.target.value)} className="w-full h-9 border rounded" />
                </div>
                <div>
                  <label className="text-xs font-bold text-gray-500 uppercase">Filled color</label>
                  <input type="color" value={L.stamps_color_filled} onChange={(e) => setField('stamps_color_filled', e.target.value)} className="w-full h-9 border rounded" />
                </div>
              </div>
            </div>

            {/* Meter */}
            <div className="rounded-lg border border-gray-200 p-3 bg-white space-y-3">
              <div className="flex items-center justify-between">
                <div className="text-sm font-semibold text-[#1C1917]">Points meter</div>
                <button
                  type="button"
                  onClick={() => setMeter({ enabled: !L.meter.enabled })}
                  className={`text-xs flex items-center gap-1 ${L.meter.enabled ? 'text-green-600' : 'text-gray-400'}`}
                >
                  {L.meter.enabled ? <Eye size={12} /> : <EyeOff size={12} />}
                  {L.meter.enabled ? 'visible' : 'hidden'}
                </button>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-xs font-bold text-gray-500 uppercase">Empty color</label>
                  <input type="color" value={L.meter.color_empty} onChange={(e) => setMeter({ color_empty: e.target.value })} className="w-full h-9 border rounded" />
                </div>
                <div>
                  <label className="text-xs font-bold text-gray-500 uppercase">Filled color</label>
                  <input type="color" value={L.meter.color_filled} onChange={(e) => setMeter({ color_filled: e.target.value })} className="w-full h-9 border rounded" />
                </div>
              </div>
              <div>
                <label className="text-xs font-bold text-gray-500 uppercase">Label (use {'{stamps_earned}'} / {'{stamps_target}'})</label>
                <input
                  type="text"
                  value={L.meter.label}
                  onChange={(e) => setMeter({ label: e.target.value })}
                  className="w-full border rounded px-2 py-1.5 text-sm"
                />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-xs font-bold text-gray-500 uppercase">Label color</label>
                  <input type="color" value={L.meter.label_color} onChange={(e) => setMeter({ label_color: e.target.value })} className="w-full h-9 border rounded" />
                </div>
                <div>
                  <label className="text-xs font-bold text-gray-500 uppercase">Label size · {L.meter.label_size}px</label>
                  <input type="range" min="8" max="20" value={L.meter.label_size} onChange={(e) => setMeter({ label_size: parseInt(e.target.value, 10) })} className="w-full" />
                </div>
              </div>
            </div>
          </div>
        )}

        {activeTab === 'style' && (
          <div className="grid grid-cols-2 gap-3">
            <div className="col-span-2 grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-bold text-gray-500 uppercase">Card background</label>
                <input type="color" value={L.card_bg_color} onChange={(e) => setField('card_bg_color', e.target.value)} className="w-full h-10 border rounded" />
              </div>
              <div>
                <label className="text-xs font-bold text-gray-500 uppercase">Banner background</label>
                <input type="color" value={L.banner_bg_color} onChange={(e) => setField('banner_bg_color', e.target.value)} className="w-full h-10 border rounded" />
              </div>
            </div>
            <div className="col-span-2">
              <label className="text-xs font-bold text-gray-500 uppercase">Logo</label>
              <div className="flex items-start gap-3">
                {L.logo_url && (
                  <div className="shrink-0 w-14 h-14 rounded border border-gray-200 bg-gray-50 flex items-center justify-center overflow-hidden">
                    <img src={L.logo_url} alt="logo preview" className="max-w-full max-h-full object-contain" />
                  </div>
                )}
                <div className="flex-1 min-w-0">
                  <input
                    type="text"
                    value={L.logo_url}
                    onChange={(e) => setField('logo_url', e.target.value)}
                    placeholder="Paste a URL (https://…/logo.png) or upload below"
                    className="w-full border rounded px-2 py-1.5 text-sm"
                  />
                  <LocalImageUploader
                    onLoaded={(dataUrl) => setField('logo_url', dataUrl)}
                    onClear={() => setField('logo_url', '')}
                    hasValue={Boolean(L.logo_url)}
                    maxSide={600}
                  />
                </div>
              </div>
            </div>
            {/* Full custom banner — replaces the entire textual banner.
                The default "5€ offerts" banner is just an example design;
                most owners will want to upload their own promo artwork. */}
            <div className="col-span-2 p-4 rounded-lg bg-[#FEF9E7] border border-[#E3A869]/40">
              <label className="text-xs font-bold text-[#7B3F00] uppercase tracking-wider">
                Full custom banner — your own design
              </label>
              <p className="text-xs text-[#7B3F00]/80 mt-1 mb-3">
                Upload a complete banner image to replace the default "5€ offerts" design above
                with your own artwork — seasonal promos, agency-designed graphics, anything.
                Recommended size: ~880 × 280 px.
              </p>
              <div className="flex items-start gap-3">
                {L.banner_full_image_url && (
                  <div className="shrink-0 w-32 h-12 rounded border border-[#E3A869]/40 bg-white overflow-hidden">
                    <img src={L.banner_full_image_url} alt="full banner preview" className="w-full h-full object-cover" />
                  </div>
                )}
                <div className="flex-1 min-w-0">
                  <input
                    type="text"
                    value={L.banner_full_image_url || ''}
                    onChange={(e) => setField('banner_full_image_url', e.target.value)}
                    placeholder="Paste a URL or upload an image below"
                    className="w-full border rounded px-2 py-1.5 text-sm"
                  />
                  <LocalImageUploader
                    onLoaded={(dataUrl) => setField('banner_full_image_url', dataUrl)}
                    onClear={() => setField('banner_full_image_url', '')}
                    hasValue={Boolean(L.banner_full_image_url)}
                    maxSide={1100}
                  />
                  {L.banner_full_image_url && (
                    <p className="text-[11px] text-[#7B3F00] mt-2 font-semibold">
                      ✓ Custom banner active — the textual banner below is hidden.
                    </p>
                  )}
                </div>
              </div>

              {/* Size + crop controls — only meaningful when a full banner is set */}
              {L.banner_full_image_url && (
                <div className="mt-4 pt-4 border-t border-[#E3A869]/40 space-y-3">
                  {/* Banner height presets + custom slider */}
                  <div>
                    <label className="text-xs font-bold text-[#7B3F00] uppercase tracking-wider">
                      Banner size · {L.banner_height_px || 116}px tall
                    </label>
                    <div className="flex items-center gap-2 mt-2">
                      {[
                        { label: 'S', val: 80, hint: 'Compact strip' },
                        { label: 'M', val: 116, hint: 'Default' },
                        { label: 'L', val: 160, hint: 'Tall' },
                        { label: 'XL', val: 220, hint: 'Hero' },
                      ].map((opt) => {
                        const active = (L.banner_height_px || 116) === opt.val;
                        return (
                          <button
                            key={opt.val}
                            type="button"
                            onClick={() => setField('banner_height_px', opt.val)}
                            title={opt.hint}
                            className={`px-3 py-1.5 text-xs font-bold rounded border transition ${
                              active
                                ? 'bg-[#B85C38] text-white border-[#B85C38]'
                                : 'bg-white text-[#7B3F00] border-[#E3A869]/40 hover:bg-[#FEF9E7]'
                            }`}
                          >
                            {opt.label} <span className="font-normal opacity-70">{opt.val}px</span>
                          </button>
                        );
                      })}
                      <input
                        type="range"
                        min={60}
                        max={280}
                        step={4}
                        value={L.banner_height_px || 116}
                        onChange={(e) => setField('banner_height_px', parseInt(e.target.value, 10))}
                        className="flex-1 ml-2 accent-[#B85C38]"
                      />
                    </div>
                  </div>

                  {/* Crop / object-position 3x3 grid — pick which part of the
                      image shows when the banner is shorter than the source. */}
                  <div>
                    <label className="text-xs font-bold text-[#7B3F00] uppercase tracking-wider">
                      Crop position · {L.banner_object_position || 'center center'}
                    </label>
                    <p className="text-[11px] text-[#7B3F00]/80 mt-0.5 mb-2">
                      Pick which part of your image stays visible when it's cropped to fit.
                    </p>
                    <div className="grid grid-cols-3 gap-1 w-32">
                      {[
                        ['left top', 'center top', 'right top'],
                        ['left center', 'center center', 'right center'],
                        ['left bottom', 'center bottom', 'right bottom'],
                      ].flat().map((pos) => {
                        const active = (L.banner_object_position || 'center center') === pos;
                        return (
                          <button
                            key={pos}
                            type="button"
                            onClick={() => setField('banner_object_position', pos)}
                            title={pos}
                            className={`aspect-square rounded border-2 transition ${
                              active
                                ? 'bg-[#B85C38] border-[#B85C38]'
                                : 'bg-white border-[#E3A869]/40 hover:border-[#B85C38]'
                            }`}
                          >
                            <span className={`block w-full h-full ${active ? 'bg-white/30' : ''}`} />
                          </button>
                        );
                      })}
                    </div>
                  </div>
                </div>
              )}
            </div>

            <div className="col-span-2">
              <label className="text-xs font-bold text-gray-500 uppercase">
                Small inline banner image (optional)
              </label>
              <p className="text-[11px] text-gray-500 mt-0.5 mb-1">
                Used as a small circular accent inside the default textual banner.
                Ignored when a full custom banner is uploaded above.
              </p>
              <div className="flex items-start gap-3">
                {L.banner_image_url && (
                  <div className="shrink-0 w-20 h-14 rounded border border-gray-200 bg-gray-50 overflow-hidden">
                    <img src={L.banner_image_url} alt="banner preview" className="w-full h-full object-cover" />
                  </div>
                )}
                <div className="flex-1 min-w-0">
                  <input
                    type="text"
                    value={L.banner_image_url}
                    onChange={(e) => setField('banner_image_url', e.target.value)}
                    placeholder="Paste a URL (https://…/promo.jpg) or upload below"
                    className="w-full border rounded px-2 py-1.5 text-sm"
                  />
                  <LocalImageUploader
                    onLoaded={(dataUrl) => setField('banner_image_url', dataUrl)}
                    onClear={() => setField('banner_image_url', '')}
                    hasValue={Boolean(L.banner_image_url)}
                    maxSide={1400}
                  />
                </div>
              </div>
            </div>
          </div>
        )}

        {activeTab === 'push' && (
          <div className="space-y-3">
            <p className="text-xs text-gray-500">Default push text — customers see it on their lock screen, tapping opens their wallet card.</p>
            <div>
              <label className="text-xs font-bold text-gray-500 uppercase">Title (defaults to business name)</label>
              <input type="text" value={L.push.title} onChange={(e) => setPush('title', e.target.value)} placeholder={businessName || 'Business name'} className="w-full border rounded px-2 py-1.5 text-sm" />
            </div>
            <div>
              <label className="text-xs font-bold text-gray-500 uppercase">Body</label>
              <textarea rows={4} value={L.push.body} onChange={(e) => setPush('body', e.target.value)} className="w-full border rounded px-2 py-1.5 text-sm" />
            </div>
            <div className="flex justify-center pt-2">
              <LockScreenPushPreview title={L.push.title} body={L.push.body} businessName={businessName} />
            </div>
          </div>
        )}
      </div>

      {/* ---------- Live preview (rendered inside an Apple-Wallet phone frame
                    so the merchant sees exactly what the customer sees) ---------- */}
      <div className="lg:sticky lg:top-4 self-start">
        <div className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-2 text-center">
          Live preview · Apple Wallet
        </div>
        <div className="rounded-xl p-4 flex justify-center"
          style={{ background: 'linear-gradient(180deg, #F3EFE7 0%, #E7E5E4 100%)' }}>
          <AppleWalletFrame width={420}>
            <AuchanPreview layout={L} ctx={ctx} width={360} />
          </AppleWalletFrame>
        </div>
      </div>
    </div>
  );
}

export default AuchanPreview;
