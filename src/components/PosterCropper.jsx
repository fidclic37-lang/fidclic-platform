import React, { useEffect, useRef, useState } from 'react';
import { X, ZoomIn } from 'lucide-react';

/**
 * PosterCropper — frame a photo for the iOS 27 poster (user, 2026-10-06:
 * « bg mein puri image rhe », like Apple's Museum sample, and nothing cut that
 * the owner did not choose). The photo always covers the whole card; the
 * owner drags it and zooms to pick what shows, and gets Apple's 345 × 505 pt
 * at 3× (1035 × 1515) as a JPEG.
 *
 * Props: file (a File), onDone(dataUrl), onCancel().
 */
const OUT_W = 1035;
const OUT_H = 1515;
const FRAME_W = 280;
const FRAME_H = Math.round(FRAME_W * (OUT_H / OUT_W));

export default function PosterCropper({ file, onDone, onCancel }) {
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
      const base = Math.max(FRAME_W / im.width, FRAME_H / im.height);
      setPos({ x: (FRAME_W - im.width * base) / 2, y: (FRAME_H - im.height * base) / 2 });
    };
    im.src = url.current;
    return () => URL.revokeObjectURL(url.current);
  }, [file]);

  if (!img) return null;
  const base = Math.max(FRAME_W / img.width, FRAME_H / img.height);
  const scale = base * zoom;
  const w = img.width * scale;
  const h = img.height * scale;
  // the photo must always cover the frame — never an empty edge
  const clamp = (p, sw = w, sh = h) => ({
    x: Math.min(0, Math.max(FRAME_W - sw, p.x)),
    y: Math.min(0, Math.max(FRAME_H - sh, p.y)),
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
    setPos(clamp({ x: d.ox + e.clientX - d.sx, y: d.oy + e.clientY - d.sy }));
  };
  const up = () => { drag.current = null; };

  const save = () => {
    const c = document.createElement('canvas');
    c.width = OUT_W; c.height = OUT_H;
    const k = OUT_W / FRAME_W;
    c.getContext('2d').drawImage(img, pos.x * k, pos.y * k, w * k, h * k);
    onDone(c.toDataURL('image/jpeg', 0.88));
  };

  return (
    <div className="fixed inset-0 z-[90] flex items-center justify-center bg-[#0B1C3F]/55 p-4" role="dialog" aria-modal="true">
      <div className="w-full max-w-[360px] rounded-2xl bg-white p-5 shadow-[0_24px_60px_-20px_rgba(11,28,63,.6)]">
        <div className="mb-3 flex items-center justify-between">
          <p className="text-[15px] font-bold text-[#0B1C3F]">Cadrer l'image poster</p>
          <button type="button" onClick={onCancel} aria-label="Fermer" className="rounded-lg p-1 text-[#64748B] hover:bg-[#F4F7FC]"><X size={18} /></button>
        </div>
        <p className="mb-3 text-[12.5px] text-[#64748B]">Glissez la photo et zoomez : ce cadre est exactement la carte Apple Wallet.</p>
        <div className="mx-auto touch-none select-none overflow-hidden rounded-[14px] bg-[#1C1D22]"
             style={{ width: FRAME_W, height: FRAME_H, cursor: 'grab', position: 'relative' }}
             onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up}>
          <img src={url.current} alt="" draggable={false}
               style={{ position: 'absolute', left: pos.x, top: pos.y, width: w, height: h, maxWidth: 'none' }} />
          {/* where Wallet draws over the photo: logo + header, barcode, fields */}
          <div className="pointer-events-none absolute inset-x-0 top-0 h-[12%] bg-gradient-to-b from-black/35 to-transparent" />
          <div className="pointer-events-none absolute left-1/2 top-[47%] h-[25%] w-[38%] -translate-x-1/2 rounded-md border border-dashed border-white/70" />
          <div className="pointer-events-none absolute inset-x-0 bottom-0 h-[22%] bg-gradient-to-t from-black/45 to-transparent" />
        </div>
        <label className="mt-4 flex items-center gap-2 text-[12.5px] text-[#475569]">
          <ZoomIn size={15} />
          <input type="range" min="1" max="4" step="0.01" value={zoom} onChange={(e) => onZoom(Number(e.target.value))} className="flex-1" />
        </label>
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" onClick={onCancel} className="rounded-xl border border-[#E1E8F5] px-4 py-2 text-[13px] font-semibold text-[#475569]">Annuler</button>
          <button type="button" onClick={save} className="rounded-xl bg-[#2F6BFF] px-4 py-2 text-[13px] font-semibold text-white">Utiliser ce cadre</button>
        </div>
      </div>
    </div>
  );
}
