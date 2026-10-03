import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Loader2, RotateCcw, X } from 'lucide-react';
import { ownerAPI } from '../lib/api';

/**
 * Paramètres › « Réinitialiser » (user, 2026-10-03): puts the tab back as it
 * was before its last save, after a confirmation. Each press goes one save
 * further back (features/settings_versions.py keeps the last 20).
 *
 * Shown only where the server keeps versions and to who may use them (the
 * owner; Préférences: everyone, for their own account). Disabled, with the
 * reason, while there is nothing to undo.
 */
const NOTES = {
  etablissement: 'Un point de vente ajouté depuis reste en place.',
  'lien-inscription': "Si l'ancien nom du lien a été pris entre-temps par un autre commerce, le lien actuel est conservé.",
  equipe: 'Les comptes créés ou supprimés et les mots de passe ne changent pas.',
  preferences: 'Seulement vos préférences, pas celles de votre équipe.',
  api: 'Les webhooks créés ou supprimés depuis, et les clés API, ne changent pas.',
};

const when = (iso) => {
  if (!iso) return '';
  const d = new Date(iso);
  return `${d.toLocaleDateString('fr-FR', { day: 'numeric', month: 'long' })} à ${d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}`;
};

export default function ResetSection({ section, label, onReverted }) {
  const [st, setSt] = useState(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [toast, setToast] = useState(null);
  const confirmBtn = useRef(null);

  const load = useCallback(() => {
    ownerAPI.settingsVersion(section).then(({ data }) => setSt(data)).catch(() => setSt(null));
  }, [section]);
  useEffect(() => { setSt(null); load(); }, [load]);
  // A save in the tab: now there is something to undo.
  useEffect(() => {
    const on = () => window.setTimeout(load, 150);
    window.addEventListener('fidclic:settings-saved', on);
    return () => window.removeEventListener('fidclic:settings-saved', on);
  }, [load]);
  useEffect(() => {
    if (!open) return undefined;
    const t = window.setTimeout(() => confirmBtn.current?.focus(), 30);
    const esc = (e) => { if (e.key === 'Escape' && !busy) setOpen(false); };
    document.addEventListener('keydown', esc);
    return () => { window.clearTimeout(t); document.removeEventListener('keydown', esc); };
  }, [open, busy]);
  useEffect(() => {
    if (!toast) return undefined;
    const t = window.setTimeout(() => setToast(null), 6000);
    return () => window.clearTimeout(t);
  }, [toast]);

  if (!st?.supported || !st.allowed) return null;

  const go = async () => {
    setBusy(true); setErr('');
    try {
      const { data } = await ownerAPI.revertSettings(section);
      setOpen(false);
      setSt(data);
      setToast({ text: `« ${label} » est revenu à son état d'avant l'enregistrement du ${when(st.saved_at)}.`, notes: data.notes || [] });
      onReverted?.();
    } catch (e) {
      setErr(e?.response?.data?.detail || 'La réinitialisation a échoué. Réessayez.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <button type="button" onClick={() => { setErr(''); setOpen(true); }} disabled={!st.available}
              title={st.available ? `Annuler le dernier enregistrement (${when(st.saved_at)})` : 'Aucun enregistrement à annuler dans cette section'}
              className="inline-flex items-center gap-1.5 rounded-xl border border-[#E6EEFB] bg-white px-3.5 py-2.5 text-[12.5px] font-medium text-[#334155] transition hover:border-[#F5C2C2] hover:text-[#C0392B] disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:border-[#E6EEFB] disabled:hover:text-[#334155]">
        <RotateCcw size={14} /> Réinitialiser
      </button>

      {open && createPortal(
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-[#0B1C3F]/40 p-4" onMouseDown={() => !busy && setOpen(false)}>
          <div role="dialog" aria-modal="true" aria-labelledby="reset-title" onMouseDown={(e) => e.stopPropagation()}
               className="relative w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl">
            <button type="button" aria-label="Fermer" onClick={() => setOpen(false)} disabled={busy}
                    className="absolute right-3 top-3 rounded-lg p-1 text-[#94A3B8] hover:bg-[#F4F7FC]"><X size={18} /></button>
            <span className="mb-3 grid h-11 w-11 place-items-center rounded-xl bg-[#FEECEC] text-[#C0392B]"><RotateCcw size={20} /></span>
            <h2 id="reset-title" className="text-[18px] font-bold text-[#0B1C3F]">Réinitialiser « {label} » ?</h2>
            <p className="mt-2 text-[13.5px] leading-relaxed text-[#475569]">
              Les réglages de cette section vont revenir à leur état d'avant le dernier enregistrement
              {st.saved_at ? <> (fait le <strong className="text-[#0B1C3F]">{when(st.saved_at)}</strong>{st.saved_by ? <> par {st.saved_by}</> : null})</> : null}.
            </p>
            {NOTES[section] && <p className="mt-2 text-[12.5px] text-[#64748B]">{NOTES[section]}</p>}
            {st.count > 1 && (
              <p className="mt-2 text-[12.5px] text-[#64748B]">Vous pourrez encore revenir {st.count - 1} enregistrement{st.count > 2 ? 's' : ''} en arrière.</p>
            )}
            <p className="mt-3 text-[13.5px] font-semibold text-[#0B1C3F]">Êtes-vous sûr de vouloir continuer ?</p>
            {err && <p className="mt-3 rounded-lg bg-[#FEECEC] px-3 py-2 text-[12.5px] text-[#C0392B]">{err}</p>}
            <div className="mt-5 flex justify-end gap-2">
              <button type="button" onClick={() => setOpen(false)} disabled={busy}
                      className="rounded-xl border border-[#E6EEFB] bg-white px-4 py-2.5 text-[13px] font-semibold text-[#334155] hover:border-[#C9D8F5]">
                Annuler
              </button>
              <button ref={confirmBtn} type="button" onClick={go} disabled={busy}
                      className="inline-flex items-center gap-2 rounded-xl bg-[#DC2626] px-4 py-2.5 text-[13px] font-semibold text-white hover:bg-[#B91C1C] disabled:opacity-70">
                {busy ? <Loader2 size={15} className="animate-spin" /> : <RotateCcw size={15} />} Oui, réinitialiser
              </button>
            </div>
          </div>
        </div>,
        document.body,
      )}

      {toast && createPortal(
        <div role="status" className="fixed bottom-6 left-1/2 z-[85] w-[min(560px,calc(100vw-32px))] -translate-x-1/2 rounded-2xl border border-[#BEE9D2] bg-[#E7F7EE] px-4 py-3 text-[13px] text-[#0F5F3C] shadow-[0_18px_40px_-20px_rgba(11,28,63,.45)]">
          <p className="font-semibold">{toast.text}</p>
          {toast.notes.map((n) => <p key={n} className="mt-1 text-[12.5px] text-[#92400E]">{n}</p>)}
        </div>,
        document.body,
      )}
    </>
  );
}
