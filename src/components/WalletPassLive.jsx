import React, { useEffect, useRef, useState } from 'react';
import { ChevronDown } from 'lucide-react';
import api, { ownerAPI } from '../lib/api';
import BarcodeSvg, { SQUARE_CODES } from './wallet/BarcodeSvg';
import { ActionTile } from './wallet/walletLook';

/**
 * WalletPassLive — the Apple Wallet pass as the SERVER builds it.
 *
 * WalletPassPreview re-implemented the pass in JavaScript and drifted from
 * the real one (user, 2026-10-04: different fields, different content). This
 * component draws what POST /api/owner/wallet/preview returns — the very
 * pass.json fields, strip image and logo build_pkpass() ships, for a sample
 * customer, with the designer's unsaved fields applied. Only the frame (sizes,
 * fonts, spacing) is drawn here, after Apple's storeCard layout.
 *
 * Props: card (the designer's current fields), width (px for a 375-pt pass).
 * barcodeId: a real customer's card instead (GET /api/card/{id}/pass-view —
 * the owner's current design with their own name and progress, 2026-10-13);
 * fallback: what to show if that cannot be read.
 *
 * iOS 27 (WWDC26): when the pass carries the « poster » style, the preview
 * opens on it — full-bleed background, primary logo, header, the member's
 * name in bold, the progress, the footer, the tiles under the pass — with a
 * switch to see the card iOS 26 and earlier show instead.
 */
function Field({ f, s, align = 'left', big = false, labelColor, color }) {
  const val = f.value === undefined || f.value === null ? '' : String(f.value);
  return (
    <div className="min-w-0" style={{ textAlign: align }}>
      <div className="truncate uppercase" style={{ fontSize: 11 * s, letterSpacing: 0.2 * s, color: labelColor, fontWeight: 600 }}>{f.label}</div>
      <div className="truncate" style={{ fontSize: (big ? 36 : 20) * s, lineHeight: 1.15, color, fontWeight: big ? 300 : 400 }}>{val}</div>
    </div>
  );
}

function Row({ fields, s, labelColor, color }) {
  if (!fields.length) return null;
  return (
    <div className="flex justify-between" style={{ gap: 12 * s, padding: `${10 * s}px ${16 * s}px 0` }}>
      {fields.map((f, i) => (
        <Field key={f.key} f={f} s={s} labelColor={labelColor} color={color}
               align={fields.length > 1 && i === fields.length - 1 ? 'right' : 'left'} />
      ))}
    </div>
  );
}

function PosterPass({ p, s, width, bc, colors = {} }) {
  // What Wallet (and Pass Designer) draw for iOS 27 « Poster Generic »: the
  // artwork full-bleed, a frosted band of its own colours at the foot where
  // the fields sit, the barcode straddling the two, the logo tile top-left.
  const h = width / 0.713;
  const header = (p.headerFields || [])[0];
  const fields = p.primaryFields || [];
  const footer = (p.footerFields || [])[0];
  const fg = colors.foregroundColor || 'rgb(255,255,255)';
  const lab = colors.labelColor || fg;
  const mono = 'ui-monospace, "SF Mono", Menlo, Consolas, monospace';
  const wide = !SQUARE_CODES.has(bc.format || 'PKBarcodeFormatQR');
  const [title, ...rest] = fields;
  const titleBold = title && !title.label;
  return (
    <div>
      <div className="relative overflow-hidden" style={{ width, height: h, borderRadius: 14 * s, color: fg, background: '#1C1D22',
        boxShadow: '0 18px 40px -22px rgba(0,0,0,.55)',
        fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", Arial, sans-serif' }}>
        {p.background && <img src={p.background} alt="" className="absolute inset-0 h-full w-full object-cover object-top" />}
        {/* the system material Wallet lays under the fields */}
        <div className="absolute inset-x-0 bottom-0" style={{ height: '24%', backdropFilter: 'blur(26px) saturate(1.6)',
          WebkitBackdropFilter: 'blur(26px) saturate(1.6)', background: 'linear-gradient(to bottom, rgba(255,255,255,.08), rgba(0,0,0,.22))' }} />
        <div className="absolute inset-x-0 top-0 flex items-start justify-between" style={{ padding: `${10 * s}px ${12 * s}px` }}>
          {p.logo ? <img src={p.logo} alt="" style={{ width: width * 0.105, height: width * 0.105, objectFit: 'cover', borderRadius: 2 * s }} /> : <span />}
          {header && (
            <div className="text-right">
              <div className="uppercase" style={{ fontSize: 11 * s, fontWeight: 700, color: lab }}>{header.label}</div>
              <div style={{ fontSize: 12.5 * s, fontFamily: mono, marginTop: 2 * s }}>{String(header.value)}</div>
            </div>
          )}
        </div>
        <div className="absolute inset-x-0 flex justify-center" style={{ top: wide ? '61%' : '44%' }}>
          <div className="flex flex-col items-center bg-white" style={{ borderRadius: 7 * s, padding: `${8 * s}px ${12 * s}px`,
            width: wide ? width * 0.77 : undefined }}>
            {wide
              ? <BarcodeSvg format={bc.format} message={bc.message} width={width * 0.68} height={58 * s} />
              : <BarcodeSvg format={bc.format} message={bc.message} width={100 * s} height={100 * s} />}
          </div>
        </div>
        <div className="absolute inset-x-0 bottom-0" style={{ padding: `0 ${12 * s}px ${12 * s}px` }}>
          <div className="flex items-end justify-between" style={{ gap: 10 * s }}>
            {title && (
              <div className="min-w-0">
                {!titleBold && <div style={{ fontSize: 10.5 * s, fontFamily: mono, color: lab }}>{title.label}</div>}
                <div className="truncate" style={titleBold
                  ? { fontSize: 19 * s, fontWeight: 700, lineHeight: 1.15 }
                  : { fontSize: 13 * s, fontFamily: mono }}>{String(title.value)}</div>
              </div>
            )}
            {rest.length > 0 && (
              <div className="flex shrink-0 text-right" style={{ gap: 12 * s }}>
                {rest.slice(0, 3).map((f) => (
                  <div key={f.key} className="min-w-0">
                    {f.label && <div style={{ fontSize: 10.5 * s, color: lab, fontWeight: 600 }}>{f.label}</div>}
                    <div className="truncate" style={{ fontSize: 13 * s, fontFamily: mono, maxWidth: 130 * s }}>{String(f.value)}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
          {footer && <div className="truncate uppercase" style={{ fontSize: 10 * s, fontFamily: mono, marginTop: 14 * s }}>{footer.value}</div>}
        </div>
      </div>
      {(p.actions || []).length > 0 && (
        <div className="mt-2 grid grid-cols-2" style={{ gap: 8 * s }}>
          {p.actions.map((a) => <ActionTile key={a.type} type={a.type} label={a.label} s={s} />)}
        </div>
      )}
    </div>
  );
}

export default function WalletPassLive({ card = {}, width = 292, visits = 3, barcodeId = null, fallback = null, onFail }) {
  const [pass, setPass] = useState(null);
  const [error, setError] = useState(false);
  const [back, setBack] = useState(false);
  const [classic, setClassic] = useState(false);     // iOS 26 view of a poster pass
  const seq = useRef(0);
  const key = JSON.stringify(card);

  useEffect(() => {
    const my = ++seq.current;
    const load = () => (barcodeId ? api.get(`/card/${barcodeId}/pass-view`) : ownerAPI.walletPreview({ card, visits }));
    const timer = setTimeout(() => {
      load()
        .then((r) => { if (my === seq.current) { setPass(r.data); setError(false); } })
        // onFail: the page reads /card/<id> for its own drawing of the card
        // only then — one request fewer on the signup's critical path
        .catch(() => { if (my === seq.current) { setError(true); onFail?.(); } });
    }, barcodeId ? 0 : 800);         // after typing stops: one preview, not one per keystroke
    return () => clearTimeout(timer);
  }, [key, visits, barcodeId]); // eslint-disable-line react-hooks/exhaustive-deps

  const s = width / 375;
  if (!pass && error && fallback) return fallback;
  if (!pass) {
    return (
      <div className="flex items-center justify-center rounded-xl bg-[#1C1D22] text-[12px] text-white/70"
           style={{ width, height: width * 1.3 }}>
        {error ? 'Aperçu indisponible — réessayez.' : 'Chargement de l’aperçu…'}
      </div>
    );
  }
  const c = pass.colors || {};
  const bg = c.backgroundColor || 'rgb(28,29,34)';
  const fg = c.foregroundColor || 'rgb(255,255,255)';
  const lab = c.labelColor || fg;
  const strip = !!pass.strip;
  const front = [...(pass.secondaryFields || []), ...(pass.auxiliaryFields || [])];
  const bc = pass.barcode || {};
  const linear = !SQUARE_CODES.has(bc.format || 'PKBarcodeFormatQR');
  const poster = pass.poster && !classic;
  const osSwitch = pass.poster && (
    <div className="mb-2 flex justify-center gap-1 text-[11px] font-semibold">
      {[['iOS 27', false], ['iOS 26 et avant', true]].map(([label, v]) => (
        <button key={label} type="button" onClick={() => setClassic(v)}
                className={`rounded-full px-2.5 py-1 ${classic === v ? 'bg-[#2F6BFF] text-white' : 'bg-[#EEF3FB] text-[#475569]'}`}>
          {label}
        </button>
      ))}
    </div>
  );
  if (poster) {
    return (
      <div translate="no" style={{ width }}>
        {osSwitch}
        <PosterPass p={pass.poster} s={s} width={width} bc={bc} colors={pass.colors} />
        {!barcodeId && (                       /* a customer's own card is no « exemple » */
          <p className="mt-1.5 text-center text-[11px] text-[#94A3B8]">
            Exemple : {pass.sample?.name}, {pass.sample?.visits} visites · nouvelle carte iOS 27
          </p>
        )}
      </div>
    );
  }

  return (
    // translate="no": a browser translation turned the sample « Marie » into
    // « Married » — the pass itself is never translated.
    <div translate="no" style={{ width }}>
      {osSwitch}
      <div className="overflow-hidden" style={{ background: bg, color: fg, borderRadius: 12 * s,
        boxShadow: '0 18px 40px -22px rgba(0,0,0,.55)', fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", Arial, sans-serif' }}>
        {/* header: logo · logoText · header field */}
        <div className="flex items-center" style={{ gap: 8 * s, padding: `${10 * s}px ${16 * s}px`, minHeight: 66 * s }}>
          {pass.logo && <img src={pass.logo} alt="" style={{ height: 50 * s, width: pass.logo_width * s, objectFit: 'contain' }} />}
          <div className="min-w-0 flex-1 truncate" style={{ fontSize: 17 * s, fontWeight: 600 }}>{pass.logoText}</div>
          {(pass.headerFields || []).map((f) => (
            <div key={f.key} className="shrink-0 text-right">
              <div className="uppercase" style={{ fontSize: 11 * s, color: lab, fontWeight: 600 }}>{f.label}</div>
              <div style={{ fontSize: 20 * s, lineHeight: 1.1 }}>{String(f.value)}</div>
            </div>
          ))}
        </div>
        {/* strip: the real strip.png, meter included */}
        {strip && <img src={pass.strip} alt="" style={{ width: '100%', aspectRatio: '375 / 144', display: 'block' }} />}
        {!strip && (pass.primaryFields || []).length > 0 && (
          <div style={{ padding: `${4 * s}px ${16 * s}px 0` }}>
            {pass.primaryFields.map((f) => <Field key={f.key} f={f} s={s} big labelColor={lab} color={fg} />)}
          </div>
        )}
        <Row fields={front} s={s} labelColor={lab} color={fg} />
        {/* barcode: one, white block, alt text under it */}
        <div className="flex justify-center" style={{ padding: `${26 * s}px 0 ${18 * s}px` }}>
          <div className="flex flex-col items-center bg-white" style={{ borderRadius: 6 * s, padding: `${10 * s}px ${12 * s}px ${6 * s}px` }}>
            {linear
              ? <BarcodeSvg format={bc.format} message={bc.message} width={width * 0.74} height={56 * s} />
              : <BarcodeSvg format={bc.format} message={bc.message} width={140 * s} height={140 * s} />}
            {bc.altText && <div style={{ fontSize: 13 * s, color: '#111', marginTop: 4 * s }}>{bc.altText}</div>}
          </div>
        </div>
      </div>

      {/* the back of the pass (the « … » button in Wallet) */}
      <button type="button" onClick={() => setBack((b) => !b)}
              className="mt-2 flex w-full items-center justify-center gap-1 text-[11.5px] font-semibold text-[#2F6BFF]">
        Au dos de la carte <ChevronDown size={14} className={back ? 'rotate-180 transition' : 'transition'} />
      </button>
      {back && (
        <dl className="mt-1 space-y-2 rounded-xl border border-[#E6EEFB] bg-white p-3 text-left text-[12px]">
          {(pass.backFields || []).map((f) => (
            <div key={f.key}>
              <dt className="font-semibold text-[#0B1C3F]">{f.label}</dt>
              <dd className="break-words text-[#475569]">{String(f.value)}</dd>
            </div>
          ))}
        </dl>
      )}
      {!barcodeId && (
        <p className="mt-1.5 text-center text-[11px] text-[#94A3B8]">
          Exemple : {pass.sample?.name}, {pass.sample?.visits} visites
        </p>
      )}
    </div>
  );
}
