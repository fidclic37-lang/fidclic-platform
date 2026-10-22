import React from 'react';
import { Lock } from 'lucide-react';

/* A page this account may not « Voir » (Équipe & accès): the platform stays
   whole around it — the menu, the other pages — and this says why (user,
   2026-10-22: « jis section ki permission nhi hai us pr jaane se dikha de
   ki not authorised »). The server refuses its calls too. */
export default function NoPageAccess({ label }) {
  return (
    <div role="alert" className="mx-auto mt-10 max-w-lg rounded-2xl border border-[#E6EEFB] bg-white p-8 text-center shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
      <span className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-[#FFF4E5] text-[#B45309]">
        <Lock size={24} />
      </span>
      <p className="text-[19px] font-bold text-[#0B1C3F]">Accès non autorisé</p>
      <p className="mt-2 text-[14px] leading-relaxed text-[#475569]">
        Vous n'avez pas la permission d'ouvrir {label ? <b>« {label} »</b> : 'cette page'}.
        Demandez-la au propriétaire du commerce (Paramètres › Équipe &amp; accès).
      </p>
    </div>
  );
}
