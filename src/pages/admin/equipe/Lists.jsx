import React, { useEffect, useRef, useState } from 'react';
import { Check, ChevronDown, ChevronUp, Plus, Settings2, Trash2, Loader2, Star, AlertTriangle } from 'lucide-react';
import { teamAPI } from '../../../lib/api';
import { field, frDateTime, Shell } from './shared';

/* Super admin › Suivi d'équipe — the team's own lists (user, 2026-10-08:
   « sab mein customize … kind and types mein same options, customization
   and sync »). Types, priorities and fonctions: one list each, picked from
   the same dropdown wherever it appears, added to from that dropdown, and
   managed (rename, colour, order, default, delete) in one window. Deleting
   one that is in use hands its tasks (or members) over — compulsory, all at
   once or one by one. */

export const KINDS = {
  types: { title: 'Types de tâches', one: 'type', add: 'Nouveau type', manage: 'Gérer les types', color: true, none: 'Sans type', fem: false },
  priorities: { title: 'Priorités', one: 'priorité', add: 'Nouvelle priorité', manage: 'Gérer les priorités', color: true, fem: true },
  fonctions: { title: 'Fonctions', one: 'fonction', add: 'Nouvelle fonction', manage: 'Gérer les fonctions', color: false, none: 'Sans fonction', fem: true },
};
export const SWATCHES = ['#2F6BFF', '#0EA5E9', '#14B8A6', '#22C55E', '#6366F1', '#A855F7', '#EC4899', '#F59E0B', '#EF4444', '#64748B'];
const err = (e, f) => e?.response?.data?.detail || f;

function useOutside(open, close) {
  const box = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const on = (e) => { if (box.current && !box.current.contains(e.target)) close(); };
    document.addEventListener('mousedown', on);
    return () => document.removeEventListener('mousedown', on);
  }, [open, close]);
  return box;
}

/* The dropdown: pick one, add one, or open the manager. */
export function ListPicker({ kind, items, value, onChange, placeholder, allLabel, counts, canEdit, onAdded, onManage, className = '', ariaLabel }) {
  const k = KINDS[kind];
  const [open, setOpen] = useState(false);
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState('');
  const [color, setColor] = useState(SWATCHES[0]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const box = useOutside(open, () => { setOpen(false); setAdding(false); });
  const cur = items.find((i) => i.id === value);
  const label = cur ? cur.name : value === 'none' ? k.none : (allLabel || placeholder || k.title);
  const pick = (id) => { onChange(id); setOpen(false); setAdding(false); };
  const add = async () => {
    if (!name.trim()) return;
    setBusy(true); setMsg('');
    try {
      const { data } = await teamAPI.listAdd(kind, { name: name.trim(), ...(k.color ? { color } : {}) });
      setName(''); setAdding(false); setOpen(false);
      await onAdded?.(data.id);
      onChange(data.id);
    } catch (e) { setMsg(err(e, 'Ajout impossible.')); } finally { setBusy(false); }
  };
  return (
    <div ref={box} className={`relative ${className}`}>
      <button type="button" onClick={() => setOpen((o) => !o)} aria-haspopup="listbox" aria-expanded={open} aria-label={ariaLabel || k.title}
              className={`${field} flex items-center justify-between gap-2 text-left`}>
        <span className={`flex min-w-0 items-center gap-2 truncate ${cur ? 'text-[#0B1C3F]' : 'text-[#64748B]'}`}>
          {cur && k.color && <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: cur.color }} />}
          <span className="truncate">{label}</span>
        </span>
        <ChevronDown size={16} className="shrink-0 text-[#64748B]" />
      </button>
      {open && (
        <div role="listbox" className="absolute left-0 top-full z-40 mt-1 w-full min-w-[230px] overflow-hidden rounded-xl border border-[#E3E9F3] bg-white shadow-[0_18px_40px_-20px_rgba(11,28,63,.35)]">
          <div className="max-h-64 overflow-y-auto p-1">
            {allLabel && (
              <Option on={!value} onClick={() => pick('')} label={allLabel} />
            )}
            {placeholder && !allLabel && k.none && <Option on={!value} onClick={() => pick('')} label={k.none} muted />}
            {items.map((i) => (
              <Option key={i.id} on={value === i.id} onClick={() => pick(i.id)} label={i.name} color={k.color ? i.color : null}
                      count={counts ? (counts[i.id] || 0) : undefined} star={kind === 'priorities' && i.default} />
            ))}
            {allLabel && k.none && counts && counts[''] ? <Option on={value === 'none'} onClick={() => pick('none')} label={k.none} muted count={counts['']} /> : null}
          </div>
          {canEdit && (
            <div className="border-t border-[#EEF2F8] p-1.5">
              {adding ? (
                <div className="space-y-2 p-1">
                  <input autoFocus value={name} onChange={(e) => setName(e.target.value)} maxLength={40} placeholder={`Nom de la ${k.one}`.replace('la type', 'du type')}
                         onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); add(); } if (e.key === 'Escape') setAdding(false); }}
                         className={`${field} h-9`} />
                  {k.color && (
                    <div className="flex flex-wrap gap-1.5">
                      {SWATCHES.map((c) => <button key={c} type="button" aria-label={`Couleur ${c}`} onClick={() => setColor(c)} className={`h-5 w-5 rounded-full ${color === c ? 'ring-2 ring-[#0B1C3F] ring-offset-1' : ''}`} style={{ background: c }} />)}
                    </div>
                  )}
                  {msg && <p className="text-[11.5px] text-[#B91C1C]">{msg}</p>}
                  <div className="flex gap-1.5">
                    <button type="button" onClick={add} disabled={!name.trim() || busy} className="inline-flex h-8 items-center gap-1 rounded-lg bg-[#2F6BFF] px-3 text-[12px] font-semibold text-white disabled:opacity-50">
                      {busy ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />} Ajouter
                    </button>
                    <button type="button" onClick={() => setAdding(false)} className="h-8 rounded-lg px-2.5 text-[12px] text-[#475569]">Annuler</button>
                  </div>
                </div>
              ) : (
                <div className="flex items-center justify-between gap-1">
                  <button type="button" onClick={() => setAdding(true)} className="inline-flex h-8 items-center gap-1.5 rounded-lg px-2 text-[12.5px] font-semibold text-[#2F6BFF] hover:bg-[#F4F8FF]"><Plus size={14} /> {k.add}</button>
                  {onManage && <button type="button" onClick={() => { setOpen(false); onManage(); }} className="inline-flex h-8 items-center gap-1 rounded-lg px-2 text-[12px] text-[#475569] hover:bg-[#F4F7FC]"><Settings2 size={13} /> Gérer</button>}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Option({ on, onClick, label, color, count, muted, star }) {
  return (
    <button type="button" role="option" aria-selected={on} onClick={onClick}
            className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-[13px] hover:bg-[#F4F7FC] ${on ? 'bg-[#F4F8FF] font-semibold' : ''} ${muted ? 'text-[#64748B]' : 'text-[#0B1C3F]'}`}>
      {color && <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: color }} />}
      <span className="min-w-0 flex-1 truncate">{label}</span>
      {star && <Star size={12} className="shrink-0 fill-[#F5B70B] text-[#F5B70B]" aria-label="Par défaut" />}
      {count !== undefined && <span className="rounded-full bg-[#F1F5F9] px-1.5 text-[11px] text-[#475569]">{count}</span>}
      {on && <Check size={14} className="shrink-0 text-[#2F6BFF]" />}
    </button>
  );
}

/* The manager: rename, colour, order, default (priorities), add, delete. */
export function ListManager({ kind, items, onClose, onChanged, say }) {
  const k = KINDS[kind];
  const [rows, setRows] = useState(items.map((x) => ({ ...x })));
  const [name, setName] = useState('');
  const [color, setColor] = useState(SWATCHES[0]);
  const [msg, setMsg] = useState('');
  const [deleting, setDeleting] = useState(null);
  useEffect(() => { setRows(items.map((x) => ({ ...x }))); }, [items]);
  const run = async (fn, ok) => { setMsg(''); try { await fn(); if (ok) say?.(ok); await onChanged(); } catch (e) { setMsg(err(e, 'Action impossible.')); } };
  const move = (i, d) => {
    const j = i + d;
    if (j < 0 || j >= rows.length) return;
    const next = [...rows]; [next[i], next[j]] = [next[j], next[i]];
    setRows(next);
    run(() => teamAPI.listOrder(kind, next.map((r) => r.id)));
  };
  const changed = (r, i) => r.name !== items[i]?.name || (k.color && r.color !== items[i]?.color);
  if (deleting) {
    return <DeleteWithMove kind={kind} item={deleting} items={items} onClose={() => setDeleting(null)}
                           onDone={async (m) => { setDeleting(null); say?.(m); await onChanged(); }} />;
  }
  return (
    <Shell title={k.title} onClose={onClose}>
      <p className="mb-3 text-[12px] text-[#64748B]">La même liste partout : ajout rapide, filtres, fenêtre des tâches.{kind === 'priorities' ? ' L\'étoile marque la priorité donnée quand aucune n\'est choisie.' : ''}</p>
      <ul className="space-y-1.5">
        {rows.map((r, i) => (
          <li key={r.id} className="flex items-center gap-1.5">
            <span className="flex flex-col">
              <button type="button" aria-label="Monter" disabled={i === 0} onClick={() => move(i, -1)} className="text-[#94A3B8] hover:text-[#0B1C3F] disabled:opacity-30"><ChevronUp size={14} /></button>
              <button type="button" aria-label="Descendre" disabled={i === rows.length - 1} onClick={() => move(i, 1)} className="text-[#94A3B8] hover:text-[#0B1C3F] disabled:opacity-30"><ChevronDown size={14} /></button>
            </span>
            {k.color && (
              <input type="color" value={r.color} aria-label={`Couleur de ${r.name}`} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, color: e.target.value } : x)))}
                     className="h-9 w-9 shrink-0 cursor-pointer rounded-lg border border-[#E3E9F3] bg-white p-1" />
            )}
            <input value={r.name} maxLength={40} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} className={`${field} h-9`} aria-label="Nom" />
            {kind === 'priorities' && (
              <button type="button" title={r.default ? 'Priorité par défaut' : 'Mettre par défaut'} aria-label="Par défaut"
                      onClick={() => !r.default && run(() => teamAPI.listEdit(kind, r.id, { name: r.name, default: true }), `« ${r.name} » par défaut.`)}
                      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg hover:bg-[#FFF8E6]">
                <Star size={15} className={r.default ? 'fill-[#F5B70B] text-[#F5B70B]' : 'text-[#CBD5E1]'} />
              </button>
            )}
            {changed(r, i) && (
              <button type="button" onClick={() => run(() => teamAPI.listEdit(kind, r.id, { name: r.name, ...(k.color ? { color: r.color } : {}) }), 'Enregistré.')}
                      className="h-9 shrink-0 rounded-lg bg-[#2F6BFF] px-3 text-[12px] font-semibold text-white">OK</button>
            )}
            <button type="button" aria-label={`Supprimer ${r.name}`} onClick={() => setDeleting(r)}
                    className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-[#94A3B8] hover:bg-[#FEF2F2] hover:text-[#DC2626]"><Trash2 size={15} /></button>
          </li>
        ))}
      </ul>
      <div className="mt-4 rounded-xl border border-dashed border-[#CBD5E1] p-3">
        <p className="mb-2 text-[12.5px] font-semibold text-[#0B1C3F]">{k.add}</p>
        <div className="flex gap-2">
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={40} placeholder="Nom" className={`${field} h-9`}
                 onKeyDown={(e) => { if (e.key === 'Enter' && name.trim()) run(async () => { await teamAPI.listAdd(kind, { name: name.trim(), ...(k.color ? { color } : {}) }); setName(''); }, 'Ajouté.'); }} />
          <button type="button" disabled={!name.trim()} onClick={() => run(async () => { await teamAPI.listAdd(kind, { name: name.trim(), ...(k.color ? { color } : {}) }); setName(''); }, 'Ajouté.')}
                  className="inline-flex h-9 shrink-0 items-center gap-1 rounded-lg bg-[#2F6BFF] px-3 text-[12.5px] font-semibold text-white disabled:opacity-50"><Plus size={14} /> Ajouter</button>
        </div>
        {k.color && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {SWATCHES.map((c) => <button key={c} type="button" aria-label={`Couleur ${c}`} onClick={() => setColor(c)} className={`h-6 w-6 rounded-full ${color === c ? 'ring-2 ring-[#0B1C3F] ring-offset-2' : ''}`} style={{ background: c }} />)}
          </div>
        )}
      </div>
      {msg && <p className="mt-3 rounded-lg bg-[#FEF2F2] px-3 py-2 text-[12.5px] text-[#B91C1C]">{msg}</p>}
    </Shell>
  );
}

/* Delete one in use: where its tasks (members) go — compulsory. */
export function DeleteWithMove({ kind, item, items, onClose, onDone }) {
  const k = KINDS[kind];
  const others = items.filter((x) => x.id !== item.id);
  const [u, setU] = useState(null);
  const [to, setTo] = useState('');
  const [moves, setMoves] = useState({});
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  useEffect(() => { teamAPI.listUsage(kind, item.id).then(({ data }) => setU(data)).catch((e) => setMsg(err(e, 'Impossible de vérifier.'))); }, [kind, item.id]);
  const rows = u ? (kind === 'fonctions' ? u.members.map((m) => ({ id: m.email, title: m.name })) : u.tasks) : [];
  const covered = rows.every((r) => moves[r.id] || to) && (!u || u.total <= rows.length || to);
  const go = async () => {
    setBusy(true); setMsg('');
    try {
      await teamAPI.listDelete(kind, item.id, { to: to || null, moves });
      onDone(`« ${item.name} » supprimé${k.fem ? 'e' : ''}.`);
    } catch (e) { setMsg(err(e, 'Suppression impossible.')); } finally { setBusy(false); }
  };
  const sel = (v, onC, opt) => (
    <select value={v} onChange={(e) => onC(e.target.value)} className={`${field} h-9`}>
      <option value="">{opt}</option>
      {others.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
    </select>
  );
  return (
    <Shell title={`Supprimer « ${item.name} »`} onClose={onClose} wide>
      {!u ? <p className="flex items-center gap-2 text-[13px] text-[#64748B]"><Loader2 size={15} className="animate-spin" /> Vérification…</p>
        : u.total === 0 ? <p className="text-[13px] text-[#475569]">Personne ne l'utilise : elle peut être supprimée sans rien déplacer.</p> : (
          <>
            <p className="mb-3 flex items-start gap-2 rounded-lg bg-[#FFF8E6] px-3 py-2 text-[12.5px] text-[#92400E]">
              <AlertTriangle size={15} className="mt-0.5 shrink-0" />
              {kind === 'fonctions'
                ? `${rows.length} membre(s) ont cette fonction : choisissez leur nouvelle fonction.`
                : `${u.total} tâche(s) utilisent ce${k.fem ? 'tte' : ''} ${k.one}${u.total > rows.length ? ' (dont des tâches supprimées ou répétées)' : ''} : choisissez où elles vont — toutes ensemble, ou une par une.`}
            </p>
            {!others.length && <p className="mb-3 text-[12.5px] text-[#B91C1C]">Ajoutez d'abord un{k.fem ? 'e autre' : ' autre'} {k.one} pour pouvoir la remplacer.</p>}
            <label className="mb-3 block text-[12px] font-semibold text-[#475569]">Tout déplacer vers
              <div className="mt-1">{sel(to, setTo, '— choisir —')}</div>
            </label>
            <div className="max-h-[42vh] overflow-y-auto rounded-xl border border-[#EEF2F8]">
              <table className="w-full border-collapse text-[12.5px]">
                <thead><tr className="border-b border-[#EEF2F8] text-left text-[11.5px] text-[#64748B]"><th className="px-3 py-2">{kind === 'fonctions' ? 'Membre' : 'Tâche'}</th><th className="px-3 py-2">Va vers</th></tr></thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.id} className="border-b border-[#F4F7FC] last:border-b-0">
                      <td className="px-3 py-2"><span className="block font-medium text-[#0B1C3F]">{r.title}</span>{r.due_at && <span className="text-[11px] text-[#94A3B8]">{frDateTime(r.due_at)}</span>}</td>
                      <td className="w-[210px] px-3 py-2">{sel(moves[r.id] || '', (v) => setMoves({ ...moves, [r.id]: v }), to ? `(${others.find((x) => x.id === to)?.name})` : '— choisir —')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      {msg && <p className="mt-3 rounded-lg bg-[#FEF2F2] px-3 py-2 text-[12.5px] text-[#B91C1C]">{msg}</p>}
      <div className="mt-4 flex justify-end gap-2">
        <button type="button" onClick={onClose} className="h-10 rounded-xl border border-[#E3E9F3] px-4 text-[13px] font-semibold text-[#475569]">Annuler</button>
        <button type="button" disabled={!u || busy || (u.total > 0 && !covered)} onClick={go}
                className="inline-flex h-10 items-center gap-2 rounded-xl bg-[#DC2626] px-5 text-[13px] font-semibold text-white disabled:opacity-50">
          {busy && <Loader2 size={14} className="animate-spin" />}{u?.total ? 'Déplacer et supprimer' : 'Supprimer'}
        </button>
      </div>
    </Shell>
  );
}
