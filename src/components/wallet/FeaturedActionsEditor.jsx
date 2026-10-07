import React from 'react';
import { ArrowDown, ArrowUp, X } from 'lucide-react';
import { ACTION_LOOK } from './walletLook';

/**
 * The two tiles iOS 27 draws under the pass — Apple's 14 Featured Actions,
 * picked like in Pass Designer (click a tile to add it, two at most), each
 * with what it needs: a link, a phone number or an Apple Maps place.
 *
 * Props: types ([{type, label, needs}] from /owner/card/settings), value
 * ([{type, url?, phone?, place?}]), onChange(rows), disabled.
 */
const HTTPS = /^https:\/\/[^/\s]+\.[^/\s]+/;

const HINT = {
  link: 'Sans lien, le bouton ouvre le site web indiqué dans Établissement ; sans site web, il n’apparaît pas.',
  link_optional: 'Laissez vide pour ouvrir la page FidClic du client (offres, avantages).',
  phone: 'Laissez vide pour le téléphone indiqué dans Établissement.',
  place: 'Dans Plans : touchez votre commerce › Partager › Copier le lien, puis collez-le ici.',
};

function Need({ row, need, onChange }) {
  const cls = 'w-full rounded-lg border border-[#E1E8F5] bg-white px-3 py-2 text-[12.5px] text-[#0B1C3F] outline-none focus:border-[#2F6BFF]';
  if (need === 'phone') {
    return <input className={cls} value={row.phone || ''} placeholder="02 47 00 00 00" onChange={(e) => onChange({ ...row, phone: e.target.value })} />;
  }
  if (need === 'place') {
    return <input className={cls} value={row.place || ''} placeholder="https://maps.apple.com/place?place-id=…" onChange={(e) => onChange({ ...row, place: e.target.value })} />;
  }
  return (
    <input className={cls} value={row.url || ''} onChange={(e) => onChange({ ...row, url: e.target.value })}
           placeholder={need === 'link_optional' ? 'https://… (facultatif)' : 'https://… (votre page de réservation, commande…)'} />
  );
}

export default function FeaturedActionsEditor({ types = [], value = [], onChange, disabled = false }) {
  const rows = (value || []).filter((r) => r && r.type).slice(0, 2);
  const meta = (t) => types.find((x) => x.type === t) || { type: t, label: t, needs: 'link' };
  const set = (next) => onChange(next.filter((r) => r && r.type));
  const missing = (r) => {
    const need = meta(r.type).needs;
    if (need === 'link') return !HTTPS.test((r.url || '').trim());
    if (need === 'place') return !(r.place || '').trim();
    return false;
  };

  return (
    <div className="space-y-3">
      {rows.length === 0 && <p className="text-[12px] text-[#94A3B8]">Aucun bouton : choisissez-en un ou deux ci-dessous.</p>}
      {rows.map((r, i) => {
        const m = meta(r.type);
        const look = ACTION_LOOK[r.type] || {};
        const Icon = look.Icon;
        return (
          <div key={r.type} className="rounded-xl border border-[#E6EEFB] bg-[#FAFCFF] p-3">
            <div className="mb-2 flex items-center gap-2">
              {Icon && (
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-white" style={{ background: look.color }}>
                  <Icon size={13} strokeWidth={2.4} />
                </span>
              )}
              <p className="min-w-0 flex-1 truncate text-[12.5px] font-semibold text-[#0B1C3F]">{m.label}</p>
              <button type="button" disabled={disabled || i === 0} onClick={() => set([rows[1], rows[0]])} aria-label="Monter"
                      className="rounded p-1 text-[#64748B] hover:bg-white disabled:opacity-30"><ArrowUp size={14} /></button>
              <button type="button" disabled={disabled || i === rows.length - 1} onClick={() => set([rows[1], rows[0]])} aria-label="Descendre"
                      className="rounded p-1 text-[#64748B] hover:bg-white disabled:opacity-30"><ArrowDown size={14} /></button>
              <button type="button" disabled={disabled} onClick={() => set(rows.filter((_, j) => j !== i))} aria-label="Retirer le bouton"
                      className="rounded p-1 text-[#E5484D] hover:bg-[#FEF2F2]"><X size={14} /></button>
            </div>
            <Need row={r} need={m.needs} onChange={(next) => set(rows.map((x, j) => (j === i ? next : x)))} />
            <p className={`mt-1 text-[11.5px] ${missing(r) ? 'text-[#B45309]' : 'text-[#94A3B8]'}`}>{HINT[m.needs]}</p>
          </div>
        );
      })}

      <div>
        <p className="mb-1.5 text-[11.5px] text-[#94A3B8]">
          {rows.length >= 2 ? 'Deux boutons au maximum : retirez-en un pour en ajouter un autre.' : 'Cliquez sur un bouton pour l’ajouter. Apple choisit l’icône et traduit le texte.'}
        </p>
        <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">
          {types.map((t) => {
            const look = ACTION_LOOK[t.type] || {};
            const Icon = look.Icon;
            const taken = rows.some((r) => r.type === t.type);
            return (
              <button key={t.type} type="button" disabled={disabled || taken || rows.length >= 2}
                      onClick={() => set([...rows, { type: t.type }])}
                      className={`flex items-center gap-2 rounded-lg border px-2 py-1.5 text-left text-[11.5px] font-semibold transition ${taken ? 'border-[#2F6BFF] bg-[#EAF1FF] text-[#2F6BFF]' : 'border-[#E6EEFB] bg-white text-[#334155] hover:border-[#2F6BFF] disabled:opacity-40'}`}>
                {Icon && (
                  <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-white" style={{ background: look.color }}>
                    <Icon size={11} strokeWidth={2.4} />
                  </span>
                )}
                <span className="min-w-0 leading-tight">{t.label}</span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
