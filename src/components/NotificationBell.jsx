/**
 * NotificationBell — the bell of the top bar and its panel (design validated
 * by the user, 2026-10-03), plus the parts the full page reuses
 * (pages/NotificationsPage.jsx).
 *
 * A business: /api/owner/insights/alerts/multi-store (its clients' alerts per
 * establishment, then what waits for its OK) + its support answers. The
 * platform team: security and support alerts.
 *
 * Every alert carries its own links from the server (`actions`, `href`):
 * clicking the alert opens its first link, « Voir les clients » exactly the
 * clients it counts, « Envoyer … » the composer already written for them.
 *
 * Read = acted on (opened, a link clicked, or « Tout marquer comme lu »).
 * « × » hides an alert until what it says changes.
 *
 * The panel is drawn in a portal: the top bar's text rule (index.css,
 * main:has(...) > div:first-child *) would otherwise repaint its colours.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate } from 'react-router-dom';
import {
  AlertTriangle, BarChart3, Bell, CalendarClock, ChevronDown, ChevronRight, Check, Crown, FileText,
  Inbox, Info, ListChecks, MessageSquare, Send, Settings, ShieldAlert, Store, TrendingDown, TrendingUp, Users, X,
} from 'lucide-react';
import api, { ownerAPI, securityAPI, supportAPI, mySupportAPI } from '../lib/api';
import { can } from '../lib/perms';
import { useBranch } from '../contexts/BranchContext';
import { useAuth } from '../contexts/AuthContext';

/* ── what was read, hidden, and when an alert was first seen ─────────────── */
const READ_KEY = 'fidclic:bell-read';
const HIDDEN_KEY = 'fidclic:bell-hidden';
const SEEN_KEY = 'fidclic:bell-seen';
const SYNC = 'fidclic:bell-state';

const loadSet = (key) => { try { return new Set(JSON.parse(localStorage.getItem(key) || '[]')); } catch { return new Set(); } };
const saveSet = (key, set) => { try { localStorage.setItem(key, JSON.stringify([...set].slice(-300))); } catch { /* private mode */ } };
const loadMap = (key) => { try { return JSON.parse(localStorage.getItem(key) || '{}') || {}; } catch { return {}; } };
const saveMap = (key, map) => {
  try {
    const keep = Object.entries(map).sort((a, b) => (a[1] < b[1] ? 1 : -1)).slice(0, 300);
    localStorage.setItem(key, JSON.stringify(Object.fromEntries(keep)));
  } catch { /* private mode */ }
};
// By alert AND by what it says: an alert whose figure changes comes back as new.
export const sig = (a) => `${a.id || a.title}|${a.metric ?? ''}|${a.title || ''}`;

/* ── how an alert looks ────────────────────────────────────────────────────── */
const TONES = {
  red: { fg: '#EF4444', bg: '#FEE2E2' },
  orange: { fg: '#F97316', bg: '#FFEDD5' },
  blue: { fg: '#2563EB', bg: '#DBEAFE' },
  green: { fg: '#16A34A', bg: '#DCFCE7' },
  violet: { fg: '#7C3AED', bg: '#EDE9FE' },
};
const kindOf = (a) => String(a.id || '').split('__').pop();

export function lookOf(a) {
  const k = kindOf(a);
  if (k === 'at_risk') return { Icon: AlertTriangle, tone: a.severity === 'critical' ? 'red' : 'orange' };
  if (k.startsWith('top_silent')) return { Icon: Crown, tone: 'orange' };
  if (k === 'one_timers') return { Icon: Users, tone: 'green' };
  if (k.startsWith('autopilot') || k.startsWith('copilot')) return { Icon: CalendarClock, tone: 'blue' };
  if (k.startsWith('pushwallet')) return { Icon: Inbox, tone: 'blue' };
  if (k.startsWith('report')) return { Icon: FileText, tone: 'violet' };
  if (k.startsWith('sup-')) return { Icon: MessageSquare, tone: 'violet' };
  if (/login|security|secu/i.test(k)) return { Icon: ShieldAlert, tone: a.severity === 'critical' ? 'red' : 'orange' };
  if (a.severity === 'critical') return { Icon: AlertTriangle, tone: 'red' };
  if (a.severity === 'warning') return { Icon: TrendingDown, tone: 'orange' };
  if (a.severity === 'win' || a.severity === 'positive') return { Icon: TrendingUp, tone: 'green' };
  if (/limit|plan|licen/i.test(k)) return { Icon: Info, tone: 'violet' };
  return { Icon: BarChart3, tone: 'blue' };
}

/** « Campagnes » / « Clients » chips. */
export function categoryOf(a) {
  const k = kindOf(a);
  if (k === 'at_risk' || k === 'one_timers' || k.startsWith('top_silent')) return 'clients';
  if (/^(autopilot|copilot|report|pushwallet)/.test(k)) return 'campagnes';
  return 'other';
}

// An alert's links, as the server wrote them. Nothing is guessed from the title.
export const actionsOf = (a) => {
  if (Array.isArray(a.actions) && a.actions.length) return a.actions.filter((x) => x && x.href);
  if (a.action && typeof a.action === 'object' && a.action.href) return [{ kind: 'open', label: a.action.label || 'Voir', href: a.action.href }];
  if (typeof a.action === 'string' && a.action) return [{ kind: 'open', label: 'Voir', href: a.action }];
  return [];
};
export const hrefOf = (a) => a.href || actionsOf(a)[0]?.href || null;

export function ago(iso, now = Date.now()) {
  const t = new Date(iso).getTime();
  if (!t) return '';
  const m = Math.max(0, Math.round((now - t) / 60000));
  if (m < 1) return 'À l’instant';
  if (m < 60) return `Il y a ${m} min`;
  const h = Math.round(m / 60);
  if (h < 24) return `Il y a ${h}h`;
  const d = Math.round(h / 24);
  return `Il y a ${d} jour${d > 1 ? 's' : ''}`;
}

/* ── the data: alerts, stores, read / hidden / first seen ──────────────────── */
export function useNotifications({ platformAdmin = false } = {}) {
  const { branchId } = useBranch();
  const { user } = useAuth();
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(false);
  const [readIds, setReadIds] = useState(() => loadSet(READ_KEY));
  const [hiddenIds, setHiddenIds] = useState(() => loadSet(HIDDEN_KEY));
  const [seen, setSeen] = useState(() => loadMap(SEEN_KEY));
  const [accountName, setAccountName] = useState('');
  const [stores, setStores] = useState([]);
  const [logo, setLogo] = useState('');

  // The bell and the page share read / hidden: one updates, the other follows.
  useEffect(() => {
    const on = () => { setReadIds(loadSet(READ_KEY)); setHiddenIds(loadSet(HIDDEN_KEY)); };
    window.addEventListener(SYNC, on);
    window.addEventListener('storage', on);
    return () => { window.removeEventListener(SYNC, on); window.removeEventListener('storage', on); };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const list = (r) => (r.status === 'fulfilled' ? (Array.isArray(r.value.data?.alerts) ? r.value.data.alerts : (Array.isArray(r.value.data) ? r.value.data : [])) : []);
    const load = async () => {
      setLoading(true);
      try {
        let main; let support;
        if (platformAdmin) {
          [main, support] = await Promise.allSettled([
            user?.role === 'super_admin' ? securityAPI.alerts() : Promise.reject(new Error('not super')),
            can(user, 'support') ? supportAPI.alerts() : Promise.reject(new Error('no support')),
          ]);
        } else {
          [main, support] = await Promise.allSettled([
            api.get('/owner/insights/alerts/multi-store').catch(() => ownerAPI.getProactiveAlerts({})),
            ['business_owner', 'administrateur', 'manager'].includes(user?.role) ? mySupportAPI.alerts() : Promise.reject(new Error('no support')),
          ]);
        }
        const merged = [...list(support), ...list(main)];
        if (cancelled) return;
        // « Il y a 3h »: when the alert first appeared on this device, unless
        // the alert carries its own date.
        const s = loadMap(SEEN_KEY); const nowIso = new Date().toISOString(); let changed = false;
        merged.forEach((a) => { const k = sig(a); if (!s[k]) { s[k] = a.created_at || nowIso; changed = true; } });
        if (changed) saveMap(SEEN_KEY, s);
        setSeen(s);
        setAlerts(merged);
      } catch (_e) { /* silent */ }
      finally { if (!cancelled) setLoading(false); }
    };
    load();
    const id = setInterval(load, 5 * 60 * 1000);
    return () => { cancelled = true; clearInterval(id); };
  }, [branchId, platformAdmin]); // eslint-disable-line react-hooks/exhaustive-deps

  // Account, establishments and the card's logo — a platform admin has no shop.
  useEffect(() => {
    if (platformAdmin) return undefined;
    let cancelled = false;
    (async () => {
      try { const t = await ownerAPI.getTenant(); if (!cancelled) setAccountName(t.data?.name || 'Mon compte'); } catch (_e) { /* silent */ }
      try {
        const b = await ownerAPI.getBranches();
        const all = Array.isArray(b.data) ? b.data : (b.data?.branches || []);
        const mine = Array.isArray(user?.branch_ids) && user?.role !== 'business_owner' ? user.branch_ids : null;
        if (!cancelled) setStores(mine ? all.filter((x) => mine.includes(x.id)) : all);
      } catch (_e) { /* silent */ }
      try {
        const c = await ownerAPI.cardTemplate();
        const l = c.data?.brand_fields?.logo_url || c.data?.logo_url || '';
        if (!cancelled) setLogo(l);
      } catch (_e) { /* silent */ }
    })();
    return () => { cancelled = true; };
  }, [platformAdmin, user?.role, user?.branch_ids]); // eslint-disable-line react-hooks/exhaustive-deps

  const isUnread = useCallback((a) => !readIds.has(sig(a)), [readIds]);
  const markRead = useCallback((list) => {
    const next = loadSet(READ_KEY); list.forEach((a) => next.add(sig(a)));
    saveSet(READ_KEY, next); setReadIds(next); window.dispatchEvent(new Event(SYNC));
  }, []);
  const hide = useCallback((a) => {
    const next = loadSet(HIDDEN_KEY); next.add(sig(a));
    saveSet(HIDDEN_KEY, next); setHiddenIds(next);
    const r = loadSet(READ_KEY); r.add(sig(a)); saveSet(READ_KEY, r); setReadIds(r);
    window.dispatchEvent(new Event(SYNC));
  }, []);
  const showHidden = useCallback(() => { saveSet(HIDDEN_KEY, new Set()); setHiddenIds(new Set()); window.dispatchEvent(new Event(SYNC)); }, []);
  const seenAt = useCallback((a) => a.created_at || seen[sig(a)] || null, [seen]);

  const visible = alerts.filter((a) => !hiddenIds.has(sig(a)));
  return {
    alerts: visible, hiddenCount: alerts.length - visible.length, loading,
    stores, accountName, logo, branchId, isUnread, markRead, hide, showHidden, seenAt,
  };
}

/** The alerts of one establishment (and those of the whole shop). */
export const ofStore = (alerts, store) => (store === 'all' ? alerts : alerts.filter((a) => !a.branch_id || a.branch_id === store));

/** Chip filter. */
export const byFilter = (alerts, filter, isUnread) => alerts.filter((a) => (
  filter === 'unread' ? isUnread(a) : filter === 'campagnes' ? categoryOf(a) === 'campagnes'
    : filter === 'clients' ? categoryOf(a) === 'clients' : true));

/* ── parts ─────────────────────────────────────────────────────────────────── */
function Thumb({ logo, size = 46 }) {
  const [broken, setBroken] = useState(false);
  useEffect(() => setBroken(false), [logo]);
  return logo && !broken ? (
    <img src={logo} alt="" onError={() => setBroken(true)} style={{ width: size + 6, height: size }}
         className="shrink-0 rounded-lg border border-[#E6EEFB] bg-white object-cover" />
  ) : (
    <span style={{ width: size + 6, height: size }} className="grid shrink-0 place-items-center rounded-lg bg-[#EAF1FF] text-[#2F6BFF]"><Store size={20} /></span>
  );
}

/** « Café Lumière - Main · ● Boutique sélectionnée » and its menu. */
export function StorePicker({ stores, value, onChange, logo, accountName }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const away = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', away);
    return () => document.removeEventListener('mousedown', away);
  }, [open]);
  const many = stores.length > 1;
  const current = value === 'all' ? null : stores.find((s) => s.id === value);
  const name = current?.name || (value === 'all' && many ? 'Toutes les boutiques' : (stores[0]?.name || accountName || 'Ma boutique'));
  const sub = value === 'all' && many ? `${stores.length} boutiques` : 'Boutique sélectionnée';
  return (
    <div ref={ref} className="relative">
      <button type="button" disabled={!many} onClick={() => setOpen((o) => !o)} aria-haspopup="listbox" aria-expanded={open}
              className="flex w-full items-center gap-3 rounded-xl border border-[#E6EEFB] bg-white p-2.5 text-left transition enabled:hover:border-[#C9D8F5]">
        <Thumb logo={logo} />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[14px] font-bold text-[#0B1C3F]">{name}</span>
          <span className="mt-0.5 flex items-center gap-1.5 text-[12px] text-[#64748B]">
            <span className="h-2 w-2 rounded-full bg-[#22C55E]" /> {sub}
          </span>
        </span>
        {many && <ChevronDown size={18} className={`mr-1 shrink-0 text-[#475569] transition ${open ? 'rotate-180' : ''}`} />}
      </button>
      {open && (
        <ul role="listbox" className="absolute left-0 right-0 top-full z-10 mt-1.5 overflow-hidden rounded-xl border border-[#E6EEFB] bg-white py-1 shadow-[0_18px_40px_-20px_rgba(11,28,63,.45)]">
          {[{ id: 'all', name: 'Toutes les boutiques' }, ...stores].map((s) => (
            <li key={s.id}>
              <button type="button" role="option" aria-selected={value === s.id} onClick={() => { onChange(s.id); setOpen(false); }}
                      className="flex w-full items-center justify-between px-3.5 py-2 text-left text-[13px] text-[#0B1C3F] hover:bg-[#F5F8FE]">
                {s.name} {value === s.id && <Check size={14} className="text-[#2F6BFF]" />}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Toutes · Non lues · Campagnes · Clients — with their counts. */
export function FilterChips({ value, onChange, counts, simple = false }) {
  const chips = simple
    ? [['all', 'Toutes'], ['unread', 'Non lues']]
    : [['all', 'Toutes'], ['unread', 'Non lues'], ['campagnes', 'Campagnes'], ['clients', 'Clients']];
  return (
    <div className="flex flex-wrap gap-1.5" role="tablist">
      {chips.map(([k, label]) => {
        const on = value === k;
        const n = counts[k] || 0;
        return (
          <button key={k} type="button" role="tab" aria-selected={on} onClick={() => onChange(k)}
                  className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-xl border px-2.5 py-[6px] text-[12.5px] font-semibold transition ${
                    on ? 'border-[#2F6BFF] bg-[#F5F8FF] text-[#2F6BFF] shadow-[0_0_0_1px_#2F6BFF_inset]' : 'border-[#E6EEFB] bg-white text-[#0B1C3F] hover:border-[#C9D8F5]'}`}>
            {label}
            <span className={`grid h-5 min-w-[20px] place-items-center rounded-full px-1.5 text-[11px] font-bold ${
              on ? 'bg-[#2F6BFF] text-white' : k === 'unread' ? 'bg-[#FEE2E2] text-[#DC2626]' : 'bg-[#EEF2F7] text-[#475569]'}`}>{n}</span>
          </button>
        );
      })}
    </div>
  );
}

/** One alert: icon tile · ● title · text · links · time ›. */
export function AlertRow({ a, unread, when, onGo, onHide, hideable = true, showBranch = true }) {
  const { Icon, tone } = lookOf(a);
  const t = TONES[tone];
  const href = hrefOf(a);
  const actions = actionsOf(a);
  return (
    <div data-alert={a.id} role={href ? 'button' : undefined} tabIndex={href ? 0 : undefined}
         onClick={() => href && onGo(a, href)}
         onKeyDown={(e) => { if (href && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); onGo(a, href); } }}
         className={`group relative flex gap-3.5 rounded-lg border-b border-[#EEF3FB] px-1 py-3.5 transition last:border-b-0 hover:bg-[#F5F8FE] focus:bg-[#F5F8FE] focus:outline-none ${
           href ? 'cursor-pointer' : ''} ${unread ? 'bg-[#FAFCFF]' : ''}`}>
      <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl" style={{ background: t.bg }}>
        <Icon size={20} color={t.fg} fill={tone === 'red' ? t.fg : 'none'} stroke={tone === 'red' ? '#FFFFFF' : t.fg} strokeWidth={tone === 'red' ? 2 : 2.2} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-start gap-2">
          <p className={`min-w-0 flex-1 text-[14px] leading-snug text-[#0B1C3F] ${unread ? 'font-bold' : 'font-semibold'}`}>
            <span className="mr-2 inline-block h-2 w-2 -translate-y-px rounded-full align-middle" style={{ background: t.fg }} aria-hidden="true" />
            {a.title}
          </p>
          {when && <span className="shrink-0 pt-0.5 text-[12px] text-[#94A3B8]">{ago(when)}</span>}
        </div>
        {a.body && <p className="mt-1 line-clamp-2 text-[12.5px] leading-snug text-[#475569]">{a.body}</p>}
        {showBranch && a.branch_name && <p className="mt-1 text-[11px] font-semibold uppercase tracking-wide text-[#94A3B8]">{a.branch_name}</p>}
        {actions.length > 0 && (
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            {actions.map((x, k) => {
              const primary = x.kind === 'campaign' || actions.length === 1;
              const XIcon = x.kind === 'customers' ? Users : x.kind === 'campaign' ? Send : null;
              return (
                <button key={k} type="button" onClick={(e) => { e.stopPropagation(); onGo(a, x.href); }}
                        className={`inline-flex items-center gap-1 whitespace-nowrap rounded-lg border px-2 py-[3px] text-[11px] font-semibold transition ${
                          primary ? 'border-[#2F6BFF] bg-[#2F6BFF] text-white hover:bg-[#2559DB]' : 'border-[#D6E3FF] bg-white text-[#2F6BFF] hover:bg-[#EAF1FF]'}`}>
                  {XIcon && <XIcon size={11} />} {x.label}
                </button>
              );
            })}
          </div>
        )}
      </div>
      <div className="flex w-6 shrink-0 flex-col items-center">
        {hideable && (
          <button type="button" aria-label="Masquer cette alerte" title="Masquer cette alerte"
                  onClick={(e) => { e.stopPropagation(); onHide(a); }}
                  className="grid h-6 w-6 place-items-center rounded-full text-[#94A3B8] opacity-0 transition hover:bg-[#EAF1FF] hover:text-[#334155] focus:opacity-100 group-hover:opacity-100">
            <X size={13} />
          </button>
        )}
        {href && <ChevronRight size={18} className="my-auto text-[#94A3B8]" />}
      </div>
    </div>
  );
}

export const EmptyAlerts = () => (
  <div className="flex flex-col items-center gap-2 px-4 py-10 text-center">
    <span className="grid h-11 w-11 place-items-center rounded-xl bg-[#DCFCE7] text-[#16A34A]"><Check size={20} /></span>
    <p className="text-[13.5px] font-semibold text-[#0B1C3F]">Tout va bien</p>
    <p className="text-[12.5px] text-[#64748B]">Aucune alerte pour le moment.</p>
  </div>
);

/* ── the bell and its panel ────────────────────────────────────────────────── */
const PANEL_W = 460;
const PANEL_MAX = 5;

const NotificationBell = ({ platformAdmin = false }) => {
  const navigate = useNavigate();
  const n = useNotifications({ platformAdmin });
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState('all');
  const [store, setStore] = useState(null);
  const [pos, setPos] = useState(null);
  const btn = useRef(null);
  const panel = useRef(null);

  // The establishment shown: the one chosen in the menu, else all of them.
  const many = n.stores.length > 1;
  const storeSel = store ?? (n.branchId && n.stores.some((s) => s.id === n.branchId) ? n.branchId : (many ? 'all' : (n.stores[0]?.id || 'all')));
  const scoped = useMemo(() => ofStore(n.alerts, storeSel), [n.alerts, storeSel]);
  const counts = useMemo(() => ({
    all: scoped.length,
    unread: scoped.filter(n.isUnread).length,
    campagnes: scoped.filter((a) => categoryOf(a) === 'campagnes').length,
    clients: scoped.filter((a) => categoryOf(a) === 'clients').length,
  }), [scoped, n.isUnread]);
  const shown = byFilter(scoped, filter, n.isUnread);
  const unreadAll = n.alerts.filter(n.isUnread).length;

  const place = useCallback(() => {
    const r = btn.current?.getBoundingClientRect();
    if (!r) return;
    const width = Math.min(PANEL_W, window.innerWidth - 16);
    setPos({ top: r.bottom + 10, left: Math.max(8, Math.min(r.right - width + 4, window.innerWidth - width - 8)), width });
  }, []);
  useEffect(() => {
    if (!open) return undefined;
    place();
    const away = (e) => {
      if (btn.current?.contains(e.target) || panel.current?.contains(e.target)) return;
      setOpen(false);
    };
    const esc = (e) => { if (e.key === 'Escape') setOpen(false); };
    window.addEventListener('resize', place);
    document.addEventListener('mousedown', away);
    document.addEventListener('keydown', esc);
    return () => { window.removeEventListener('resize', place); document.removeEventListener('mousedown', away); document.removeEventListener('keydown', esc); };
  }, [open, place]);

  const go = (a, href) => {
    if (!href) return;
    n.markRead([a]);
    setOpen(false);
    navigate(href);
  };
  const seeAll = () => {
    setOpen(false);
    const q = new URLSearchParams();
    if (storeSel && storeSel !== 'all') q.set('store', storeSel);
    if (filter !== 'all') q.set('filter', filter);
    navigate(`/dashboard/notifications${q.toString() ? `?${q}` : ''}`);
  };

  return (
    <div className="relative">
      <button
        ref={btn}
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="relative grid h-10 w-10 place-items-center rounded-xl border transition hover:-translate-y-px"
        style={{ background: '#FFFFFF', borderColor: '#E6EEFB', boxShadow: '0 6px 16px -10px rgba(11,28,63,0.35)' }}
        aria-label={`Notifications — ${unreadAll} non lue${unreadAll > 1 ? 's' : ''}`}
        aria-expanded={open}
        title={unreadAll > 0 ? `${unreadAll} alerte${unreadAll > 1 ? 's' : ''} non lue${unreadAll > 1 ? 's' : ''}` : 'Aucune nouvelle alerte'}
      >
        {/* Literal colours: the toolbar's text rule (index.css) repaints classes. */}
        <Bell size={19} color="#2F6BFF" fill="#2F6BFF" strokeWidth={2} />
        {unreadAll > 0 && (
          <span className="absolute -right-1.5 -top-1.5 flex h-5 min-w-[20px] items-center justify-center rounded-full px-1.5 text-[10.5px] font-bold"
                style={{ background: '#EF4444', color: '#FFFFFF', border: '2px solid #FFFFFF' }}>
            {unreadAll > 9 ? '9+' : unreadAll}
          </span>
        )}
      </button>

      {open && pos && createPortal(
        <div ref={panel} role="dialog" aria-label="Notifications"
             style={{ position: 'fixed', top: pos.top, left: pos.left, width: pos.width, zIndex: 60 }}
             className="overflow-hidden rounded-2xl border border-[#E6EEFB] bg-white shadow-[0_28px_60px_-24px_rgba(11,28,63,.45)]">
          <div className="px-5 pb-3 pt-4">
            <div className="mb-3.5 flex items-center justify-between gap-3">
              <h2 className="text-[19px] font-bold text-[#0B1C3F]">Notifications</h2>
              <div className="flex items-center gap-3">
                {counts.unread > 0 && (
                  <button type="button" onClick={() => n.markRead(scoped)} className="text-[12.5px] font-semibold text-[#2F6BFF] hover:underline">
                    Tout marquer comme lu
                  </button>
                )}
                {!platformAdmin && (
                  <button type="button" aria-label="Réglages des notifications" title="Réglages des notifications"
                          onClick={() => { setOpen(false); navigate('/dashboard/parametres/notifications'); }}
                          className="grid h-8 w-8 place-items-center rounded-lg text-[#475569] hover:bg-[#F1F5FB]">
                    <Settings size={18} />
                  </button>
                )}
              </div>
            </div>
            {!platformAdmin && (
              <div className="mb-3.5">
                <StorePicker stores={n.stores} value={storeSel} onChange={(v) => { setStore(v); setFilter('all'); }} logo={n.logo} accountName={n.accountName} />
              </div>
            )}
            <FilterChips value={filter} onChange={setFilter} counts={counts} simple={platformAdmin} />
          </div>

          <div className="max-h-[min(460px,calc(100vh-280px))] overflow-y-auto px-4">
            {n.loading && n.alerts.length === 0 ? (
              <div key="loading" className="px-4 py-10 text-center text-[13px] text-[#64748B]">Chargement…</div>
            ) : shown.length === 0 ? <EmptyAlerts /> : (
              shown.slice(0, PANEL_MAX).map((a, i) => (
                <AlertRow key={a.id || i} a={a} unread={n.isUnread(a)} when={n.seenAt(a)} onGo={go} onHide={n.hide} hideable={!platformAdmin}
                          showBranch={storeSel === 'all' && many} />
              ))
            )}
          </div>

          <div className="space-y-2 px-5 pb-4 pt-3">
            {n.hiddenCount > 0 && (
              <p className="text-center text-[11.5px] text-[#64748B]">
                <button type="button" onClick={n.showHidden} className="font-semibold text-[#2F6BFF] hover:underline">
                  Réafficher {n.hiddenCount} alerte{n.hiddenCount > 1 ? 's' : ''} masquée{n.hiddenCount > 1 ? 's' : ''}
                </button>
              </p>
            )}
            {!platformAdmin && (
              <button type="button" onClick={seeAll}
                      className="flex w-full items-center justify-center gap-2 rounded-xl border-[1.5px] border-[#2F6BFF] bg-white py-2.5 text-[13.5px] font-semibold text-[#2F6BFF] transition hover:bg-[#F5F8FF]">
                <ListChecks size={17} /> {storeSel === 'all' && many ? 'Voir toutes les notifications' : 'Voir toutes les notifications de cette boutique'}
                {shown.length > PANEL_MAX && <span className="rounded-full bg-[#EAF1FF] px-2 py-0.5 text-[11px]">+{shown.length - PANEL_MAX}</span>}
              </button>
            )}
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
};

export default NotificationBell;
