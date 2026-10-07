import React from 'react';
import { Plane, TrainFront, Bus, Ship, ArrowRight } from 'lucide-react';
import BarcodeSvg, { SQUARE_CODES } from './BarcodeSvg';
import { ActionTile } from './walletLook';

/**
 * PassPreview — draws a pass.json the way Wallet lays it out, for every
 * style: posterGeneric (iOS 27), generic, storeCard, coupon, eventTicket,
 * boardingPass. It draws what the SERVER built (POST /api/owner/wallet/preview
 * with the editor's design) — fields, colours, images, barcodes — so only the
 * frame is ours, after Apple's layouts and Pass Designer's canvas.
 *
 * Props: pj (pass.json), style (which style dict to draw), images ({base:
 * data URL}), actions ([{type,label}] — tiles, iOS 27 only), width (px).
 */
const FONT = '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", Arial, sans-serif';
const MONO = 'ui-monospace, "SF Mono", Menlo, Consolas, monospace';
const val = (f) => (f?.value === undefined || f?.value === null ? '' : String(f.value));
const ALIGN = { PKTextAlignmentLeft: 'left', PKTextAlignmentCenter: 'center', PKTextAlignmentRight: 'right' };
// iOS 27 adds these; older iPhones skip them and show the next barcode
export const NEW_CODES = new Set(['PKBarcodeFormatCode39', 'PKBarcodeFormatCodabar', 'PKBarcodeFormatEAN13', 'PKBarcodeFormatI2of5']);
const codeFor = (pj, legacy) => (pj.barcodes || []).find((b) => !legacy || !NEW_CODES.has(b.format)) || (pj.barcodes || [])[0];

function Field({ f, s, big = false, align, lab, fg }) {
  return (
    <div className="min-w-0" style={{ textAlign: ALIGN[f.textAlignment] || align || 'left' }}>
      {f.label && <div className="truncate uppercase" style={{ fontSize: 11 * s, letterSpacing: 0.2 * s, color: lab, fontWeight: 600 }}>{f.label}</div>}
      <div className="truncate" style={{ fontSize: (big ? 34 : 19) * s, lineHeight: 1.15, color: fg, fontWeight: big ? 300 : 400 }}>{val(f)}</div>
    </div>
  );
}

function Row({ fields = [], s, lab, fg }) {
  if (!fields.length) return null;
  return (
    <div className="flex justify-between" style={{ gap: 12 * s, padding: `${10 * s}px ${16 * s}px 0` }}>
      {fields.map((f, i) => (
        <Field key={f.key} f={f} s={s} lab={lab} fg={fg}
               align={fields.length > 1 && i === fields.length - 1 ? 'right' : 'left'} />
      ))}
    </div>
  );
}

function Code({ bc, s, width }) {
  if (!bc?.format) return null;
  const square = SQUARE_CODES.has(bc.format);
  const pdf = bc.format === 'PKBarcodeFormatPDF417';
  return (
    <div className="flex flex-col items-center bg-white" style={{ borderRadius: 6 * s, padding: `${10 * s}px ${12 * s}px ${6 * s}px` }}>
      {square
        ? <BarcodeSvg format={bc.format} message={bc.message} width={128 * s} height={128 * s} />
        : <BarcodeSvg format={bc.format} message={bc.message} width={width * 0.74} height={(pdf ? 70 : 58) * s} />}
      {bc.altText && <div style={{ fontSize: 12.5 * s, color: '#111', marginTop: 4 * s }}>{bc.altText}</div>}
    </div>
  );
}

function Header({ pj, block, logo, s, lab, fg }) {
  return (
    <div className="flex items-center" style={{ gap: 8 * s, padding: `${10 * s}px ${16 * s}px`, minHeight: 60 * s }}>
      {logo && <img src={logo} alt="" style={{ height: 40 * s, maxWidth: 140 * s, objectFit: 'contain' }} />}
      <div className="min-w-0 flex-1 truncate" style={{ fontSize: 17 * s, fontWeight: 600, color: fg }}>{pj.logoText}</div>
      {(block.headerFields || []).map((f) => (
        <div key={f.key} className="shrink-0 text-right">
          {f.label && <div className="uppercase" style={{ fontSize: 10.5 * s, color: lab, fontWeight: 600 }}>{f.label}</div>}
          <div style={{ fontSize: 17 * s, lineHeight: 1.1, color: fg }}>{val(f)}</div>
        </div>
      ))}
    </div>
  );
}

const TRANSIT_ICON = { PKTransitTypeAir: Plane, PKTransitTypeTrain: TrainFront, PKTransitTypeBus: Bus, PKTransitTypeBoat: Ship };

function ClassicPass({ pj, style, images, width, legacy }) {
  const s = width / 375;
  const block = pj[style] || {};
  const fg = pj.foregroundColor || 'rgb(255,255,255)';
  const lab = pj.labelColor || fg;
  const bg = pj.backgroundColor || 'rgb(28,29,34)';
  const bc = codeFor(pj, legacy);
  const prim = block.primaryFields || [];
  const strip = ['storeCard', 'coupon', 'eventTicket'].includes(style) ? images.strip : null;
  const blurBg = style === 'eventTicket' && images.background && !strip;
  const thumb = ['generic', 'eventTicket'].includes(style) ? images.thumbnail : null;
  const Transit = TRANSIT_ICON[block.transitType] || ArrowRight;
  const coupon = style === 'coupon';
  return (
    <div className="relative overflow-hidden" style={{ width, background: bg, color: fg, borderRadius: coupon ? 4 * s : 12 * s,
      boxShadow: '0 18px 40px -22px rgba(0,0,0,.55)', fontFamily: FONT,
      ...(coupon ? { WebkitMaskImage: `radial-gradient(circle at ${5 * s}px ${5 * s}px, transparent ${3 * s}px, #000 ${3.5 * s}px)`,
        WebkitMaskSize: `${10 * s}px 100%`, WebkitMaskRepeat: 'round', WebkitMaskPosition: '0 -5px' } : {}) }}>
      {blurBg && (
        <img src={images.background} alt="" className="absolute inset-0 h-full w-full object-cover"
             style={{ filter: `blur(${18 * s}px)`, transform: 'scale(1.2)', opacity: 0.9 }} />
      )}
      <div className="relative">
        <Header pj={pj} block={block} logo={images.logo} s={s} lab={lab} fg={fg} />
        {strip ? (
          <div className="relative">
            <img src={strip} alt="" style={{ width: '100%', aspectRatio: style === 'eventTicket' ? '375 / 98' : '375 / 144', objectFit: 'cover', display: 'block' }} />
            {prim[0] && (
              <div className="absolute inset-x-0 bottom-0" style={{ padding: `0 ${16 * s}px ${8 * s}px` }}>
                <Field f={prim[0]} s={s} big lab={pj.stripColor || lab} fg={fg} />
              </div>
            )}
          </div>
        ) : style === 'boardingPass' ? (
          <div className="flex items-center justify-between" style={{ padding: `${4 * s}px ${16 * s}px 0`, gap: 8 * s }}>
            {prim[0] && <Field f={prim[0]} s={s} big lab={lab} fg={fg} />}
            <Transit size={26 * s} style={{ color: lab, flexShrink: 0 }} />
            {prim[1] && <Field f={prim[1]} s={s} big align="right" lab={lab} fg={fg} />}
          </div>
        ) : (prim.length > 0 || thumb) && (
          <div className="flex items-start justify-between" style={{ padding: `${4 * s}px ${16 * s}px 0`, gap: 10 * s }}>
            <div className="min-w-0 flex-1">{prim[0] && <Field f={prim[0]} s={s} big lab={lab} fg={fg} />}</div>
            {thumb && <img src={thumb} alt="" style={{ width: 90 * s * 0.85, height: 90 * s * 0.85, objectFit: 'cover', borderRadius: 4 * s }} />}
          </div>
        )}
        {style === 'boardingPass' ? (
          <>
            <Row fields={block.auxiliaryFields} s={s} lab={lab} fg={fg} />
            <Row fields={block.secondaryFields} s={s} lab={lab} fg={fg} />
          </>
        ) : ['storeCard', 'coupon'].includes(style) ? (
          <Row fields={[...(block.secondaryFields || []), ...(block.auxiliaryFields || [])].slice(0, 4)} s={s} lab={lab} fg={fg} />
        ) : (
          <>
            <Row fields={block.secondaryFields} s={s} lab={lab} fg={fg} />
            <Row fields={block.auxiliaryFields} s={s} lab={lab} fg={fg} />
          </>
        )}
        {style === 'boardingPass' && images.footer && (
          <img src={images.footer} alt="" style={{ width: '76%', margin: `${10 * s}px auto 0`, display: 'block' }} />
        )}
        <div className="flex justify-center" style={{ padding: `${22 * s}px 0 ${16 * s}px` }}>
          <Code bc={bc} s={s} width={width} />
        </div>
      </div>
    </div>
  );
}

function PosterPass({ pj, images, width }) {
  // What Wallet (and Pass Designer) draw for iOS 27 « Poster Generic »: the
  // artwork full-bleed, the logo top-left, the header top-right, the barcode
  // straddling the photo and the footer band (system material, or the
  // design's footer colour), the primary fields and the footer in the band.
  const s = width / 375;
  const p = pj.posterGeneric || {};
  const h = width / 0.713;
  const header = (p.headerFields || [])[0];
  const [title, ...rest] = p.primaryFields || [];
  const footer = p.footerFields || [];
  const fg = pj.foregroundColor || 'rgb(255,255,255)';
  const lab = pj.labelColor || fg;
  const bc = (pj.barcodes || [])[0] || {};
  const square = SQUARE_CODES.has(bc.format);
  const titleBold = title && !title.label;
  const band = pj.footerBackgroundColor
    ? { background: pj.footerBackgroundColor }
    : { backdropFilter: 'blur(26px) saturate(1.6)', WebkitBackdropFilter: 'blur(26px) saturate(1.6)',
        background: 'linear-gradient(to bottom, rgba(255,255,255,.08), rgba(0,0,0,.22))' };
  return (
    <div className="relative overflow-hidden" style={{ width, height: h, borderRadius: 14 * s, color: fg, background: '#1C1D22',
      boxShadow: '0 18px 40px -22px rgba(0,0,0,.55)', fontFamily: FONT }}>
      {images.background && <img src={images.background} alt="" className="absolute inset-0 h-full w-full object-cover object-top" />}
      {!pj.suppressHeaderDarkening && (
        <div className="absolute inset-x-0 top-0" style={{ height: '18%', background: 'linear-gradient(to bottom, rgba(0,0,0,.38), transparent)' }} />
      )}
      <div className="absolute inset-x-0 bottom-0" style={{ height: '27%', ...band }} />
      <div className="absolute inset-x-0 top-0 flex items-start justify-between" style={{ padding: `${10 * s}px ${12 * s}px` }}>
        {images.primaryLogo ? <img src={images.primaryLogo} alt="" style={{ height: width * 0.105, maxWidth: width * 0.4, objectFit: 'contain' }} /> : <span />}
        {header && (
          <div className="text-right">
            {header.label && <div className="uppercase" style={{ fontSize: 11 * s, fontWeight: 700, color: lab }}>{header.label}</div>}
            <div style={{ fontSize: 12.5 * s, fontFamily: MONO, marginTop: 2 * s }}>{val(header)}</div>
          </div>
        )}
      </div>
      <div className="absolute inset-x-0 flex justify-center" style={{ top: square ? '44%' : '58%' }}>
        <div className="flex flex-col items-center bg-white" style={{ borderRadius: 7 * s, padding: `${8 * s}px ${12 * s}px ${4 * s}px` }}>
          {square
            ? <BarcodeSvg format={bc.format} message={bc.message} width={108 * s} height={108 * s} />
            : <BarcodeSvg format={bc.format} message={bc.message} width={width * 0.68} height={(bc.format === 'PKBarcodeFormatPDF417' ? 64 : 54) * s} />}
          {bc.altText && <div style={{ fontSize: 11 * s, color: '#111', marginTop: 2 * s, fontFamily: MONO }}>{bc.altText}</div>}
        </div>
      </div>
      <div className="absolute inset-x-0 bottom-0" style={{ padding: `0 ${12 * s}px ${11 * s}px` }}>
        <div className="flex items-end justify-between" style={{ gap: 10 * s }}>
          {title && (
            <div className="min-w-0">
              {!titleBold && <div style={{ fontSize: 10.5 * s, fontFamily: MONO, color: lab }}>{title.label}</div>}
              <div className="truncate" style={titleBold
                ? { fontSize: 19 * s, fontWeight: 700, lineHeight: 1.15 }
                : { fontSize: 15 * s, fontWeight: 600 }}>{val(title)}</div>
            </div>
          )}
          {rest.length > 0 && (
            <div className="flex shrink-0 text-right" style={{ gap: 12 * s }}>
              {rest.slice(0, 3).map((f) => (
                <div key={f.key} className="min-w-0">
                  {f.label && <div style={{ fontSize: 10.5 * s, color: lab, fontWeight: 600 }}>{f.label}</div>}
                  <div className="truncate" style={{ fontSize: 13 * s, fontFamily: MONO, maxWidth: 120 * s }}>{val(f)}</div>
                </div>
              ))}
            </div>
          )}
        </div>
        {footer.length > 0 && (
          <div className="flex justify-between" style={{ gap: 10 * s, marginTop: 12 * s }}>
            {footer.slice(0, 2).map((f, i) => (
              <div key={f.key} className="min-w-0" style={{ textAlign: i ? 'right' : 'left' }}>
                {f.label && <div style={{ fontSize: 9.5 * s, color: lab, fontWeight: 600 }}>{f.label}</div>}
                <div className="truncate uppercase" style={{ fontSize: 10 * s, fontFamily: MONO }}>{val(f)}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default function PassPreview({ pj, style, images = {}, actions = [], width = 260, legacy = false }) {
  if (!pj || !pj[style]) return null;
  const s = width / 375;
  return (
    <div translate="no" style={{ width }}>
      {style === 'posterGeneric'
        ? <PosterPass pj={pj} images={images} width={width} />
        : <ClassicPass pj={pj} style={style} images={images} width={width} legacy={legacy} />}
      {style === 'posterGeneric' && actions.length > 0 && (
        <div className="mt-2 grid grid-cols-2" style={{ gap: 8 * s }}>
          {actions.slice(0, 2).map((a) => <ActionTile key={a.type} type={a.type} label={a.label} s={s} />)}
        </div>
      )}
    </div>
  );
}

// The back of the pass: Wallet shows it under ⋯ › Pass Details.
export function PassBack({ pj, style }) {
  const rows = (pj?.[style] || {}).backFields || [];
  if (!rows.length) return <p className="text-[12px] text-[#94A3B8]">Aucun champ au dos.</p>;
  return (
    <dl className="divide-y divide-[#EEF2F9] rounded-xl border border-[#E6EEFB] bg-white text-left text-[12px]">
      {rows.map((f) => (
        <div key={f.key} className="px-3 py-2">
          <dt className="font-semibold text-[#0B1C3F]">{f.label}</dt>
          <dd className="whitespace-pre-line break-words text-[#475569]">{val(f)}</dd>
        </div>
      ))}
    </dl>
  );
}
