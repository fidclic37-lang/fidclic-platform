import React, { useEffect, useState } from 'react';

/**
 * BarcodeSvg — any of Wallet's eight formats, drawn for real (bwip-js, loaded
 * only when a preview needs it). The message is the one the pass carries, so
 * the preview's code scans like the customer's.
 */
const BCID = {
  PKBarcodeFormatQR: 'qrcode',
  PKBarcodeFormatPDF417: 'pdf417',
  PKBarcodeFormatAztec: 'azteccode',
  PKBarcodeFormatCode128: 'code128',
  PKBarcodeFormatCode39: 'code39',
  PKBarcodeFormatCodabar: 'rationalizedCodabar',
  PKBarcodeFormatEAN13: 'ean13',
  PKBarcodeFormatI2of5: 'interleaved2of5',
};
export const SQUARE_CODES = new Set(['PKBarcodeFormatQR', 'PKBarcodeFormatAztec']);

let lib = null;
const load = () => {
  if (!lib) lib = import('bwip-js/browser').then((m) => m.default || m);
  return lib;
};

export default function BarcodeSvg({ format = 'PKBarcodeFormatQR', message, width, height }) {
  const [svg, setSvg] = useState('');
  useEffect(() => {
    let live = true;
    load().then((bw) => {
      let text = String(message || 'FT-EXEMPLE1');
      if (format === 'PKBarcodeFormatCodabar') text = `A${text}A`;
      const opts = { bcid: BCID[format] || 'qrcode', text, scale: 3, includetext: false };
      if (format === 'PKBarcodeFormatPDF417') opts.columns = 4;
      try {
        let out = bw.toSVG(opts);
        // linear codes stretch to the slot, like Wallet; square ones keep their shape
        if (!SQUARE_CODES.has(format)) out = out.replace('<svg ', '<svg preserveAspectRatio="none" ');
        if (live) setSvg(out);
      } catch {
        if (live) setSvg('');
      }
    }).catch(() => live && setSvg(''));
    return () => { live = false; };
  }, [format, message]);
  return (
    <div style={{ width, height }} className="[&>svg]:block [&>svg]:h-full [&>svg]:w-full"
         // generated here from the pass's own message: no outside markup
         dangerouslySetInnerHTML={{ __html: svg }} />
  );
}
