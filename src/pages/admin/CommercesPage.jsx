import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Store, Users, Plus, Search, Download, List, LayoutGrid, MapPin, MoreHorizontal, ChevronDown, ChevronUp, ChevronsUpDown,
  Eye, ExternalLink, PauseCircle, PlayCircle, SlidersHorizontal, Loader2, Copy, CreditCard,
} from 'lucide-react';
import { adminAPI } from '../../lib/api';
import { Card, Kpi, Select, Loading, Breadcrumb, Pager, Modal, Logo, useToast, downloadBlob, nf, BLUE, inputCls } from '../crm/ui';
import { toneOf } from '../crm/emailUi';

/* Super admin › Commerces — built to the approved « Tous les commerces »
   mockup. Statut = weekly cards AND scans, the weaker decides (rules
   editable, decided with the user 2026-10-01). */

export const STATUS_TONE = { actif: ['#E7F7EE', '#0F8B58'], inactif: ['#FDECEF', '#E11D48'], a_risque: ['#FFF4DB', '#D97706'], suspendu: ['#F1F5F9', '#475569'],
  resilie: ['#F1F5F9', '#0B1C3F'], non_converti: ['#F3EEFF', '#7C3AED'] };
export const weekly = (c) => (c.cards_week == null ? null : `${c.cards_week} cartes · ${c.scans_week} scans / semaine`);
export const StatusPill = ({ s, label }) => { const [bg, fg] = STATUS_TONE[s] || STATUS_TONE.suspendu; return <span className="whitespace-nowrap rounded-md px-2.5 py-1 text-[12px] font-medium" style={{ background: bg, color: fg }}>{label}</span>; };
export const PLAN_TONE = { essai: ['#F1F5F9', '#475569'], silver: ['#FFF4DB', '#B45309'], gold: ['#EAF1FF', '#2F6BFF'], vip: ['#FDECEF', '#E11D48'], franchise: ['#F3EEFF', '#7C3AED'] };
export const PlanPill = ({ p }) => { const [bg, fg] = PLAN_TONE[p?.key] || (p?.color ? [`${p.color}1F`, p.color] : PLAN_TONE.essai); return <span className="inline-block min-w-[64px] whitespace-nowrap rounded-md px-2.5 py-1 text-center text-[12px] font-medium" style={{ background: bg, color: fg }}>{p?.label}</span>; };
export function CommerceLogo({ c, size = 30 }) {
  const [broken, setBroken] = useState(false);
  return c.logo && !broken
    ? <img src={c.logo} alt="" className="shrink-0 rounded-full border border-[#EDF1F7] object-cover" style={{ width: size, height: size }} onError={() => setBroken(true)} />
    : <Logo name={c.name} size={size} />;
}
const ago = (iso) => {
  if (!iso) return 'Jamais';
  const d = new Date(iso); const t = d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
  const days = Math.floor((new Date().setHours(0, 0, 0, 0) - new Date(d).setHours(0, 0, 0, 0)) / 86400000);
  if (days === 0) return `Aujourd'hui, ${t}`;
  if (days === 1) return `Hier, ${t}`;
  if (days < 7) return `il y a ${days} jours`;
  return d.toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric' });
};
const TABS = [['', 'Tous', 'all', ['#2F6BFF', '#fff', '#EAF1FF']], ['actif', 'Actifs', 'actif', ['#E7F7EE', '#0F8B58', '#fff']], ['inactif', 'Inactifs', 'inactif', ['#FDECEF', '#E11D48', '#fff']],
  ['a_risque', 'À risque', 'a_risque', ['#FFF4DB', '#D97706', '#fff']], ['nouveaux', 'Nouveaux', 'nouveaux', ['#F3EEFF', '#7C3AED', '#fff']],
  ['resilie', 'Résiliés', 'resilie', ['#F1F5F9', '#0B1C3F', '#fff']], ['non_converti', 'Essais non convertis', 'non_converti', ['#F3EEFF', '#7C3AED', '#fff']]];

export async function openViewAs(id, say) {
  const w = window.open('about:blank', '_blank');
  try {
    const { data } = await adminAPI.viewAs(id);
    if (w) w.location.href = `/voir-compte#t=${encodeURIComponent(data.token)}`;
  } catch (e) { if (w) w.close(); say?.(e?.response?.data?.detail || 'Ouverture impossible.'); }
}

export default function CommercesPage() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const tab = params.get('tab') || '';
  const [d, setD] = useState(null);
  const [f, setF] = useState({ q: '', sector: '', city: '', plan: '', status: '' });
  const [sort, setSort] = useState('-clients');
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(15);
  const [view, setView] = useState('list');
  const [menu, setMenu] = useState(null);
  const [modal, setModal] = useState(null);
  const [picked, setPicked] = useState([]);
  const [say, toast] = useToast();

  const load = useCallback(() => {
    adminAPI.commerces({ ...f, tab, sort, page, per_page: perPage }).then(({ data }) => setD(data)).catch(() => setD((x) => x || { rows: [], cards: [], counts: {}, options: {}, pages: 1, total: 0 }));
  }, [f, tab, sort, page, perPage]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { setPage(1); }, [tab]);
  const setFilter = (k) => (v) => { setPage(1); setF({ ...f, [k]: v }); };
  const sortBy = (k) => setSort(sort === `-${k}` ? k : `-${k}`);
  const act = async (fn, m) => { try { await fn(); say(m); load(); } catch (e) { say(e?.response?.data?.detail || 'Action impossible.'); } };

  if (!d) return <Loading />;
  const K = Object.fromEntries((d.cards || []).map((c) => [c.key, c]));
  const SortTh = ({ k, children }) => (
    <th className="px-2 py-2 font-medium"><button type="button" onClick={() => sortBy(k)} className="inline-flex items-center gap-1">{children}
      {sort === `-${k}` ? <ChevronDown size={13} /> : sort === k ? <ChevronUp size={13} /> : <ChevronsUpDown size={13} className="text-[#CBD5E1]" />}</button></th>
  );
  const rowMenu = (c) => (
    <span className="absolute right-2 top-full z-20 flex w-52 flex-col overflow-hidden rounded-xl border border-[#E6EEFB] bg-white py-1 text-[13px] shadow-lg">
      <button type="button" onClick={() => navigate(`/admin/commerces/${c.id}`)} className="flex items-center gap-2 px-3 py-2 text-left hover:bg-[#F4F7FC]"><Eye size={14} /> Voir le commerce</button>
      <button type="button" onClick={() => { setMenu(null); openViewAs(c.id, say); }} className="flex items-center gap-2 px-3 py-2 text-left hover:bg-[#F4F7FC]"><ExternalLink size={14} /> Accéder au compte</button>
      {c.suspended
        ? <button type="button" onClick={() => { setMenu(null); act(() => adminAPI.reactivateCommerce(c.id), `${c.name} réactivé.`); }} className="flex items-center gap-2 px-3 py-2 text-left text-[#0F8B58] hover:bg-[#F0FDF4]"><PlayCircle size={14} /> Réactiver</button>
        : <button type="button" onClick={() => { setMenu(null); setModal({ type: 'suspend', c }); }} className="flex items-center gap-2 px-3 py-2 text-left text-[#E11D48] hover:bg-[#FEF2F2]"><PauseCircle size={14} /> Suspendre</button>}
    </span>
  );

  return (
    <div className="crm" onClick={() => setMenu(null)}>
      <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <Breadcrumb items={[['Super Admin', '/admin'], ['Commerces']]} />
          <h1 className="text-[28px] font-bold leading-tight text-[#0B1C3F]">Tous les commerces</h1>
          <p className="text-[15px] text-[#475569]">Gérez et suivez tous vos commerces clients sur FIDCLIC.</p>
        </div>
        <div className="flex gap-2">
          <button type="button" onClick={() => setModal({ type: 'rules' })} title="Règles du statut" className="inline-flex h-10 items-center gap-2 rounded-xl border border-[#DCE3EE] bg-white px-3 text-[13px] text-[#475569]"><SlidersHorizontal size={15} /> Règles du statut</button>
          <button type="button" onClick={() => setModal({ type: 'add' })} className="inline-flex h-10 items-center gap-2 rounded-xl px-4 text-[13.5px] font-medium text-white" style={{ background: BLUE }}><Plus size={16} /> Ajouter un commerce</button>
        </div>
      </header>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-6">
        <Kpi icon={Store} tone="#2F6BFF" bg="#EAF1FF" value={nf(K.total?.value)} label="Commerces" delta={K.total?.delta} series={K.total?.series || []} />
        {[['actif', 'Actifs', '#10B981', '#E7F7EE'], ['inactif', 'Inactifs', '#E11D48', '#FDECEF'], ['a_risque', 'À risque', '#F59E0B', '#FFF4DB']].map(([k, l, c, bg]) => (
          <button key={k} type="button" onClick={() => setParams(k ? { tab: k } : {})} className="flex items-center gap-3 rounded-2xl border border-[#EDF1F7] bg-white p-4 text-left shadow-[0_1px_2px_rgba(11,28,63,.03)] hover:border-[#BFD3FF]">
            <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl" style={{ background: bg }}><i className="h-3 w-3 rounded-full" style={{ background: c }} /></span>
            <span><strong className="block text-[22px] leading-tight text-[#0B1C3F]">{nf(K[k]?.value)}</strong><span className="block text-[13px] text-[#475569]">{l}</span><span className="text-[12px] text-[#64748B]">{K[k]?.pct ?? 0}% du total</span></span>
          </button>
        ))}
        <button type="button" onClick={() => setParams({ tab: 'nouveaux' })} className="flex items-center gap-3 rounded-2xl border border-[#EDF1F7] bg-white p-4 text-left shadow-[0_1px_2px_rgba(11,28,63,.03)] hover:border-[#BFD3FF]">
          <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-[#F3EEFF] text-[#7C3AED]"><CreditCard size={20} /></span>
          <span><strong className="block text-[22px] leading-tight text-[#0B1C3F]">+{nf(K.nouveaux?.value)}</strong><span className="block text-[13px] text-[#475569]">Nouveaux</span><span className="text-[12px] text-[#64748B]">ce mois-ci</span></span>
        </button>
        <Kpi icon={Users} tone="#10B981" bg="#E7F7EE" value={nf(K.clients?.value)} label="Clients finaux" delta={K.clients?.delta} series={K.clients?.series || []} />
      </div>

      <Card className="mt-4">
        <div className="grid gap-2 md:grid-cols-[1.6fr_repeat(4,1fr)] md:items-end">
          <label className="relative"><Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
            <input className={`${inputCls} pl-9`} placeholder="Rechercher un commerce, ville, secteur…" value={f.q} onChange={(e) => setFilter('q')(e.target.value)} /></label>
          <Select label="Secteur" value={f.sector} onChange={setFilter('sector')}><option value="">Tous</option>{(d.options.sectors || []).map((s) => <option key={s}>{s}</option>)}</Select>
          <Select label="Ville" value={f.city} onChange={setFilter('city')}><option value="">Toutes</option>{(d.options.cities || []).map((s) => <option key={s}>{s}</option>)}</Select>
          <Select label="Plan" value={f.plan} onChange={setFilter('plan')}><option value="">Tous</option>{(d.options.plans || []).map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}</Select>
          <Select label="Statut" value={f.status} onChange={setFilter('status')}><option value="">Tous</option><option value="actif">Actif</option><option value="inactif">Inactif</option><option value="a_risque">À risque</option><option value="suspendu">Suspendu</option><option value="resilie">Résilié</option><option value="non_converti">Essai non converti</option></Select>
        </div>
      </Card>

      <Card className="mt-4">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          {TABS.map(([k, l, c, [bg, fg]]) => { const on = tab === k; return (
            <button key={l} type="button" onClick={() => setParams(k ? { tab: k } : {})} className="inline-flex items-center gap-2 rounded-xl px-3.5 py-2 text-[13px] font-medium"
                    style={on ? { background: k ? fg : BLUE, color: '#fff' } : { background: k ? bg : '#F4F7FC', color: k ? fg : '#0B1C3F' }}>
              {l} <span className="rounded-md px-1.5 text-[12px]" style={{ background: on ? 'rgba(255,255,255,.25)' : '#fff' }}>{nf(d.counts[c] || 0)}</span>
            </button>); })}
          <span className="flex-1" />
          <button type="button" onClick={() => downloadBlob(adminAPI.commercesExport({ ...f, tab }), 'commerces.csv').catch(() => say('Export impossible.'))} className="inline-flex h-9 items-center gap-2 rounded-xl border border-[#2F6BFF] bg-white px-3.5 text-[13px] font-medium text-[#2F6BFF]"><Download size={15} /> Exporter (CSV)</button>
          <span className="flex overflow-hidden rounded-xl border border-[#DCE3EE]">
            <button type="button" aria-label="Liste" onClick={() => setView('list')} className={`px-2.5 py-2 ${view === 'list' ? 'bg-[#2F6BFF] text-white' : 'bg-white text-[#475569]'}`}><List size={15} /></button>
            <button type="button" aria-label="Grille" onClick={() => setView('grid')} className={`px-2.5 py-2 ${view === 'grid' ? 'bg-[#2F6BFF] text-white' : 'bg-white text-[#475569]'}`}><LayoutGrid size={15} /></button>
          </span>
        </div>

        {view === 'list' ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[980px] text-[13px]">
              <thead><tr className="border-b border-[#EDF1F7] text-left text-[#64748B]">
                <th className="w-8 px-2 py-2"><input type="checkbox" aria-label="Tout choisir" checked={d.rows.length > 0 && d.rows.every((r) => picked.includes(r.id))} onChange={(e) => setPicked(e.target.checked ? d.rows.map((r) => r.id) : [])} className="accent-[#2F6BFF]" /></th>
                <SortTh k="name">Commerce</SortTh><th className="px-2 py-2 font-medium">Secteur</th><th className="px-2 py-2 font-medium">Ville</th><th className="px-2 py-2 font-medium">Plan</th>
                <SortTh k="clients">Clients</SortTh><SortTh k="visits">Visites</SortTh><SortTh k="last_activity">Dernière activité</SortTh><SortTh k="status">Statut</SortTh><th className="px-2 py-2 font-medium">Actions</th>
              </tr></thead>
              <tbody>
                {d.rows.map((c) => (
                  <tr key={c.id} onClick={() => navigate(`/admin/commerces/${c.id}`)} className="cursor-pointer border-b border-[#F4F7FC] hover:bg-[#FAFCFF]">
                    <td className="px-2 py-2" onClick={(e) => e.stopPropagation()}><input type="checkbox" aria-label={`Choisir ${c.name}`} checked={picked.includes(c.id)} onChange={(e) => setPicked(e.target.checked ? [...picked, c.id] : picked.filter((x) => x !== c.id))} className="accent-[#2F6BFF]" /></td>
                    <td className="px-2 py-2"><span className="flex items-center gap-2.5"><CommerceLogo c={c} /><span className="max-w-[200px] truncate font-medium text-[#0B1C3F]">{c.name}</span></span></td>
                    <td className="px-2 py-2 text-[#475569]">{c.sector ? <span className="flex items-center gap-1.5"><Store size={13} className="text-[#94A3B8]" />{c.sector}</span> : '—'}</td>
                    <td className="px-2 py-2 text-[#475569]">{c.city ? <span className="flex items-center gap-1.5"><MapPin size={13} className="text-[#94A3B8]" />{c.city}</span> : '—'}</td>
                    <td className="px-2 py-2"><PlanPill p={c.plan} /></td>
                    <td className="px-2 py-2 tabular-nums text-[#0B1C3F]">{nf(c.clients)}</td>
                    <td className="px-2 py-2 tabular-nums text-[#0B1C3F]">{nf(c.visits)}</td>
                    <td className="whitespace-nowrap px-2 py-2 text-[#475569]">{ago(c.last_activity)}</td>
                    <td className="px-2 py-2"><span title={weekly(c) || c.status_label}><StatusPill s={c.status} label={c.status_label} /></span></td>
                    <td className="relative px-2 py-2" onClick={(e) => e.stopPropagation()}>
                      <button type="button" aria-label="Actions" onClick={() => setMenu(menu === c.id ? null : c.id)} className="rounded p-1 hover:bg-[#F4F7FC]"><MoreHorizontal size={16} /></button>
                      {menu === c.id && rowMenu(c)}
                    </td>
                  </tr>
                ))}
                {!d.rows.length && <tr><td colSpan={10} className="py-12 text-center text-[#64748B]">Aucun commerce ici.</td></tr>}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {d.rows.map((c) => (
              <button key={c.id} type="button" onClick={() => navigate(`/admin/commerces/${c.id}`)} className="rounded-2xl border border-[#EDF1F7] p-4 text-left hover:border-[#BFD3FF]">
                <p className="flex items-center gap-3"><CommerceLogo c={c} size={40} /><span className="min-w-0 flex-1"><strong className="block truncate text-[#0B1C3F]">{c.name}</strong><span className="text-[12px] text-[#64748B]">{[c.sector, c.city].filter(Boolean).join(' · ')}</span></span><StatusPill s={c.status} label={c.status_label} /></p>
                <p className="mt-3 grid grid-cols-3 gap-2 text-center text-[12px] text-[#64748B]">
                  <span><strong className="block text-[15px] text-[#0B1C3F]">{nf(c.clients)}</strong>clients</span>
                  <span><strong className="block text-[15px] text-[#0B1C3F]">{nf(c.visits)}</strong>visites</span>
                  <span title={weekly(c) || ''}><strong className="block text-[15px] text-[#0B1C3F]">{c.cards_week ?? '—'}</strong>cartes/sem.</span>
                </p>
                <p className="mt-3 flex items-center justify-between"><PlanPill p={c.plan} /><span className="text-[11.5px] text-[#94A3B8]">{ago(c.last_activity)}</span></p>
              </button>
            ))}
          </div>
        )}
        <Pager page={page} pages={d.pages} total={d.total} perPage={perPage} onPage={setPage} onPerPage={(n) => { setPerPage(n); setPage(1); }} what="commerces" />
      </Card>

      {toast}
      {modal?.type === 'suspend' && <SuspendModal c={modal.c} onClose={() => setModal(null)} onDone={(m) => { setModal(null); say(m); load(); }} />}
      {modal?.type === 'rules' && <RulesModal rules={d.rules} onClose={() => setModal(null)} onDone={() => { setModal(null); say('Règles enregistrées.'); load(); }} />}
      {modal?.type === 'add' && <AddCommerceModal onClose={() => setModal(null)} onDone={(id) => { setModal(null); navigate(`/admin/commerces/${id}`); }} />}
    </div>
  );
}

/* Résilier (user, 2026-10-01): the client told us they stop. The account
   closes at once AND the customers' cards stop working; nothing is deleted. */
export function ResilierModal({ c, onClose, onDone }) {
  const [reason, setReason] = useState('');
  const [told, setTold] = useState(new Date().toISOString().slice(0, 10));
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const ok = reason.trim().length >= 2 && confirm.trim().toUpperCase() === 'RÉSILIER';
  const go = async () => {
    setBusy(true);
    try {
      const { data } = await adminAPI.resilierCommerce(c.id, { reason: reason.trim(), contacted_at: told });
      onDone(`${c.name} résilié${data.sessions_ended ? ` · ${data.sessions_ended} session(s) fermée(s)` : ''}.`);
    } catch (e) { setErr(e?.response?.data?.detail?.[0]?.msg || e?.response?.data?.detail || 'Résiliation impossible.'); setBusy(false); }
  };
  return (
    <Modal title={`Résilier ${c.name} ?`} onClose={onClose}>
      <ul className="mb-3 space-y-1.5 rounded-xl bg-[#FEF2F2] p-3 text-[13px] text-[#7F1D1D]">
        <li>• Le compte est <strong>fermé tout de suite</strong> : le propriétaire et l'équipe ne peuvent plus se connecter.</li>
        <li>• Les <strong>cartes des clients cessent de fonctionner</strong> (carte, Wallet, inscriptions).</li>
        <li>• Aucune donnée n'est supprimée : « Annuler la résiliation » rouvre tout.</li>
      </ul>
      <label className="block"><span className="mb-1 block text-[11.5px] text-[#64748B]">Raison (obligatoire)</span>
        <textarea rows={3} className={`${inputCls} h-auto py-2`} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Ex. le gérant a appelé : fermeture du magasin…" /></label>
      <label className="mt-2 block"><span className="mb-1 block text-[11.5px] text-[#64748B]">Date de l'appel / de la demande</span>
        <input type="date" className={inputCls} value={told} max={new Date().toISOString().slice(0, 10)} onChange={(e) => setTold(e.target.value)} /></label>
      <label className="mt-2 block"><span className="mb-1 block text-[11.5px] text-[#64748B]">Tapez RÉSILIER pour confirmer</span>
        <input className={inputCls} value={confirm} onChange={(e) => setConfirm(e.target.value)} placeholder="RÉSILIER" /></label>
      {err && <p className="mt-2 text-[13px] text-[#C0392B]">{String(err)}</p>}
      <button type="button" disabled={busy || !ok} onClick={go} className="mt-3 flex w-full items-center justify-center gap-2 rounded-lg bg-[#0B1C3F] py-2.5 text-[13.5px] font-semibold text-white disabled:opacity-40">{busy && <Loader2 size={15} className="animate-spin" />} Résilier le commerce</button>
    </Modal>
  );
}

export function SuspendModal({ c, onClose, onDone }) {
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const go = async () => {
    setBusy(true);
    try { const { data } = await adminAPI.suspendCommerce(c.id, reason); onDone(`${c.name} suspendu${data.sessions_ended ? ` · ${data.sessions_ended} session(s) fermée(s)` : ''}.`); }
    catch (e) { setErr(e?.response?.data?.detail || 'Suspension impossible.'); setBusy(false); }
  };
  return (
    <Modal title={`Suspendre ${c.name} ?`} onClose={onClose}>
      <ul className="mb-3 space-y-1.5 text-[13px] text-[#334155]">
        <li>• Le propriétaire et l'équipe <strong>ne peuvent plus se connecter</strong> (les sessions ouvertes se ferment tout de suite).</li>
        <li>• Les <strong>cartes des clients continuent de fonctionner</strong>.</li>
        <li>• Vous pouvez réactiver le commerce en un clic.</li>
      </ul>
      <label className="block"><span className="mb-1 block text-[11.5px] text-[#64748B]">Motif (interne, facultatif)</span>
        <input className={inputCls} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Ex. impayé, demande du commerce…" /></label>
      {err && <p className="mt-2 text-[13px] text-[#C0392B]">{err}</p>}
      <button type="button" disabled={busy} onClick={go} className="mt-3 flex w-full items-center justify-center gap-2 rounded-lg bg-[#E11D48] py-2.5 text-[13.5px] font-semibold text-white disabled:opacity-50">{busy && <Loader2 size={15} className="animate-spin" />} Suspendre</button>
    </Modal>
  );
}

function RulesModal({ rules, onClose, onDone }) {
  const [f, setF] = useState({ actif_min: rules?.actif_min ?? 25, inactif_max: rules?.inactif_max ?? 15, window_days: rules?.window_days ?? 7 });
  const [err, setErr] = useState('');
  const save = async () => {
    try { await adminAPI.commercesRules({ actif_min: Number(f.actif_min), inactif_max: Number(f.inactif_max), window_days: Number(f.window_days) }); onDone(); }
    catch (e) { setErr(e?.response?.data?.detail?.[0]?.msg || e?.response?.data?.detail || 'Enregistrement impossible.'); }
  };
  const box = 'h-9 w-20 rounded-lg border border-[#DCE3EE] px-2';
  return (
    <Modal title="Règles du statut" onClose={onClose}>
      <p className="mb-3 text-[13px] text-[#475569]">Le statut dépend, <strong>par semaine</strong>, du nombre de <strong>nouvelles cartes</strong> données <strong>et</strong> de <strong>scans</strong> en magasin. Le plus faible des deux décide.</p>
      <div className="space-y-2 text-[13.5px]">
        <label className="flex flex-wrap items-center gap-2"><span className="w-24 font-medium text-[#0F8B58]">Actif</span> plus de <input type="number" min={0} className={box} value={f.actif_min} onChange={(e) => setF({ ...f, actif_min: e.target.value })} /> cartes et scans / semaine</label>
        <p className="flex flex-wrap items-center gap-2"><span className="w-24 font-medium text-[#D97706]">À risque</span> entre {f.inactif_max} et {f.actif_min} cartes et scans / semaine</p>
        <label className="flex flex-wrap items-center gap-2"><span className="w-24 font-medium text-[#E11D48]">Inactif</span> moins de <input type="number" min={0} className={box} value={f.inactif_max} onChange={(e) => setF({ ...f, inactif_max: e.target.value })} /> cartes ou scans / semaine</label>
        <label className="flex flex-wrap items-center gap-2 pt-1"><span className="w-24 text-[#475569]">Calculé sur</span><input type="number" min={1} max={90} className={box} value={f.window_days} onChange={(e) => setF({ ...f, window_days: e.target.value })} /> derniers jours (ramenés à une semaine)</label>
      </div>
      <p className="mt-3 text-[12px] text-[#64748B]">Ex. 30 cartes mais 10 scans dans la semaine → Inactif. Les commerces résiliés et les essais non convertis ont leur propre statut.</p>
      {err && <p className="mt-2 text-[13px] text-[#C0392B]">{String(err)}</p>}
      <button type="button" onClick={save} className="mt-4 w-full rounded-lg py-2.5 text-[13.5px] font-semibold text-white" style={{ background: BLUE }}>Enregistrer</button>
    </Modal>
  );
}

function AddCommerceModal({ onClose, onDone }) {
  const [f, setF] = useState({ name: '', sector: '', city: '', postal_code: '', phone: '', owner_first_name: '', owner_last_name: '', owner_email: '' });
  const [err, setErr] = useState('');
  const [done, setDone] = useState(null);
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true); setErr('');
    try { const { data } = await adminAPI.addCommerce(f); setDone(data); }
    catch (e) { setErr(e?.response?.data?.detail || 'Création impossible.'); }
    setBusy(false);
  };
  const inp = (k, label, ph, cls = '') => <label className={`block ${cls}`}><span className="mb-1 block text-[11.5px] text-[#64748B]">{label}</span><input className={inputCls} value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} placeholder={ph} /></label>;
  if (done) {
    return (
      <Modal title="Commerce créé" onClose={() => onDone(done.id)}>
        <p className="mb-3 text-[13.5px] text-[#334155]">Transmettez ces identifiants au propriétaire. <strong>Le mot de passe ne sera plus affiché</strong> ; il pourra le changer dans Paramètres › Sécurité.</p>
        <div className="space-y-2 rounded-xl bg-[#F8FAFF] p-3 font-mono text-[13px]">
          <p>Email : {done.owner.email}</p><p>Mot de passe : {done.owner.password}</p>
        </div>
        <button type="button" onClick={() => navigator.clipboard?.writeText(`Email : ${done.owner.email}\nMot de passe : ${done.owner.password}\nConnexion : ${window.location.origin}/login`)} className="mt-3 inline-flex items-center gap-2 text-[13px] text-[#2F6BFF]"><Copy size={14} /> Copier</button>
        <button type="button" onClick={() => onDone(done.id)} className="mt-3 w-full rounded-lg py-2.5 text-[13.5px] font-semibold text-white" style={{ background: BLUE }}>Ouvrir la fiche du commerce</button>
      </Modal>
    );
  }
  return (
    <Modal title="Ajouter un commerce" onClose={onClose}>
      <div className="grid gap-2 sm:grid-cols-2">
        {inp('name', 'Nom du commerce *', 'Ex. Café Milano', 'sm:col-span-2')}
        {inp('sector', 'Secteur', 'Ex. Café')}{inp('city', 'Ville', 'Ex. Tours')}
        {inp('postal_code', 'Code postal', '37000')}{inp('phone', 'Téléphone', '02 47 …')}
        {inp('owner_first_name', 'Prénom du propriétaire', '')}{inp('owner_last_name', 'Nom du propriétaire', '')}
        {inp('owner_email', 'Email du propriétaire *', 'contact@commerce.fr', 'sm:col-span-2')}
      </div>
      <p className="mt-2 text-[12px] text-[#64748B]">Le commerce démarre son essai gratuit de 28 jours. Un compte propriétaire est créé avec un mot de passe provisoire.</p>
      {err && <p className="mt-2 text-[13px] text-[#C0392B]">{err}</p>}
      <button type="button" disabled={busy || !f.name.trim() || !f.owner_email.includes('@')} onClick={save} className="mt-3 flex w-full items-center justify-center gap-2 rounded-lg py-2.5 text-[13.5px] font-semibold text-white disabled:opacity-50" style={{ background: BLUE }}>{busy && <Loader2 size={15} className="animate-spin" />} Créer le commerce</button>
    </Modal>
  );
}
