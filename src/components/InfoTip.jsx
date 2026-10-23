import { fitRect, viewW, viewH } from '../lib/fit';
import React, { useCallback, useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { HelpCircle } from 'lucide-react';
import { help as helpFor } from '../lib/metricHelp';

/**
 * « ? » — what a figure means, how it is computed, what it is for
 * (lib/metricHelp, user 2026-10-02).
 *
 *   <InfoTip k="ltv" />               the glossary entry « ltv »
 *   <InfoTip k="returning" page="fidelisation" />   « fidelisation:returning » first
 *
 * Opens on hover and on keyboard focus (desktop), and on a tap (phones). It
 * sits inside clickable cards, so its own clicks never reach the card. The
 * bubble is drawn in a portal with fixed coordinates, so no card's overflow
 * can clip it, and it flips to stay on screen.
 */
const W = 300;

export default function InfoTip({ k, page, className = '', size = 13 }) {
  const entry = helpFor(k, page);
  const [open, setOpen] = useState(false);
  const [pinned, setPinned] = useState(false);
  const [pos, setPos] = useState(null);
  const btn = useRef(null);
  const bubble = useRef(null);
  const id = useId();

  const place = useCallback(() => {
    if (!btn.current) return;
    const r = fitRect(btn.current);                 // the app's pixels, even when it is scaled to fit
    const vw = viewW(), vh = viewH();
    const width = Math.min(W, vw - 24);
    const left = Math.max(12, Math.min(r.left + r.width / 2 - width / 2, vw - width - 12));
    const below = r.bottom + 8;
    const h = bubble.current?.offsetHeight || 190;
    const top = below + h > vh - 8 && r.top - 8 - h > 8 ? r.top - 8 - h : below;
    setPos({ left, top, width });
  }, []);

  useEffect(() => {
    if (!open) return undefined;
    place();
    const raf = requestAnimationFrame(place);          // again, with the bubble's real height
    const away = (e) => {
      if (btn.current?.contains(e.target) || bubble.current?.contains(e.target)) return;
      setOpen(false); setPinned(false);
    };
    const esc = (e) => { if (e.key === 'Escape') { setOpen(false); setPinned(false); } };
    window.addEventListener('scroll', place, true);
    window.addEventListener('resize', place);
    document.addEventListener('mousedown', away);
    document.addEventListener('touchstart', away);
    document.addEventListener('keydown', esc);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('scroll', place, true);
      window.removeEventListener('resize', place);
      document.removeEventListener('mousedown', away);
      document.removeEventListener('touchstart', away);
      document.removeEventListener('keydown', esc);
    };
  }, [open, place]);

  if (!entry) return null;
  const stop = (e) => { e.stopPropagation(); };

  return (
    <>
      <button ref={btn} type="button" aria-label={`Comprendre : ${entry.t}`} aria-describedby={open ? id : undefined}
              aria-expanded={open}
              onClick={(e) => { e.stopPropagation(); e.preventDefault(); setPinned((p) => !p); setOpen((o) => (pinned ? false : true)); }}
              onMouseEnter={() => setOpen(true)} onMouseLeave={() => { if (!pinned) setOpen(false); }}
              onFocus={() => setOpen(true)} onBlur={() => { if (!pinned) setOpen(false); }}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') e.stopPropagation(); }}
              onMouseDown={stop} onTouchStart={stop}
              className={`inline-flex shrink-0 items-center justify-center rounded-full align-middle text-[#94A3B8] transition hover:text-[#2F6BFF] focus:text-[#2F6BFF] focus:outline-none ${className}`}>
        <HelpCircle size={size} strokeWidth={2.2} />
      </button>
      {open && createPortal(
        <div ref={bubble} id={id} role="tooltip" onClick={stop} onMouseDown={stop}
             onMouseEnter={() => setOpen(true)} onMouseLeave={() => { if (!pinned) setOpen(false); }}
             style={{ position: 'fixed', left: pos?.left ?? -9999, top: pos?.top ?? -9999, width: pos?.width ?? W, zIndex: 80 }}
             className="rounded-xl border border-[#E6EEFB] bg-white p-3.5 text-left shadow-[0_24px_48px_-18px_rgba(11,28,63,.45)]">
          <p className="mb-1.5 text-[13px] font-bold leading-snug text-[#0B1C3F]">{entry.t}</p>
          <p className="text-[12px] leading-snug text-[#334155]">{entry.what}</p>
          <p className="mt-2 text-[10.5px] font-bold uppercase tracking-wide text-[#94A3B8]">Comment c'est calculé</p>
          <p className="whitespace-pre-line text-[11.5px] leading-snug text-[#475569]">{entry.how}</p>
          <p className="mt-2 text-[10.5px] font-bold uppercase tracking-wide text-[#2F6BFF]">À quoi ça sert</p>
          <p className="text-[11.5px] leading-snug text-[#475569]">{entry.why}</p>
        </div>,
        document.body,
      )}
    </>
  );
}
