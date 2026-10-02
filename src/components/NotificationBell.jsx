/**
 * NotificationBell — header bell with unread count + dropdown.
 *
 * A business: /api/owner/insights/alerts/multi-store (its clients' alerts per
 * establishment, then what waits for its OK) + its support answers. The
 * platform team: security and support alerts.
 *
 * Every alert carries its own links from the server (`actions`, `href`):
 * « Voir les clients » opens exactly the clients it counts, « Envoyer … » the
 * composer already written for them, and clicking the alert opens its first
 * link (user, 2026-10-03).
 *
 * Read = acted on (opened, a link clicked, or « Tout marquer comme lu »).
 * « × » hides an alert until what it says changes.
 */
import React, { useEffect, useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Bell, AlertTriangle, TrendingDown, TrendingUp, Sparkles, X, Building2, Users, Send, ChevronRight } from 'lucide-react';
import api, { ownerAPI, securityAPI, supportAPI, mySupportAPI } from '../lib/api';
import { can } from '../lib/perms';
import { useBranch } from '../contexts/BranchContext';
import { useAuth } from '../contexts/AuthContext';

// What has been read, and what the owner hid: by alert AND by what it says,
// so an alert whose figure changes (15 → 22 clients) comes back as new.
const READ_KEY = 'fidclic:bell-read';
const HIDDEN_KEY = 'fidclic:bell-hidden';

const loadSet = (key) => {
  try { return new Set(JSON.parse(localStorage.getItem(key) || '[]')); } catch { return new Set(); }
};
const saveSet = (key, set) => {
  try { localStorage.setItem(key, JSON.stringify([...set].slice(-300))); } catch { /* private mode */ }
};
const sig = (a) => `${a.id || a.title}|${a.metric ?? ''}|${a.title || ''}`;

const severityIcon = (severity) => {
  if (severity === 'critical') return AlertTriangle;
  if (severity === 'warning')  return TrendingDown;
  if (severity === 'positive' || severity === 'win') return TrendingUp;
  return Sparkles;
};
const severityColor = (severity) => {
  // The dashboard's own palette (Tableau de bord / Analyses).
  if (severity === 'critical') return '#E11D48';
  if (severity === 'warning')  return '#D97706';
  if (severity === 'positive' || severity === 'win') return '#0F8B58';
  return '#2F6BFF';
};

// An alert's links, as the server wrote them (`actions`: the clients' list,
// the composer written for them; or one « Voir … » link). Nothing is guessed
// from the title any more.
const actionsOf = (a) => {
  if (Array.isArray(a.actions) && a.actions.length) return a.actions.filter((x) => x && x.href);
  if (a.action && typeof a.action === 'object' && a.action.href) return [{ kind: 'open', label: a.action.label || 'Voir', href: a.action.href }];
  if (typeof a.action === 'string' && a.action) return [{ kind: 'open', label: 'Voir', href: a.action }];
  return [];
};
const hrefOf = (a) => a.href || actionsOf(a)[0]?.href || null;

const NotificationBell = ({ platformAdmin = false }) => {
  const navigate = useNavigate();
  const { branchId } = useBranch();
  const { user } = useAuth();
  const [alerts, setAlerts] = useState([]);
  const [readIds, setReadIds] = useState(() => loadSet(READ_KEY));
  const [hiddenIds, setHiddenIds] = useState(() => loadSet(HIDDEN_KEY));
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  // Account / franchise headline data — business name + list of all stores
  const [accountName, setAccountName] = useState('');
  const [stores, setStores] = useState([]);
  const wrapperRef = useRef(null);

  // Fetch alerts on mount + every 5 minutes while page is open.
  // Uses the multi-store endpoint so each alert is tagged with its branch_name —
  // the user instantly sees which store the alert refers to.
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      try {
        // The super admin's bell: suspicious, blocked and locked logins of
        // FidClic's team (Sécurité). A business: its own alerts, per store.
        // Centre de support adds its own: new tickets, mentions and
        // assignments for the team; the team's answers for a business.
        const list = (r) => (r.status === 'fulfilled' ? (Array.isArray(r.value.data?.alerts) ? r.value.data.alerts : (Array.isArray(r.value.data) ? r.value.data : [])) : []);
        let main;
        let support;
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
        if (!cancelled) setAlerts(merged);
      } catch (_e) { /* silent */ }
      finally { if (!cancelled) setLoading(false); }
    };
    load();
    const id = setInterval(load, 5 * 60 * 1000);
    return () => { cancelled = true; clearInterval(id); };
  }, [branchId, platformAdmin]);

  // Account info — load once. Tenant name + branches for the dropdown header.
  // A platform admin has no shop of their own: these would only answer 403.
  useEffect(() => {
    if (platformAdmin) return undefined;
    let cancelled = false;
    (async () => {
      try {
        const t = await ownerAPI.getTenant();
        if (!cancelled) setAccountName(t.data?.name || 'Mon compte');
      } catch (_e) { /* silent */ }
      try {
        const b = await ownerAPI.getBranches();
        const all = Array.isArray(b.data) ? b.data : (b.data?.branches || []);
        // An administrateur or a manager: its own establishments only.
        const mine = Array.isArray(user?.branch_ids) && user?.role !== 'business_owner' ? user.branch_ids : null;
        if (!cancelled) setStores(mine ? all.filter((x) => mine.includes(x.id)) : all);
      } catch (_e) { /* silent */ }
    })();
    return () => { cancelled = true; };
  }, [platformAdmin, user?.role, user?.branch_ids]); // eslint-disable-line react-hooks/exhaustive-deps

  // Click-outside to close
  useEffect(() => {
    if (!open) return undefined;
    const handler = (e) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const shown = alerts.filter((a) => !hiddenIds.has(sig(a)));
  const hiddenCount = alerts.length - shown.length;
  const isUnread = (a) => !readIds.has(sig(a));
  const unreadCount = shown.filter(isUnread).length;

  const markRead = (list) => {
    const next = new Set(readIds);
    list.forEach((a) => next.add(sig(a)));
    setReadIds(next); saveSet(READ_KEY, next);
  };
  const hide = (a) => {
    const next = new Set(hiddenIds); next.add(sig(a));
    setHiddenIds(next); saveSet(HIDDEN_KEY, next);
    markRead([a]);
  };
  const showHidden = () => { setHiddenIds(new Set()); saveSet(HIDDEN_KEY, new Set()); };
  // An alert is read once the owner acts on it — opens it or one of its links.
  const go = (a, href) => {
    if (!href) return;
    markRead([a]);
    setOpen(false);
    navigate(href);
  };

  return (
    <div ref={wrapperRef} className="relative">
      {/* Soft pulsing halo on unread — only when there's something to look at,
          otherwise the bell sits quiet so it doesn't fight for attention. */}
      {unreadCount > 0 && (
        <style>{`
          @keyframes ftBellPulse {
            0%, 100% { box-shadow: 0 0 0 0 rgba(20,80,184,0.45), 0 4px 14px -4px rgba(20,80,184,0.55); }
            50%      { box-shadow: 0 0 0 6px rgba(20,80,184,0.08), 0 4px 14px -4px rgba(20,80,184,0.55); }
          }
        `}</style>
      )}
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="relative w-10 h-10 rounded-[12px] flex items-center justify-center transition-all hover:scale-105"
        style={{
          // The FidClic logo's blue tile, like the account icon beside it.
          background: 'linear-gradient(135deg, #1F63E0 0%, #1450B8 100%)',
          boxShadow: unreadCount > 0
            ? '0 4px 14px -4px rgba(20,80,184,0.55)'
            : '0 8px 16px -10px rgba(20,80,184,0.8)',
          animation: unreadCount > 0 ? 'ftBellPulse 2.4s ease-in-out infinite' : 'none',
        }}
        aria-label={`Notifications — ${unreadCount} non lue${unreadCount > 1 ? 's' : ''}`}
        title={unreadCount > 0 ? `${unreadCount} alerte${unreadCount > 1 ? 's' : ''} non lue${unreadCount > 1 ? 's' : ''}` : 'Aucune nouvelle alerte'}
      >
        {/* A literal colour, not currentColor: the toolbar's text rule (index.css,
            main:has(...) > div:first-child *) would repaint the strokes slate. */}
        <Bell size={18} color="#FFFFFF" fill="#FFFFFF" strokeWidth={2.2} />
        {unreadCount > 0 && (
          <span
            className="absolute -top-1.5 -right-1.5 min-w-[20px] h-5 px-1.5 rounded-full text-[10px] font-bold flex items-center justify-center"
            style={{
              background: '#F8B008',
              color: '#0B1C3F',
              border: '1.5px solid #FFFFFF',
              boxShadow: '0 2px 4px rgba(11,28,63,0.25)',
            }}
          >
            {unreadCount > 9 ? '9+' : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div
          className="absolute right-0 mt-2 w-[420px] max-w-[calc(100vw-24px)] rounded-2xl border z-50 overflow-hidden"
          style={{ borderColor: '#E6EEFB', background: '#FFFFFF', boxShadow: '0 24px 48px -20px rgba(11,28,63,.35)' }}
        >
          {/* Account headline — the franchise/business name + every store under it */}
          <div
            className="px-4 py-3 border-b relative overflow-hidden"
            style={{ borderColor: '#E6EEFB', background: 'linear-gradient(135deg, #FFFFFF 0%, #EAF1FF 100%)', color: '#0B1C3F' }}
          >
            <div className="flex items-start justify-between gap-2 relative">
              <div className="flex-1 min-w-0">
                <p className="text-[10px] font-bold uppercase tracking-widest text-[#64748B]">Compte</p>
                <p className="text-[15px] font-bold leading-tight truncate text-[#0B1C3F]">
                  {accountName || 'Mon compte'}
                </p>
                {stores.length > 0 ? (
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {stores.slice(0, 6).map((s) => (
                      <span
                        key={s.id}
                        className="inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full"
                        style={{ background: '#FFFFFF', color: '#2F6BFF', border: '1px solid #D6E3FF' }}
                      >
                        <Building2 size={9} /> {s.name}
                      </span>
                    ))}
                    {stores.length > 6 && (
                      <span className="text-[10px] text-[#64748B] self-center">+{stores.length - 6} autres</span>
                    )}
                  </div>
                ) : (
                  <p className="text-[11px] text-[#64748B] mt-1">Boutique unique · résumé toutes boutiques</p>
                )}
              </div>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="w-7 h-7 rounded-full hover:bg-[#DCE7FF] flex items-center justify-center shrink-0"
                aria-label="Fermer"
              >
                <X size={14} style={{ color: '#475569' }} />
              </button>
            </div>
          </div>
          <div className="px-4 py-2 border-b flex items-center justify-between" style={{ borderColor: '#E6EEFB', background: '#F5F8FE' }}>
            <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: '#64748B' }}>
              {platformAdmin ? 'Alertes' : 'Alertes par boutique'}
            </p>
            {unreadCount > 0 ? (
              <button type="button" onClick={() => markRead(shown)}
                      className="text-[11px] font-semibold hover:underline" style={{ color: '#2F6BFF' }}>
                Tout marquer comme lu
              </button>
            ) : (
              <p className="text-[10px]" style={{ color: '#94A3B8' }}>Mise à jour toutes les 5 min</p>
            )}
          </div>
          <div className="max-h-[420px] overflow-y-auto">
            {loading && alerts.length === 0 ? (
              <div className="px-4 py-8 text-center text-sm" style={{ color: '#64748B' }}>
                <span>Chargement…</span>
              </div>
            ) : shown.length === 0 ? (
              <div className="px-4 py-8 text-center text-sm" style={{ color: '#64748B' }}>
                <span>Tout va bien — aucune alerte pour le moment ✨</span>
              </div>
            ) : (
              shown.map((a, i) => {
                const Icon = severityIcon(a.severity);
                const color = severityColor(a.severity);
                const unread = isUnread(a);
                const actions = actionsOf(a);
                const href = hrefOf(a);
                return (
                  <div
                    key={a.id || i}
                    data-alert={a.id}
                    role={href ? 'button' : undefined}
                    tabIndex={href ? 0 : undefined}
                    onClick={() => go(a, href)}
                    onKeyDown={(e) => { if (href && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); go(a, href); } }}
                    className={`group relative px-4 py-3 border-b last:border-b-0 transition ${href ? 'cursor-pointer hover:bg-[#F5F8FE] focus:bg-[#F5F8FE] focus:outline-none' : ''}`}
                    style={{
                      borderColor: '#EEF3FB',
                      background: unread ? `linear-gradient(90deg, ${color}0D 0%, transparent 30%)` : undefined,
                    }}
                  >
                    <div className="flex gap-3 items-start">
                      <div className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
                           style={{ background: `${color}1A` }}>
                        <Icon size={16} style={{ color }} />
                      </div>
                      <div className="flex-1 min-w-0 pr-5">
                        {a.branch_name && (
                          <span
                            className="inline-flex items-center gap-1 text-[9px] font-bold uppercase tracking-widest px-2 py-0.5 rounded-full mb-1.5"
                            style={{ background: `${color}1A`, color, border: `1px solid ${color}33` }}
                            title={`Boutique : ${a.branch_name}`}
                          >
                            <Building2 size={9} /> {a.branch_name}
                          </span>
                        )}
                        <p className="text-sm font-bold leading-tight" style={{ color: '#0B1C3F' }}>
                          {unread && <span className="mr-1.5 inline-block h-2 w-2 rounded-full align-middle" style={{ background: color }} aria-label="Non lue" />}
                          {a.title}
                        </p>
                        {a.body && (
                          <p className="text-xs mt-1 leading-snug" style={{ color: '#475569' }}>
                            {a.body}
                          </p>
                        )}
                      </div>
                    </div>
                    {!platformAdmin && (
                      <button type="button" aria-label="Masquer cette alerte" title="Masquer cette alerte"
                              onClick={(e) => { e.stopPropagation(); hide(a); }}
                              className="absolute right-2.5 top-2.5 grid h-6 w-6 place-items-center rounded-full text-[#94A3B8] opacity-60 transition hover:bg-[#EAF1FF] hover:text-[#334155] hover:opacity-100 group-hover:opacity-100">
                        <X size={13} />
                      </button>
                    )}
                    {actions.length > 0 && (
                      <div className="mt-2 ml-12 flex items-center gap-2 flex-wrap">
                        {actions.map((x, k) => {
                          const primary = x.kind === 'campaign' || (actions.length === 1);
                          const XIcon = x.kind === 'customers' ? Users : x.kind === 'campaign' ? Send : null;
                          return (
                            <button key={k} type="button"
                                    onClick={(e) => { e.stopPropagation(); go(a, x.href); }}
                                    className={`inline-flex items-center gap-1 text-[11px] font-semibold rounded-lg px-2.5 py-1 transition ${primary ? 'text-white hover:bg-[#2559DB]' : 'hover:bg-[#EAF1FF]'}`}
                                    // Literal colours: the toolbar's text rule (index.css) repaints classes.
                                    style={primary ? { background: '#2F6BFF', border: '1px solid #2F6BFF', color: '#FFFFFF' }
                                      : { background: '#FFFFFF', color: '#2F6BFF', border: '1px solid #D6E3FF' }}>
                              {XIcon && <XIcon size={11} color={primary ? '#FFFFFF' : '#2F6BFF'} />} {x.label}
                              {primary && <ChevronRight size={11} color="#FFFFFF" style={{ opacity: 0.8 }} />}
                            </button>
                          );
                        })}
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>
          {alerts.length > 0 && (
            <div className="px-4 py-2 border-t text-center" style={{ borderColor: '#E6EEFB', background: '#F5F8FE' }}>
              <p className="text-[10.5px]" style={{ color: '#64748B' }}>
                {shown.length > 0 && <span>Cliquez sur une alerte pour agir.</span>}
                {hiddenCount > 0 && (
                  <>
                    {shown.length > 0 && ' · '}
                    <button type="button" onClick={showHidden} className="font-semibold hover:underline" style={{ color: '#2F6BFF' }}>
                      Réafficher {hiddenCount} alerte{hiddenCount > 1 ? 's' : ''} masquée{hiddenCount > 1 ? 's' : ''}
                    </button>
                  </>
                )}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default NotificationBell;
