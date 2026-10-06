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
 *
 * iOS 27 (WWDC26): when the pass carries the « poster » style, the preview
 * opens on it — full-bleed background, primary logo, header, the member's
 * name in bold, the progress, the footer, the tiles under the pass — with a
 * switch to see the card iOS 26 and earlier show instead.
 */
function PosterPass({ p, s, width, bc, linear, colors = {} }) {
  // Apple's iOS 27 poster (WWDC26 Museum sample, the user's iPhone): the
  // background covers the WHOLE card, fields included; Wallet darkens its
  // foot so the text reads. Labels and values in Wallet's monospace.
  const h = width / 0.72;
  const header = (p.headerFields || [])[0];
  const fields = p.primaryFields || [];
  const footer = (p.footerFields || [])[0];
  const fg = colors.foregroundColor || 'rgb(255,255,255)';
  const lab = colors.labelColor || 'rgba(255,255,255,.75)';
  const mono = 'ui-monospace, "SF Mono", Menlo, Consolas, monospace';
  const shadow = '0 1px 2px rgba(0,0,0,.45)';
  const big = fields.length && !fields[0].label;          // no label → Apple's bold title
  return (
    <div>
      <div className="relative overflow-hidden" style={{ width, height: h, borderRadius: 14 * s, color: fg,
        boxShadow: '0 18px 40px -22px rgba(0,0,0,.55)', background: '#1C1D22',
        fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", Arial, sans-serif' }}>
        {p.background && <img src={p.background} alt="" className="absolute inset-0 h-full w-full object-cover object-top" />}
        <div className="absolute inset-x-0 bottom-0" style={{ height: '38%',
          background: 'linear-gradient(to top, rgba(0,0,0,.62), rgba(0,0,0,.28) 60%, transparent)' }} />
        <div className="absolute inset-x-0 top-0 flex items-start justify-between" style={{ padding: `${12 * s}px ${14 * s}px` }}>
          {p.logo ? <img src={p.logo} alt="" style={{ height: 32 * s, maxWidth: 160 * s, objectFit: 'contain' }} /> : <span />}
          {header && (
            <div className="text-right" style={{ textShadow: shadow }}>
              <div className="uppercase" style={{ fontSize: 12 * s, fontWeight: 700, color: lab }}>{header.label}</div>
              <div style={{ fontSize: 13 * s, fontFamily: mono }}>{String(header.value)}</div>
            </div>
          )}
        </div>
        <div className="absolute inset-x-0 flex justify-center" style={{ top: '45%' }}>
          <div className="flex flex-col items-center bg-white" style={{ borderRadius: 6 * s, padding: `${7 * s}px ${8 * s}px ${4 * s}px` }}>
            {linear
              ? <Code128Barcode value={bc.altText || 'FT-EXEMPLE1'} height={44 * s} />
              : <QRCodeSVG value={bc.message || 'FT-EXEMPLE1'} size={Math.round(100 * s)} level="M" />}
            {bc.altText && <div style={{ fontSize: 10 * s, color: '#111', marginTop: 2 * s }}>{bc.altText}</div>}
          </div>
        </div>
        <div className="absolute inset-x-0 bottom-0" style={{ padding: `0 ${14 * s}px ${12 * s}px`, textShadow: shadow }}>
          <div className="flex items-end justify-between" style={{ gap: 10 * s }}>
            {fields.slice(0, 4).map((f, i) => (
              <div key={f.key} className="min-w-0" style={{ textAlign: i > 0 && i === fields.length - 1 ? 'right' : 'left' }}>
                {f.label && <div style={{ fontSize: 11 * s, fontFamily: mono, color: lab }}>{f.label}</div>}
                <div className="truncate" style={i === 0 && big
                  ? { fontSize: 26 * s, fontWeight: 700, lineHeight: 1.1 }
                  : { fontSize: 13.5 * s, fontFamily: mono }}>{String(f.value)}</div>
              </div>
            ))}
          </div>
          {footer && <div className="truncate" style={{ fontSize: 11 * s, fontFamily: mono, marginTop: 12 * s }}>{footer.value}</div>}
        </div>
      </div>
      {(p.actions || []).length > 0 && (
        <div className="mt-2 grid grid-cols-2" style={{ gap: 8 * s }}>
          {p.actions.map((a) => (
            <div key={a.type} className="rounded-xl border border-[#E6EEFB] bg-white text-left" style={{ padding: 10 * s }}>
              <span className="mb-1 inline-block h-5 w-5 rounded-full bg-[#2F6BFF]/15" />
              <div className="truncate text-[12px] font-semibold text-[#0B1C3F]">{a.label}</div>
              <div className="text-[10.5px] text-[#94A3B8]">Ouvrir le site</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function WalletPassLive({ card = {}, width = 292, visits = 3 }) {
  const [pass, setPass] = useState(null);
  const [error, setError] = useState(false);
  const [back, setBack] = useState(false);
  const [classic, setClassic] = useState(false);     // iOS 26 view of a poster pass
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
        <PosterPass p={pass.poster} s={s} width={width} bc={bc} linear={linear} colors={pass.colors} />
        <p className="mt-1.5 text-center text-[11px] text-[#94A3B8]">
          Exemple : {pass.sample?.name}, {pass.sample?.visits} visites · nouvelle carte iOS 27
        </p>
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
