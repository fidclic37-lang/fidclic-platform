import React, { useEffect, useState } from 'react';
import { Lock, Flashlight, Camera } from 'lucide-react';

/**
 * The phone of the Campagnes wizard (mockups): a lock screen at the moment the
 * message will arrive, the notification signed with the SHOP's name and logo
 * (what Apple / Google Wallet really show — user's choice, 2026-10-10), the
 * variables filled from a real recipient.
 */
const DAYS = ['dimanche', 'lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi'];
const MONTHS = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre'];

export function fillMessage(text, sample, shop) {
  const s = sample || {};
  const values = {
    'prénom': s.first_name || 'Sarah', prenom: s.first_name || 'Sarah', nom_commerce: shop || 'votre commerce',
    points: String(s.points ?? 120), 'prochaine_récompense': s.next_reward || 'votre récompense',
    points_manquants: String(s.points_missing ?? 3), visites: String(s.visits ?? 5),
  };
  return String(text || '').replace(/\{([a-zéèàù_]+)\}/gi, (m, k) => (k in values ? `\u0001${values[k]}\u0002` : m));
}

// bold for the filled variables, red for a discount (« -20% »)
function Rich({ text }) {
  const parts = [];
  String(text).split(/(\u0001[^\u0002]*\u0002|-\s?\d+(?:[.,]\d+)?\s?(?:%|€))/g).forEach((p, i) => {
    if (!p) return;
    if (p.startsWith('\u0001')) parts.push(<b key={i}>{p.slice(1, -1)}</b>);
    else if (/^-\s?\d/.test(p)) parts.push(<span key={i} className="font-semibold text-[#E11D48]">{p}</span>);
    else parts.push(<React.Fragment key={i}>{p}</React.Fragment>);
  });
  return <>{parts}</>;
}

export default function PhonePreview({ at, shop, logo, title, message, sample, icon = null }) {
  const d = at ? new Date(at) : new Date();
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  const body = message ? fillMessage(message, sample, shop) : 'Profitez-en dès maintenant !';
  const [logoOk, setLogoOk] = useState(true);
  useEffect(() => setLogoOk(true), [logo]);
  return (
    <div className="mx-auto w-full max-w-[200px]">
      {/* A real phone's proportions (≈ 9 : 19.5), thin bezel, side buttons.
          Drawn at 270 px wide it stood 585 px tall and ran the length of the
          form beside it (user, 2026-10-15) — the preview is here to be glanced
          at, not to be the page. 200 px wide keeps the shape and gives back
          the height. */}
      <div className="relative">
        <span className="absolute -left-[3px] top-[18%] h-8 w-[3px] rounded-l bg-[#1E293B]" />
        <span className="absolute -left-[3px] top-[28%] h-12 w-[3px] rounded-l bg-[#1E293B]" />
        <span className="absolute -right-[3px] top-[24%] h-16 w-[3px] rounded-r bg-[#1E293B]" />
        <div className="relative flex aspect-[9/19.5] flex-col overflow-hidden rounded-[42px] border-[7px] border-[#0F172A] bg-gradient-to-b from-[#3B5BFD] via-[#5B3FE0] to-[#7A2FD0] px-3 pb-2 pt-2.5 shadow-[0_30px_60px_-30px_rgba(15,23,42,.8)]">
          <div className="mx-auto h-[22px] w-[84px] shrink-0 rounded-full bg-[#0F172A]" />
          <div className="mt-4 text-center text-white">
            <Lock size={13} className="mx-auto opacity-90" />
            <p className="mt-1 text-[12.5px] font-medium">{DAYS[d.getDay()]} {d.getDate()} {MONTHS[d.getMonth()]}</p>
            <p className="text-[52px] font-semibold leading-none tracking-tight tabular-nums">{hh}:{mm}</p>
          </div>
          <div className="mt-5 rounded-2xl bg-white/85 p-2.5 text-[12px] leading-snug text-[#0B1C3F] shadow-lg backdrop-blur">
            <div className="mb-1 flex items-center gap-2">
              {logo && logoOk
                ? <img src={logo} alt="" onError={() => setLogoOk(false)} className="h-6 w-6 rounded-md bg-white object-contain" />
                : <span className="flex h-6 w-6 items-center justify-center rounded-md bg-[#1463FF] text-[11px] font-bold text-white">{(shop || 'F').charAt(0)}</span>}
              <span translate="no" className="notranslate flex-1 truncate text-[12.5px] font-semibold">{shop || 'Votre commerce'}</span>
              <span className="text-[10.5px] text-[#64748B]">maintenant</span>
            </div>
            {!message && title && <p className="font-semibold">{icon}{title}</p>}
            <p className="break-words"><Rich text={body} /></p>
          </div>
          <div className="flex-1" />
          <div className="flex items-center justify-between px-3 text-white">
            <span className="flex h-9 w-9 items-center justify-center rounded-full bg-black/25"><Flashlight size={15} /></span>
            <span className="flex h-9 w-9 items-center justify-center rounded-full bg-black/25"><Camera size={15} /></span>
          </div>
          <div className="mx-auto mb-0.5 mt-3 h-1 w-24 shrink-0 rounded-full bg-white/80" />
        </div>
      </div>
    </div>
  );
}
