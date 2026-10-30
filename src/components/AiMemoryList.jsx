import React, { useEffect, useState } from 'react';
import { Check, Loader2, Pencil, Plus, Trash2, X } from 'lucide-react';
import { ownerAPI } from '../lib/api';

/**
 * « Ce que FidClic IA retient » — what this account told FidClic IA about
 * itself (user, 2026-10-30): kept from the chat (« Retiens que… », or found
 * by the regular pass) or written here. Each account sees, edits and
 * deletes its own; phone numbers and e-mails are hidden by the server.
 * api/features/copilot_memory.py
 */
export default function AiMemoryList({ onCount }) {
  const [items, setItems] = useState(null);
  const [max, setMax] = useState(300);
  const [draft, setDraft] = useState('');
  const [edit, setEdit] = useState(null);          // {id, text}
  const [busy, setBusy] = useState('');
  const [err, setErr] = useState('');

  const load = () => ownerAPI.aiMemory()
    .then(({ data }) => { setItems(data.items || []); setMax(data.max_chars || 300); onCount?.(data.count || 0); })
    .catch(() => setItems([]));
  useEffect(() => { load(); }, []);                 // eslint-disable-line react-hooks/exhaustive-deps

  const run = async (key, fn) => {
    setBusy(key); setErr('');
    try { await fn(); await load(); }
    catch (e) { setErr(e?.response?.data?.detail || "L'enregistrement a échoué."); }
    finally { setBusy(''); }
  };
  const add = (e) => { e.preventDefault(); if (draft.trim()) run('add', async () => { await ownerAPI.addAiMemory(draft.trim()); setDraft(''); }); };
  const save = () => run(edit.id, async () => { await ownerAPI.editAiMemory(edit.id, edit.text.trim()); setEdit(null); });

  if (items === null) return <p className="flex items-center gap-2 text-[12.5px] text-[#64748B]"><Loader2 size={14} className="animate-spin" /> Chargement…</p>;
  return (
    <div data-testid="ai-memory">
      {items.length === 0 ? (
        <p className="rounded-xl bg-[#F8FAFF] px-3 py-2.5 text-[12.5px] text-[#64748B]">
          Rien pour l'instant. Dites-le dans le chat (« Retiens que je ferme le lundi ») ou écrivez-le ci-dessous.
        </p>
      ) : (
        <ul className="divide-y divide-[#F1F5F9]">
          {items.map((it) => (
            <li key={it.id} className="flex items-start gap-2 py-2">
              {edit?.id === it.id ? (
                <>
                  <input value={edit.text} maxLength={max} autoFocus aria-label="Nouveau texte"
                         onChange={(e) => setEdit({ ...edit, text: e.target.value })}
                         onKeyDown={(e) => { if (e.key === 'Enter') save(); if (e.key === 'Escape') setEdit(null); }}
                         className="min-w-0 flex-1 rounded-lg border border-[#DCE3EE] px-2.5 py-1.5 text-[13px] outline-none focus:border-[#2F6BFF]" />
                  <button type="button" onClick={save} disabled={!edit.text.trim() || busy === it.id} aria-label="Enregistrer"
                          className="rounded-md p-1.5 text-[#0F8B58] hover:bg-[#F1FBF5] disabled:opacity-50"><Check size={15} /></button>
                  <button type="button" onClick={() => setEdit(null)} aria-label="Annuler"
                          className="rounded-md p-1.5 text-[#64748B] hover:bg-[#F4F7FC]"><X size={15} /></button>
                </>
              ) : (
                <>
                  <div className="min-w-0 flex-1">
                    <p className="text-[13px] leading-snug text-[#0B1C3F]">{it.text}</p>
                    <p className="text-[11px] text-[#94A3B8]">{it.source === 'vous' ? 'Ajouté par vous' : 'Retenu dans le chat'}</p>
                  </div>
                  <button type="button" onClick={() => setEdit({ id: it.id, text: it.text })} aria-label={`Modifier « ${it.text} »`}
                          className="rounded-md p-1.5 text-[#64748B] hover:bg-[#F4F7FC]"><Pencil size={14} /></button>
                  <button type="button" disabled={busy === it.id} aria-label={`Supprimer « ${it.text} »`}
                          onClick={() => run(it.id, () => ownerAPI.deleteAiMemory(it.id))}
                          className="rounded-md p-1.5 text-[#DC2626] hover:bg-[#FEF2F2] disabled:opacity-50"><Trash2 size={14} /></button>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
      <form onSubmit={add} className="mt-3 flex items-center gap-2">
        <input value={draft} onChange={(e) => setDraft(e.target.value)} maxLength={max}
               placeholder="Ex. : Fermé le lundi, ma cible : les familles du quartier…" aria-label="Ajouter ce que FidClic IA doit retenir"
               className="min-w-0 flex-1 rounded-lg border border-[#DCE3EE] px-3 py-2 text-[13px] outline-none focus:border-[#2F6BFF]" />
        <button type="submit" disabled={!draft.trim() || busy === 'add'}
                className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-[#2F6BFF] px-3 py-2 text-[12.5px] font-semibold text-white hover:bg-[#2559DB] disabled:opacity-50">
          {busy === 'add' ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />} Ajouter
        </button>
      </form>
      {err && <p role="alert" className="mt-2 text-[12px] text-[#DC2626]">{err}</p>}
    </div>
  );
}
