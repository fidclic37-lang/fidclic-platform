import React, { useEffect, useState } from 'react';
import { Info } from 'lucide-react';
import { fill } from './meta';

/**
 * « Aperçu de la notification » — one preview only, the Wallet notification
 * (user, 2026-10-11: no « Push classique » / « Wallet » tabs). The shop's name
 * and logo sign it; the variables are filled from a real client; the action
 * button shows as it does on the card.
 */
export default function WalletPreview({ shop, logo, title, body, image, button, sample, extra }) {
  const [logoOk, setLogoOk] = useState(true);
  useEffect(() => setLogoOk(true), [logo]);
  const t = fill(title, sample, shop, extra);
  const b = fill(body, sample, shop, extra);
  return (
    <section className="rounded-2xl border border-[#E6EEFB] bg-white p-4 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
      <p className="mb-3 flex items-center gap-2 text-[14.5px] font-bold text-[#0B1C3F]">
        Aperçu de la notification
        <span title="Ce que vos clients verront sur leur téléphone, avec leurs propres informations."><Info size={15} className="text-[#64748B]" /></span>
      </p>
      <p className="mb-2 inline-flex rounded-lg bg-[#EEF4FF] px-3 py-1 text-[12px] font-semibold text-[#1463FF]">Notification Wallet</p>
      <div className="rounded-2xl bg-gradient-to-br from-[#1E6BFF] via-[#5B3FE0] to-[#D946EF] p-3">
        <div className="rounded-2xl bg-white/95 p-3 shadow-lg">
          <div className="mb-1.5 flex items-center gap-2">
            {logo && logoOk
              ? <img src={logo} alt="" onError={() => setLogoOk(false)} className="h-7 w-7 rounded-lg bg-white object-contain" />
              : <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-[#1463FF] text-[11.5px] font-bold text-white">{(shop || 'F').charAt(0)}</span>}
            <span translate="no" className="notranslate min-w-0 flex-1 truncate text-[12.5px] font-bold text-[#0B1C3F]">{shop || 'Votre commerce'}</span>
            <span className="text-[11px] text-[#64748B]">maintenant</span>
          </div>
          <div className="flex gap-3">
            <div className="min-w-0 flex-1">
              <p className="break-words text-[12.5px] font-bold leading-snug text-[#0B1C3F]">{t || 'Titre de la notification'}</p>
              <p className="mt-0.5 break-words text-[12px] leading-snug text-[#334155]">{b || 'Votre message apparaîtra ici.'}</p>
            </div>
            {image && <img src={image} alt="" className="h-12 w-12 shrink-0 rounded-xl object-cover" />}
          </div>
          {button && (
            <span className="mt-2.5 block rounded-xl bg-[#F1F5FF] py-2 text-center text-[12.5px] font-semibold text-[#1463FF]">{button}</span>
          )}
        </div>
      </div>
      {button && (
        <p className="mt-2 text-[11px] leading-snug text-[#64748B]">
          Apple et Google Wallet n'affichent pas de bouton dans la notification : un appui ouvre la carte du client, où ce bouton s'affiche en haut (et au dos de la carte Wallet).
        </p>
      )}
    </section>
  );
}
