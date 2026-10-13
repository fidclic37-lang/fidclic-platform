import React, { useEffect, useRef, useState } from 'react';
import { X, ZoomIn } from 'lucide-react';
import { fitZoom } from '../lib/fit';

/**
 * PosterCropper — frame a photo for the iOS 27 poster (user, 2026-10-06:
 * « bg mein puri image rhe », like Apple's Museum sample, and nothing cut that
 * the owner did not choose). The photo always covers the whole card; the
 * owner drags it and zooms to pick what shows, and gets Apple's 345 × 505 pt
 * at 3× (1035 × 1515) as a JPEG.
 *
 * Props: file (a File), onDone(dataUrl), onCancel(); outW / outH and title
 * frame any other Wallet image the same way (the card editor's banner…).
 */
export default function PosterCropper({ file, onDone, onCancel, outW = 1035, outH = 1515, title = "Cadrer l'image poster",
                                       guides = true, fit = false, round = false, fill = '#FFFFFF' }) {
  // `fit`: the slider may go below « couvre le cadre », down to the whole image
  // inside it. A poster must never show an empty edge, so it stays off there;
  // a logo must never be cut, so the registration image turns it on.
  const OUT_W = outW;
  const OUT_H = outH;
  const FRAME_W = OUT_W >= OUT_H ? 300 : 280;
  const FRAME_H = Math.round(FRAME_W * (OUT_H / OUT_W));
  const [img, setImg] = useState(null);
  const [zoom, setZoom] = useState(1);            // 1 = just covers the frame
  const [pos, setPos] = useState({ x: 0, y: 0 }); // image top-left, frame px
  const drag = useRef(null);
  const url = useRef(null);

  useEffect(() => {
    url.current = URL.createObjectURL(file);
    const im = new Image();
    im.onload = () => {
      setImg(im);
      const cover = Math.max(FRAME_W / im.width, FRAME_H / im.height);
      // With `fit`, open on the whole image: the owner should not have to find
      // a slider to stop their logo being cut.
      const z = fit ? Math.min(Math.min(FRAME_W / im.width, FRAME_H / im.height) / cover, 1) : 1;
      setZoom(z);
      const s0 = cover * z;
      setPos({ x: (FRAME_W - im.width * s0) / 2, y: (FRAME_H - im.height * s0) / 2 });
    };
    im.src = url.current;
    return () => URL.revokeObjectURL(url.current);
  }, [file, fit]);

  if (!img) return null;
  const base = Math.max(FRAME_W / img.width, FRAME_H / img.height);
  // « Toute l'image »: the zoom at which the whole picture sits in the frame.
  const contain = Math.min(FRAME_W / img.width, FRAME_H / img.height) / base;
  const minZoom = fit ? Math.min(contain, 1) : 1;
  const scale = base * zoom;
  const w = img.width * scale;
  const h = img.height * scale;
  // Covering the frame: never an empty edge. Smaller than the frame (only
  // reachable with `fit`): centred on that axis, so nothing is cut.
  const clamp = (p, sw = w, sh = h) => ({
    x: sw <= FRAME_W ? (FRAME_W - sw) / 2 : Math.min(0, Math.max(FRAME_W - sw, p.x)),
    y: sh <= FRAME_H ? (FRAME_H - sh) / 2 : Math.min(0, Math.max(FRAME_H - sh, p.y)),
  });

  const onZoom = (z) => {
    const ns = base * z;
    const cx = FRAME_W / 2 - pos.x;              // keep the centre where it is
    const cy = FRAME_H / 2 - pos.y;
    const k = ns / scale;
    setZoom(z);
    setPos(clamp({ x: FRAME_W / 2 - cx * k, y: FRAME_H / 2 - cy * k }, img.width * ns, img.height * ns));
  };

  const down = (e) => {
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = { sx: e.clientX, sy: e.clientY, ox: pos.x, oy: pos.y };
  };
  const move = (e) => {
    if (!drag.current) return;
    const d = drag.current;
    const k = fitZoom();                          // the pointer moves in screen pixels
    setPos(clamp({ x: d.ox + (e.clientX - d.sx) / k, y: d.oy + (e.clientY - d.sy) / k }));
  };
  const up = () => { drag.current = null; };

  const save = () => {
    const c = document.createElement('canvas');
    c.width = OUT_W; c.height = OUT_H;
    const k = OUT_W / FRAME_W;
    const ctx = c.getContext('2d');
    // zoomed out the picture no longer fills the square: give it a ground,
    // or JPEG would turn the empty part black.
    ctx.fillStyle = fill;
    ctx.fillRect(0, 0, OUT_W, OUT_H);
    ctx.drawImage(img, pos.x * k, pos.y * k, w * k, h * k);
    onDone(c.toDataURL('image/jpeg', 0.88));
  };

  return (
    <div className="fixed inset-0 z-[90] flex items-center justify-center bg-[#0B1C3F]/55 p-4" role="dialog" aria-modal="true">
      <div className="w-full max-w-[360px] rounded-2xl bg-white p-5 shadow-[0_24px_60px_-20px_rgba(11,28,63,.6)]">
        <div className="mb-3 flex items-center justify-between">
          <p className="text-[15px] font-bold text-[#0B1C3F]">{title}</p>
          <button type="button" onClick={onCancel} aria-label="Fermer" className="rounded-lg p-1 text-[#64748B] hover:bg-[#F4F7FC]"><X size={18} /></button>
        </div>
        <p className="mb-3 text-[12.5px] text-[#64748B]">
          {fit ? "Glissez la photo et zoomez. « Toute l'image » : rien n'est coupé."
               : 'Glissez la photo et zoomez : ce cadre est exactement la carte Apple Wallet.'}
        </p>
        <div className={`mx-auto touch-none select-none overflow-hidden ${round ? 'rounded-full' : 'rounded-[14px]'}`}
             style={{ width: FRAME_W, height: FRAME_H, cursor: 'grab', position: 'relative',
                      background: fit ? fill : '#1C1D22' }}
             onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up}>
          <img src={url.current} alt="" draggable={false}
               style={{ position: 'absolute', left: pos.x, top: pos.y, width: w, height: h, maxWidth: 'none' }} />
          {/* where Wallet draws over the photo: logo + header, barcode, fields */}
          {guides && <>
          <div className="pointer-events-none absolute inset-x-0 top-0 h-[12%] bg-gradient-to-b from-black/35 to-transparent" />
          <div className="pointer-events-none absolute left-1/2 top-[47%] h-[25%] w-[38%] -translate-x-1/2 rounded-md border border-dashed border-white/70" />
          <div className="pointer-events-none absolute inset-x-0 bottom-0 h-[22%] bg-gradient-to-t from-black/45 to-transparent" />
          </>}
        </div>
        <label className="mt-4 flex items-center gap-2 text-[12.5px] text-[#475569]">
          <ZoomIn size={15} />
          <input type="range" min={minZoom} max="4" step="0.01" value={zoom}
                 onChange={(e) => onZoom(Number(e.target.value))} className="flex-1" />
        </label>
        {fit && (
          <div className="mt-2 flex gap-2">
            <button type="button" onClick={() => onZoom(contain)}
                    className="rounded-lg border border-[#E1E8F5] px-2.5 py-1 text-[12px] font-semibold text-[#475569]">
              Toute l'image
            </button>
            <button type="button" onClick={() => onZoom(1)}
                    className="rounded-lg border border-[#E1E8F5] px-2.5 py-1 text-[12px] font-semibold text-[#475569]">
              Remplir le cadre
            </button>
          </div>
        )}
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" onClick={onCancel} className="rounded-xl border border-[#E1E8F5] px-4 py-2 text-[13px] font-semibold text-[#475569]">Annuler</button>
          <button type="button" onClick={save} className="rounded-xl bg-[#2F6BFF] px-4 py-2 text-[13px] font-semibold text-white">Utiliser ce cadre</button>
        </div>
      </div>
    </div>
  );
}
