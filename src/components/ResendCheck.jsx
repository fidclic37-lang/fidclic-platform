import React, { useCallback, useRef, useState } from 'react';
import { AlertTriangle, Check, X } from 'lucide-react';
import { ownerAPI } from '../lib/api';

/**
 * « Déjà contactés » — the pop-up before a campaign goes out (user, 2026-10-02).
 *
 * A client can be in two segments at once. Before sending, the page asks the
 * server who on this list already received a campaign in the last few days
 * (features/resend_guard.py). If nobody did, the send goes straight on. If some
 * did, they are listed — when, and what they got — and the owner ticks who
 * should get this one too. Nobody is ticked at first: sending twice is the
 * choice that has to be made, not the one that happens.
 *
 *   const [guard, resendModal] = useResendCheck();
 *   const exclude = await guard({ customer_ids });   // null = cancelled
 *   ...send with exclude_ids: exclude
 *   return <>{resendModal}...</>
 */
const nf = (n) => (n ?? 0).toLocaleString('fr-FR');

const when = (iso) => {
  const d = new Date(iso);
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const day = new Date(d); day.setHours(0, 0, 0, 0);
  const diff = Math.round((today - day) / 86400000);
  const hm = d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
  if (diff <= 0) return `Aujourd'hui à ${hm}`;
  if (diff === 1) return `Hier à ${hm}`;
  return `Il y a ${diff} jours`;
};

export function useResendCheck() {
  const [state, setState] = useState(null);       // { recent, total, days, picked:Set }
  const resolver = useRef(null);

  const guard = useCallback(async (body) => {
    const { data } = await ownerAPI.campaignRecentCheck(body);
    if (!data.recent?.length) return [];
    return new Promise((resolve) => {
      resolver.current = resolve;
      setState({ recent: data.recent, total: data.total, days: data.window_days, picked: new Set() });
    });
  }, []);

  const finish = (value) => {
    const r = resolver.current;
    resolver.current = null;
    setState(null);
    if (r) r(value);
  };

  let modal = null;
  if (state) {
    const { recent, total, days, picked } = state;
    const toggle = (id) => setState((s) => {
      const next = new Set(s.picked);
      if (next.has(id)) next.delete(id); else next.add(id);
      return { ...s, picked: next };
    });
    const all = picked.size === recent.length;
    const excluded = recent.filter((r) => !picked.has(r.id)).map((r) => r.id);
    const going = total - excluded.length;
    modal = (
      <div className="fixed inset-0 z-[60] flex items-center justify-center bg-[#0B1C3F]/40 p-4" onClick={() => finish(null)}>
        <div role="dialog" aria-modal="true" aria-labelledby="resend-title"
             className="flex max-h-[88vh] w-full max-w-xl flex-col rounded-2xl bg-white shadow-[0_30px_70px_-30px_rgba(11,28,63,.6)]"
             onClick={(e) => e.stopPropagation()}>
          <div className="flex items-start gap-3 border-b border-[#EEF3FB] p-5">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#FFF7E6] text-[#B45309]">
              <AlertTriangle size={19} />
            </span>
            <div className="min-w-0 flex-1">
              <h3 id="resend-title" className="text-[16px] font-bold text-[#0B1C3F]">
                {nf(recent.length)} client{recent.length > 1 ? 's ont' : ' a'} déjà reçu une campagne récemment
              </h3>
              <p className="mt-0.5 text-[12.5px] leading-snug text-[#64748B]">
                Dans les {days} derniers jours. Voulez-vous vraiment leur envoyer celle-ci aussi ?
                Cochez ceux qui doivent la recevoir ; les autres ne la recevront pas.
              </p>
            </div>
            <button type="button" onClick={() => finish(null)} aria-label="Fermer" className="text-[#94A3B8] hover:text-[#334155]">
              <X size={18} />
            </button>
          </div>

          <div className="flex items-center justify-between px-5 pt-3 text-[12px]">
            <span className="text-[#64748B]">{nf(picked.size)} coché{picked.size > 1 ? 's' : ''} sur {nf(recent.length)}</span>
            <button type="button" className="font-semibold text-[#2F6BFF] hover:underline"
                    onClick={() => setState((s) => ({ ...s, picked: all ? new Set() : new Set(recent.map((r) => r.id)) }))}>
              {all ? 'Tout décocher' : 'Tout cocher'}
            </button>
          </div>

          <ul className="mx-5 my-3 min-h-0 flex-1 divide-y divide-[#EEF3FB] overflow-y-auto rounded-xl border border-[#E6EEFB]">
            {recent.map((r) => {
              const on = picked.has(r.id);
              return (
                <li key={r.id}>
                  <label className="flex cursor-pointer items-center gap-3 px-3 py-2.5 hover:bg-[#F5F8FE]">
                    <span className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-md border transition ${
                      on ? 'border-[#2F6BFF] bg-[#2F6BFF] text-white' : 'border-[#CBD5E1] bg-white'}`}>
                      {on && <Check size={13} strokeWidth={3} />}
                    </span>
                    <input type="checkbox" className="sr-only" checked={on} onChange={() => toggle(r.id)} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13px] font-semibold text-[#0B1C3F]">{r.name}</span>
                      <span className="block truncate text-[11.5px] text-[#64748B]">
                        {r.kind} « {r.title} »
                      </span>
                    </span>
                    <span className="shrink-0 text-right text-[11.5px] font-medium text-[#B45309]">{when(r.at)}</span>
                  </label>
                </li>
              );
            })}
          </ul>

          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-[#EEF3FB] p-5">
            <p className="text-[12px] text-[#64748B]">
              {going > 0
                ? <>La campagne partira à <b className="text-[#0B1C3F]">{nf(going)}</b> client{going > 1 ? 's' : ''}.</>
                : 'Plus personne ne recevra cette campagne.'}
            </p>
            <div className="flex gap-2">
              <button type="button" onClick={() => finish(null)}
                      className="rounded-xl border border-[#E6EEFB] px-4 py-2.5 text-[13px] font-semibold text-[#334155]">
                Annuler
              </button>
              <button type="button" disabled={going <= 0} onClick={() => finish(excluded)}
                      className="rounded-xl bg-[#2F6BFF] px-4 py-2.5 text-[13px] font-semibold text-white transition hover:bg-[#2559DB] disabled:opacity-50">
                Envoyer à {nf(going)} client{going > 1 ? 's' : ''}
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }
  return [guard, modal];
}
