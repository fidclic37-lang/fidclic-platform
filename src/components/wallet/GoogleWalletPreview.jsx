import React from 'react';
import BarcodeSvg, { SQUARE_CODES } from './BarcodeSvg';

/**
 * GoogleWalletPreview — the Google Wallet card as the SERVER builds it
 * (POST /api/owner/wallet/google-preview: the loyaltyClass + loyaltyObject
 * google_save_url() sends), drawn after Google's Android layout: one colour,
 * the round (or wide) logo and the shop's name, the programme name, the rows
 * of values, the barcode, the hero banner; and the « Détails » screen.
 */
const CODE_AS = {
  QR_CODE: 'PKBarcodeFormatQR', AZTEC: 'PKBarcodeFormatAztec', PDF_417: 'PKBarcodeFormatPDF417',
  DATA_MATRIX: 'PKBarcodeFormatQR', CODE_128: 'PKBarcodeFormatCode128', CODE_39: 'PKBarcodeFormatCode39',
  EAN_13: 'PKBarcodeFormatEAN13', CODABAR: 'PKBarcodeFormatCodabar',
};
const FONT = 'Roboto, "Google Sans", system-ui, -apple-system, sans-serif';

// Google picks the text colour from the background
const inkOn = (hex) => {
  const m = String(hex || '').match(/^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i);
  if (!m) return '#fff';
  const [r, g, b] = m.slice(1).map((x) => parseInt(x, 16) / 255);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.6 ? '#1F1F1F' : '#FFFFFF';
};

function resolve(path, obj) {
  if (path === 'object.accountName') return { label: 'Nom', value: obj.accountName };
  if (path === 'object.accountId') return { label: 'N° de carte', value: obj.accountId };
  const m = String(path).match(/textModulesData\['([^']+)'\]/);
  const mod = m && (obj.textModulesData || []).find((t) => t.id === m[1]);
  return mod ? { label: mod.header, value: mod.body } : null;
}

function Item({ it, ink, align }) {
  if (!it) return <div />;
  return (
    <div className="min-w-0" style={{ textAlign: align }}>
      <div className="truncate" style={{ fontSize: 10.5, opacity: 0.8 }}>{it.label}</div>
      <div className="truncate" style={{ fontSize: 14, fontWeight: 500, color: ink }}>{String(it.value ?? '')}</div>
    </div>
  );
}

export default function GoogleWalletPreview({ data, width = 250 }) {
  if (!data) return null;
  const cls = data.class || {};
  const obj = data.object || {};
  const bg = cls.hexBackgroundColor || '#1C1D22';
  const ink = inkOn(bg);
  const rows = cls.classTemplateInfo?.cardTemplateOverride?.cardRowTemplateInfos;
  const field = (item) => resolve(item?.firstValue?.fields?.[0]?.fieldPath, obj);
  const defaultRows = [
    [obj.loyaltyPoints && { label: obj.loyaltyPoints.label, value: obj.loyaltyPoints.balance?.int ?? obj.loyaltyPoints.balance?.string },
      obj.secondaryLoyaltyPoints && { label: obj.secondaryLoyaltyPoints.label, value: obj.secondaryLoyaltyPoints.balance?.string ?? obj.secondaryLoyaltyPoints.balance?.int }],
    [{ label: 'Nom', value: obj.accountName }],
  ];
  const drawn = rows ? rows.map((r) => (r.oneItem ? [field(r.oneItem.item)]
    : r.twoItems ? [field(r.twoItems.startItem), field(r.twoItems.endItem)]
      : [field(r.threeItems?.startItem), field(r.threeItems?.middleItem), field(r.threeItems?.endItem)]))
    : defaultRows.map((r) => r.filter(Boolean)).filter((r) => r.length);
  const code = obj.barcode || {};
  const fmt = CODE_AS[code.type] || 'PKBarcodeFormatQR';
  const square = SQUARE_CODES.has(fmt) || code.type === 'DATA_MATRIX';
  const img = data.images || {};

  return (
    <div translate="no" className="flex flex-wrap justify-center gap-5" style={{ fontFamily: FONT }}>
      <div style={{ width }}>
        <p className="mb-1.5 text-center text-[11px] font-semibold text-[#64748B]">Carte (Android)</p>
        <div className="overflow-hidden" style={{ background: bg, color: ink, borderRadius: 18, boxShadow: '0 18px 40px -22px rgba(0,0,0,.45)' }}>
          <div className="flex items-center gap-2 px-4 pt-3.5">
            {img.wide ? (
              <img src={img.wide} alt="" style={{ height: 30, maxWidth: '80%', objectFit: 'contain' }} />
            ) : (
              <>
                {img.logo
                  ? <img src={img.logo} alt="" style={{ width: 30, height: 30, borderRadius: '50%', objectFit: 'cover' }} />
                  : <span style={{ width: 30, height: 30, borderRadius: '50%', background: 'rgba(255,255,255,.3)' }} />}
                <span className="truncate" style={{ fontSize: 13 }}>{cls.issuerName}</span>
              </>
            )}
          </div>
          <div className="truncate px-4 pt-2.5" style={{ fontSize: 20, lineHeight: 1.25 }}>{cls.programName}</div>
          <div className="space-y-2.5 px-4 pt-3">
            {drawn.map((r, i) => (
              <div key={i} className="grid gap-3" style={{ gridTemplateColumns: `repeat(${r.length}, minmax(0, 1fr))` }}>
                {r.map((it, j) => <Item key={j} it={it} ink={ink} align={r.length > 1 && j === r.length - 1 ? 'right' : r.length === 3 && j === 1 ? 'center' : 'left'} />)}
              </div>
            ))}
          </div>
          <div className="flex justify-center px-4 pb-4 pt-4">
            <div className="flex flex-col items-center rounded-xl bg-white px-3 pb-1.5 pt-3">
              {square
                ? <BarcodeSvg format={fmt} message={code.value} width={118} height={118} />
                : <BarcodeSvg format={fmt} message={code.value} width={width * 0.7} height={56} />}
              {code.alternateText && <div style={{ fontSize: 11, color: '#1F1F1F', marginTop: 4 }}>{code.alternateText}</div>}
            </div>
          </div>
          {img.hero && <img src={img.hero} alt="" style={{ width: '100%', aspectRatio: '1032 / 336', objectFit: 'cover', display: 'block' }} />}
        </div>
      </div>

      <div style={{ width }}>
        <p className="mb-1.5 text-center text-[11px] font-semibold text-[#64748B]">Détails (touchez la carte)</p>
        <div className="space-y-2 rounded-2xl border border-[#E6EEFB] bg-white p-3 text-left text-[12px] text-[#1F1F1F]">
          {(obj.messages || []).map((m) => (
            <div key={m.id} className="rounded-xl bg-[#EEF3FB] p-2.5">
              <p className="font-semibold">{m.header}</p>
              <p className="text-[#475569]">{m.body}</p>
            </div>
          ))}
          {(obj.textModulesData || []).map((t) => (
            <div key={t.id}>
              <p className="text-[11px] text-[#5F6368]">{t.header}</p>
              <p className="whitespace-pre-line break-words">{t.body}</p>
            </div>
          ))}
          {(obj.linksModuleData?.uris || []).length > 0 && (
            <div className="border-t border-[#EEF2F9] pt-2">
              {obj.linksModuleData.uris.map((l, i) => (
                <p key={i} className="truncate py-0.5 font-medium text-[#1A73E8]">{l.description || l.uri}</p>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
