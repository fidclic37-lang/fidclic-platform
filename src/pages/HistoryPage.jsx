import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  History as HistoryIcon, Download, ChevronDown, ChevronLeft, ChevronRight,
  List, Users, Gift, QrCode, MessageSquare, CreditCard, Send, UserPlus,
  Search, Calendar, RotateCcw, Loader2, MoreHorizontal, X, ArrowUpRight,
} from 'lucide-react';
import { ownerAPI } from '../lib/api';
import { useBranch } from '../contexts/BranchContext';
import { perPage as prefPerPage } from '../lib/prefs';

/**
 * Historique — every activity on the loyalty programme, in one table.
 *
 * Built to the approved mockup and wired to /api/owner/history/* : the six
 * tabs, the four figures, the four filters, the paginated table and the CSV
 * export all hit the same feed, so what is exported is exactly what is shown.
 *
 * Nothing on this page is demo data. An empty shop reads zero and says so.
 */
const BLUE = '#2F6BFF';

// +3, -10, 0 — or a dash when the row has no such figure
const signed = (v, none) => (v === null || v === undefined ? none : `${v > 0 ? '+' : ''}${v}`);

const ICONS = { qr: QrCode, gift: Gift, message: MessageSquare, user: UserPlus, send: Send, card: CreditCard };
const TAB_ICONS = {
  all: List, clients: Users, points: Gift, scan: QrCode, messages: MessageSquare, card: CreditCard,
};
const TONES = {
  blue:   { bg: '#EAF1FF', fg: '#2F6BFF' },
  amber:  { bg: '#FFF3E3', fg: '#B45309' },
  violet: { bg: '#F0ECFF', fg: '#6D4AFF' },
  green:  { bg: '#E7F7EE', fg: '#0F8B58' },
  slate:  { bg: '#EEF2F8', fg: '#475569' },
};
/* Avatar colours are picked from the name, so the same client always keeps the
   same chip across pages and sessions. */
const AVATARS = ['#E8F0FF:#2F6BFF', '#FFE9EC:#D9345B', '#E9F8EF:#0F8B58', '#FFF1DE:#B45309',
                 '#F1ECFF:#6D4AFF', '#E6F6FA:#0E7490', '#FCE9F6:#B83280'];
const avatarFor = (name) => {
  let h = 0;
  for (let i = 0; i < (name || '').length; i += 1) h = (h * 31 + name.charCodeAt(i)) >>> 0;
  const [bg, fg] = AVATARS[h % AVATARS.length].split(':');
  return { bg, fg };
};

const ymd = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const MONTHS = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.'];
const prettyDay = (iso) => {
  const d = new Date(iso);
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
};
const prettyStamp = (iso) => {
  const d = new Date(iso);
  return `${d.getDate()} ${MONTHS[d.getMonth()]}, ${d.getFullYear()}, ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
};

/* ── building blocks ──────────────────────────────────────────────────── */
const StatCard = ({ card }) => {
  const Icon = ICONS[card.icon] || QrCode;
  const tone = TONES[card.tone] || TONES.blue;
  const up = (card.delta_pct ?? 0) >= 0;
  return (
    <div className="flex items-center gap-4 rounded-2xl border border-[#E6EEFB] bg-white p-5 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
      <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl"
            style={{ background: tone.bg, color: tone.fg }}>
        <Icon size={22} />
      </span>
      <div className="min-w-0">
        <p className="text-[26px] font-bold leading-none tracking-tight text-[#0B1C3F] tabular-nums">
          {card.value.toLocaleString('fr-FR')}
        </p>
        <p className="mt-1 text-[12.5px] text-[#64748B]">{card.label}</p>
        {card.delta_pct === null ? (
          <p className="mt-2 text-[11px] leading-tight text-[#94A3B8]">pas encore de période précédente</p>
        ) : (
          /* Badge on its own line with the caption under it, as in the mockup —
             side by side, "vs période précédente" wraps on a narrow card. */
          <div className="mt-2">
            <span className="inline-flex items-center gap-0.5 rounded-md px-1.5 py-0.5 text-[11.5px] font-semibold"
                  style={up ? { background: '#E7F7EE', color: '#0F8B58' } : { background: '#FEECEC', color: '#C0392B' }}>
              {up ? '↑' : '↓'} {up ? '+' : ''}{card.delta_pct}%
            </span>
            <span className="mt-1 block text-[11px] leading-tight text-[#94A3B8]">vs période précédente</span>
          </div>
        )}
      </div>
    </div>
  );
};

const Field = ({ label, children }) => (
  <label className="block min-w-0">
    <span className="mb-1.5 block text-[12px] font-semibold text-[#475569]">{label}</span>
    {children}
  </label>
);

const inputCls =
  'w-full rounded-xl border border-[#E6EEFB] bg-white py-2.5 pl-9 pr-3 text-[13px] text-[#0B1C3F] outline-none transition placeholder:text-[#94A3B8] focus:border-[#2F6BFF]';
const selectCls =
  'w-full appearance-none rounded-xl border border-[#E6EEFB] bg-white py-2.5 pl-3 pr-9 text-[13px] text-[#0B1C3F] outline-none transition focus:border-[#2F6BFF]';

/** The period picker: two native date inputs behind one mockup-shaped button. */
const PeriodPicker = ({ from, to, onChange }) => {
  const [open, setOpen] = useState(false);
  const box = useRef(null);
  useEffect(() => {
    const away = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', away);
    return () => document.removeEventListener('mousedown', away);
  }, []);
  const preset = (days) => {
    const end = new Date();
    const start = new Date(); start.setDate(end.getDate() - (days - 1));
    onChange(ymd(start), ymd(end)); setOpen(false);
  };
  return (
    <div className="relative" ref={box}>
      <button
        type="button" onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 rounded-xl border border-[#E6EEFB] bg-white px-3 py-2.5 text-left text-[13px] text-[#0B1C3F] transition hover:border-[#2F6BFF]"
      >
        <Calendar size={15} className="shrink-0 text-[#2F6BFF]" />
        <span className="min-w-0 flex-1 truncate">{prettyDay(from)} – {prettyDay(to)}</span>
        <ChevronDown size={15} className="shrink-0 text-[#94A3B8]" />
      </button>
      {open && (
        <div className="absolute left-0 top-full z-30 mt-2 w-[300px] rounded-xl border border-[#E6EEFB] bg-white p-3 shadow-[0_24px_60px_-28px_rgba(11,28,63,.5)]">
          <div className="flex flex-wrap gap-1.5">
            {[['7 jours', 7], ['30 jours', 30], ['90 jours', 90], ['12 mois', 365]].map(([label, d]) => (
              <button key={d} type="button" onClick={() => preset(d)}
                      className="rounded-lg border border-[#E6EEFB] px-2.5 py-1 text-[12px] font-medium text-[#334155] transition hover:border-[#2F6BFF] hover:text-[#2F6BFF]">
                {label}
              </button>
            ))}
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2">
            <label className="block">
              <span className="mb-1 block text-[11px] font-semibold text-[#64748B]">Du</span>
              <input type="date" value={from} max={to} onChange={(e) => onChange(e.target.value, to)}
                     className="w-full rounded-lg border border-[#E6EEFB] px-2 py-1.5 text-[12.5px] text-[#0B1C3F] outline-none focus:border-[#2F6BFF]" />
            </label>
            <label className="block">
              <span className="mb-1 block text-[11px] font-semibold text-[#64748B]">Au</span>
              <input type="date" value={to} min={from} onChange={(e) => onChange(from, e.target.value)}
                     className="w-full rounded-lg border border-[#E6EEFB] px-2 py-1.5 text-[12.5px] text-[#0B1C3F] outline-none focus:border-[#2F6BFF]" />
            </label>
          </div>
        </div>
      )}
    </div>
  );
};

/** Row detail — the "Voir" button opens this rather than navigating away. */
const RowDrawer = ({ row, onClose, onGoCustomer }) => {
  useEffect(() => {
    const key = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, [onClose]);
  if (!row) return null;
  const tone = TONES[row.tone] || TONES.blue;
  const Icon = ICONS[row.icon] || QrCode;
  const lines = [
    ['Date et heure', prettyStamp(row.at)],
    ...(row.store ? [['Établissement', row.store]] : []),
    ['Client', row.customer_name],
    ['Numéro de carte', row.customer_barcode || '—'],
    ["Type d'activité", row.label],
    ['Détails', row.detail || '—'],
    ['Points', signed(row.points, '—')],
    ['Tampons', signed(row.stamps, '—')],
    ['Montant', row.amount ? `${row.amount.toFixed(2).replace('.', ',')} €` : '—'],
  ];
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-[#0B1C3F]/25 p-0 sm:items-center sm:p-6" onClick={onClose}>
      <div className="w-full max-w-md overflow-hidden rounded-t-2xl bg-white shadow-2xl sm:rounded-2xl"
           onClick={(e) => e.stopPropagation()}>
        <header className="flex items-center gap-3 border-b border-[#E6EEFB] px-5 py-4">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl"
                style={{ background: tone.bg, color: tone.fg }}><Icon size={19} /></span>
          <div className="min-w-0 flex-1">
            <h3 className="text-[15px] font-bold text-[#0B1C3F]">{row.label}</h3>
            <p className="text-[12px] text-[#64748B]">{prettyStamp(row.at)}</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Fermer" className="text-[#94A3B8] hover:text-[#0B1C3F]">
            <X size={18} />
          </button>
        </header>
        <dl className="px-5 py-4">
          {lines.map(([k, v]) => (
            <div key={k} className="flex items-start justify-between gap-4 border-b border-[#F1F5FB] py-2.5 last:border-b-0">
              <dt className="text-[12.5px] text-[#64748B]">{k}</dt>
              <dd className="text-right text-[13px] font-medium text-[#0B1C3F]">{v}</dd>
            </div>
          ))}
        </dl>
        {row.customer_id && (
          <div className="border-t border-[#E6EEFB] px-5 py-3.5">
            <button type="button" onClick={() => onGoCustomer(row)}
                    className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-[#2F6BFF] hover:underline">
              Voir la fiche client <ArrowUpRight size={14} />
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

/* ── page ─────────────────────────────────────────────────────────────── */
const todayISO = ymd(new Date());
const monthAgoISO = (() => { const d = new Date(); d.setDate(d.getDate() - 20); return ymd(d); })();

export default function HistoryPage() {
  const navigate = useNavigate();
  const [meta, setMeta] = useState({ tabs: [], actions: [], per_page_options: [10, 25, 50, 100] });
  // Points or Tampons in the last column (user, 2026-10-15): the shop's own
  // programme first, the other one a click away
  const [unitPick, setUnitPick] = useState(null);
  const unit = unitPick || meta.unit || 'points';
  const [tab, setTab] = useState('all');
  const [from, setFrom] = useState(monthAgoISO);
  const [to, setTo] = useState(todayISO);
  const [action, setAction] = useState('');
  const [customer, setCustomer] = useState('');
  const [typed, setTyped] = useState('');          // debounced into `customer`
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(() => prefPerPage());
  const [feed, setFeed] = useState({ rows: [], total: 0, pages: 1 });
  // « Établissement » (QA F29): where each row happened, as soon as the shop has several
  const { branches } = useBranch();
  const showStore = (branches || []).length > 1 || new Set(feed.rows.map((r) => r.store_id)).size > 1;
  const heads = ['Date et heure', ...(showStore ? ['Établissement'] : []), 'Client', "Type d'activité", 'Détails', 'Points', 'Action'];
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [drawer, setDrawer] = useState(null);
  const [menuFor, setMenuFor] = useState(null);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    ownerAPI.historyFilters().then(({ data }) => setMeta(data)).catch(() => {});
  }, []);

  // One request per keystroke would hammer the feed; wait for a pause.
  useEffect(() => {
    const id = setTimeout(() => { setCustomer(typed.trim()); setPage(1); }, 300);
    return () => clearTimeout(id);
  }, [typed]);

  const params = useMemo(() => ({
    from, to, tab, page, per_page: perPage,
    ...(action ? { action } : {}),
    ...(customer ? { customer } : {}),
  }), [from, to, tab, page, perPage, action, customer]);

  useEffect(() => {
    let alive = true;
    setLoading(true); setError('');
    ownerAPI.historyActivity(params)
      .then(({ data }) => { if (alive) setFeed(data); })
      .catch((e) => { if (alive) setError(e?.response?.data?.detail || "Impossible de charger l'historique."); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [params]);

  useEffect(() => {
    let alive = true;
    ownerAPI.historyStats({ from, to })
      .then(({ data }) => { if (alive) setStats(data); })
      .catch(() => { if (alive) setStats(null); });
    return () => { alive = false; };
  }, [from, to]);

  const setPeriod = useCallback((f, t) => { setFrom(f); setTo(t); setPage(1); }, []);
  const reset = () => {
    setTab('all'); setFrom(monthAgoISO); setTo(todayISO);
    setAction(''); setTyped(''); setCustomer(''); setPage(1); setPerPage(10);
  };
  const dirty = tab !== 'all' || from !== monthAgoISO || to !== todayISO || action || customer || perPage !== 10;

  const exportCsv = async () => {
    setExporting(true);
    try {
      const { data } = await ownerAPI.historyExport({
        from, to, tab, ...(action ? { action } : {}), ...(customer ? { customer } : {}),
      });
      const url = URL.createObjectURL(new Blob([data], { type: 'text/csv;charset=utf-8' }));
      const a = document.createElement('a');
      a.href = url; a.download = `fidclic-historique-${from}-${to}.csv`;
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
    } catch {
      setError("L'export n'a pas abouti. Réessayez dans un instant.");
    } finally {
      setExporting(false);
    }
  };

  const fr = (n) => Number(n || 0).toLocaleString('fr-FR').replace(/\u202f/g, '\u00a0');
  const first = feed.total === 0 ? 0 : (feed.page - 1) * feed.per_page + 1;
  const last = Math.min(feed.total, feed.page * feed.per_page);
  const pageNumbers = useMemo(() => {
    const total = feed.pages || 1;
    if (total <= 5) return Array.from({ length: total }, (_, i) => i + 1);
    const start = Math.max(1, Math.min(feed.page - 2, total - 4));
    return Array.from({ length: 5 }, (_, i) => start + i);
  }, [feed.pages, feed.page]);

  return (
    <div className="hst" onClick={() => setMenuFor(null)}>
      {/* header */}
      <header className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-[#EAF1FF] text-[#2F6BFF]">
            <HistoryIcon size={23} />
          </span>
          <div>
            <h1 className="text-[23px] font-bold leading-tight text-[#0B1C3F]">Historique</h1>
            <p className="text-[13px] text-[#64748B]">
              Consultez toutes les activités liées à votre programme de fidélité.
            </p>
          </div>
        </div>
        <button
          type="button" onClick={exportCsv} disabled={exporting}
          className="inline-flex items-center gap-2 rounded-xl border border-[#E6EEFB] bg-white px-4 py-2.5 text-[13px] font-semibold text-[#0B1C3F] transition hover:border-[#2F6BFF] hover:text-[#2F6BFF] disabled:opacity-60"
        >
          {exporting ? <Loader2 size={15} className="animate-spin" /> : <Download size={15} />}
          Exporter <ChevronDown size={14} className="text-[#94A3B8]" />
        </button>
      </header>

      {/* tabs */}
      <nav className="mb-5 flex gap-1.5 overflow-x-auto rounded-2xl border border-[#E6EEFB] bg-white p-1.5 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
        {meta.tabs.map((t) => {
          const Icon = TAB_ICONS[t.key] || List;
          const on = tab === t.key;
          return (
            <button
              key={t.key} type="button"
              onClick={() => { setTab(t.key); setAction(''); setPage(1); }}
              className={`inline-flex shrink-0 items-center gap-2 rounded-xl px-3.5 py-2.5 text-[13px] font-semibold transition ${
                on ? 'bg-[#2F6BFF] text-white shadow-[0_10px_22px_-14px_rgba(47,107,255,.9)]'
                   : 'text-[#475569] hover:bg-[#F4F7FC]'}`}
            >
              <Icon size={15} /> {t.label}
            </button>
          );
        })}
      </nav>

      {/* the four figures */}
      <div className="mb-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {(stats?.cards || []).map((c) => <StatCard key={c.key} card={c} />)}
        {!stats && Array.from({ length: 4 }, (_, i) => (
          <div key={i} className="h-[116px] animate-pulse rounded-2xl border border-[#E6EEFB] bg-white" />
        ))}
      </div>

      {/* filters + table */}
      <section className="rounded-2xl border border-[#E6EEFB] bg-white shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
        <div className="grid gap-3 border-b border-[#EEF3FB] p-4 lg:grid-cols-[1.15fr_1fr_1.2fr_1fr_auto] lg:items-end">
          <Field label="Période">
            <PeriodPicker from={from} to={to} onChange={setPeriod} />
          </Field>
          <Field label="Type d'activité">
            <div className="relative">
              <select className={selectCls} value={tab}
                      onChange={(e) => { setTab(e.target.value); setAction(''); setPage(1); }}>
                {meta.tabs.map((t) => (
                  <option key={t.key} value={t.key}>{t.key === 'all' ? 'Tous' : t.label}</option>
                ))}
              </select>
              <ChevronDown size={15} className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
            </div>
          </Field>
          <Field label="Client">
            <div className="relative">
              <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
              <input className={inputCls} value={typed} onChange={(e) => setTyped(e.target.value)}
                     placeholder="Rechercher un client…" />
            </div>
          </Field>
          <Field label="Action">
            <div className="relative">
              <select className={selectCls} value={action}
                      onChange={(e) => { setAction(e.target.value); setPage(1); }}>
                <option value="">Toutes les actions</option>
                {meta.actions.map((a) => <option key={a.key} value={a.key}>{a.label}</option>)}
              </select>
              <ChevronDown size={15} className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
            </div>
          </Field>
          <button
            type="button" onClick={reset} disabled={!dirty}
            className="inline-flex h-[42px] items-center justify-center gap-1.5 rounded-xl border border-[#E6EEFB] px-4 text-[13px] font-semibold text-[#475569] transition hover:border-[#2F6BFF] hover:text-[#2F6BFF] disabled:opacity-45 disabled:hover:border-[#E6EEFB] disabled:hover:text-[#475569]"
          >
            <RotateCcw size={14} /> Réinitialiser
          </button>
        </div>

        {error && (
          <p className="mx-4 mt-4 rounded-xl bg-[#FEECEC] px-4 py-2.5 text-[12.5px] text-[#C0392B]">{error}</p>
        )}

        <div className="overflow-x-auto">
          <table className="w-full min-w-[920px] border-collapse">
            <thead>
              <tr className="border-b border-[#EEF3FB] text-left">
                {heads.map((h) => (
                  <th key={h}
                      className={`px-4 py-3 text-[12px] font-semibold uppercase tracking-[0.04em] text-[#64748B] ${
                        h === 'Points' ? 'text-right' : ''}`}>
                    {h === 'Points' ? (
                      <span className="inline-flex rounded-lg bg-[#F1F5F9] p-0.5 normal-case tracking-normal" role="group" aria-label="Afficher les points ou les tampons">
                        {[['points', 'Points'], ['stamps', 'Tampons']].map(([k, l]) => (
                          <button key={k} type="button" aria-pressed={unit === k} onClick={() => setUnitPick(k)}
                                  className={`rounded-md px-2 py-0.5 text-[11.5px] font-semibold ${unit === k ? 'bg-white text-[#0B1C3F] shadow-sm' : 'text-[#64748B]'}`}>
                            {l}
                          </button>
                        ))}
                      </span>
                    ) : h}
                    {/* How many on this page, out of all (user, 2026-10-03): 20/31, then 11/31. */}
                    {h === 'Client' && feed.total > 0 && (
                      <span className="ml-2 rounded-md bg-[#EAF1FF] px-1.5 py-0.5 text-[11px] font-bold normal-case tracking-normal text-[#2F6BFF] tabular-nums"
                            title={`${feed.rows.length} sur cette page, ${feed.total} au total`}>
                        {fr(feed.rows.length)}/{fr(feed.total)}
                      </span>
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading && feed.rows.length === 0 && (
                <tr key="loading"><td colSpan={heads.length} className="px-4 py-14 text-center text-[13px] text-[#64748B]">
                  <Loader2 size={16} className="mr-2 inline animate-spin" /> Chargement de l'historique…
                </td></tr>
              )}
              {!loading && feed.rows.length === 0 && (
                <tr><td colSpan={heads.length} className="px-4 py-14 text-center">
                  <p className="text-[13.5px] font-semibold text-[#0B1C3F]">Aucune activité sur cette période</p>
                  <p className="mt-1 text-[12.5px] text-[#64748B]">
                    Élargissez la période ou retirez un filtre pour voir plus d'activités.
                  </p>
                </td></tr>
              )}
              {feed.rows.map((r) => {
                const Icon = ICONS[r.icon] || QrCode;
                const tone = TONES[r.tone] || TONES.blue;
                const av = avatarFor(r.customer_name);
                return (
                  <tr key={`${r.action}-${r.id}-${r.at}`} className="border-b border-[#F4F7FC] last:border-b-0 transition hover:bg-[#FAFCFF]">
                    <td className="whitespace-nowrap px-4 py-3 text-[12.5px] text-[#475569] tabular-nums">
                      {prettyStamp(r.at)}
                    </td>
                    {showStore && (
                      <td className="max-w-[180px] px-4 py-3">
                        <span translate="no" className="notranslate block truncate text-[12.5px] text-[#334155]" title={r.store}>{r.store || '—'}</span>
                      </td>
                    )}
                    <td className="px-4 py-3">
                      <span className="flex items-center gap-2.5">
                        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[10.5px] font-bold"
                              style={{ background: av.bg, color: av.fg }}>
                          {r.initials}
                        </span>
                        <span translate="no" className="notranslate truncate text-[13px] font-medium text-[#0B1C3F]">{r.customer_name}</span>
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span className="flex items-center gap-2">
                        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md"
                              style={{ background: tone.bg, color: tone.fg }}>
                          <Icon size={13} />
                        </span>
                        <span className="whitespace-nowrap text-[12.5px] text-[#334155]">{r.label}</span>
                      </span>
                    </td>
                    <td className="max-w-[320px] px-4 py-3">
                      <span className="block truncate text-[12.5px] text-[#475569]" title={r.detail}>{r.detail || '—'}</span>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-right text-[12.5px] font-semibold tabular-nums"
                        style={{ color: r[unit] > 0 ? '#0F8B58' : r[unit] < 0 ? '#C0392B' : '#94A3B8' }}>
                      {signed(r[unit], '-')}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3">
                      <span className="flex items-center gap-1.5">
                        <button type="button" onClick={() => setDrawer(r)}
                                className="rounded-lg border border-[#E6EEFB] px-3 py-1.5 text-[12px] font-semibold text-[#334155] transition hover:border-[#2F6BFF] hover:text-[#2F6BFF]">
                          Voir
                        </button>
                        <span className="relative">
                          <button
                            type="button" aria-label="Plus d'actions"
                            onClick={(e) => { e.stopPropagation(); setMenuFor(menuFor === r.id ? null : r.id); }}
                            className="rounded-lg px-1.5 py-1.5 text-[#94A3B8] transition hover:bg-[#F4F7FC] hover:text-[#0B1C3F]"
                          >
                            <MoreHorizontal size={16} />
                          </button>
                          {menuFor === r.id && (
                            <span
                              className="absolute right-0 top-full z-20 mt-1 flex w-[190px] flex-col overflow-hidden rounded-xl border border-[#E6EEFB] bg-white py-1 shadow-[0_24px_60px_-28px_rgba(11,28,63,.5)]"
                              onClick={(e) => e.stopPropagation()}
                            >
                              <button type="button" onClick={() => { setDrawer(r); setMenuFor(null); }}
                                      className="px-3 py-2 text-left text-[12.5px] text-[#334155] hover:bg-[#F4F7FC]">
                                Voir le détail
                              </button>
                              {r.customer_id && (
                                <button type="button"
                                        onClick={() => navigate(`/dashboard/customers?q=${encodeURIComponent(r.customer_barcode || r.customer_name)}`)}
                                        className="px-3 py-2 text-left text-[12.5px] text-[#334155] hover:bg-[#F4F7FC]">
                                  Voir la fiche client
                                </button>
                              )}
                              <button type="button"
                                      onClick={() => { setAction(r.action); setPage(1); setMenuFor(null); }}
                                      className="px-3 py-2 text-left text-[12.5px] text-[#334155] hover:bg-[#F4F7FC]">
                                Filtrer sur « {r.label} »
                              </button>
                            </span>
                          )}
                        </span>
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* pagination */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[#EEF3FB] px-4 py-3.5">
          <p className="inline-flex flex-wrap items-center gap-1 rounded-lg bg-[#F1F5FF] px-3 py-1.5 text-[13.5px] font-semibold text-[#0B1C3F]">
            Affichage de <strong className="font-extrabold text-[#2F6BFF] tabular-nums">{fr(first)} à {fr(last)}</strong>
            sur <strong className="font-extrabold text-[#2F6BFF] tabular-nums">{fr(feed.total)}</strong> résultats
          </p>
          <div className="flex items-center gap-2">
            <button type="button" disabled={feed.page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}
                    className="flex h-8 w-8 items-center justify-center rounded-lg border border-[#E6EEFB] text-[#475569] transition hover:border-[#2F6BFF] hover:text-[#2F6BFF] disabled:opacity-40 disabled:hover:border-[#E6EEFB]">
              <ChevronLeft size={15} />
            </button>
            {pageNumbers.map((n) => (
              <button
                key={n} type="button" onClick={() => setPage(n)}
                className={`h-8 min-w-8 rounded-lg px-2 text-[12.5px] font-semibold transition ${
                  n === feed.page ? 'bg-[#2F6BFF] text-white'
                                  : 'border border-[#E6EEFB] text-[#475569] hover:border-[#2F6BFF] hover:text-[#2F6BFF]'}`}
              >
                {n}
              </button>
            ))}
            <button type="button" disabled={feed.page >= feed.pages} onClick={() => setPage((p) => p + 1)}
                    className="flex h-8 w-8 items-center justify-center rounded-lg border border-[#E6EEFB] text-[#475569] transition hover:border-[#2F6BFF] hover:text-[#2F6BFF] disabled:opacity-40 disabled:hover:border-[#E6EEFB]">
              <ChevronRight size={15} />
            </button>
            <div className="relative ml-1">
              <select
                value={perPage} onChange={(e) => { setPerPage(Number(e.target.value)); setPage(1); }}
                className="appearance-none rounded-lg border border-[#E6EEFB] bg-white py-1.5 pl-3 pr-8 text-[12.5px] text-[#334155] outline-none focus:border-[#2F6BFF]"
              >
                {([...new Set([...(meta.per_page_options || [10, 25, 50, 100]), prefPerPage()])].sort((a, b) => a - b)).map((n) => (
                  <option key={n} value={n}>{n} par page</option>
                ))}
              </select>
              <ChevronDown size={14} className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
            </div>
          </div>
        </div>
      </section>

      <RowDrawer
        row={drawer} onClose={() => setDrawer(null)}
        onGoCustomer={(r) => navigate(`/dashboard/customers?q=${encodeURIComponent(r.customer_barcode || r.customer_name)}`)}
      />
    </div>
  );
}
