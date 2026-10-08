import React, { useRef, useState } from 'react';
import { QRCodeSVG } from 'qrcode.react';
import { Download, Printer, Image as ImageIcon } from 'lucide-react';

/**
 * JoinQRPoster — print-ready customer-acquisition poster.
 *
 * Renders a card-shaped poster:
 *   • Big QR pointing to /join/<slug>
 *   • Business name + a friendly French invite line
 *   • Customer-friendly instructions (3 steps)
 *
 * Two output paths:
 *   1. "Download PNG"  → uses canvas to rasterise the SVG, triggers a save
 *   2. "Print"          → opens browser print dialog with the poster only
 *
 * Owner prints this, slips it into a table tent / counter sign, customers
 * scan with their phone, fill the form, get a wallet card. Done.
 */
const JoinQRPoster = ({ joinUrl, businessName }) => {
  const posterRef = useRef(null);
  const svgRef = useRef(null);
  const [downloading, setDownloading] = useState(false);

  // Convert the rendered poster <div> to a PNG via SVG → canvas.
  // We rasterise just the QR for PNG, plus an SVG header with the business
  // name and instructions composed in JS so the result is ~300dpi clean.
  const downloadPNG = async () => {
    setDownloading(true);
    try {
      // 1. Pull the QR's SVG markup.
      const qrSvg = svgRef.current?.querySelector('svg');
      if (!qrSvg) throw new Error('QR not ready');
      const qrXml = new XMLSerializer().serializeToString(qrSvg);

      // 2. Compose a print-ready poster as a single SVG.
      const W = 1240;   // ~ A4 portrait at 150dpi
      const H = 1748;
      const safeName = (businessName || 'Notre boutique').replace(/&/g, '&amp;').replace(/</g, '&lt;');
      const compositeSvg = `
<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">
  <rect width="${W}" height="${H}" fill="#FAFAF8"/>
  <rect x="80" y="80" width="${W - 160}" height="${H - 160}" rx="40" fill="#ffffff" stroke="#E9E5E0" stroke-width="2"/>
  <text x="${W / 2}" y="220" text-anchor="middle" font-family="Cormorant Garamond, Georgia, serif" font-size="56" font-weight="700" fill="#171412">${safeName}</text>
  <text x="${W / 2}" y="290" text-anchor="middle" font-family="Manrope, sans-serif" font-size="28" fill="#B85C38" letter-spacing="4">REJOIGNEZ NOTRE PROGRAMME DE FIDÉLITÉ</text>
  <g transform="translate(${(W - 600) / 2}, 380)">
    <rect width="600" height="600" fill="#FFFFFF"/>
    <g transform="scale(${600 / Math.max(qrSvg.viewBox?.baseVal?.width || qrSvg.getAttribute('width') || 200, 1)})">
      ${qrXml.replace(/<\?xml[^>]*\?>/, '').replace(/<svg[^>]*>/, '').replace(/<\/svg>/, '')}
    </g>
  </g>
  <text x="${W / 2}" y="1080" text-anchor="middle" font-family="Manrope, sans-serif" font-size="32" font-weight="600" fill="#171412">Scannez ce QR avec votre téléphone</text>

  <text x="200"  y="1200" font-family="Manrope, sans-serif" font-size="56" font-weight="700" fill="#B85C38">1.</text>
  <text x="290"  y="1200" font-family="Manrope, sans-serif" font-size="32" fill="#171412">Ouvrez l'appareil photo de votre téléphone</text>

  <text x="200"  y="1300" font-family="Manrope, sans-serif" font-size="56" font-weight="700" fill="#B85C38">2.</text>
  <text x="290"  y="1300" font-family="Manrope, sans-serif" font-size="32" fill="#171412">Visez le QR code, touchez le lien qui apparaît</text>

  <text x="200"  y="1400" font-family="Manrope, sans-serif" font-size="56" font-weight="700" fill="#B85C38">3.</text>
  <text x="290"  y="1400" font-family="Manrope, sans-serif" font-size="32" fill="#171412">Remplissez votre nom — votre carte de fidélité est prête !</text>

  <text x="${W / 2}" y="1620" text-anchor="middle" font-family="Manrope, sans-serif" font-size="22" fill="#8D857D">Aucune application à télécharger · Vos données restent privées</text>
</svg>`;

      // 3. Convert SVG → PNG via Canvas.
      const blob = new Blob([compositeSvg], { type: 'image/svg+xml;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const img = new Image();
      img.crossOrigin = 'anonymous';
      await new Promise((resolve, reject) => {
        img.onload = resolve;
        img.onerror = reject;
        img.src = url;
      });
      const canvas = document.createElement('canvas');
      canvas.width = W;
      canvas.height = H;
      const ctx = canvas.getContext('2d');
      ctx.fillStyle = '#FAFAF8';
      ctx.fillRect(0, 0, W, H);
      ctx.drawImage(img, 0, 0, W, H);
      URL.revokeObjectURL(url);
      const pngUrl = canvas.toDataURL('image/png');
      const a = document.createElement('a');
      a.href = pngUrl;
      a.download = `affiche-fidclic-${(businessName || 'poster').replace(/[^a-z0-9]/gi, '-').toLowerCase()}.png`;
      a.click();
    } catch (e) {
      console.error('Poster download failed', e);
      alert("Impossible de télécharger l'affiche : " + (e?.message || 'erreur inconnue'));
    } finally {
      setDownloading(false);
    }
  };

  const print = () => {
    const w = window.open('', '_blank');
    if (!w) return alert("Activez les pop-ups pour imprimer l'affiche.");
    w.document.write(`
      <!DOCTYPE html>
      <html lang="fr">
      <head>
        <meta charset="utf-8" />
        <title>Affiche FidClic — ${businessName || ''}</title>
        <style>
          @page { size: A4 portrait; margin: 1cm; }
          body { font-family: -apple-system, system-ui, sans-serif; text-align: center; padding: 40px 20px; color: #171412; }
          h1 { font-family: 'Cormorant Garamond', Georgia, serif; font-size: 56px; margin: 0 0 8px; }
          .subtitle { font-size: 18px; color: #B85C38; letter-spacing: 4px; text-transform: uppercase; margin-bottom: 40px; }
          .qr-wrap { background: white; padding: 24px; border-radius: 16px; display: inline-block; }
          .qr-wrap svg { width: 320px; height: 320px; }
          .invite { font-size: 24px; font-weight: 600; margin: 28px 0 32px; }
          ol { text-align: left; max-width: 460px; margin: 0 auto; padding: 0; list-style: none; }
          li { display: flex; align-items: flex-start; gap: 14px; margin-bottom: 16px; font-size: 18px; }
          li b { color: #B85C38; font-size: 28px; }
          .foot { font-size: 13px; color: #8D857D; margin-top: 36px; }
        </style>
      </head>
      <body>
        <h1>${businessName || 'Notre boutique'}</h1>
        <div class="subtitle">Rejoignez notre programme de fidélité</div>
        <div class="qr-wrap" id="qrwrap">${posterRef.current?.querySelector('#poster-qr')?.innerHTML || ''}</div>
        <p class="invite">Scannez ce QR avec votre téléphone</p>
        <ol>
          <li><b>1.</b> Ouvrez l'appareil photo de votre téléphone</li>
          <li><b>2.</b> Visez le QR code et touchez le lien qui apparaît</li>
          <li><b>3.</b> Remplissez votre nom — votre carte de fidélité est prête !</li>
        </ol>
        <p class="foot">Aucune application à télécharger · Vos données restent privées</p>
        <script>setTimeout(() => { window.print(); window.close(); }, 250);<\/script>
      </body>
      </html>
    `);
    w.document.close();
  };

  return (
    <div ref={posterRef} className="bg-white rounded-2xl border border-[#E9E5E0] p-5 mt-4">
      <div className="text-xs font-bold uppercase tracking-widest text-[#8D857D] mb-3">
        Affiche QR pour le comptoir
      </div>
      <div className="flex flex-col md:flex-row gap-5 items-start">
        {/* Mini preview */}
        <div className="bg-[#FAFAF8] border border-[#E9E5E0] rounded-xl p-4 text-center mx-auto" id="poster-qr-preview">
          <p className="text-xs font-bold mb-1" style={{ color: '#171412' }}>{businessName || 'Notre boutique'}</p>
          <p className="text-[9px] uppercase tracking-widest mb-2" style={{ color: '#B85C38' }}>Rejoignez notre programme</p>
          <div ref={svgRef} id="poster-qr" className="bg-white p-2 rounded inline-block">
            {/* the shop's QR opens /…/qr: its signups count as « QR code en magasin » */}
            <QRCodeSVG value={`${String(joinUrl || '').replace(/\/$/, '')}/qr`} size={140} level="M" />
          </div>
          <p className="text-[10px] mt-2" style={{ color: '#8D857D' }}>Scannez avec votre téléphone</p>
        </div>

        {/* Actions */}
        <div className="flex-1 space-y-2 text-sm">
          <p className="text-[#57504A]">
            Imprimez cette affiche et placez-la sur votre comptoir / table.
            Vos clients la scannent avec l'appareil photo de leur téléphone et reçoivent immédiatement leur carte de fidélité.
          </p>
          <ol className="text-xs text-[#8D857D] list-decimal pl-5 space-y-0.5">
            <li>Ils scannent le QR</li>
            <li>Remplissent nom + téléphone</li>
            <li>Reçoivent leur carte avec QR personnel</li>
            <li>Vous scannez leur QR à chaque visite</li>
          </ol>
          <div className="flex flex-wrap gap-2 pt-2">
            <button
              type="button"
              onClick={print}
              className="inline-flex items-center gap-2 px-3 py-2 text-xs font-semibold text-white rounded-lg"
              style={{ background: '#B85C38' }}
            >
              <Printer size={13} /> Imprimer maintenant
            </button>
            <button
              type="button"
              onClick={downloadPNG}
              disabled={downloading}
              className="inline-flex items-center gap-2 px-3 py-2 text-xs font-semibold rounded-lg border"
              style={{ borderColor: '#E9E5E0', color: '#171412' }}
            >
              <ImageIcon size={13} /> {downloading ? 'Génération…' : 'Télécharger en PNG'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default JoinQRPoster;
