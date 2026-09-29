import React, { useCallback, useEffect, useState } from 'react';
import { Check, X, Loader2, Store, Users, Inbox } from 'lucide-react';
import { ownerAPI } from '../lib/api';

/**
 * « À valider » — what the scenarios prepared this morning, per
 * establishment. Nothing leaves until the owner, an administrateur or a
 * manager covering that establishment validates it (features/push_wallet.py).
 */
const nf = (n) => (n ?? 0).toLocaleString('fr-FR');
const when = (iso) => {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' }) + ' · '
    + d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
};

export default function PendingLotsPanel({ onChanged }) {
  const [lots, setLots] = useState(null);
  const [busy, setBusy] = useState('');
  const [msg, setMsg] = useState('');
  const [err, setErr] = useState('');

  const load = useCallback(() => {
    ownerAPI.pushWalletPending()
      .then(({ data }) => setLots(data.lots || []))
      .catch((e) => { setLots([]); setErr(e?.response?.data?.detail || 'Impossible de charger les envois à valider.'); });
  }, []);
  useEffect(() => { load(); }, [load]);

  const act = async (lot, approve) => {
    setBusy(lot.id); setErr(''); setMsg('');
    try {
      if (approve) {
        const { data } = await ownerAPI.approvePushWalletLot(lot.id);
        setMsg(`« ${lot.scenario} » envoyé à ${nf(data.sent)} client${data.sent > 1 ? 's' : ''}`
          + (data.skipped ? ` (${nf(data.skipped)} déjà contacté${data.skipped > 1 ? 's' : ''} récemment).` : '.'));
      } else {
        await ownerAPI.skipPushWalletLot(lot.id);
        setMsg(`« ${lot.scenario} » ignoré : rien n'a été envoyé.`);
      }
      load(); onChanged?.();
    } catch (e) { setErr(e?.response?.data?.detail || "L'action n'a pas abouti."); load(); }
    finally { setBusy(''); }
  };

  return (
    <div className="p-4 sm:p-5">
      <p className="mb-4 text-[12.5px] leading-snug text-[#64748B]">
        Chaque matin, vos scénarios préparent leurs envois ici, par établissement. Rien ne part sans validation.
        Seul l'anniversaire est envoyé automatiquement.
      </p>
      {msg && <p className="mb-3 rounded-xl bg-[#E7F7EE] px-4 py-2.5 text-[12.5px] text-[#0F8B58]">{msg}</p>}
      {err && <p className="mb-3 rounded-xl bg-[#FEECEC] px-4 py-2.5 text-[12.5px] text-[#C0392B]">{err}</p>}
      {lots === null ? (
        <p className="py-10 text-center text-[13px] text-[#64748B]"><Loader2 size={16} className="mr-2 inline animate-spin" /> Chargement…</p>
      ) : lots.length === 0 ? (
        <div className="flex flex-col items-center gap-2 py-12 text-center">
          <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[#EAF1FF] text-[#2F6BFF]"><Inbox size={20} /></span>
          <p className="text-[13.5px] font-semibold text-[#0B1C3F]">Rien à valider</p>
          <p className="text-[12.5px] text-[#64748B]">Les prochains envois préparés apparaîtront ici.</p>
        </div>
      ) : (
        <ul className="space-y-3">
          {lots.map((lot) => (
            <li key={lot.id} className="rounded-2xl border border-[#E6EEFB] p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-[14px] font-bold text-[#0B1C3F]">{lot.scenario}</p>
                  <p className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-[#64748B]">
                    <span className="inline-flex items-center gap-1"><Store size={12} /> {lot.store}</span>
                    <span className="inline-flex items-center gap-1"><Users size={12} /> {nf(lot.count)} client{lot.count > 1 ? 's' : ''}</span>
                    <span>Préparé le {when(lot.prepared_at)}</span>
                  </p>
                </div>
                <div className="flex shrink-0 gap-2">
                  <button type="button" onClick={() => act(lot, false)} disabled={!!busy}
                          className="inline-flex items-center gap-1.5 rounded-xl border border-[#E6EEFB] px-3.5 py-2 text-[12.5px] font-semibold text-[#475569] hover:border-[#C0392B] hover:text-[#C0392B] disabled:opacity-50">
                    <X size={14} /> Ignorer
                  </button>
                  <button type="button" onClick={() => act(lot, true)} disabled={!!busy}
                          className="inline-flex items-center gap-1.5 rounded-xl bg-[#2F6BFF] px-3.5 py-2 text-[12.5px] font-semibold text-white hover:bg-[#2559DB] disabled:opacity-50">
                    {busy === lot.id ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />} Valider et envoyer
                  </button>
                </div>
              </div>
              <div className="mt-3 rounded-xl bg-[#F4F7FC] px-3.5 py-2.5">
                <p className="text-[12.5px] font-semibold text-[#0B1C3F]">{lot.title}</p>
                <p className="text-[12px] leading-snug text-[#475569]">{lot.body}</p>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
