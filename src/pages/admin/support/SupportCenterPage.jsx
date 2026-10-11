import { vh } from '../../../lib/fit';
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Inbox, Clock3, Clock, CheckCircle2, AlertTriangle, ArrowUpRight, ArrowDownRight, Download, Plus, Search, Filter, LayoutGrid,
  Check, CheckCheck, MoreVertical, Phone, Mail, MapPin, ExternalLink, Crown, Users, Megaphone, BarChart3, X, ChevronDown, AtSign,
  Send, UserRound, CircleAlert, LayoutList, Flag, Store, ChevronLeft, Loader2, Pencil, Trash2, StickyNote, RotateCcw, Link2,
  MailOpen, Info,
} from 'lucide-react';
import { supportAPI } from '../../../lib/api';
import { Breadcrumb, Modal, Loading, useToast, downloadBlob, nf } from '../../crm/ui';
import {
  STATUS_TONE, PRIORITY_TONE, PRIORITY_BAR, TAG_TONE, StatusPill, Avatar, when, clock, fullDate, dayLabel, errText,
  Attachment, EmojiButton, useUploads, AttachButton, UploadChips,
} from './shared';

/* Super admin › « Centre de support » — built to the approved mockup
   (2026-10-01; features/support_center.py). Inbox on the left, the
   conversation in the middle, the commerce on the right. Everything the
   team writes reaches the merchant's « Besoin d'aide ? › Mes demandes »
   (and their email) — except internal notes. */

const KPI = {
  nouveau: [Inbox, '#2F6BFF', '#EAF1FF'], en_cours: [Clock3, '#F59E0B', '#FFF4DB'], en_attente: [Clock, '#8B5CF6', '#F3EEFF'],
  resolu: [CheckCircle2, '#10B981', '#E7F7EE'], urgent: [AlertTriangle, '#E11D48', '#FDECEF'],
};
const KPI_TAB = { nouveau: 'nouveaux', en_cours: 'en_cours', en_attente: 'en_attente', resolu: 'resolus', urgent: 'urgents' };
const POLL_LIST = 20000;
const POLL_THREAD = 12000;
const fetchFile = (id, inline) => supportAPI.file(id, inline);

function Kpi({ k, active, onClick }) {
  const [I, color, bg] = KPI[k.key];
  const bad = k.key === 'urgent' ? (k.delta ?? 0) > 0 : (k.delta ?? 0) < 0;
  return (
    <button type="button" onClick={onClick} aria-pressed={active}
            className={`flex items-center gap-4 rounded-2xl border bg-white px-5 py-4 text-left shadow-[0_1px_2px_rgba(11,28,63,.03)] transition hover:border-[#BFD3FF] ${active ? 'border-[#2F6BFF] ring-2 ring-[#2F6BFF]/15' : 'border-[#EDF1F7]'}`}>
      <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl" style={{ background: bg, color }}><I size={28} strokeWidth={2} /></span>
      <span className="min-w-0">
        <span className="block text-[24px] font-bold leading-none" style={{ color: k.key === 'urgent' ? '#E11D48' : '#0B1C3F' }}>{nf(k.value)}</span>
        <span className="mt-1.5 block text-[13px] text-[#64748B]">{k.label}</span>
        {k.delta === null || k.delta === undefined
          ? <span className="mt-1 block text-[12.5px] text-[#94A3B8]" title="Sur les 30 derniers jours">—</span>
          : <span className={`mt-1 inline-flex items-center gap-0.5 text-[12.5px] font-semibold ${bad ? 'text-[#E11D48]' : 'text-[#10B981]'}`} title={`${k.period} sur les 30 derniers jours, contre les 30 jours précédents`}>
              {k.delta >= 0 ? '+' : ''}{k.delta}% {k.delta >= 0 ? <ArrowUpRight size={14} /> : <ArrowDownRight size={14} />}
            </span>}
      </span>
    </button>
  );
}

function useOutside(open, close) {
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const out = (e) => { if (ref.current && !ref.current.contains(e.target)) close(); };
    document.addEventListener('mousedown', out);
    return () => document.removeEventListener('mousedown', out);
  }, [open, close]);
  return ref;
}

/* A dropdown that looks like the mockup's: icon, label, chevron; tinted. */
function FieldSelect({ icon: I, value, onChange, options, tone, label, disabled }) {
  const [bg, fg] = tone || ['#FFFFFF', '#0B1C3F'];
  return (
    <label className="block">
      {label && <span className="mb-1.5 block text-[13px] font-semibold text-[#0B1C3F]">{label}</span>}
      <span className="relative block">
        {I && <I size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2" style={{ color: fg }} />}
        <select value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)}
                className={`h-11 w-full appearance-none rounded-xl border ${I ? 'pl-9' : 'pl-3'} pr-9 text-[13.5px] font-medium outline-none focus:ring-2 focus:ring-[#2F6BFF]/20 disabled:opacity-60`}
                style={{ background: bg, color: fg, borderColor: tone ? `${fg}40` : '#DCE3EE' }}>
          {options.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
        <ChevronDown size={16} className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2" style={{ color: fg }} />
      </span>
    </label>
  );
}

/* ------------------------------------------------------------------ page */
export default function SupportCenterPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const [say, toast] = useToast();
  const [ov, setOv] = useState(null);
  const [list, setList] = useState(null);
  const [tab, setTab] = useState('tous');
  const [q, setQ] = useState('');
  const [query, setQuery] = useState('');
  const [f, setF] = useState({ status: '', priority: '', category: '', assigned: '', tag: '', plan: '', unread: '' });
  const [page, setPage] = useState(1);
  const [picked, setPicked] = useState(() => new Set());
  const [d, setD] = useState(null);
  const [loadingTicket, setLoadingTicket] = useState(false);
  const [newOpen, setNewOpen] = useState(false);
  const [repliesOpen, setRepliesOpen] = useState(false);
  const [tagsOpen, setTagsOpen] = useState(false);
  const [err, setErr] = useState('');
  const [showInfo, setShowInfo] = useState(false);
  const sel = params.get('ticket');

  useEffect(() => { const t = setTimeout(() => { setQuery(q.trim()); setPage(1); }, 300); return () => clearTimeout(t); }, [q]);

  const loadList = useCallback(() => {
    supportAPI.tickets({ tab, q: query, ...f, page, per_page: 30 }).then(({ data }) => { setList(data); setErr(''); })
      .catch((e) => setErr(errText(e, 'Impossible de charger les tickets.')));
    supportAPI.overview().then(({ data }) => setOv(data)).catch(() => {});
  }, [tab, query, f, page]);
  // Kept in refs so the loader never changes identity: a loader that changed
  // on every render would fetch the ticket again on every render.
  const sayRef = useRef(say);
  const paramsRef = useRef(setParams);
  sayRef.current = say;
  paramsRef.current = setParams;
  const loadTicket = useCallback((id, quiet) => {
    if (!id) { setD(null); return; }
    if (!quiet) setLoadingTicket(true);
    supportAPI.ticket(id).then(({ data }) => setD(data))
      .catch((e) => { if (!quiet) { sayRef.current(errText(e, 'Ticket introuvable.')); paramsRef.current((p) => { p.delete('ticket'); return p; }); } })
      .finally(() => setLoadingTicket(false));
  }, []);

  useEffect(() => { loadList(); }, [loadList]);
  useEffect(() => { loadTicket(sel); }, [sel, loadTicket]);
  // Live: the list and the open conversation refresh while the page is visible.
  useEffect(() => {
    const a = setInterval(() => { if (!document.hidden) loadList(); }, POLL_LIST);
    const b = setInterval(() => { if (!document.hidden && sel) loadTicket(sel, true); }, POLL_THREAD);
    return () => { clearInterval(a); clearInterval(b); };
  }, [loadList, loadTicket, sel]);

  const open = (id) => setParams((p) => { p.set('ticket', id); return p; });
  const refresh = () => { loadList(); if (sel) loadTicket(sel, true); };
  // One change at a time, in the order they were made: a quick second click
  // never reaches the server before the first.
  const queue = useRef(Promise.resolve());
  const patch = (body) => {
    const id = sel;
    queue.current = queue.current.then(() => supportAPI.patch(id, body)).then(() => refresh()).catch((e) => say(errText(e, 'Modification impossible.')));
    return queue.current;
  };
  const opts = list?.options || d?.options;
  const fCount = Object.values(f).filter(Boolean).length;

  const exportCsv = () => {
    const p = picked.size ? { ids: [...picked].join(',') } : { tab, q: query, ...f };
    downloadBlob(supportAPI.exportTickets(p), 'support-tickets.csv').catch(() => say('Export impossible.'));
  };
  const bulk = (body, msg) => supportAPI.bulk({ ids: [...picked], ...body }).then(() => { setPicked(new Set()); refresh(); say(msg); })
    .catch((e) => say(errText(e, 'Action impossible.')));

  return (
    <div className="crm">
      <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <Breadcrumb items={[['Super Admin', '/admin'], ['Support commerçants']]} />
          <h1 className="text-[30px] font-bold leading-tight tracking-[-0.01em] text-[#0B1C3F]">Centre de support</h1>
          <p className="text-[15px] text-[#475569]">Gérez toutes les demandes des commerçants et apportez des réponses rapides et efficaces.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={exportCsv} className="inline-flex h-11 items-center gap-2 rounded-xl border border-[#2F6BFF] bg-white px-4 text-[14px] font-medium text-[#2F6BFF] hover:bg-[#EFF5FF]">
            <Download size={17} /> {picked.size ? `Exporter (${picked.size})` : 'Exporter'}
          </button>
          <button type="button" onClick={() => setNewOpen(true)} className="inline-flex h-11 items-center gap-2 rounded-xl bg-[#2F6BFF] px-5 text-[14.5px] font-semibold text-white shadow-[0_6px_16px_-6px_rgba(47,107,255,.6)] hover:bg-[#1E5BFF]">
            <Plus size={18} /> Nouveau ticket
          </button>
        </div>
      </header>

      {err && <p className="mb-3 rounded-xl bg-[#FEF2F2] px-4 py-3 text-[13px] text-[#B91C1C]">{err}</p>}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {ov ? ov.kpis.map((k) => (
          <Kpi key={k.key} k={k} active={tab === KPI_TAB[k.key]} onClick={() => { setTab(tab === KPI_TAB[k.key] ? 'tous' : KPI_TAB[k.key]); setPage(1); }} />
        )) : [0, 1, 2, 3, 4].map((i) => <div key={i} className="h-[96px] animate-pulse rounded-2xl border border-[#EDF1F7] bg-white" />)}
      </div>

      <div className="mt-4 grid items-start gap-4 lg:grid-cols-[minmax(320px,410px)_1fr] 2xl:grid-cols-[minmax(340px,410px)_1fr_300px]">
        {/* ------------------------------------------------ inbox */}
        <section className={`rounded-2xl border border-[#EDF1F7] bg-white shadow-[0_1px_2px_rgba(11,28,63,.03)] ${sel ? 'hidden lg:block' : ''}`}>
          <Inboxx list={list} tab={tab} setTab={(t) => { setTab(t); setPage(1); }} q={q} setQ={setQ} f={f} setF={(x) => { setF(x); setPage(1); }}
                  fCount={fCount} opts={opts} sel={sel} open={open} picked={picked} setPicked={setPicked} page={page} setPage={setPage}
                  bulk={bulk} refresh={refresh} />
        </section>

        {/* ------------------------------------------------ conversation */}
        <section className={`min-w-0 rounded-2xl border border-[#EDF1F7] bg-white shadow-[0_1px_2px_rgba(11,28,63,.03)] ${sel ? '' : 'hidden lg:block'}`}>
          {!sel ? <Empty /> : (loadingTicket && (!d || d.ticket.id !== sel)) ? <div className="p-6"><Loading /></div> : d && d.ticket.id === sel ? (
            <Thread d={d} patch={patch} refresh={refresh} say={say} back={() => setParams((p) => { p.delete('ticket'); return p; })}
                    openReplies={() => setRepliesOpen(true)} toggleInfo={() => setShowInfo((s) => !s)} navigate={navigate} />
          ) : null}
        </section>

        {/* ------------------------------------------------ commerce */}
        {d && sel && d.ticket.id === sel && (
          <aside className={`rounded-2xl border border-[#EDF1F7] bg-white p-5 shadow-[0_1px_2px_rgba(11,28,63,.03)] lg:col-span-2 2xl:col-span-1 2xl:block ${showInfo ? 'block' : 'hidden'}`}>
            <InfoPanel d={d} patch={patch} openTags={() => setTagsOpen(true)} navigate={navigate} />
          </aside>
        )}
      </div>

      {newOpen && <NewTicket opts={opts} onClose={() => setNewOpen(false)} onDone={(id) => { setNewOpen(false); refresh(); open(id); say('Ticket créé.'); }} />}
      {repliesOpen && <RepliesModal onClose={() => setRepliesOpen(false)} say={say} />}
      {tagsOpen && <TagsModal onClose={() => setTagsOpen(false)} onSaved={() => { setTagsOpen(false); refresh(); say('Tags enregistrés.'); }} />}
      {toast}
    </div>
  );
}

const Empty = () => (
  <div className="flex min-h-[520px] flex-col items-center justify-center gap-3 p-8 text-center">
    <span className="flex h-16 w-16 items-center justify-center rounded-2xl bg-[#EAF1FF] text-[#2F6BFF]"><MailOpen size={30} /></span>
    <p className="text-[15px] font-semibold text-[#0B1C3F]">Sélectionnez une conversation</p>
    <p className="max-w-[320px] text-[13px] text-[#64748B]">Choisissez un ticket dans la boîte de réception pour lire l'échange et répondre au commerçant.</p>
  </div>
);

/* ------------------------------------------------------------------ inbox */
function Inboxx({ list, tab, setTab, q, setQ, f, setF, fCount, opts, sel, open, picked, setPicked, page, setPage, bulk, refresh }) {
  const [filters, setFilters] = useState(false);
  const [menu, setMenu] = useState(false);
  const fRef = useOutside(filters, () => setFilters(false));
  const mRef = useOutside(menu, () => setMenu(false));
  const [assignOpen, setAssignOpen] = useState(false);
  const aRef = useOutside(assignOpen, () => setAssignOpen(false));
  const rows = list?.rows || [];
  const allPicked = rows.length > 0 && rows.every((r) => picked.has(r.id));
  const toggle = (id) => setPicked((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const TABS = [['tous', 'Tous', list?.tabs?.tous], ['nouveaux', 'Nouveaux', list?.tabs?.nouveaux], ['en_cours', 'En cours', list?.tabs?.en_cours]];
  const extra = { en_attente: 'En attente', urgents: 'Urgents', resolus: 'Résolus' }[tab];
  const sf = (k) => (v) => setF({ ...f, [k]: v });
  return (
    <>
      <div className="flex items-center gap-2.5 px-4 pb-3 pt-4">
        <Inbox size={22} className="text-[#2F6BFF]" />
        <h2 className="text-[17px] font-bold text-[#0B1C3F]">Boîte de réception</h2>
        <span className="rounded-full bg-[#EAF1FF] px-2.5 py-0.5 text-[12.5px] font-semibold text-[#2F6BFF]" title="Tickets non résolus">{nf(list?.open ?? 0)}</span>
        <span ref={mRef} className="relative ml-auto">
          <button type="button" aria-label="Options de la boîte" onClick={() => setMenu((m) => !m)} className="flex h-8 w-8 items-center justify-center rounded-lg text-[#2F6BFF] hover:bg-[#F4F7FC]"><LayoutGrid size={17} /></button>
          {menu && (
            <div className="absolute right-0 top-9 z-30 w-60 overflow-hidden rounded-xl border border-[#EDF1F7] bg-white py-1 text-[13px] shadow-lg">
              <button type="button" className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-[#F4F7FC]" onClick={() => { setMenu(false); bulk({ read: true }, 'Marqués comme lus.'); }} disabled={!picked.size}>
                <CheckCheck size={15} /> Marquer la sélection comme lue{picked.size ? ` (${picked.size})` : ''}</button>
              <button type="button" className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-[#F4F7FC]" onClick={() => { setMenu(false); setF({ ...f, unread: f.unread ? '' : '1' }); }}>
                <MailOpen size={15} /> {f.unread ? 'Afficher tous les tickets' : 'Afficher les non lus'}</button>
              <button type="button" className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-[#F4F7FC]" onClick={() => { setMenu(false); setF({ ...f, assigned: 'moi' }); }}>
                <UserRound size={15} /> Mes tickets</button>
              <button type="button" className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-[#F4F7FC]" onClick={() => { setMenu(false); refresh(); }}>
                <RotateCcw size={15} /> Rafraîchir</button>
            </div>
          )}
        </span>
      </div>
      <div className="flex items-center gap-2 px-4">
        <label className="relative block flex-1">
          <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#64748B]" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Rechercher un message..." className="h-10 w-full rounded-xl border border-[#E2E8F0] bg-white pl-9 pr-3 text-[13px] text-[#0B1C3F] outline-none placeholder:text-[#64748B] focus:border-[#2F6BFF]" />
        </label>
        <span ref={fRef} className="relative">
          <button type="button" aria-label="Filtres" onClick={() => setFilters((o) => !o)} className={`relative flex h-10 w-10 items-center justify-center rounded-xl border ${fCount ? 'border-[#2F6BFF] bg-[#EFF5FF] text-[#2F6BFF]' : 'border-[#E2E8F0] text-[#475569]'} hover:border-[#2F6BFF]`}>
            <Filter size={17} />
            {fCount > 0 && <span className="absolute -right-1.5 -top-1.5 rounded-full bg-[#2F6BFF] px-1.5 text-[10.5px] font-bold text-white">{fCount}</span>}
          </button>
          {filters && opts && (
            <div className="absolute right-0 top-12 z-30 w-[300px] space-y-2.5 rounded-2xl border border-[#EDF1F7] bg-white p-4 shadow-xl">
              <FieldSelect label="Statut" value={f.status} onChange={sf('status')} options={[['', 'Tous'], ...opts.statuses.map((s) => [s.key, s.label])]} />
              <FieldSelect label="Priorité" value={f.priority} onChange={sf('priority')} options={[['', 'Toutes'], ...opts.priorities.map((s) => [s.key, s.label])]} />
              <FieldSelect label="Catégorie" value={f.category} onChange={sf('category')} options={[['', 'Toutes'], ...opts.categories.map((s) => [s.key, s.label])]} />
              <FieldSelect label="Assigné à" value={f.assigned} onChange={sf('assigned')} options={[['', 'Tout le monde'], ['moi', 'Moi'], ['aucun', 'Non assigné'], ...opts.team.map((m) => [m.email, m.name])]} />
              <FieldSelect label="Tag" value={f.tag} onChange={sf('tag')} options={[['', 'Tous'], ...opts.tags.map((t) => [t.label, t.label])]} />
              <FieldSelect label="Plan" value={f.plan} onChange={sf('plan')} options={[['', 'Tous'], ...opts.plans.map((p) => [p.key, p.label])]} />
              <label className="flex items-center gap-2 pt-1 text-[13px] text-[#0B1C3F]"><input type="checkbox" checked={f.unread === '1'} onChange={(e) => setF({ ...f, unread: e.target.checked ? '1' : '' })} className="h-4 w-4 accent-[#2F6BFF]" /> Non lus seulement</label>
              {fCount > 0 && <button type="button" onClick={() => setF({ status: '', priority: '', category: '', assigned: '', tag: '', plan: '', unread: '' })} className="text-[12.5px] font-medium text-[#2F6BFF] hover:underline">Réinitialiser les filtres</button>}
            </div>
          )}
        </span>
      </div>
      <div className="flex flex-wrap gap-1.5 px-4 pb-2 pt-3" role="tablist">
        {TABS.map(([k, l, n]) => (
          <button key={k} type="button" role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
                  className={`h-9 rounded-xl px-3.5 text-[13px] ${tab === k ? 'bg-[#EAF1FF] font-semibold text-[#2F6BFF]' : 'text-[#475569] hover:bg-[#F4F7FC]'}`}>{l} ({nf(n ?? 0)})</button>
        ))}
        {extra && <span className="flex h-9 items-center gap-1 rounded-xl bg-[#EAF1FF] px-3.5 text-[13px] font-semibold text-[#2F6BFF]">{extra}<button type="button" aria-label="Retirer" onClick={() => setTab('tous')}><X size={13} /></button></span>}
      </div>

      {picked.size > 0 && (
        <div className="mx-4 mb-2 flex flex-wrap items-center gap-2 rounded-xl bg-[#F5F8FF] px-3 py-2 text-[12.5px]">
          <label className="flex items-center gap-2 font-medium text-[#0B1C3F]"><input type="checkbox" checked={allPicked} onChange={() => setPicked(allPicked ? new Set() : new Set(rows.map((r) => r.id)))} className="h-4 w-4 accent-[#2F6BFF]" /> {picked.size} sélectionné{picked.size > 1 ? 's' : ''}</label>
          <button type="button" onClick={() => bulk({ status: 'resolu' }, 'Tickets résolus.')} className="ml-auto rounded-lg border border-[#BFD3FF] bg-white px-2.5 py-1 font-medium text-[#2F6BFF]">Résolu</button>
          <span ref={aRef} className="relative">
            <button type="button" onClick={() => setAssignOpen((o) => !o)} className="inline-flex items-center gap-1 rounded-lg border border-[#BFD3FF] bg-white px-2.5 py-1 font-medium text-[#2F6BFF]">Assigner <ChevronDown size={13} /></button>
            {assignOpen && opts && (
              <div className="absolute right-0 top-8 z-30 w-52 overflow-hidden rounded-xl border border-[#EDF1F7] bg-white py-1 shadow-lg">
                {[...opts.team.map((m) => [m.email, m.name]), ['', 'Personne']].map(([e, n]) => (
                  <button key={e || 'none'} type="button" onClick={() => { setAssignOpen(false); bulk({ assigned_to: e }, e ? `Assignés à ${n}.` : 'Désassignés.'); }} className="block w-full px-3 py-2 text-left hover:bg-[#F4F7FC]">{n}</button>
                ))}
              </div>
            )}
          </span>
          <button type="button" onClick={() => setPicked(new Set())} aria-label="Annuler la sélection" className="text-[#64748B]"><X size={15} /></button>
        </div>
      )}

      {!list ? <div className="px-4 pb-4"><Loading /></div> : (
        <ul className="max-h-[calc(100vh-330px)] min-h-[420px] overflow-y-auto px-2 pb-2">
          {rows.map((r) => (
            <li key={r.id}>
              <div role="button" tabIndex={0} onClick={() => open(r.id)} onKeyDown={(e) => { if (e.key === 'Enter') open(r.id); }}
                   className={`group flex cursor-pointer items-center gap-3 rounded-xl px-2 py-3 ${sel === r.id ? 'bg-[#EEF4FF]' : 'hover:bg-[#F8FAFF]'} border-b border-[#F1F5F9]`}>
                <input type="checkbox" aria-label={`Sélectionner ${r.commerce.name}`} checked={picked.has(r.id)} onClick={(e) => e.stopPropagation()} onChange={() => toggle(r.id)} className="h-4 w-4 shrink-0 rounded accent-[#2F6BFF]" />
                <Avatar name={r.commerce.name} logo={r.commerce.logo} size={38} />
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-2">
                    <span className={`truncate text-[13.5px] text-[#0B1C3F] ${r.unread ? 'font-bold' : 'font-semibold'}`}>{r.commerce.name}</span>
                  </span>
                  <span className="mt-0.5 flex items-center gap-1.5">
                    <span className="h-3.5 w-[3px] shrink-0 rounded-full" style={{ background: PRIORITY_BAR[r.priority] || '#CBD5E1' }} title={`Priorité ${r.priority_label}`} />
                    <span className={`truncate text-[12.5px] ${r.unread ? 'text-[#0B1C3F]' : 'text-[#64748B]'}`}>{r.last_from === 'team' ? 'Vous : ' : ''}{r.preview || r.subject}</span>
                  </span>
                </span>
                <span className="flex shrink-0 flex-col items-end gap-1.5">
                  <span className="text-[11.5px] text-[#64748B]">{when(r.last_message_at)}</span>
                  <StatusPill s={r.status} label={r.status_label} />
                </span>
                <span className="w-5 shrink-0">
                  {r.unread > 0 && <span className="flex h-5 w-5 items-center justify-center rounded-full bg-[#2F6BFF] text-[10.5px] font-bold text-white">{r.unread}</span>}
                </span>
              </div>
            </li>
          ))}
          {!rows.length && <li className="px-4 py-16 text-center text-[13px] text-[#64748B]">Aucun ticket ici.</li>}
        </ul>
      )}
      {list && list.pages > 1 && (
        <div className="flex items-center justify-between border-t border-[#F1F5F9] px-4 py-2.5 text-[12.5px] text-[#475569]">
          <span>{(page - 1) * list.per_page + 1}–{Math.min(list.total, page * list.per_page)} sur {nf(list.total)}</span>
          <span className="flex gap-1">
            <button type="button" disabled={page <= 1} onClick={() => setPage(page - 1)} className="rounded-lg border border-[#DCE3EE] px-2.5 py-1 disabled:opacity-40">Précédent</button>
            <button type="button" disabled={page >= list.pages} onClick={() => setPage(page + 1)} className="rounded-lg border border-[#DCE3EE] px-2.5 py-1 disabled:opacity-40">Suivant</button>
          </span>
        </div>
      )}
    </>
  );
}

/* ------------------------------------------------------------------ thread */
function Thread({ d, patch, refresh, say, back, openReplies, toggleInfo, navigate }) {
  const t = d.ticket;
  const c = d.commerce || {};
  const [menu, setMenu] = useState(false);
  const mRef = useOutside(menu, () => setMenu(false));
  const end = useRef(null);
  const count = d.messages.length;
  useEffect(() => { end.current?.scrollIntoView({ block: 'end' }); }, [t.id, count]);
  const resolved = t.status === 'resolu';
  const groups = useMemo(() => {
    const out = [];
    d.messages.forEach((m) => {
      const day = new Date(m.created_at).toDateString();
      if (!out.length || out[out.length - 1].day !== day) out.push({ day, at: m.created_at, items: [] });
      out[out.length - 1].items.push(m);
    });
    return out;
  }, [d.messages]);
  const copyLink = () => { navigator.clipboard?.writeText(`${window.location.origin}/admin/support?ticket=${t.id}`).then(() => say('Lien copié.')).catch(() => {}); };

  return (
    <div className="flex h-full min-h-[640px] flex-col">
      <header className="flex flex-wrap items-center gap-3 border-b border-[#F1F5F9] px-5 py-4">
        <button type="button" onClick={back} aria-label="Retour à la boîte de réception" className="-ml-1 rounded-lg p-1 text-[#475569] hover:bg-[#F4F7FC] lg:hidden"><ChevronLeft size={20} /></button>
        <Avatar name={t.commerce.name} logo={t.commerce.logo} size={44} />
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-[17px] font-bold text-[#0B1C3F]">{t.commerce.name}</h2>
          <p className="flex flex-wrap items-center gap-2 text-[12.5px] text-[#64748B]">
            {t.commerce.sector && <span>{t.commerce.sector}</span>}
            {t.commerce.plan && <span className="inline-flex items-center gap-1 rounded-md bg-[#FFF4DB] px-2 py-0.5 text-[11.5px] font-semibold text-[#B45309]"><Crown size={12} className="text-[#F59E0B]" /> {t.commerce.plan.label}</span>}
            {!t.commerce.id && t.contact && <span>{t.contact}</span>}
          </p>
        </div>
        <button type="button" onClick={() => patch({ status: resolved ? 'en_cours' : 'resolu' })}
                className={`inline-flex h-10 items-center gap-2 rounded-xl border px-4 text-[13px] font-medium ${resolved ? 'border-[#DCE3EE] text-[#475569] hover:border-[#2F6BFF]' : 'border-[#2F6BFF] text-[#2F6BFF] hover:bg-[#EFF5FF]'}`}>
          {resolved ? <><RotateCcw size={16} /> Rouvrir le ticket</> : <><Check size={16} /> Marquer comme résolu</>}
        </button>
        <button type="button" onClick={toggleInfo} aria-label="Informations commerce" className="rounded-lg p-2 text-[#475569] hover:bg-[#F4F7FC] 2xl:hidden"><Info size={18} /></button>
        <span ref={mRef} className="relative">
          <button type="button" aria-label="Plus d'actions" onClick={() => setMenu((m) => !m)} className="rounded-lg p-2 text-[#0B1C3F] hover:bg-[#F4F7FC]"><MoreVertical size={18} /></button>
          {menu && (
            <div className="absolute right-0 top-10 z-30 w-64 overflow-hidden rounded-xl border border-[#EDF1F7] bg-white py-1 text-[13px] text-[#0B1C3F] shadow-lg">
              {t.commerce.id && <button type="button" className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-[#F4F7FC]" onClick={() => navigate(`/admin/commerces/${t.commerce.id}`)}><Store size={15} /> Voir le commerce</button>}
              <button type="button" className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-[#F4F7FC]" onClick={() => { setMenu(false); supportAPI.unread(t.id).then(() => { refresh(); back(); say('Marqué comme non lu.'); }); }}><MailOpen size={15} /> Marquer comme non lu</button>
              <button type="button" className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-[#F4F7FC]" onClick={() => { setMenu(false); downloadBlob(supportAPI.exportThread(t.id), 'conversation.csv').catch(() => say('Export impossible.')); }}><Download size={15} /> Exporter la conversation</button>
              <button type="button" className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-[#F4F7FC]" onClick={() => { setMenu(false); copyLink(); }}><Link2 size={15} /> Copier le lien du ticket</button>
              <button type="button" className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-[#F4F7FC]" onClick={() => { setMenu(false); openReplies(); }}><LayoutList size={15} /> Gérer les réponses enregistrées</button>
            </div>
          )}
        </span>
      </header>

      <div className="flex-1 space-y-5 overflow-y-auto px-5 py-5" style={{ maxHeight: `calc(${vh(100)} - 360px)`, minHeight: 360 }}>
        <p className="text-center text-[12px] text-[#64748B]">
          <span className="rounded-full bg-[#F4F7FC] px-3 py-1">Objet : <strong className="font-semibold text-[#0B1C3F]">{t.subject}</strong> · {t.category_label} · ouvert le {fullDate(t.created_at)}</span>
        </p>
        {groups.map((g) => (
          <div key={g.day} className="space-y-5">
            <p className="text-center text-[11.5px] font-medium uppercase tracking-[.04em] text-[#94A3B8]">{dayLabel(g.at)}</p>
            {g.items.filter((m) => m.meta?.field !== 'rating').map((m) => <Message key={m.id} m={m} name={t.commerce.name} logo={t.commerce.logo} />)}
          </div>
        ))}
        {t.rating && (
          <div className="mx-auto w-fit rounded-xl bg-[#FFF8E6] px-4 py-2 text-center text-[12.5px] text-[#92400E]">
            Note du commerçant : {'★'.repeat(t.rating.stars)}{'☆'.repeat(5 - t.rating.stars)}{t.rating.comment ? ` — « ${t.rating.comment} »` : ''}
          </div>
        )}
        <div ref={end} />
      </div>

      <Composer d={d} refresh={refresh} say={say} openReplies={openReplies} />
    </div>
  );
}

function Message({ m, name, logo }) {
  if (m.kind === 'event') {
    return <p className="text-center text-[12px] text-[#94A3B8]">{m.body} · {m.author_name} · {clock(m.created_at)}</p>;
  }
  const team = m.author_type === 'team';
  const note = m.kind === 'note';
  const bubble = note ? 'bg-[#FFF8E6] border border-[#FDE7B0]' : team ? 'bg-[#EEF4FF]' : 'bg-[#F6F8FC]';
  return (
    <div className={`flex gap-3 ${team ? 'flex-row-reverse' : ''}`}>
      {team ? <Avatar name={m.author_name} size={36} color="#2F6BFF" /> : <Avatar name={name} logo={logo} size={36} />}
      <div className={`min-w-0 max-w-[82%] ${team ? 'items-end' : ''}`}>
        {!team && <p className="mb-1.5 text-[13px]"><strong className="font-semibold text-[#0B1C3F]">{name}</strong><span className="ml-2 text-[12px] text-[#94A3B8]">{clock(m.created_at)}</span>
          {m.author_name && m.author_name !== name && <span className="ml-2 text-[12px] text-[#64748B]">({m.author_name})</span>}</p>}
        <div className={`rounded-2xl px-4 py-3 text-[13.5px] leading-[1.55] text-[#1E293B] ${bubble}`}>
          {team && (
            <p className="mb-1.5 text-[13px]">
              <strong className="font-semibold text-[#0B1C3F]">{m.author_name}</strong>
              <span className="ml-2 text-[12px] text-[#94A3B8]">{clock(m.created_at)}</span>
              {note && <span className="ml-2 inline-flex items-center gap-1 rounded-md bg-[#FDE7B0] px-1.5 py-0.5 text-[11px] font-semibold text-[#92400E]"><StickyNote size={11} /> Note interne</span>}
            </p>
          )}
          {m.body && <p className="whitespace-pre-wrap break-words">{m.body}</p>}
          {m.attachments?.length > 0 && <div className={`mt-2.5 flex flex-wrap gap-2 ${m.body ? '' : '-mt-0.5'}`}>{m.attachments.map((a) => <Attachment key={a.id} a={a} fetchFile={fetchFile} />)}</div>}
          {team && !note && (
            <p className="mt-1 flex justify-end" title={m.read ? 'Lu par le commerçant' : 'Envoyé'}>
              {m.read ? <CheckCheck size={16} className="text-[#2F6BFF]" /> : <Check size={16} className="text-[#94A3B8]" />}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

function Composer({ d, refresh, say, openReplies }) {
  const t = d.ticket;
  const team = d.options?.team || [];
  const [mode, setMode] = useState('message');
  const [text, setText] = useState('');
  const [sending, setSending] = useState(false);
  const [replies, setReplies] = useState(null);
  const [mention, setMention] = useState(false);
  const mRef = useOutside(mention, () => setMention(false));
  const up = useUploads(supportAPI.upload);
  const area = useRef(null);
  useEffect(() => { setText(''); setMode('message'); up.clear(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [t.id]);
  useEffect(() => { supportAPI.replies().then(({ data }) => setReplies(data.rows)).catch(() => setReplies([])); }, []);

  const insert = (s) => {
    const el = area.current;
    if (!el) { setText((x) => x + s); return; }
    const a = el.selectionStart ?? text.length; const b = el.selectionEnd ?? text.length;
    const next = text.slice(0, a) + s + text.slice(b);
    setText(next);
    requestAnimationFrame(() => { el.focus(); el.selectionStart = el.selectionEnd = a + s.length; });
  };
  const first = (d.commerce?.owner || '').split(' ')[0] || '';
  const applyReply = (id) => {
    if (id === '__manage') { openReplies(); return; }
    const r = (replies || []).find((x) => x.id === id);
    if (!r) return;
    insert(r.body.replaceAll('{prenom}', first || 'Madame, Monsieur').replaceAll('{commerce}', t.commerce.name));
  };
  const mentions = team.filter((m) => text.includes(`@${m.name}`)).map((m) => m.email);
  const send = () => {
    if (sending || (!text.trim() && !up.ids.length) || !up.ready) return;
    setSending(true);
    supportAPI.send(t.id, { body: text, kind: mode, attachments: up.ids, mentions })
      .then(() => { setText(''); up.clear(); refresh(); say(mode === 'note' ? 'Note ajoutée.' : 'Réponse envoyée au commerçant.'); })
      .catch((e) => say(errText(e, 'Envoi impossible.')))
      .finally(() => setSending(false));
  };
  const note = mode === 'note';
  return (
    <div className="border-t border-[#F1F5F9] px-5 pb-4 pt-3">
      <div className="mb-2 flex gap-1" role="tablist">
        {[['message', 'Répondre'], ['note', 'Note interne']].map(([k, l]) => (
          <button key={k} type="button" role="tab" aria-selected={mode === k} onClick={() => setMode(k)}
                  className={`h-8 rounded-lg px-3.5 text-[13px] ${mode === k ? (k === 'note' ? 'bg-[#FFF4DB] font-semibold text-[#B45309]' : 'bg-[#EAF1FF] font-semibold text-[#2F6BFF]') : 'text-[#64748B] hover:bg-[#F4F7FC]'}`}>{l}</button>
        ))}
      </div>
      <div className={`rounded-xl border ${note ? 'border-[#FDE7B0] bg-[#FFFCF3]' : 'border-[#DCE3EE] bg-white'} focus-within:border-[#2F6BFF]`}>
        <textarea ref={area} value={text} onChange={(e) => setText(e.target.value)} rows={3}
                  onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) send(); }}
                  placeholder={note ? 'Note visible uniquement par l\'équipe FidClic… (@ pour mentionner)' : 'Écrivez votre réponse...'}
                  className="block w-full resize-y rounded-xl bg-transparent px-3.5 py-3 text-[13.5px] text-[#0B1C3F] outline-none placeholder:text-[#94A3B8]" />
        <UploadChips up={up} />
        <div className="flex flex-wrap items-center gap-1 px-2 pb-2">
          <AttachButton onFiles={up.add} />
          <EmojiButton onPick={insert} />
          <span ref={mRef} className="relative">
            <button type="button" aria-label="Mentionner un membre de l'équipe" onClick={() => setMention((o) => !o)} className="flex h-8 w-8 items-center justify-center rounded-lg text-[#64748B] hover:bg-[#F4F7FC] hover:text-[#0B1C3F]"><AtSign size={18} /></button>
            {mention && (
              <span className="absolute bottom-10 left-0 z-30 block w-56 overflow-hidden rounded-xl border border-[#EDF1F7] bg-white py-1 text-[13px] shadow-lg">
                <span className="block px-3 py-1.5 text-[11.5px] text-[#94A3B8]">Mentionner (prévient la personne)</span>
                {team.map((m) => (
                  <button key={m.email} type="button" onClick={() => { insert(`@${m.name} `); setMention(false); if (mode !== 'note') setMode('note'); }}
                          className="flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-[#F4F7FC]"><Avatar name={m.name} size={22} color="#2F6BFF" /> {m.name}</button>
                ))}
              </span>
            )}
          </span>
          <span className="ml-auto flex items-center gap-2">
            <span className="relative">
              <select aria-label="Réponse enregistrée" value="" onChange={(e) => applyReply(e.target.value)} className="h-10 max-w-[200px] appearance-none rounded-xl border border-[#DCE3EE] bg-white pl-3 pr-8 text-[13px] text-[#0B1C3F]">
                <option value="">Réponse enregistrée</option>
                {(replies || []).map((r) => <option key={r.id} value={r.id}>{r.title}</option>)}
                <option value="__manage">Gérer les réponses…</option>
              </select>
              <ChevronDown size={15} className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-[#0B1C3F]" />
            </span>
            <button type="button" onClick={send} disabled={sending || (!text.trim() && !up.ids.length) || !up.ready}
                    className={`inline-flex h-10 items-center gap-2 rounded-xl px-4 text-[13.5px] font-semibold text-white disabled:opacity-50 ${note ? 'bg-[#D97706] hover:bg-[#B45309]' : 'bg-[#2F6BFF] hover:bg-[#1E5BFF]'}`}>
              {sending ? <Loader2 size={16} className="animate-spin" /> : note ? <StickyNote size={16} /> : <Send size={16} />} {note ? 'Ajouter la note' : 'Envoyer'}
            </button>
          </span>
        </div>
      </div>
      {!note && <p className="mt-1.5 text-[11.5px] text-[#94A3B8]">Le commerçant reçoit la réponse dans « Besoin d'aide ? » et par email. Ctrl + Entrée pour envoyer.</p>}
    </div>
  );
}

/* ------------------------------------------------------------------ commerce panel */
function InfoPanel({ d, patch, openTags, navigate }) {
  const t = d.ticket;
  const c = d.commerce || {};
  const o = d.options;
  const [adding, setAdding] = useState(false);
  const [newTag, setNewTag] = useState('');
  const aRef = useOutside(adding, () => setAdding(false));
  // What was just picked shows at once; the server's answer then confirms it
  // (and two quick changes never overwrite each other).
  // A server answer that left before the latest change must not undo it:
  // for 3 s after a change, the panel keeps what was picked.
  const [local, setLocal] = useState({});
  const [tags, setTagsLocal] = useState(t.tags);
  const tagsRef = useRef(t.tags);
  const touched = useRef(0);
  const fresh = () => Date.now() - touched.current > 3000;
  useEffect(() => { if (fresh()) setLocal({}); }, [d]);       // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (fresh()) { setTagsLocal(t.tags); tagsRef.current = t.tags; } }, [t.id, t.tags]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { touched.current = 0; setLocal({}); setTagsLocal(t.tags); tagsRef.current = t.tags; }, [t.id]);   // eslint-disable-line react-hooks/exhaustive-deps
  const v = { status: t.status, priority: t.priority, category: t.category, assigned: t.assigned?.email || '', ...local };
  const change = (k, field) => (val) => { touched.current = Date.now(); setLocal((x) => ({ ...x, [k]: val })); patch({ [field]: val }); };
  const tagTone = (l) => TAG_TONE[(o.tags.find((x) => x.label === l) || {}).color] || TAG_TONE.slate;
  const show = (next) => { touched.current = Date.now(); tagsRef.current = next; setTagsLocal(next); };
  const addTag = (l) => {
    const x = (l || '').trim();
    if (x && !tagsRef.current.includes(x)) { show([...tagsRef.current, x]); patch({ add_tags: [x] }); }
    setNewTag(''); setAdding(false);
  };
  const removeTag = (l) => { show(tagsRef.current.filter((x) => x !== l)); patch({ remove_tags: [l] }); };
  const statusTone = STATUS_TONE[v.status];
  const prioTone = PRIORITY_TONE[v.priority];
  const me = o.team.find((m) => m.email === v.assigned);
  return (
    <div className="space-y-5">
      <div className="flex items-center gap-2">
        <Users size={17} className="text-[#2F6BFF]" />
        <h3 className="flex-1 text-[14px] font-bold text-[#0B1C3F]">Informations commerce</h3>
        {c.id && <button type="button" onClick={() => navigate(`/admin/commerces/${c.id}`)} className="rounded-lg border border-[#BFD3FF] px-3 py-1 text-[12.5px] font-medium text-[#2F6BFF] hover:bg-[#EFF5FF]">Éditer</button>}
      </div>
      {c.id ? (
        <>
          <div className="flex items-center gap-3">
            <Avatar name={c.name} logo={c.logo} size={58} />
            <div className="min-w-0">
              <p className="truncate text-[14.5px] font-bold text-[#0B1C3F]">{c.name}</p>
              <p className="truncate text-[12.5px] text-[#64748B]">{c.sector}</p>
              <span className="mt-1 inline-block rounded-md px-2 py-0.5 text-[11.5px] font-medium" style={{ background: c.status === 'actif' ? '#E7F7EE' : c.status === 'suspendu' ? '#F1F5F9' : '#FFF4DB', color: c.status === 'actif' ? '#0F8B58' : c.status === 'suspendu' ? '#475569' : '#D97706' }}>{c.status_label}</span>
            </div>
          </div>
          <ul className="space-y-2.5 text-[13px] text-[#0B1C3F]">
            {c.phone && <li className="flex items-center gap-2.5"><Phone size={16} className="shrink-0 text-[#2F6BFF]" /><a href={`tel:${c.phone.replace(/\s/g, '')}`} className="hover:text-[#2F6BFF]">{c.phone}</a></li>}
            {c.email && <li className="flex items-center gap-2.5"><Mail size={16} className="shrink-0 text-[#2F6BFF]" /><a href={`mailto:${c.email}`} className="truncate hover:text-[#2F6BFF]">{c.email}</a></li>}
            {c.city && <li className="flex items-center gap-2.5"><MapPin size={16} className="shrink-0 text-[#2F6BFF]" />{c.address || c.city}</li>}
            <li><a href={`/admin/commerces/${c.id}`} target="_blank" rel="noopener noreferrer" className="flex items-center gap-2.5 text-[#2F6BFF] hover:underline"><Link2 size={16} className="shrink-0" /> Voir sur la plateforme <ExternalLink size={13} /></a></li>
          </ul>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="flex items-center gap-1.5 text-[14px] font-bold text-[#F59E0B]"><Crown size={17} /> Plan {c.plan?.label}</span>
            {c.plan_since && <span className="text-[12px] text-[#64748B]">Depuis le {new Date(c.plan_since).toLocaleDateString('fr-FR')}</span>}
          </div>
          <div className="grid grid-cols-3 gap-2 text-[12px] text-[#64748B]">
            {[[Users, nf(c.clients), 'clients'], [Megaphone, nf(c.campaigns), 'campagnes'], [BarChart3, c.satisfaction != null ? `${String(c.satisfaction).replace('.', ',')}/5` : '—', 'satisfaction']].map(([I, v, l]) => (
              <span key={l} className="flex items-start gap-1.5" title={l === 'satisfaction' ? `${c.ratings || 0} avis sur ses demandes de support` : undefined}>
                <I size={17} className="mt-0.5 shrink-0 text-[#2F6BFF]" />
                <span><strong className="block text-[14px] font-bold text-[#0B1C3F]">{v}</strong>{l}</span>
              </span>
            ))}
          </div>
        </>
      ) : (
        <div className="rounded-xl bg-[#F8FAFF] p-3 text-[13px] text-[#475569]">
          <p className="font-semibold text-[#0B1C3F]">{c.contact?.name || 'Contact sans commerce'}</p>
          {c.contact?.email && <a href={`mailto:${c.contact.email}`} className="text-[#2F6BFF]">{c.contact.email}</a>}
        </div>
      )}

      <div className="border-t border-[#F1F5F9] pt-4">
        <div className="mb-2.5 flex items-center justify-between">
          <h4 className="text-[13.5px] font-bold text-[#0B1C3F]">Tags</h4>
          <button type="button" onClick={openTags} className="rounded-lg border border-[#BFD3FF] px-3 py-1 text-[12.5px] font-medium text-[#2F6BFF] hover:bg-[#EFF5FF]">Gérer</button>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {tags.map((l) => { const [bg, fg] = tagTone(l); return (
            <span key={l} className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[12px] font-medium" style={{ background: bg, color: fg }}>
              {l}<button type="button" aria-label={`Retirer ${l}`} onClick={() => removeTag(l)}><X size={12} /></button>
            </span>); })}
          <span ref={aRef} className="relative">
            <button type="button" aria-label="Ajouter un tag" onClick={() => setAdding((a) => !a)} className="flex h-7 w-7 items-center justify-center rounded-full border border-[#DCE3EE] text-[#64748B] hover:border-[#2F6BFF] hover:text-[#2F6BFF]"><Plus size={14} /></button>
            {adding && (
              <div className="absolute right-0 top-9 z-30 w-56 rounded-xl border border-[#EDF1F7] bg-white p-2 shadow-lg">
                <input autoFocus value={newTag} onChange={(e) => setNewTag(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') addTag(newTag); }} placeholder="Nouveau tag…" className="mb-1 h-9 w-full rounded-lg border border-[#DCE3EE] px-2.5 text-[12.5px] outline-none focus:border-[#2F6BFF]" />
                <div className="max-h-48 overflow-y-auto">
                  {o.tags.filter((x) => !tags.includes(x.label) && x.label.toLowerCase().includes(newTag.toLowerCase())).map((x) => (
                    <button key={x.label} type="button" onClick={() => addTag(x.label)} className="block w-full rounded-md px-2 py-1.5 text-left text-[12.5px] hover:bg-[#F4F7FC]">{x.label}</button>
                  ))}
                  {newTag.trim() && !o.tags.some((x) => x.label.toLowerCase() === newTag.trim().toLowerCase()) && (
                    <button type="button" onClick={() => addTag(newTag)} className="block w-full rounded-md px-2 py-1.5 text-left text-[12.5px] font-medium text-[#2F6BFF] hover:bg-[#F4F7FC]">Créer « {newTag.trim()} »</button>
                  )}
                </div>
              </div>
            )}
          </span>
        </div>
      </div>

      <div className="space-y-3.5 border-t border-[#F1F5F9] pt-4">
        <label className="block">
          <span className="mb-1.5 block text-[13px] font-semibold text-[#0B1C3F]">Assigner le ticket</span>
          <span className="relative block">
            <span className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2">{me ? <Avatar name={me.name} size={24} color="#2F6BFF" /> : <UserRound size={18} className="text-[#94A3B8]" />}</span>
            <select value={v.assigned} onChange={(e) => change('assigned', 'assigned_to')(e.target.value)} className="h-11 w-full appearance-none rounded-xl border border-[#DCE3EE] bg-white pl-11 pr-9 text-[13.5px] font-medium text-[#0B1C3F] outline-none focus:border-[#2F6BFF]">
              <option value="">Non assigné</option>
              {o.team.map((m) => <option key={m.email} value={m.email}>{m.name}</option>)}
            </select>
            <ChevronDown size={16} className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[#0B1C3F]" />
          </span>
        </label>
        <FieldSelect label="Statut" icon={CircleAlert} value={v.status} onChange={change('status', 'status')} tone={statusTone} options={o.statuses.map((s) => [s.key, s.label])} />
        <FieldSelect label="Catégorie" icon={LayoutList} value={v.category} onChange={change('category', 'category')} options={o.categories.map((s) => [s.key, s.label])} />
        <FieldSelect label="Priorité" icon={Flag} value={v.priority} onChange={change('priority', 'priority')} tone={prioTone} options={o.priorities.map((s) => [s.key, s.label])} />
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ modals */
function NewTicket({ opts, onClose, onDone }) {
  const [q, setQ] = useState('');
  const [found, setFound] = useState([]);
  const [shop, setShop] = useState(null);
  const [form, setForm] = useState({ subject: '', category: 'autre', priority: 'normale', kind: 'message', body: '', assigned_to: '' });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const up = useUploads(supportAPI.upload);
  useEffect(() => {
    if (shop) return undefined;
    const t = setTimeout(() => supportAPI.commerces(q).then(({ data }) => setFound(data.rows)).catch(() => setFound([])), 200);
    return () => clearTimeout(t);
  }, [q, shop]);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const submit = () => {
    if (!shop) { setErr('Choisissez un commerce.'); return; }
    if (!form.subject.trim() || !form.body.trim()) { setErr("L'objet et le message sont obligatoires."); return; }
    setBusy(true); setErr('');
    supportAPI.create({ ...form, tenant_id: shop.id, attachments: up.ids, assigned_to: form.assigned_to || null })
      .then(({ data }) => onDone(data.id)).catch((e) => setErr(errText(e, 'Création impossible.'))).finally(() => setBusy(false));
  };
  const field = 'h-11 w-full rounded-xl border border-[#DCE3EE] bg-white px-3 text-[13.5px] text-[#0B1C3F] outline-none focus:border-[#2F6BFF]';
  return (
    <Modal title="Nouveau ticket" onClose={onClose}>
      <div className="space-y-3">
        <div>
          <span className="mb-1 block text-[12.5px] font-medium text-[#475569]">Commerce</span>
          {shop ? (
            <div className="flex items-center gap-3 rounded-xl border border-[#BFD3FF] bg-[#F5F8FF] p-2.5">
              <Avatar name={shop.name} logo={shop.logo} size={34} />
              <span className="min-w-0 flex-1"><strong className="block truncate text-[13.5px] text-[#0B1C3F]">{shop.name}</strong><span className="text-[12px] text-[#64748B]">{[shop.sector, shop.city, shop.plan?.label].filter(Boolean).join(' · ')}</span></span>
              <button type="button" onClick={() => setShop(null)} className="text-[12.5px] font-medium text-[#2F6BFF]">Changer</button>
            </div>
          ) : (
            <>
              <label className="relative block"><Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
                <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Rechercher un commerce…" className={`${field} pl-9`} /></label>
              <ul className="mt-1 max-h-48 overflow-y-auto rounded-xl border border-[#EDF1F7]">
                {found.map((s) => (
                  <li key={s.id}><button type="button" onClick={() => setShop(s)} className="flex w-full items-center gap-2.5 px-3 py-2 text-left hover:bg-[#F4F7FC]">
                    <Avatar name={s.name} logo={s.logo} size={28} /><span className="min-w-0"><span className="block truncate text-[13px] font-medium text-[#0B1C3F]">{s.name}</span><span className="text-[11.5px] text-[#64748B]">{[s.sector, s.city].filter(Boolean).join(' · ')}</span></span>
                  </button></li>
                ))}
                {!found.length && <li className="px-3 py-3 text-[12.5px] text-[#94A3B8]">Aucun commerce trouvé.</li>}
              </ul>
            </>
          )}
        </div>
        <label className="block"><span className="mb-1 block text-[12.5px] font-medium text-[#475569]">Objet</span><input value={form.subject} onChange={set('subject')} maxLength={200} placeholder="Ex. Suite à votre appel" className={field} /></label>
        <div className="grid gap-3 sm:grid-cols-3">
          <label className="block"><span className="mb-1 block text-[12.5px] font-medium text-[#475569]">Catégorie</span><select value={form.category} onChange={set('category')} className={field}>{opts?.categories.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}</select></label>
          <label className="block"><span className="mb-1 block text-[12.5px] font-medium text-[#475569]">Priorité</span><select value={form.priority} onChange={set('priority')} className={field}>{opts?.priorities.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}</select></label>
          <label className="block"><span className="mb-1 block text-[12.5px] font-medium text-[#475569]">Assigner à</span><select value={form.assigned_to} onChange={set('assigned_to')} className={field}><option value="">Moi</option>{opts?.team.map((m) => <option key={m.email} value={m.email}>{m.name}</option>)}</select></label>
        </div>
        <div className="flex gap-1">
          {[['message', 'Message au commerçant'], ['note', 'Note interne']].map(([k, l]) => (
            <button key={k} type="button" onClick={() => setForm({ ...form, kind: k })} className={`h-8 rounded-lg px-3 text-[12.5px] ${form.kind === k ? 'bg-[#EAF1FF] font-semibold text-[#2F6BFF]' : 'text-[#64748B] hover:bg-[#F4F7FC]'}`}>{l}</button>
          ))}
        </div>
        <div className="rounded-xl border border-[#DCE3EE] focus-within:border-[#2F6BFF]">
          <textarea value={form.body} onChange={set('body')} rows={5} placeholder={form.kind === 'note' ? 'Visible uniquement par l\'équipe…' : 'Le commerçant le verra dans « Besoin d\'aide ? » et le recevra par email.'}
                    className="block w-full resize-y rounded-xl bg-transparent px-3 py-2.5 text-[13.5px] text-[#0B1C3F] outline-none" />
          <UploadChips up={up} />
          <div className="px-2 pb-2"><AttachButton onFiles={up.add} /></div>
        </div>
        {err && <p className="text-[12.5px] text-[#E11D48]">{err}</p>}
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" onClick={onClose} className="h-10 rounded-xl border border-[#DCE3EE] px-4 text-[13px] text-[#475569]">Annuler</button>
          <button type="button" onClick={submit} disabled={busy || !up.ready} className="inline-flex h-10 items-center gap-2 rounded-xl bg-[#2F6BFF] px-5 text-[13.5px] font-semibold text-white disabled:opacity-60">{busy && <Loader2 size={15} className="animate-spin" />} Créer le ticket</button>
        </div>
      </div>
    </Modal>
  );
}

function RepliesModal({ onClose, say }) {
  const [rows, setRows] = useState(null);
  const [edit, setEdit] = useState(null);
  const load = () => supportAPI.replies().then(({ data }) => setRows(data.rows)).catch(() => setRows([]));
  useEffect(() => { load(); }, []);
  const save = () => {
    const body = { title: edit.title.trim(), body: edit.body.trim() };
    if (!body.title || !body.body) { say('Titre et texte obligatoires.'); return; }
    (edit.id ? supportAPI.editReply(edit.id, body) : supportAPI.addReply(body)).then(() => { setEdit(null); load(); say('Réponse enregistrée.'); })
      .catch((e) => say(errText(e, 'Enregistrement impossible.')));
  };
  const field = 'w-full rounded-xl border border-[#DCE3EE] bg-white px-3 text-[13.5px] text-[#0B1C3F] outline-none focus:border-[#2F6BFF]';
  return (
    <Modal title="Réponses enregistrées" onClose={onClose} wide>
      <p className="mb-3 text-[12.5px] text-[#64748B]">Insérées depuis « Réponse enregistrée ». <code className="rounded bg-[#F1F5F9] px-1">{'{prenom}'}</code> devient le prénom du commerçant, <code className="rounded bg-[#F1F5F9] px-1">{'{commerce}'}</code> le nom du commerce.</p>
      {edit ? (
        <div className="space-y-2.5">
          <input value={edit.title} onChange={(e) => setEdit({ ...edit, title: e.target.value })} maxLength={80} placeholder="Titre" className={`${field} h-11`} />
          <textarea value={edit.body} onChange={(e) => setEdit({ ...edit, body: e.target.value })} rows={8} placeholder="Texte de la réponse" className={`${field} py-2.5`} />
          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => setEdit(null)} className="h-10 rounded-xl border border-[#DCE3EE] px-4 text-[13px] text-[#475569]">Annuler</button>
            <button type="button" onClick={save} className="h-10 rounded-xl bg-[#2F6BFF] px-5 text-[13.5px] font-semibold text-white">Enregistrer</button>
          </div>
        </div>
      ) : !rows ? <Loading /> : (
        <>
          <ul className="divide-y divide-[#F1F5F9]">
            {rows.map((r) => (
              <li key={r.id} className="flex items-start gap-3 py-3">
                <span className="min-w-0 flex-1"><strong className="block text-[13.5px] text-[#0B1C3F]">{r.title}</strong><span className="line-clamp-2 whitespace-pre-wrap text-[12.5px] text-[#64748B]">{r.body}</span></span>
                <button type="button" aria-label={`Modifier ${r.title}`} onClick={() => setEdit(r)} className="rounded-lg p-1.5 text-[#475569] hover:bg-[#F4F7FC]"><Pencil size={15} /></button>
                <button type="button" aria-label={`Supprimer ${r.title}`} onClick={() => { if (window.confirm(`Supprimer « ${r.title} » ?`)) supportAPI.deleteReply(r.id).then(load); }} className="rounded-lg p-1.5 text-[#E11D48] hover:bg-[#FDECEF]"><Trash2 size={15} /></button>
              </li>
            ))}
          </ul>
          <button type="button" onClick={() => setEdit({ title: '', body: '' })} className="mt-3 inline-flex h-10 items-center gap-2 rounded-xl bg-[#2F6BFF] px-4 text-[13.5px] font-semibold text-white"><Plus size={16} /> Nouvelle réponse</button>
        </>
      )}
    </Modal>
  );
}

function TagsModal({ onClose, onSaved }) {
  const [tags, setTags] = useState(null);
  const [colors, setColors] = useState([]);
  useEffect(() => { supportAPI.tags().then(({ data }) => { setTags(data.tags.map((x) => ({ ...x, was: x.label }))); setColors(data.colors); }).catch(() => setTags([])); }, []);
  const save = () => {
    const r = {};
    tags.forEach((x) => { if (x.was && x.was !== x.label.trim() && x.label.trim()) r[x.was] = x.label.trim(); });
    supportAPI.saveTags({ tags: tags.filter((x) => x.label.trim()).map(({ label, color }) => ({ label: label.trim(), color })), renamed: r }).then(onSaved);
  };
  return (
    <Modal title="Gérer les tags" onClose={onClose}>
      {!tags ? <Loading /> : (
        <div className="space-y-2">
          {tags.map((x, i) => (
            <div key={i} className="flex items-center gap-2">
              <input value={x.label} onChange={(e) => setTags(tags.map((y, j) => (j === i ? { ...y, label: e.target.value } : y)))} maxLength={40} className="h-10 flex-1 rounded-xl border border-[#DCE3EE] px-3 text-[13.5px] outline-none focus:border-[#2F6BFF]" />
              <span className="flex gap-1">
                {colors.map((c) => <button key={c} type="button" aria-label={c} onClick={() => setTags(tags.map((y, j) => (j === i ? { ...y, color: c } : y)))} className={`h-6 w-6 rounded-full border-2 ${x.color === c ? 'border-[#0B1C3F]' : 'border-transparent'}`} style={{ background: TAG_TONE[c][1] }} />)}
              </span>
              <button type="button" aria-label="Supprimer" onClick={() => setTags(tags.filter((_, j) => j !== i))} className="rounded-lg p-1.5 text-[#E11D48] hover:bg-[#FDECEF]"><Trash2 size={15} /></button>
            </div>
          ))}
          <button type="button" onClick={() => setTags([...tags, { label: '', color: 'blue' }])} className="inline-flex items-center gap-1.5 text-[13px] font-medium text-[#2F6BFF]"><Plus size={15} /> Ajouter un tag</button>
          <p className="text-[12px] text-[#94A3B8]">Un tag renommé suit ses tickets ; un tag supprimé est retiré des tickets.</p>
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={onClose} className="h-10 rounded-xl border border-[#DCE3EE] px-4 text-[13px] text-[#475569]">Annuler</button>
            <button type="button" onClick={save} className="h-10 rounded-xl bg-[#2F6BFF] px-5 text-[13.5px] font-semibold text-white">Enregistrer</button>
          </div>
        </div>
      )}
    </Modal>
  );
}
