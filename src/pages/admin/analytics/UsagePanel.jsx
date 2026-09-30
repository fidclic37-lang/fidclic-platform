import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  CreditCard, Bell, MapPin, ArrowUp, ArrowDown, Search, Download, Filter, Check, X, Info, MoreHorizontal, Eye, Mail, SlidersHorizontal,
  ChevronLeft, ChevronRight, ChevronDown, Loader2,
} from 'lucide-react';
import { adminAPI } from '../../../lib/api';
import { useToast, downloadBlob, nf } from '../../crm/ui';
import { StatusPill, PlanPill, CommerceLogo } from '../CommercesPage';

/* Super admin › Analytics — « Utilisation des plans », taken from the
   « Gestion des abonnements » mockup (features/analytics_usage.py): three
   figures, then « Utilisation par commerce / Répartition par plan /
   Renouvellements » with filters, CSV export and pages. */

const eur = (v) => `${Number(v || 0).toLocaleString('fr-FR', { maximumFractionDigits: 2 })} €`;
const day = (iso) => (iso ? new Date(iso).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric' }) : '—');
const TABS = [['commerces', 'Utilisation par commerce'], ['plans', 'Répartition par plan'], ['renewals', 'Renouvellements']];
const MORE = {
  ia: ['IA', [['', 'Tous'], ['oui', 'Incluse'], ['non', 'Non incluse']]],
  geo: ['Géolocalisation', [['', 'Tous'], ['on', 'Activée'], ['off', 'Incluse, non activée'], ['none', 'Non incluse']]],
  wallet: ['Wallet', [['', 'Tous'], ['oui', 'Inclus'], ['non', 'Non inclus']]],
  multi: ['Multi-sites', [['', 'Tous'], ['oui', 'Inclus'], ['non', 'Non inclus']]],
  usage: ['Utilisation', [['', 'Toutes'], ['alerte', 'Proche de la limite'], ['atteinte', 'Limite atteinte']]],
  renew: ['Renouvellement', [['', 'Tous'], ['7', 'Sous 7 jours'], ['30', 'Sous 30 jours']]],
  sub: ['Abonnement', [['', 'Tous'], ['payant', 'Payant'], ['essai', 'En essai']]],
};
const EMPTY = { q: '', plan: '', sector: '', city: '', status: '', ia: '', geo: '', wallet: '', multi: '', usage: '', renew: '', sub: '' };
const RENEW_TONE = { renouvellement: ['#EAF1FF', '#2F6BFF'], fin_essai: ['#F3EEFF', '#7C3AED'], fin_abonnement: ['#F1F5F9', '#475569'], retard: ['#FDECEF', '#E11D48'] };

/* ---------------------------------------------------------------- figures */
function Figure({ icon: I, tone, bg, value, label, delta, sub }) {
  const up = (delta ?? 0) >= 0;
  return (
    <div className="flex items-center gap-4 rounded-2xl border border-[#EDF1F7] bg-white px-5 py-4 shadow-[0_1px_2px_rgba(11,28,63,.03)]">
      <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl" style={{ background: bg, color: tone }}><I size={24} /></span>
      <div className="min-w-0">
        <p className="text-[22px] font-bold leading-none text-[#0B1C3F]">{value}</p>
        <p className="mt-1.5 text-[12.5px] leading-tight text-[#475569]">{label}</p>
        {sub ? <p className="mt-1.5 text-[12px] text-[#64748B]">{sub}</p>
          : delta !== undefined && delta !== null
            ? <p className={`mt-1.5 flex items-center gap-1 text-[12.5px] font-semibold ${up ? 'text-[#10B981]' : 'text-[#E11D48]'}`}>{up ? <ArrowUp size={13} /> : <ArrowDown size={13} />}{up ? '+' : ''}{delta}%</p>
            : <p className="mt-1.5 text-[12px] text-[#94A3B8]">—</p>}
      </div>
    </div>
  );
}

export function UsageFigures({ range }) {
  const [f, setF] = useState(null);
  useEffect(() => { adminAPI.usageFigures(range).then(({ data }) => setF(data)).catch(() => setF(null)); }, [range]);
  if (!f) return <div className="grid gap-3 md:grid-cols-3">{[0, 1, 2].map((i) => <div key={i} className="h-[98px] animate-pulse rounded-2xl border border-[#EDF1F7] bg-white" />)}</div>;
  return (
    <div className="grid gap-3 md:grid-cols-3">
      <Figure icon={CreditCard} tone="#10B981" bg="#E7F7EE" value={nf(f.cards.value)} label="Cartes actives" delta={f.cards.delta} />
      <Figure icon={Bell} tone="#F43F5E" bg="#FDECEF" value={nf(f.push.value)} label={`Notifications envoyées (${f.push.month ? 'mois' : 'période'})`} delta={f.push.delta} />
      <Figure icon={MapPin} tone="#8B5CF6" bg="#F3EEFF" value={nf(f.geo.value)} label="Géolocalisation activée" sub={`${f.geo.pct}% des commerces`} />
    </div>
  );
}

/* ---------------------------------------------------------------- bits */
const Tip = ({ text }) => (
  <span className="group relative inline-flex align-middle">
    <Info size={12.5} className="text-[#94A3B8]" />
    <span className="pointer-events-none absolute left-1/2 top-5 z-20 hidden w-56 -translate-x-1/2 rounded-lg bg-[#0B1C3F] px-2.5 py-2 text-left text-[11.5px] font-normal normal-case leading-snug text-white shadow-lg group-hover:block">{text}</span>
  </span>
);
const Yes = ({ title }) => <span title={title} className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-[#E7F7EE] text-[#10B981]"><Check size={14} strokeWidth={3} /></span>;
const No = ({ title, grey }) => <span title={title} className={`inline-flex h-6 w-6 items-center justify-center ${grey ? 'text-[#64748B]' : 'text-[#E11D48]'}`}><X size={15} strokeWidth={2.5} /></span>;
const Off = ({ title }) => <span title={title} className="inline-flex h-6 w-6 items-center justify-center rounded-full border border-dashed border-[#CBD5E1] text-[#94A3B8]"><Check size={12} strokeWidth={2.5} /></span>;

function Meter({ u, color }) {
  const hot = u.pct !== null && u.pct > 90;
  return (
    <div className="w-[128px]">
      <p className="flex items-baseline justify-between gap-2 whitespace-nowrap text-[12.5px]">
        <span><strong className="font-semibold text-[#0B1C3F]">{nf(u.used)}</strong><span className="text-[#64748B]"> / {u.limit ? nf(u.limit) : 'illimité'}</span></span>
        {u.pct !== null && <span className={`text-[12px] ${u.pct >= 100 ? 'font-semibold text-[#E11D48]' : 'text-[#64748B]'}`}>{u.pct}%</span>}
      </p>
      <span className="mt-1 block h-[5px] overflow-hidden rounded-full bg-[#EEF2F8]">
        {u.pct !== null && <span className="block h-full rounded-full" style={{ width: `${Math.min(100, u.pct)}%`, background: hot ? '#F59E0B' : color }} />}
      </span>
    </div>
  );
}

function Pick({ label, value, onChange, options, width = 'w-[150px]' }) {
  return (
    <label className={`block ${width}`}>
      <span className="mb-1 block text-[12px] text-[#475569]">{label}</span>
      <span className="relative block">
        <select value={value} onChange={(e) => onChange(e.target.value)} className="h-10 w-full appearance-none rounded-lg border border-[#DCE3EE] bg-white pl-3 pr-8 text-[13px] text-[#0B1C3F] outline-none focus:border-[#2F6BFF]">
          {options.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
        <ChevronDown size={15} className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-[#0B1C3F]" />
      </span>
    </label>
  );
}

function Pages({ d, what, onPage, onPerPage }) {
  const { page, pages, total, per_page: per } = d;
  const nums = [];
  for (let i = 1; i <= pages; i += 1) if (i <= 5 || i === pages || Math.abs(i - page) <= 1) nums.push(i);
  const shown = [];
  nums.forEach((n, i) => { if (i && n - nums[i - 1] > 1) shown.push('…'); shown.push(n); });
  return (
    <div className="mt-3 flex flex-wrap items-center gap-3 px-1 text-[12.5px]">
      <span className="text-[#475569]">Affichage de {total ? (page - 1) * per + 1 : 0} à {Math.min(total, page * per)} sur {nf(total)} {what}</span>
      <span className="ml-auto flex flex-wrap items-center gap-1.5">
        <span className="relative mr-3">
          <select aria-label="Lignes par page" value={per} onChange={(e) => onPerPage(Number(e.target.value))} className="h-9 appearance-none rounded-lg border border-[#DCE3EE] bg-white pl-3 pr-8 text-[12.5px] font-medium text-[#0B1C3F]">
            {[10, 25, 50, 100].map((n) => <option key={n} value={n}>{n} par page</option>)}
          </select>
          <ChevronDown size={14} className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2" />
        </span>
        <button type="button" aria-label="Page précédente" disabled={page <= 1} onClick={() => onPage(page - 1)} className="flex h-8 w-8 items-center justify-center rounded-lg text-[#2F6BFF] disabled:opacity-30"><ChevronLeft size={16} /></button>
        {shown.map((n, i) => (n === '…' ? <span key={`e${i}`} className="px-1 text-[#94A3B8]">…</span>
          : <button key={n} type="button" onClick={() => onPage(n)} className={`h-8 min-w-8 rounded-lg px-2 font-medium ${n === page ? 'bg-[#2F6BFF] text-white' : 'text-[#0B1C3F] hover:bg-[#F4F7FC]'}`}>{n}</button>))}
        <button type="button" aria-label="Page suivante" disabled={page >= pages} onClick={() => onPage(page + 1)} className="flex h-8 w-8 items-center justify-center rounded-lg text-[#2F6BFF] disabled:opacity-30"><ChevronRight size={16} /></button>
      </span>
    </div>
  );
}

function RowMenu({ c, onClose }) {
  const navigate = useNavigate();
  const ref = useRef(null);
  useEffect(() => {
    const out = (e) => { if (ref.current && !ref.current.contains(e.target)) onClose(); };
    document.addEventListener('mousedown', out);
    return () => document.removeEventListener('mousedown', out);
  }, [onClose]);
  const item = 'flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-[#F4F7FC]';
  return (
    <div ref={ref} className="absolute right-2 top-9 z-30 w-56 overflow-hidden rounded-xl border border-[#EDF1F7] bg-white py-1 text-[13px] text-[#0B1C3F] shadow-lg">
      <button type="button" className={item} onClick={() => navigate(`/admin/commerces/${c.id}`)}><Eye size={14} /> Voir le commerce</button>
      <button type="button" className={item} onClick={() => navigate(`/admin/commerces/${c.id}?contact=1`)}><Mail size={14} /> Contacter</button>
      <button type="button" className={item} onClick={() => navigate('/admin/plan-limits')}><SlidersHorizontal size={14} /> Limites du plan {c.plan.label}</button>
    </div>
  );
}

const Loader = () => <div className="flex items-center justify-center gap-2 py-16 text-[13px] text-[#64748B]"><Loader2 size={16} className="animate-spin" /> Chargement…</div>;

/* ---------------------------------------------------------------- panel */
export default function UsagePanel() {
  const [tab, setTab] = useState('commerces');
  const [f, setF] = useState(EMPTY);
  const [more, setMore] = useState(false);
  const [page, setPage] = useState(1);
  const [per, setPer] = useState(10);
  const [sort, setSort] = useState('name');
  const [d, setD] = useState(null);
  const [plans, setPlans] = useState(null);
  const [rn, setRn] = useState(null);
  const [within, setWithin] = useState('30');
  const [kind, setKind] = useState('');
  const [picked, setPicked] = useState(() => new Set());
  const [menu, setMenu] = useState(null);
  const [err, setErr] = useState('');
  const [say, toast] = useToast();
  const navigate = useNavigate();
  const [q, setQ] = useState('');

  useEffect(() => { const t = setTimeout(() => { setF((x) => (x.q === q ? x : { ...x, q })); setPage(1); }, 300); return () => clearTimeout(t); }, [q]);
  const set = (k) => (v) => { setF((x) => ({ ...x, [k]: v })); setPage(1); };
  const fail = (e) => setErr(typeof e?.response?.data?.detail === 'string' ? e.response.data.detail : 'Impossible de charger les données.');

  const load = useCallback(() => {
    setErr('');
    if (tab === 'commerces') adminAPI.usageCommerces({ ...f, sort, page, per_page: per }).then(({ data }) => setD(data)).catch(fail);
    else if (tab === 'plans') adminAPI.usagePlans().then(({ data }) => setPlans(data)).catch(fail);
    else adminAPI.usageRenewals({ within, kind, q: f.q, plan: f.plan, sector: f.sector, city: f.city, status: f.status, page, per_page: per })
      .then(({ data }) => setRn(data)).catch(fail);
  }, [tab, f, sort, page, per, within, kind]);
  useEffect(() => { load(); }, [load]);

  const moreCount = Object.keys(MORE).filter((k) => f[k]).length;
  const opts = (d || rn)?.options;
  const exportCsv = () => {
    const ids = picked.size && tab !== 'plans' ? [...picked].join(',') : '';
    const params = tab === 'plans' ? { tab } : { tab, ...f, within, kind, ...(ids ? { ids } : {}) };
    downloadBlob(adminAPI.usageExport(params), `fidclic-${tab}.csv`).catch(() => say('Export impossible.'));
  };
  const toggle = (id) => setPicked((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const pageIds = (d?.rows || []).map((r) => r.id);
  const allPicked = pageIds.length > 0 && pageIds.every((id) => picked.has(id));
  const toggleAll = () => setPicked((s) => { const n = new Set(s); pageIds.forEach((id) => (allPicked ? n.delete(id) : n.add(id))); return n; });
  const sortBy = (k) => { setSort((s) => (s === k ? `-${k}` : s === `-${k}` ? k : (k === 'name' || k === 'renewal' ? k : `-${k}`))); setPage(1); };
  const Th = ({ k, children, className = '' }) => (
    <th className={`px-2 py-3 font-medium ${className}`}>
      {k ? <button type="button" onClick={() => sortBy(k)} className="inline-flex items-center gap-1 hover:text-[#0B1C3F]">{children}{sort.replace('-', '') === k && (sort.startsWith('-') ? <ArrowDown size={12} /> : <ArrowUp size={12} />)}</button> : children}
    </th>
  );
  const goNear = (plan) => { setTab('commerces'); setF({ ...EMPTY, plan, usage: 'alerte' }); setQ(''); setPage(1); };

  const filters = opts && (
    <div className="flex flex-wrap items-end gap-3 px-1 pb-3">
      <label className="relative block min-w-[220px] flex-1 self-end">
        <Search size={17} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-[#64748B]" />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Rechercher un commerce..." className="h-11 w-full rounded-xl border border-[#E2E8F0] bg-[#F8FAFC] pl-10 pr-3 text-[13.5px] text-[#0B1C3F] outline-none placeholder:text-[#64748B] focus:border-[#2F6BFF]" />
      </label>
      <Pick label="Plan" value={f.plan} onChange={set('plan')} options={[['', 'Tous'], ...opts.plans.map((p) => [p.key, p.label])]} />
      <Pick label="Secteur" value={f.sector} onChange={set('sector')} options={[['', 'Tous'], ...opts.sectors.map((s) => [s, s])]} />
      <Pick label="Ville" value={f.city} onChange={set('city')} options={[['', 'Toutes les villes'], ...opts.cities.map((s) => [s, s])]} />
      <Pick label="Statut" value={f.status} onChange={set('status')} options={[['', 'Tous'], ...opts.statuses.map((s) => [s.key, s.label])]} />
      {tab === 'commerces' ? (
        <button type="button" onClick={() => setMore((m) => !m)} className={`inline-flex h-11 items-center gap-2 rounded-xl border px-5 text-[13px] font-semibold ${more || moreCount ? 'border-[#2F6BFF] bg-[#EFF5FF] text-[#2F6BFF]' : 'border-[#BFD3FF] bg-white text-[#2F6BFF]'}`}>
          <Filter size={16} /> Plus de filtres{moreCount ? <span className="rounded-full bg-[#2F6BFF] px-1.5 text-[11px] text-white">{moreCount}</span> : null}
        </button>
      ) : (
        <>
          <Pick label="Échéance" value={within} onChange={(v) => { setWithin(v); setPage(1); }} options={[['7', 'Sous 7 jours'], ['30', 'Sous 30 jours'], ['90', 'Sous 90 jours'], ['all', 'Toutes']]} />
          <Pick label="Type" value={kind} onChange={(v) => { setKind(v); setPage(1); }} options={[['', 'Tous'], ...(rn?.kinds || []).map((k) => [k.key, k.label])]} />
        </>
      )}
    </div>
  );

  return (
    <section className="mt-4 rounded-2xl border border-[#EDF1F7] bg-white p-3 shadow-[0_1px_2px_rgba(11,28,63,.03)] sm:p-4">
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap gap-1" role="tablist">
          {TABS.map(([k, l]) => (
            <button key={k} type="button" role="tab" aria-selected={tab === k} onClick={() => { setTab(k); setPage(1); setMore(false); setMenu(null); }}
                    className={`h-10 rounded-full px-5 text-[13.5px] font-medium ${tab === k ? 'bg-[#2F6BFF] text-white shadow-[0_2px_6px_rgba(47,107,255,.3)]' : 'text-[#0B1C3F] hover:bg-[#F4F7FC]'}`}>{l}</button>
          ))}
        </div>
        <span className="ml-auto flex items-center gap-2">
          {picked.size > 0 && tab !== 'plans' && (
            <span className="text-[12.5px] text-[#475569]">{picked.size} sélectionné{picked.size > 1 ? 's' : ''} · <button type="button" onClick={() => setPicked(new Set())} className="text-[#2F6BFF] hover:underline">Désélectionner</button></span>
          )}
          <button type="button" onClick={exportCsv} className="inline-flex h-10 items-center gap-2 rounded-lg border border-[#2F6BFF] bg-white px-4 text-[13px] font-semibold text-[#2F6BFF] hover:bg-[#EFF5FF]">
            <Download size={16} /> Exporter (CSV)
          </button>
        </span>
      </div>

      {err && <p className="mb-3 rounded-xl bg-[#FEF2F2] px-4 py-3 text-[13px] text-[#B91C1C]">{err}</p>}
      {tab !== 'plans' && filters}
      {tab === 'commerces' && more && (
        <div className="mx-1 mb-3 rounded-xl border border-[#E2E8F0] bg-[#F8FAFC] p-3">
          <div className="flex flex-wrap gap-3">
            {Object.entries(MORE).map(([k, [label, options]]) => <Pick key={k} label={label} value={f[k]} onChange={set(k)} options={options} width="w-[170px]" />)}
          </div>
          {moreCount > 0 && <button type="button" onClick={() => { setF((x) => ({ ...x, ...Object.fromEntries(Object.keys(MORE).map((k) => [k, ''])) })); setPage(1); }} className="mt-2 text-[12.5px] font-medium text-[#2F6BFF] hover:underline">Réinitialiser ces filtres</button>}
        </div>
      )}

      {tab === 'commerces' && (!d ? <Loader /> : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1180px] text-left text-[13px]">
              <thead className="border-b border-[#EDF1F7] text-[12.5px] text-[#475569]">
                <tr>
                  <th className="w-8 px-2 py-3"><input type="checkbox" aria-label="Tout sélectionner" checked={allPicked} onChange={toggleAll} className="h-4 w-4 rounded border-[#CBD5E1] accent-[#2F6BFF]" /></th>
                  <Th k="name" className="pl-12">Commerce</Th>
                  <Th k="plan" className="text-center">Plan</Th>
                  <Th className="text-center">Statut</Th>
                  <Th k="cards"><span className="inline-flex items-center gap-1">Cartes <Tip text="Cartes actives (clients venus au moins une fois dans les 12 derniers mois) / limite du plan." /></span></Th>
                  <Th k="push"><span className="inline-flex items-center gap-1">Notifications <Tip text="Notifications envoyées ce mois-ci / limite mensuelle du plan." /></span></Th>
                  <Th className="text-center"><span className="inline-flex items-center gap-1">IA <Tip text="Le plan donne accès à FIDCLIC AI (analyses de base ou avancées)." /></span></Th>
                  <Th className="text-center"><span className="inline-flex items-center gap-1">Géo <Tip text="Coche verte : incluse et activée par le commerce. Coche en pointillés : incluse mais pas activée. Croix : pas dans le plan." /></span></Th>
                  <Th className="text-center"><span className="inline-flex items-center gap-1">Wallet <Tip text="Carte ajoutable à Apple Wallet et Google Wallet (selon le plan)." /></span></Th>
                  <Th className="text-center"><span className="inline-flex items-center gap-1">Multi-sites <Tip text="Plusieurs points de vente dans un même compte (selon le plan)." /></span></Th>
                  <Th k="renewal">Prochain renouvellement</Th>
                  <Th className="text-center">Actions</Th>
                </tr>
              </thead>
              <tbody>
                {d.rows.map((c) => {
                  const soon = c.renewal && (c.renewal.days <= 7 || c.renewal.kind === 'retard');
                  return (
                    <tr key={c.id} onClick={() => navigate(`/admin/commerces/${c.id}`)} className={`cursor-pointer border-b border-[#F1F5F9] hover:bg-[#FAFCFF] ${picked.has(c.id) ? 'bg-[#F5F9FF]' : ''}`}>
                      <td className="px-2 py-2.5" onClick={(e) => e.stopPropagation()}><input type="checkbox" aria-label={`Sélectionner ${c.name}`} checked={picked.has(c.id)} onChange={() => toggle(c.id)} className="h-4 w-4 rounded border-[#CBD5E1] accent-[#2F6BFF]" /></td>
                      <td className="px-2 py-2.5">
                        <span className="flex items-center gap-3"><CommerceLogo c={c} size={30} />
                          <span className="min-w-0"><strong className="block max-w-[190px] truncate text-[13px] font-semibold text-[#0B1C3F]">{c.name}</strong>
                            <span className="block max-w-[190px] truncate text-[12px] text-[#64748B]">{[c.sector, c.city].filter(Boolean).join(' · ')}</span></span></span>
                      </td>
                      <td className="px-2 py-2.5 text-center"><PlanPill p={c.plan} />{c.trial && <span className="mt-0.5 block text-[11px] text-[#7C3AED]">en essai</span>}</td>
                      <td className="px-2 py-2.5 text-center"><StatusPill s={c.status} label={c.status_label} /></td>
                      <td className="px-2 py-2.5"><Meter u={c.cards} color="#2F6BFF" /></td>
                      <td className="px-2 py-2.5"><Meter u={c.push} color="#10B981" /></td>
                      <td className="px-2 py-2.5 text-center">{c.ai ? <Yes title={c.ai_level === 'advanced' ? 'Analyses avancées' : 'Analyses de base'} /> : <No title="Pas d'IA dans ce plan" />}</td>
                      <td className="px-2 py-2.5 text-center">{c.geo === 'on' ? <Yes title="Activée" /> : c.geo === 'off' ? <Off title="Incluse, non activée par le commerce" /> : <No title="Pas dans ce plan" />}</td>
                      <td className="px-2 py-2.5 text-center">{c.wallet ? <Yes title="Inclus" /> : <No title="Pas dans ce plan" />}</td>
                      <td className="px-2 py-2.5 text-center">{c.multi ? <Yes title="Inclus" /> : <No grey title="Pas dans ce plan" />}</td>
                      <td className="whitespace-nowrap px-2 py-2.5">
                        {c.renewal ? <span title={c.renewal.kind_label} className={`text-[13px] ${soon ? 'font-medium text-[#E11D48]' : 'text-[#475569]'}`}>{day(c.renewal.at)}</span> : <span className="text-[#94A3B8]">—</span>}
                        {c.renewal && c.renewal.kind !== 'renouvellement' && <span className="block text-[11px] text-[#64748B]">{c.renewal.kind_label}</span>}
                      </td>
                      <td className="relative px-2 py-2.5 text-center" onClick={(e) => e.stopPropagation()}>
                        <button type="button" aria-label={`Actions pour ${c.name}`} onClick={() => setMenu(menu === c.id ? null : c.id)} className="rounded p-1 text-[#0B1C3F] hover:bg-[#F4F7FC]"><MoreHorizontal size={18} /></button>
                        {menu === c.id && <RowMenu c={c} onClose={() => setMenu(null)} />}
                      </td>
                    </tr>
                  );
                })}
                {!d.rows.length && <tr><td colSpan={12} className="py-12 text-center text-[#64748B]">Aucun commerce ne correspond à ces filtres.</td></tr>}
              </tbody>
            </table>
          </div>
          <Pages d={d} what="commerces" onPage={setPage} onPerPage={(n) => { setPer(n); setPage(1); }} />
        </>
      ))}

      {tab === 'plans' && (!plans ? <Loader /> : <PlanSplit p={plans} onNear={goNear} onPlan={(k) => { setTab('commerces'); setF({ ...EMPTY, plan: k }); setQ(''); setPage(1); }} />)}

      {tab === 'renewals' && (!rn ? <Loader /> : (
        <>
          <div className="mb-3 grid gap-2 px-1 sm:grid-cols-2 xl:grid-cols-5">
            {[['Sous 7 jours', `${nf(rn.summary.week)} commerce${rn.summary.week > 1 ? 's' : ''}`, `${eur(rn.summary.week_amount)} à renouveler`, '#2F6BFF', () => { setWithin('7'); setKind(''); }],
              ['Sous 30 jours', `${nf(rn.summary.month)} commerce${rn.summary.month > 1 ? 's' : ''}`, `${eur(rn.summary.month_amount)} à renouveler`, '#2F6BFF', () => { setWithin('30'); setKind(''); }],
              ["Fins d'essai (7 jours)", nf(rn.summary.trials), 'à convertir', '#7C3AED', () => { setWithin('7'); setKind('fin_essai'); }],
              ['Paiements en retard', nf(rn.summary.late), 'à relancer', '#E11D48', () => { setWithin('all'); setKind('retard'); }],
              ["Fins d'abonnement", nf(rn.summary.ending), 'résiliation prévue', '#475569', () => { setWithin('all'); setKind('fin_abonnement'); }],
            ].map(([t, v, s, c, go]) => (
              <button key={t} type="button" onClick={() => { go(); setPage(1); }} className="rounded-xl border border-[#EDF1F7] bg-[#FAFCFF] px-4 py-3 text-left hover:border-[#BFD3FF]">
                <span className="block text-[12px] text-[#64748B]">{t}</span>
                <strong className="block text-[17px] text-[#0B1C3F]" style={{ color: c }}>{v}</strong>
                <span className="block text-[12px] text-[#475569]">{s}</span>
              </button>
            ))}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] text-left text-[13px]">
              <thead className="border-b border-[#EDF1F7] text-[12.5px] text-[#475569]">
                <tr><th className="px-2 py-3 font-medium">Commerce</th><th className="px-2 py-3 text-center font-medium">Plan</th><th className="px-2 py-3 text-center font-medium">Statut</th>
                  <th className="px-2 py-3 font-medium">Type</th><th className="px-2 py-3 font-medium">Date</th><th className="px-2 py-3 font-medium">Échéance</th>
                  <th className="px-2 py-3 text-right font-medium">Montant</th><th className="px-2 py-3 font-medium">Moyen de paiement</th><th className="px-2 py-3 text-center font-medium">Actions</th></tr>
              </thead>
              <tbody>
                {rn.rows.map((c) => {
                  const r = c.renewal; const [bg, fg] = RENEW_TONE[r.kind] || RENEW_TONE.renouvellement;
                  const when = r.days < 0 ? `il y a ${-r.days} j` : r.days === 0 ? "aujourd'hui" : `dans ${r.days} j`;
                  return (
                    <tr key={c.id} onClick={() => navigate(`/admin/commerces/${c.id}`)} className="cursor-pointer border-b border-[#F1F5F9] hover:bg-[#FAFCFF]">
                      <td className="px-2 py-2.5"><span className="flex items-center gap-3"><CommerceLogo c={c} size={30} /><span className="min-w-0"><strong className="block max-w-[210px] truncate font-semibold text-[#0B1C3F]">{c.name}</strong><span className="block truncate text-[12px] text-[#64748B]">{[c.sector, c.city].filter(Boolean).join(' · ')}</span></span></span></td>
                      <td className="px-2 py-2.5 text-center"><PlanPill p={c.plan} /></td>
                      <td className="px-2 py-2.5 text-center"><StatusPill s={c.status} label={c.status_label} /></td>
                      <td className="px-2 py-2.5"><span className="whitespace-nowrap rounded-md px-2.5 py-1 text-[12px] font-medium" style={{ background: bg, color: fg }}>{r.kind_label}</span></td>
                      <td className="whitespace-nowrap px-2 py-2.5 text-[#475569]">{day(r.at)}</td>
                      <td className={`whitespace-nowrap px-2 py-2.5 ${r.days <= 7 || r.kind === 'retard' ? 'font-medium text-[#E11D48]' : 'text-[#475569]'}`}>{when}</td>
                      <td className="whitespace-nowrap px-2 py-2.5 text-right font-semibold text-[#0B1C3F]">{r.kind === 'fin_essai' ? <span className="font-normal text-[#64748B]">{eur(c.price)} si converti</span> : `${eur(c.price)} / mois`}</td>
                      <td className="whitespace-nowrap px-2 py-2.5 text-[#475569]">{c.payment?.last4 ? `${(c.payment.brand || 'Carte').toUpperCase()} •••• ${c.payment.last4}` : '—'}</td>
                      <td className="relative px-2 py-2.5 text-center" onClick={(e) => e.stopPropagation()}>
                        <button type="button" aria-label={`Actions pour ${c.name}`} onClick={() => setMenu(menu === c.id ? null : c.id)} className="rounded p-1 hover:bg-[#F4F7FC]"><MoreHorizontal size={18} /></button>
                        {menu === c.id && <RowMenu c={c} onClose={() => setMenu(null)} />}
                      </td>
                    </tr>
                  );
                })}
                {!rn.rows.length && <tr><td colSpan={9} className="py-12 text-center text-[#64748B]">Aucun renouvellement sur cette période.</td></tr>}
              </tbody>
            </table>
          </div>
          <Pages d={rn} what="commerces" onPage={setPage} onPerPage={(n) => { setPer(n); setPage(1); }} />
        </>
      ))}
      {toast}
    </section>
  );
}

function PlanSplit({ p, onNear, onPlan }) {
  const AI = { none: 'Non', basic: 'Analyses de base', advanced: 'Analyses avancées' };
  const Bar = ({ pct, color }) => <span className="mt-1 block h-[5px] w-[110px] overflow-hidden rounded-full bg-[#EEF2F8]"><span className="block h-full rounded-full" style={{ width: `${Math.min(100, pct || 0)}%`, background: pct > 90 ? '#F59E0B' : color }} /></span>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[1080px] text-left text-[13px]">
        <thead className="border-b border-[#EDF1F7] text-[12.5px] text-[#475569]">
          <tr>
            <th className="px-2 py-3 font-medium">Plan</th><th className="px-2 py-3 font-medium">Commerces</th><th className="px-2 py-3 font-medium">Payants · essai</th>
            <th className="px-2 py-3 text-right font-medium">MRR</th><th className="px-2 py-3 font-medium">Cartes actives</th><th className="px-2 py-3 font-medium">Notifications (mois)</th>
            <th className="px-2 py-3 text-center font-medium"><span className="inline-flex items-center gap-1">Proches de la limite <Tip text={`Commerces ayant utilisé au moins ${p.threshold} % de leurs cartes ou de leurs notifications (seuil de Plan Limits).`} /></span></th>
            <th className="px-2 py-3 text-center font-medium">IA</th><th className="px-2 py-3 text-center font-medium">Géo</th><th className="px-2 py-3 text-center font-medium">Wallet</th><th className="px-2 py-3 text-center font-medium">Multi-sites</th>
          </tr>
        </thead>
        <tbody>
          {p.rows.map((r) => (
            <tr key={r.key} className="border-b border-[#F1F5F9]">
              <td className="px-2 py-3">
                <button type="button" onClick={() => onPlan(r.key)} className="flex items-center gap-3 text-left" title="Voir ces commerces">
                  <PlanPill p={r} />
                  <span className="text-[12.5px] text-[#475569]">{r.on_quote ? 'sur devis' : `${nf(r.price)}€ / mois`}</span>
                </button>
              </td>
              <td className="px-2 py-3">
                <strong className="text-[#0B1C3F]">{nf(r.count)}</strong><span className="text-[#64748B]"> · {r.pct}% du total</span>
                <span className="mt-1 block h-[5px] w-[120px] overflow-hidden rounded-full bg-[#EEF2F8]"><span className="block h-full rounded-full" style={{ width: `${r.pct}%`, background: r.color }} /></span>
              </td>
              <td className="px-2 py-3 text-[#475569]">{nf(r.paying)} · {nf(r.trials)}</td>
              <td className="whitespace-nowrap px-2 py-3 text-right font-semibold text-[#0B1C3F]">{eur(r.mrr)}</td>
              <td className="px-2 py-3"><strong className="text-[#0B1C3F]">{nf(r.cards)}</strong>{r.cards_pct !== null && <span className="text-[12px] text-[#64748B]"> · {r.cards_pct}% en moyenne</span>}{r.cards_pct !== null && <Bar pct={r.cards_pct} color="#2F6BFF" />}</td>
              <td className="px-2 py-3"><strong className="text-[#0B1C3F]">{nf(r.push)}</strong>{r.push_pct !== null ? <span className="text-[12px] text-[#64748B]"> · {r.push_pct}% en moyenne</span> : <span className="text-[12px] text-[#64748B]"> · illimité</span>}{r.push_pct !== null && <Bar pct={r.push_pct} color="#10B981" />}</td>
              <td className="px-2 py-3 text-center">{r.near ? <button type="button" onClick={() => onNear(r.key)} className="rounded-md bg-[#FFF4DB] px-2.5 py-1 text-[12.5px] font-semibold text-[#D97706] hover:underline">{nf(r.near)}</button> : <span className="text-[#94A3B8]">0</span>}</td>
              <td className="px-2 py-3 text-center">{r.ai_level !== 'none' ? <span title={AI[r.ai_level] || r.ai_level}><Yes /></span> : <No title="Pas d'IA" />}</td>
              <td className="px-2 py-3 text-center">{r.geo ? <span className="inline-flex flex-col items-center"><Yes /><span className="mt-0.5 text-[11px] text-[#64748B]">{nf(r.geo_on)} activée{r.geo_on > 1 ? 's' : ''}</span></span> : <No />}</td>
              <td className="px-2 py-3 text-center">{r.wallet ? <Yes /> : <No />}</td>
              <td className="px-2 py-3 text-center">{r.multi ? <Yes /> : <No grey />}</td>
            </tr>
          ))}
          {!p.rows.length && <tr><td colSpan={11} className="py-12 text-center text-[#64748B]">Aucun commerce pour le moment.</td></tr>}
        </tbody>
        {p.rows.length > 0 && (
          <tfoot><tr className="text-[13px] font-semibold text-[#0B1C3F]"><td className="px-2 py-3">Total</td><td className="px-2 py-3">{nf(p.total)} commerces</td><td /><td className="whitespace-nowrap px-2 py-3 text-right">{eur(p.mrr)}</td><td colSpan={7} /></tr></tfoot>
        )}
      </table>
    </div>
  );
}
