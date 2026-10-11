import React, { useEffect, useState } from 'react';
import { X, Loader2, Minus, Plus, History } from 'lucide-react';
import { ownerAPI } from '../lib/api';
import PhoneField, { phoneValueError } from './PhoneField';

/* Clients › « Modifier la fiche » and « Ajuster points / tampons » (QA UX04,
   user, 2026-10-08). The same rules as the signup form; a phone or e-mail
   already used by another client is refused; every change goes to the
   client's history and the Historique; the Wallet card follows. */

const MONTHS = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre'];
const DAYS_IN = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
const field = 'h-11 w-full rounded-xl border border-[#E6EEFB] bg-white px-3 text-[13.5px] text-[#0B1C3F] outline-none focus:border-[#2F6BFF]';
const err = (e, f) => e?.response?.data?.detail || f;

function Shell({ title, sub, onClose, children, footer }) {
  useEffect(() => {
    const k = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', k);
    return () => window.removeEventListener('keydown', k);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-[#0B1C3F]/40 sm:items-center sm:p-4" onClick={onClose}
         role="dialog" aria-modal="true" aria-label={title}>
      <div className="max-h-[92vh] w-full max-w-lg overflow-y-auto rounded-t-2xl bg-white p-5 shadow-[0_30px_70px_-30px_rgba(11,28,63,.6)] sm:rounded-2xl"
           onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 className="text-[16px] font-bold text-[#0B1C3F]">{title}</h3>
            {sub && <p className="text-[12.5px] text-[#64748B]">{sub}</p>}
          </div>
          <button type="button" onClick={onClose} aria-label="Fermer" title="Fermer" className="text-[#94A3B8] hover:text-[#334155]"><X size={18} /></button>
        </div>
        {children}
        {footer && <div className="mt-5 flex justify-end gap-2">{footer}</div>}
      </div>
    </div>
  );
}

const Label = ({ children }) => <span className="mb-1 block text-[12px] font-semibold text-[#475569]">{children}</span>;
const btn = 'inline-flex h-10 items-center gap-2 rounded-xl px-4 text-[13px] font-semibold';

function Changes({ rows }) {
  if (!rows?.length) return null;
  return (
    <div className="mt-5 border-t border-[#EEF3FB] pt-3">
      <p className="mb-2 flex items-center gap-1.5 text-[12px] font-semibold text-[#475569]"><History size={13} /> Dernières modifications</p>
      <ul className="max-h-36 space-y-1.5 overflow-y-auto text-[12px]">
        {rows.map((r, i) => (
          <li key={i} className="text-[#334155]">
            <span className="text-[#94A3B8]">{new Date(r.at).toLocaleString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })} · </span>
            {r.text}{r.reason ? ` — ${r.reason}` : ''}{r.by ? <span className="text-[#94A3B8]"> · {r.by}</span> : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

/* ── « Modifier la fiche » ─────────────────────────────────────────────── */
export function FicheModal({ clientId, onClose, onSaved }) {
  const [d, setD] = useState(null);
  const [f, setF] = useState(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  useEffect(() => {
    ownerAPI.clientFiche(clientId)
      .then(({ data }) => { setD(data); setF({ ...data.client }); })
      .catch((e) => setMsg(err(e, 'Fiche introuvable.')));
  }, [clientId]);
  const [mm, dd] = (f?.birthday || '').split('-');
  // the year (user, 2026-10-09: the age shows in Clients) — optional here
  const yy = (f?.birth_date || '').slice(0, 4);
  const THIS_YEAR = new Date().getFullYear();
  const setBirthday = (m, day) => {
    const max = DAYS_IN[(Number(m) || 1) - 1];
    const dfix = day && Number(day) > max ? String(max).padStart(2, '0') : day;
    setF({ ...f, birthday: m || dfix ? `${m || ''}-${dfix || ''}` : '' });
  };
  const save = async () => {
    setBusy(true); setMsg('');
    const body = {};
    ['name', 'phone', 'email', 'postal_code', 'is_student', 'acquisition_source'].forEach((k) => {
      if (f[k] !== d.client[k]) body[k] = f[k];
    });
    if (f.birthday !== d.client.birthday || (f.birth_date || '') !== (d.client.birth_date || '')) {
      const [m2, d2] = (f.birthday || '').split('-');
      const y2 = (f.birth_date || '').slice(0, 4);
      body.birthday = y2 && m2 && d2 ? `${y2}-${m2}-${d2}` : f.birthday;
    }
    if (!Object.keys(body).length) { onClose(); return; }
    try {
      const { data } = await ownerAPI.saveClientFiche(clientId, body);
      onSaved(data.changed.length ? 'Fiche enregistrée.' : 'Aucun changement.');
    } catch (e) { setMsg(err(e, "La fiche n'a pas pu être enregistrée.")); } finally { setBusy(false); }
  };
  return (
    <Shell title="Modifier la fiche" sub={d ? `${d.client.name} · ${d.client.barcode_id || ''}` : null} onClose={onClose}
           footer={f && (<>
             <button type="button" onClick={onClose} className={`${btn} border border-[#E6EEFB] text-[#475569]`}>Annuler</button>
             <button type="button" onClick={save} disabled={busy} className={`${btn} bg-[#2F6BFF] text-white hover:bg-[#2559DB] disabled:opacity-60`}>
               {busy && <Loader2 size={14} className="animate-spin" />}Enregistrer
             </button>
           </>)}>
      {!f ? (msg ? null : <p className="flex items-center gap-2 text-[13px] text-[#64748B]"><Loader2 size={15} className="animate-spin" /> Chargement…</p>) : (
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="sm:col-span-2"><Label>Nom</Label>
            <input translate="no" value={f.name} maxLength={80} onChange={(e) => setF({ ...f, name: e.target.value })} className={field} />
          </label>
          <div><Label>Téléphone</Label>
            {/* the signup's own rule and field (user, 2026-10-09) */}
            <div className="flex h-11 items-stretch rounded-xl border border-[#E6EEFB] bg-white focus-within:border-[#2F6BFF]">
              <PhoneField value={f.phone} onChange={(v) => setF({ ...f, phone: v })} aria-label="Téléphone"
                          selectClassName="shrink-0 cursor-pointer rounded-l-xl border-r border-[#E6EEFB] bg-transparent pl-2 pr-1 text-[13px] text-[#0B1C3F] outline-none"
                          inputClassName="min-w-0 flex-1 rounded-r-xl bg-transparent px-3 text-[13.5px] text-[#0B1C3F] outline-none" />
            </div>
            {f.phone && phoneValueError(f.phone) && <p className="mt-1 text-[11.5px] text-[#B91C1C]">{phoneValueError(f.phone)}</p>}
          </div>
          <label><Label>E-mail (facultatif)</Label>
            <input type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} className={field} />
          </label>
          <div className="sm:col-span-2"><Label>Date de naissance{d.client.age != null ? ` · ${d.client.age} ans` : ''}</Label>
            <div className="flex gap-2">
              <select aria-label="Jour" value={dd || ''} onChange={(e) => setBirthday(mm, e.target.value)} className={field}>
                <option value="">Jour</option>
                {Array.from({ length: DAYS_IN[(Number(mm) || 1) - 1] }, (_, i) => String(i + 1).padStart(2, '0'))
                  .map((x) => <option key={x} value={x}>{Number(x)}</option>)}
              </select>
              <select aria-label="Mois" value={mm || ''} onChange={(e) => setBirthday(e.target.value, dd)} className={field}>
                <option value="">Mois</option>
                {MONTHS.map((m, i) => <option key={m} value={String(i + 1).padStart(2, '0')}>{m}</option>)}
              </select>
              <select aria-label="Année" value={yy || ''} className={field}
                      onChange={(e) => setF({ ...f, birth_date: e.target.value ? `${e.target.value}-${mm || '01'}-${dd || '01'}` : '' })}>
                <option value="">Année</option>
                {Array.from({ length: THIS_YEAR - 1899 }, (_, i) => String(THIS_YEAR - i)).map((y) => <option key={y} value={y}>{y}</option>)}
              </select>
            </div>
          </div>
          <label><Label>Code postal</Label>
            <input inputMode="numeric" maxLength={5} value={f.postal_code} onChange={(e) => setF({ ...f, postal_code: e.target.value.replace(/\D/g, '').slice(0, 5) })} className={field} />
          </label>
          <label><Label>Comment nous a-t-il connu ?</Label>
            <select value={f.acquisition_source || ''} onChange={(e) => setF({ ...f, acquisition_source: e.target.value })} className={field}>
              <option value="">Non renseigné</option>
              {d.sources.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
            </select>
          </label>
          <label className="flex items-center gap-2.5 self-end pb-2.5 text-[13px] text-[#334155]">
            <input type="checkbox" checked={!!f.is_student} onChange={(e) => setF({ ...f, is_student: e.target.checked })} className="h-4 w-4 accent-[#2F6BFF]" />
            Étudiant·e
          </label>
        </div>
      )}
      {msg && <p className="mt-3 rounded-lg bg-[#FEF2F2] px-3 py-2 text-[12.5px] text-[#B91C1C]">{msg}</p>}
      <Changes rows={d?.changes} />
    </Shell>
  );
}

/* ── « Ajuster points / tampons » ──────────────────────────────────────── */
function Stepper({ label, value, onChange, hint }) {
  return (
    <div>
      <Label>{label}</Label>
      <div className="flex items-center gap-2">
        <button type="button" aria-label={`Retirer 1 — ${label}`} onClick={() => onChange(value - 1)}
                className="flex h-11 w-11 items-center justify-center rounded-xl border border-[#E6EEFB] text-[#334155] hover:border-[#2F6BFF]"><Minus size={16} /></button>
        <input type="number" value={value} onChange={(e) => onChange(Number(e.target.value) || 0)} aria-label={label}
               className={`${field} text-center tabular-nums`} />
        <button type="button" aria-label={`Ajouter 1 — ${label}`} onClick={() => onChange(value + 1)}
                className="flex h-11 w-11 items-center justify-center rounded-xl border border-[#E6EEFB] text-[#334155] hover:border-[#2F6BFF]"><Plus size={16} /></button>
      </div>
      {hint && <p className="mt-1 text-[11.5px] text-[#64748B]">{hint}</p>}
    </div>
  );
}

export function AdjustModal({ clientId, onClose, onSaved }) {
  const [d, setD] = useState(null);
  const [points, setPoints] = useState(0);
  const [visits, setVisits] = useState(0);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  useEffect(() => {
    ownerAPI.clientFiche(clientId).then(({ data }) => setD(data)).catch((e) => setMsg(err(e, 'Fiche introuvable.')));
  }, [clientId]);
  const c = d?.client;
  const save = async () => {
    setMsg('');
    if (!points && !visits) { setMsg('Indiquez des points ou des tampons à ajouter ou retirer.'); return; }
    if (!reason.trim()) { setMsg("Indiquez la raison de l'ajustement."); return; }
    setBusy(true);
    try {
      const { data } = await ownerAPI.adjustClient(clientId, { points, visits, reason: reason.trim() });
      onSaved(data.text);
    } catch (e) { setMsg(err(e, "L'ajustement n'a pas pu être enregistré.")); } finally { setBusy(false); }
  };
  return (
    <Shell title="Ajuster points / tampons" sub={c ? `${c.name} · ${c.barcode_id || ''}` : null} onClose={onClose}
           footer={c && (<>
             <button type="button" onClick={onClose} className={`${btn} border border-[#E6EEFB] text-[#475569]`}>Annuler</button>
             <button type="button" onClick={save} disabled={busy} className={`${btn} bg-[#2F6BFF] text-white hover:bg-[#2559DB] disabled:opacity-60`}>
               {busy && <Loader2 size={14} className="animate-spin" />}Enregistrer l'ajustement
             </button>
           </>)}>
      {!c ? (msg ? null : <p className="flex items-center gap-2 text-[13px] text-[#64748B]"><Loader2 size={15} className="animate-spin" /> Chargement…</p>) : (
        <>
          <div className="mb-4 grid grid-cols-3 gap-2 text-center">
            {/* stamps are the card's meter; visits stay the real scans (QA R5 F22) */}
            {[['Points', c.points, null],
              ['Tampons (carte en cours)', c.stamps_in_cycle,
               [c.stamps_adjusted ? `dont ${c.stamps_adjusted > 0 ? '+' : ''}${c.stamps_adjusted} à la main` : null,
                c.paper_stamps ? `${c.paper_stamps} de la carte papier` : null].filter(Boolean).join(' · ') || null],
              ['Visites (scans)', c.visits, null]].map(([l, v, sub]) => (
              <div key={l} className="rounded-xl bg-[#F5F8FE] px-2 py-2.5">
                <p className="text-[18px] font-bold text-[#0B1C3F]">{v}</p>
                <p className="text-[11px] leading-tight text-[#64748B]">{l}</p>
                {sub && <p className="mt-0.5 text-[10.5px] leading-tight text-[#2F6BFF]">{sub}</p>}
              </div>
            ))}
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Stepper label="Points" value={points} onChange={setPoints} hint={points ? `Nouveau solde : ${c.points + points} points` : null} />
            <Stepper label="Tampons" value={visits} onChange={setVisits}
                     hint={visits ? `Carte en cours : ${c.stamps_in_cycle + visits} tampon${c.stamps_in_cycle + visits > 1 ? 's' : ''}` : null} />
          </div>
          <label className="mt-3 block"><Label>Raison (obligatoire)</Label>
            <input value={reason} maxLength={300} onChange={(e) => setReason(e.target.value)} placeholder="Ex. visite oubliée au comptoir, geste commercial…" className={field} />
          </label>
          <p className="mt-2 text-[11.5px] text-[#64748B]">La raison est gardée dans l'historique du client. Les tampons ne changent que la carte en cours : le nombre de visites, le palier et vos statistiques restent ceux des scans.</p>
        </>
      )}
      {msg && <p className="mt-3 rounded-lg bg-[#FEF2F2] px-3 py-2 text-[12.5px] text-[#B91C1C]">{msg}</p>}
      <Changes rows={d?.changes} />
    </Shell>
  );
}
