import React, { useEffect, useState } from 'react';
import { Info } from 'lucide-react';
import { fill } from './meta';

/**
 * « Aperçu de la notification » — the message on a locked iPhone, as the
 * client will see it (user, 2026-10-11: one preview, the lock screen, in
 * every automation, following each change live). The shop's name and logo
 * sign it; the variables are filled from a real client.
 */
const parisNow = () => {
  const d = new Date();
  const time = new Intl.DateTimeFormat('fr-FR', { timeZone: 'Europe/Paris', hour: '2-digit', minute: '2-digit' }).format(d);
  const day = new Intl.DateTimeFormat('fr-FR', { timeZone: 'Europe/Paris', weekday: 'long', day: 'numeric', month: 'long' }).format(d);
  return { time, day: day.charAt(0).toUpperCase() + day.slice(1) };
};

export default function LockScreenPreview({ shop, logo, title, body, image, button, sample, extra, note, compact, bigImage }) {
  const [logoOk, setLogoOk] = useState(true);
  const [now, setNow] = useState(parisNow);
  useEffect(() => setLogoOk(true), [logo]);
  useEffect(() => { const t = setInterval(() => setNow(parisNow()), 30000); return () => clearInterval(t); }, []);
  const t = fill(title, sample, shop, extra);
  const b = fill(body, sample, shop, extra);
  return (
    <section className="rounded-2xl border border-[#E6EEFB] bg-white p-4 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
      <p className="mb-3 flex items-center gap-2 text-[14.5px] font-bold text-[#0B1C3F]">
        Aperçu de la notification
        <span title="Ce que vos clients verront sur l'écran verrouillé de leur téléphone, avec leurs propres informations."><Info size={15} className="text-[#64748B]" /></span>
      </p>
      <div className="mx-auto w-full max-w-[300px] rounded-[38px] bg-[#0B1220] p-[7px] shadow-[0_24px_50px_-28px_rgba(11,28,63,.7)]">
        <div className={`relative overflow-hidden rounded-[32px] bg-[radial-gradient(120%_80%_at_85%_10%,#F59E0B_0%,rgba(245,158,11,0)_45%),linear-gradient(160deg,#0F1D4A_0%,#1E3A8A_45%,#2F6BFF_70%,#F97316_100%)] px-3 pb-5 ${compact ? 'pt-7' : 'pt-9'}`}>
          <span className="absolute left-1/2 top-2 h-[18px] w-[86px] -translate-x-1/2 rounded-full bg-black" />
          <p className={`text-center font-light leading-none text-white ${compact ? 'text-[40px]' : 'text-[52px]'}`} aria-label="Heure">{now.time}</p>
          <p className="mt-1 text-center text-[13px] font-medium text-white/90">{now.day}</p>
          <div className={`${compact ? 'mt-4' : 'mt-7'} rounded-2xl bg-white/90 p-3 shadow-lg backdrop-blur`}>
            <div className="mb-1 flex items-center gap-2">
              {logo && logoOk
                ? <img src={logo} alt="" onError={() => setLogoOk(false)} className="h-6 w-6 rounded-md bg-white object-contain" />
                : <span className="flex h-6 w-6 items-center justify-center rounded-md bg-[#1463FF] text-[11px] font-bold text-white">{(shop || 'F').charAt(0)}</span>}
              <span translate="no" className="notranslate min-w-0 flex-1 truncate text-[12px] font-bold text-[#0B1C3F]">{shop || 'Votre commerce'}</span>
              <span className="text-[11px] text-[#64748B]">maintenant</span>
            </div>
            <div className="flex gap-2.5">
              <div className="min-w-0 flex-1">
                <p className="break-words text-[12.5px] font-bold leading-snug text-[#0B1C3F]">{t || 'Titre de la notification'}</p>
                <p className="mt-0.5 break-words text-[12px] leading-snug text-[#334155]">{b || 'Votre message apparaîtra ici.'}</p>
              </div>
              {image && !bigImage && <img src={image} alt="" className="h-11 w-11 shrink-0 rounded-lg object-cover" />}
            </div>
            {/* an expanded notification (Android / the card): the picture large, the button under it */}
            {image && bigImage && <img src={image} alt="" className="mt-2 w-full rounded-xl object-cover" />}
            {button && bigImage && (
              <span className="mt-2 block rounded-xl bg-[#1463FF] py-2 text-center text-[12px] font-semibold text-white">{button}</span>
            )}
          </div>
          {button && !bigImage && (
            <span className="mt-2 block rounded-xl bg-white/85 py-2 text-center text-[12px] font-semibold text-[#1463FF]">{button}</span>
          )}
        </div>
      </div>
      {(button || note) && (
        <p className="mt-2 text-[11px] leading-snug text-[#64748B]">
          {note || "Apple et Google Wallet n'affichent pas de bouton dans la notification : un appui ouvre la carte du client, où ce bouton s'affiche en haut (et au dos de la carte Wallet)."}
        </p>
      )}
    </section>
  );
}
