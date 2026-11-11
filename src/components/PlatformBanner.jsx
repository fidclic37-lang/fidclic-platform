import React, { useEffect, useState } from 'react';
import { Info, AlertTriangle, X } from 'lucide-react';
import { platformAPI } from '../lib/api';

/* Floating at the bottom of the window, outside <main> (see DashboardLayout);
   `above` lifts it over the « Accéder au compte » bar.
   The maintenance banner FidClic's team sets in Super admin › Paramètres ›
   Plateforme (2026-11-11): on top of every shop's pages between its start
   and end. « × » hides that banner for this tab's session only; a new banner
   (new text or dates) shows again. */

const KEY = 'fidclic:platform-banner-hidden';
const EVERY_MS = 5 * 60 * 1000;

export default function PlatformBanner({ above = false }) {
  const [b, setB] = useState(null);
  const [hidden, setHidden] = useState(() => { try { return sessionStorage.getItem(KEY) || ''; } catch { return ''; } });
  useEffect(() => {
    let off = false;
    const load = () => { if (!document.hidden) platformAPI.status().then(({ data }) => { if (!off) setB(data?.banner || null); }).catch(() => {}); };
    load();
    const t = setInterval(load, EVERY_MS);
    return () => { off = true; clearInterval(t); };
  }, []);
  if (!b || hidden === b.id) return null;
  const warn = b.level === 'warning';
  const I = warn ? AlertTriangle : Info;
  return (
    <div role="status" data-testid="platform-banner"
         className={`fixed left-1/2 ${above ? 'bottom-24' : 'bottom-4'} z-[65] flex w-[min(760px,calc(100%-32px))] -translate-x-1/2 items-start gap-2.5 rounded-xl border px-4 py-2.5 text-[13.5px] shadow-[0_12px_32px_-14px_rgba(11,28,63,.45)] ${warn ? 'border-[#FDE68A] bg-[#FFFBEB] text-[#92400E]' : 'border-[#BFD3FF] bg-[#EFF5FF] text-[#1E40AF]'}`}>
      <I size={16} className="mt-0.5 shrink-0" />
      <span className="min-w-0 flex-1 whitespace-pre-line break-words"><b translate="no">FidClic</b> · {b.message}</span>
      <button type="button" aria-label="Masquer le bandeau" onClick={() => { setHidden(b.id); try { sessionStorage.setItem(KEY, b.id); } catch { /* private mode */ } }}
              className="shrink-0 opacity-70 hover:opacity-100"><X size={15} /></button>
    </div>
  );
}
