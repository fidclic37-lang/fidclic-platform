import React, { useEffect, useRef, useState } from 'react';
import { QRCodeSVG } from 'qrcode.react';
import { ChevronDown } from 'lucide-react';
import Code128Barcode from './Code128Barcode';
import { ownerAPI } from '../lib/api';

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

export default function WalletPassLive({ card = {}, width = 292, visits = 3 }) {
  const [pass, setPass] = useState(null);
  const [error, setError] = useState(false);
  const [back, setBack] = useState(false);
  const seq = useRef(0);
  const key = JSON.stringify(card);

  useEffect(() => {
    const my = ++seq.current;
    const timer = setTimeout(() => {
      ownerAPI.walletPreview({ card, visits })
        .then((r) => { if (my === seq.current) { setPass(r.data); setError(false); } })
        .catch(() => { if (my === seq.current) setError(true); });
    }, 350);
    return () => clearTimeout(timer);
  }, [key, visits]); // eslint-disable-line react-hooks/exhaustive-deps

  const s = width / 375;
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
  const linear = bc.format === 'PKBarcodeFormatCode128';

  return (
    // translate="no": a browser translation turned the sample « Marie » into
    // « Married » — the pass itself is never translated.
    <div translate="no" style={{ width }}>
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
              ? <Code128Barcode value={bc.altText || 'FT-EXEMPLE1'} height={56 * s} />
              : <QRCodeSVG value={bc.message || 'FT-EXEMPLE1'} size={Math.round(140 * s)} level="M" />}
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
      <p className="mt-1.5 text-center text-[11px] text-[#94A3B8]">
        Exemple : {pass.sample?.name}, {pass.sample?.visits} visites
      </p>
    </div>
  );
}
