import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Phone, Mail, Eye, Search, Download, X, Loader2, Copy } from 'lucide-react';
import { adminAPI } from '../../lib/api';
import { nf } from '../crm/ui';
import { StatusPill, PlanPill, CommerceLogo, weekly } from './CommercesPage';

/* Dashboard (user, 2026-10-01): every figure opens the businesses behind it,
   with what is needed to act at once — call, write (FidClic's email, from the
   business's page), open the business. */

const dateFr = (iso) => (iso ? new Date(iso).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric' }) : '');
const STANDING_TONE = { essai: ['#F3EEFF', '#7C3AED'], abonne: ['#E7F7EE', '#0F8B58'], impaye: ['#FDECEF', '#E11D48'], resilie: ['#F1F5F9', '#0B1C3F'], non_converti: ['#FFF4DB', '#B45309'] };
const money = (v) => `€${Number(v || 0).toLocaleString('fr-FR', { maximumFractionDigits: 2 })}`;

function detailOf(key, r) {
  if (key === 'essai') return r.trial_ends_at ? `Fin de l'essai : ${dateFr(r.trial_ends_at)}` : 'En essai';
  if (key === 'non_converti') return `Essai terminé le ${dateFr(r.trial_ends_at)}`;
  if (key === 'resilie') return `Résilié le ${dateFr(r.resiliated_at)}${r.resiliation_reason ? ` — ${r.resiliation_reason}` : ''}`;
  if (key === 'impaye') return r.suspended_at ? `Suspendu le ${dateFr(r.suspended_at)}${r.suspended_reason ? ` — ${r.suspended_reason}` : ''}` : `Paiement en retard · ${money(r.price)} / mois`;
  if (key === 'nouveaux') return `Inscrit le ${dateFr(r.created_at)}`;
  if (['actif', 'inactif', 'a_risque'].includes(key)) return weekly(r) || '—';
  if (key === 'abonne' || key === 'commerces') return r.standing === 'essai' ? `Fin de l'essai : ${dateFr(r.trial_ends_at)}` : `${money(r.price)} / mois`;
  return '';
}

export default function CommerceListModal({ listKey, range, onClose }) {
  const navigate = useNavigate();
  const [d, setD] = useState(null);
  const [err, setErr] = useState('');
  const [q, setQ] = useState('');
  const [copied, setCopied] = useState('');
  const from = range?.from;
  const to = range?.to;
  useEffect(() => {      // keyed on the dates, not the object — no refetch on every render
    adminAPI.dashboardList(listKey, { from, to }).then(({ data }) => setD(data)).catch((e) => setErr(e?.response?.data?.detail || 'Liste indisponible.'));
  }, [listKey, from, to]);
  useEffect(() => {
    const k = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', k);
    return () => window.removeEventListener('keydown', k);
  }, [onClose]);
  const rows = useMemo(() => {
    const f = q.trim().toLowerCase();
    return (d?.rows || []).filter((r) => !f || `${r.name} ${r.city} ${r.sector} ${r.owner} ${r.email} ${r.phone}`.toLowerCase().includes(f));
  }, [d, q]);
  const isMoney = d && ['ca', 'mrr'].includes(listKey);
  const copy = (txt) => { navigator.clipboard?.writeText(txt).then(() => { setCopied(txt); setTimeout(() => setCopied(''), 1500); }).catch(() => {}); };
  const exportCsv = () => {
    const head = ['Commerce', 'Secteur', 'Ville', 'Plan', 'Situation', 'Statut', 'Détail', d?.metric_label, 'Contact', 'Email', 'Téléphone'].filter((x) => x !== undefined && x !== null);
    const lines = rows.map((r) => [r.name, r.sector, r.city, r.plan?.label, r.standing_label, r.status_label, detailOf(listKey, r),
      ...(d?.metric_label ? [r.metric] : []), r.owner, r.email, r.phone]);
    const csv = '﻿' + [head, ...lines].map((l) => l.map((x) => `"${String(x ?? '').replace(/"/g, '""')}"`).join(';')).join('\n');
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    const a = document.createElement('a'); a.href = url; a.download = `fidclic-${listKey}.csv`; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  };
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-[#0B1C3F]/35 sm:items-center sm:p-6" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-label={d?.title || 'Commerces'} onClick={(e) => e.stopPropagation()}
           className="flex max-h-[92vh] w-full max-w-6xl flex-col overflow-hidden rounded-t-2xl bg-white shadow-2xl sm:rounded-2xl">
        <header className="flex flex-wrap items-center gap-3 border-b border-[#EDF1F7] px-5 py-4">
          <div className="min-w-0 flex-1">
            <h3 className="text-[17px] font-bold text-[#0B1C3F]">{d?.title || 'Commerces'} {d && <span className="ml-1 rounded-full bg-[#EAF1FF] px-2.5 py-0.5 text-[12.5px] font-semibold text-[#2F6BFF]">{nf(d.rows.length)}</span>}</h3>
            {d && ['resilie', 'non_converti', 'ca'].includes(listKey) && <p className="text-[12px] text-[#64748B]">Période : {dateFr(d.period.from)} – {dateFr(d.period.to)}</p>}
          </div>
          <label className="relative block w-full sm:w-64">
            <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Rechercher…" className="h-10 w-full rounded-xl border border-[#DCE3EE] pl-9 pr-3 text-[13px] outline-none focus:border-[#2F6BFF]" />
          </label>
          <button type="button" onClick={exportCsv} disabled={!rows.length} className="inline-flex h-10 items-center gap-2 rounded-xl border border-[#2F6BFF] px-3.5 text-[13px] font-medium text-[#2F6BFF] disabled:opacity-40"><Download size={15} /> Exporter</button>
          <button type="button" onClick={onClose} aria-label="Fermer" className="rounded-lg p-1.5 text-[#94A3B8] hover:text-[#0B1C3F]"><X size={19} /></button>
        </header>
        <div className="flex-1 overflow-y-auto px-3 pb-3">
          {!d ? (
            <div className="flex items-center justify-center gap-2 py-16 text-[13px] text-[#64748B]">{err || <><Loader2 size={15} className="animate-spin" /> Chargement…</>}</div>
          ) : !rows.length ? (
            <p className="py-16 text-center text-[13px] text-[#64748B]">{q ? 'Aucun commerce ne correspond.' : 'Aucun commerce ici pour le moment.'}</p>
          ) : (
            <table className="w-full min-w-[900px] text-left text-[13px]">
              <thead className="sticky top-0 bg-white text-[12px] text-[#64748B]">
                <tr className="border-b border-[#EDF1F7]">
                  <th className="px-2 py-2.5 font-medium">Commerce</th><th className="px-2 py-2.5 font-medium">Situation</th>
                  <th className="px-2 py-2.5 font-medium">Détail</th>{d.metric_label && <th className="px-2 py-2.5 text-right font-medium">{d.metric_label}</th>}
                  <th className="px-2 py-2.5 font-medium">Contact</th><th className="px-2 py-2.5 text-right font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => { const [bg, fg] = STANDING_TONE[r.standing] || STANDING_TONE.abonne; return (
                  <tr key={r.id} className="border-b border-[#F4F7FC] align-middle hover:bg-[#FAFCFF]">
                    <td className="px-2 py-2.5">
                      <span className="flex items-center gap-2.5"><CommerceLogo c={r} size={32} />
                        <span className="min-w-0"><strong className="block max-w-[220px] truncate font-semibold text-[#0B1C3F]">{r.name}</strong>
                          <span className="block max-w-[220px] truncate text-[12px] text-[#64748B]">{[r.sector, r.city].filter(Boolean).join(' · ')}</span></span></span>
                    </td>
                    <td className="px-2 py-2.5">
                      <span className="flex flex-wrap items-center gap-1.5"><PlanPill p={r.plan} />
                        <span className="rounded-md px-2 py-0.5 text-[11.5px] font-medium" style={{ background: bg, color: fg }}>{r.standing_label}</span>
                        {r.status && !['resilie', 'non_converti'].includes(r.status) && <StatusPill s={r.status} label={r.status_label} />}</span>
                    </td>
                    <td className="max-w-[260px] px-2 py-2.5 text-[12.5px] text-[#475569]">{detailOf(listKey, r)}</td>
                    {d.metric_label && <td className="whitespace-nowrap px-2 py-2.5 text-right font-semibold text-[#0B1C3F]">{isMoney ? money(r.metric) : nf(r.metric)}</td>}
                    <td className="px-2 py-2.5 text-[12.5px]">
                      {r.owner && <span className="block font-medium text-[#0B1C3F]">{r.owner}</span>}
                      {r.email && <button type="button" onClick={() => copy(r.email)} title="Copier l'email" className="flex items-center gap-1 text-[#475569] hover:text-[#2F6BFF]">{r.email}{copied === r.email ? <span className="text-[11px] text-[#0F8B58]">copié</span> : <Copy size={11} className="opacity-50" />}</button>}
                      {r.phone && <button type="button" onClick={() => copy(r.phone)} title="Copier le numéro" className="flex items-center gap-1 text-[#475569] hover:text-[#2F6BFF]">{r.phone}{copied === r.phone ? <span className="text-[11px] text-[#0F8B58]">copié</span> : <Copy size={11} className="opacity-50" />}</button>}
                      {!r.email && !r.phone && <span className="text-[#94A3B8]">Aucun contact</span>}
                    </td>
                    <td className="px-2 py-2.5">
                      <span className="flex justify-end gap-1.5">
                        <a href={r.phone ? `tel:${r.phone.replace(/\s/g, '')}` : undefined} aria-disabled={!r.phone} title={r.phone ? `Appeler ${r.phone}` : 'Pas de numéro'}
                           className={`inline-flex h-8 items-center gap-1.5 rounded-lg border px-2.5 text-[12.5px] font-medium ${r.phone ? 'border-[#BFE8D2] text-[#0F8B58] hover:bg-[#E7F7EE]' : 'pointer-events-none border-[#EDF1F7] text-[#CBD5E1]'}`}><Phone size={13} /> Appeler</a>
                        <button type="button" onClick={() => navigate(`/admin/commerces/${r.id}?contact=1`)} title="Écrire depuis FidClic"
                                className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-[#BFD3FF] px-2.5 text-[12.5px] font-medium text-[#2F6BFF] hover:bg-[#EFF5FF]"><Mail size={13} /> Email</button>
                        <button type="button" onClick={() => navigate(`/admin/commerces/${r.id}`)} title="Voir le commerce"
                                className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-[#DCE3EE] px-2.5 text-[12.5px] font-medium text-[#0B1C3F] hover:bg-[#F4F7FC]"><Eye size={13} /> Voir</button>
                      </span>
                    </td>
                  </tr>); })}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
