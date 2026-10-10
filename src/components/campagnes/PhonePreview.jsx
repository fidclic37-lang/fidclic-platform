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
    <div className="mx-auto w-full max-w-[300px]">
      <div className="relative overflow-hidden rounded-[44px] border-[10px] border-[#0F172A] bg-gradient-to-b from-[#3B5BFD] via-[#5B3FE0] to-[#7A2FD0] px-4 pb-6 pt-3 shadow-[0_30px_60px_-30px_rgba(15,23,42,.8)]">
        <div className="mx-auto mb-3 h-6 w-28 rounded-full bg-[#0F172A]" />
        <div className="text-center text-white">
          <Lock size={14} className="mx-auto opacity-90" />
          <p className="mt-1 text-[13px] font-medium">{DAYS[d.getDay()]} {d.getDate()} {MONTHS[d.getMonth()]}</p>
          <p className="text-[54px] font-semibold leading-none tracking-tight tabular-nums">{hh}:{mm}</p>
        </div>
        <div className="mt-6 rounded-2xl bg-white/85 p-3 text-[12.5px] leading-snug text-[#0B1C3F] shadow-lg backdrop-blur">
          <div className="mb-1 flex items-center gap-2">
            {logo && logoOk
              ? <img src={logo} alt="" onError={() => setLogoOk(false)} className="h-7 w-7 rounded-lg bg-white object-contain" />
              : <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-[#1463FF] text-[12px] font-bold text-white">{(shop || 'F').charAt(0)}</span>}
            <span translate="no" className="notranslate flex-1 truncate text-[13px] font-semibold">{shop || 'Votre commerce'}</span>
            <span className="text-[11px] text-[#64748B]">maintenant</span>
          </div>
          {!message && title && <p className="font-semibold">{icon}{title}</p>}
          <p className="break-words"><Rich text={body} /></p>
        </div>
        <div className="mt-24 flex items-center justify-between px-4 text-white">
          <span className="flex h-10 w-10 items-center justify-center rounded-full bg-black/25"><Flashlight size={16} /></span>
          <span className="flex h-10 w-10 items-center justify-center rounded-full bg-black/25"><Camera size={16} /></span>
        </div>
        <div className="mx-auto mt-3 h-1 w-28 rounded-full bg-white/80" />
      </div>
    </div>
  );
}
