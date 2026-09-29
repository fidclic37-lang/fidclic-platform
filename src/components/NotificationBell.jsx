/**
 * NotificationBell — header bell with unread count + dropdown.
 *
 * Pulls from the existing /api/owner/insights/alerts endpoint (smart alerts).
 * For multi-store franchises, alerts follow the establishment menu: the
 * chosen establishment, or every establishment the account covers.
 *
 * "Unread" is tracked in localStorage by alert ID hash. When the user opens
 * the dropdown, all currently-shown alerts are marked read.
 */
import React, { useEffect, useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Bell, AlertTriangle, TrendingDown, TrendingUp, Sparkles, X, Building2, Users, Send, Cake, ChevronRight } from 'lucide-react';
import api, { ownerAPI } from '../lib/api';
import { useBranch } from '../contexts/BranchContext';
import { useAuth } from '../contexts/AuthContext';

const STORAGE_KEY = 'ft_read_alerts_v1';

const loadReadIds = () => {
  try {
    return new Set(JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]'));
  } catch { return new Set(); }
};
const saveReadIds = (set) => {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify([...set])); } catch { /* ignore */ }
};

const severityIcon = (severity) => {
  if (severity === 'critical') return AlertTriangle;
  if (severity === 'warning')  return TrendingDown;
  if (severity === 'positive') return TrendingUp;
  return Sparkles;
};
const severityColor = (severity) => {
  if (severity === 'critical') return '#B85C38';
  if (severity === 'warning')  return '#E3A869';
  if (severity === 'positive') return '#4A5D23';
  return '#B85C38';
};

// Resolve an alert into "Voir clients" + "Envoyer campagne" navigation
// targets based on its type/title keywords. Each alert in the dropdown
// becomes a real to-do item the owner can act on in two clicks.
const resolveAlertActions = (alert) => {
  const title = (alert.title || '').toLowerCase();
  const type = (alert.type || alert.category || '').toLowerCase();
  // Birthday flow
  if (type.includes('birthday') || title.includes('anniversaire') || title.includes('birthday')) {
    return {
      icon: Cake,
      customersUrl: '/dashboard/customers?has_birthday_this_month=true',
      campaignUrl: '/dashboard/campaigns?preset_name=' + encodeURIComponent('Joyeux anniversaire') +
        '&preset_content=' + encodeURIComponent('Joyeux anniversaire {first_name} ! Une attention vous attend chez {business_name}.'),
      campaignLabel: 'Envoyer un vœu',
    };
  }
  // At risk / about to lose / inactif
  if (type.includes('at_risk') || type.includes('inactive') || title.includes('risque') || title.includes('inactif') || title.includes('point de partir')) {
    return {
      icon: Users,
      customersUrl: '/dashboard/customers?inactive_days_min=14&inactive_days_max=29',
      campaignUrl: '/dashboard/campaigns?preset_name=' + encodeURIComponent('Vous nous manquez') +
        '&preset_content=' + encodeURIComponent('{first_name}, ça fait un moment ! Une attention vous attend chez {business_name}.'),
      campaignLabel: 'Envoyer "We miss you"',
    };
  }
  // New customers
  if (type.includes('new') || title.includes('nouveau') || title.includes('nouveaux')) {
    return {
      icon: Users,
      customersUrl: '/dashboard/customers?created_within_days=7',
      campaignUrl: '/dashboard/campaigns?preset_name=' + encodeURIComponent('Bienvenue') +
        '&preset_content=' + encodeURIComponent('Bienvenue {first_name} ! Une attention vous attend lors de votre prochain passage.'),
      campaignLabel: 'Envoyer Bienvenue',
    };
  }
  // VIP / loyal segment
  if (type.includes('vip') || type.includes('loyal') || title.includes('vip') || title.includes('loyal')) {
    return {
      icon: Users,
      customersUrl: '/dashboard/customers?tier=vip',
      campaignUrl: '/dashboard/campaigns?preset_name=' + encodeURIComponent('Merci VIP') +
        '&preset_content=' + encodeURIComponent('{first_name}, un grand merci pour votre fidélité. Une attention exclusive vous attend.'),
      campaignLabel: 'Récompenser les VIP',
    };
  }
  // Default — just open Customers
  return {
    icon: Users,
    customersUrl: '/dashboard/customers',
    campaignUrl: '/dashboard/campaigns',
    campaignLabel: 'Envoyer une campagne',
  };
};

const NotificationBell = ({ platformAdmin = false }) => {
  const navigate = useNavigate();
  const { branchId } = useBranch();
  const { user } = useAuth();
  const [alerts, setAlerts] = useState([]);
  const [readIds, setReadIds] = useState(loadReadIds);
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
        // Try multi-store first; fall back to single-tenant if it 404s
        let res;
        try {
          res = await api.get('/owner/insights/alerts/multi-store');
        } catch (_e) {
          res = await ownerAPI.getProactiveAlerts({});
        }
        if (!cancelled) setAlerts(Array.isArray(res.data?.alerts) ? res.data.alerts : (res.data || []));
      } catch (_e) { /* silent */ }
      finally { if (!cancelled) setLoading(false); }
    };
    load();
    const id = setInterval(load, 5 * 60 * 1000);
    return () => { cancelled = true; clearInterval(id); };
  }, [branchId]);

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

  const unreadAlerts = alerts.filter((a) => !readIds.has(a.id || a.title));
  const unreadCount = unreadAlerts.length;

  const markAllRead = () => {
    const next = new Set(readIds);
    alerts.forEach((a) => next.add(a.id || a.title));
    setReadIds(next);
    saveReadIds(next);
  };

  const handleOpen = () => {
    setOpen(true);
    // After 600ms, mark visible alerts as read so the dot doesn't disappear instantly
    setTimeout(markAllRead, 600);
  };

  return (
    <div ref={wrapperRef} className="relative">
      {/* Soft pulsing halo on unread — only when there's something to look at,
          otherwise the bell sits quiet so it doesn't fight for attention. */}
      {unreadCount > 0 && (
        <style>{`
          @keyframes ftBellPulse {
            0%, 100% { box-shadow: 0 0 0 0 rgba(184,92,56,0.55), 0 4px 14px -4px rgba(184,92,56,0.55); }
            50%      { box-shadow: 0 0 0 6px rgba(184,92,56,0.10), 0 4px 14px -4px rgba(184,92,56,0.55); }
          }
        `}</style>
      )}
      <button
        type="button"
        onClick={() => (open ? setOpen(false) : handleOpen())}
        className="relative w-11 h-11 rounded-full flex items-center justify-center transition-all hover:scale-105"
        style={{
          background: 'linear-gradient(135deg, #B85C38 0%, #E3A869 100%)',
          border: '2px solid color-mix(in srgb, var(--flc-card, #FFFFFF) 85%, transparent)',
          boxShadow: unreadCount > 0
            ? '0 4px 14px -4px rgba(184,92,56,0.55)'
            : '0 2px 8px -2px rgba(184,92,56,0.35)',
          animation: unreadCount > 0 ? 'ftBellPulse 2.4s ease-in-out infinite' : 'none',
        }}
        aria-label={`Notifications — ${unreadCount} unread`}
        title={unreadCount > 0 ? `${unreadCount} alerte(s) non lue(s) · toutes les boutiques` : 'Aucune alerte · toutes les boutiques'}
      >
        <Bell size={18} style={{ color: 'white' }} fill="white" strokeWidth={2.2} />
        {unreadCount > 0 && (
          <span
            className="absolute -top-1.5 -right-1.5 min-w-[20px] h-5 px-1.5 rounded-full text-[10px] font-bold flex items-center justify-center"
            style={{
              background: 'var(--flc-card, #FFFFFF)',
              color: 'var(--flc-accent, #B85C38)',
              border: '1.5px solid #B85C38',
              boxShadow: '0 2px 4px rgba(184,92,56,0.4)',
            }}
          >
            {unreadCount > 9 ? '9+' : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div
          className="absolute right-0 mt-2 w-[380px] rounded-2xl border shadow-2xl z-50 overflow-hidden"
          style={{ borderColor: 'var(--flc-line, #EFE9E0)', background: 'var(--flc-card, #FFFFFF)' }}
        >
          {/* Account headline — the franchise/business name + every store under it */}
          <div
            className="px-4 py-3 border-b relative overflow-hidden"
            style={{
              borderColor: '#EFE9E0',
              background: 'linear-gradient(135deg, #171412 0%, #2A1C2E 100%)',
              color: 'white',
            }}
          >
            <div className="flex items-start justify-between gap-2 relative">
              <div className="flex-1 min-w-0">
                <p className="text-[9px] font-bold uppercase tracking-widest opacity-70">Compte</p>
                <p className="text-base font-bold leading-tight truncate"
                   style={{ fontFamily: 'Cormorant Garamond' }}>
                  {accountName || 'Mon compte'}
                </p>
                {stores.length > 0 ? (
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {stores.slice(0, 6).map((s) => (
                      <span
                        key={s.id}
                        className="inline-flex items-center gap-1 text-[9px] font-bold px-1.5 py-0.5 rounded-full"
                        style={{ background: 'rgba(227,168,105,0.18)', color: '#FFD7A8', border: '1px solid rgba(227,168,105,0.35)' }}
                      >
                        <Building2 size={9} /> {s.name}
                      </span>
                    ))}
                    {stores.length > 6 && (
                      <span className="text-[9px] opacity-70 self-center">+{stores.length - 6} autres</span>
                    )}
                  </div>
                ) : (
                  <p className="text-[10px] opacity-70 mt-1">Boutique unique · résumé toutes boutiques</p>
                )}
              </div>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="w-7 h-7 rounded-full hover:bg-white/10 flex items-center justify-center shrink-0"
                aria-label="Close"
              >
                <X size={14} style={{ color: 'white' }} />
              </button>
            </div>
          </div>
          <div className="px-4 py-2 border-b flex items-center justify-between" style={{ borderColor: 'var(--flc-line, #EFE9E0)', background: 'var(--flc-paper2, #FAFAF8)' }}>
            <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: '#8D857D' }}>
              Alertes par boutique
            </p>
            <p className="text-[9px]" style={{ color: '#A8A29E' }}>
              MAJ 5 min
            </p>
          </div>
          <div className="max-h-[420px] overflow-y-auto">
            {loading && alerts.length === 0 ? (
              <div className="px-4 py-8 text-center text-sm" style={{ color: '#8D857D' }}>
                Chargement…
              </div>
            ) : alerts.length === 0 ? (
              <div className="px-4 py-8 text-center text-sm" style={{ color: '#8D857D' }}>
                Tout va bien — aucune alerte aujourd'hui ✨
              </div>
            ) : (
              alerts.map((a, i) => {
                const Icon = severityIcon(a.severity);
                const color = severityColor(a.severity);
                const isUnread = !readIds.has(a.id || a.title);
                const actions = resolveAlertActions(a);
                return (
                  <div
                    key={a.id || i}
                    className="px-4 py-3 border-b last:border-b-0"
                    style={{
                      borderColor: '#F5F1EB',
                      background: isUnread ? `linear-gradient(90deg, ${color}0F 0%, transparent 30%)` : 'white',
                    }}
                  >
                    <div className="flex gap-3 items-start">
                      <div className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
                           style={{ background: `${color}1A` }}>
                        <Icon size={16} style={{ color }} />
                      </div>
                      <div className="flex-1 min-w-0">
                        {a.branch_name && (
                          <span
                            className="inline-flex items-center gap-1 text-[9px] font-bold uppercase tracking-widest px-2 py-0.5 rounded-full mb-1.5"
                            style={{
                              background: `${color}1A`,
                              color: color,
                              border: `1px solid ${color}33`,
                            }}
                            title={`Boutique : ${a.branch_name}`}
                          >
                            <Building2 size={9} /> {a.branch_name}
                          </span>
                        )}
                        <p className="text-sm font-bold leading-tight" style={{ color: '#171412' }}>
                          {a.title}
                        </p>
                        {a.body && (
                          <p className="text-xs mt-1 leading-snug" style={{ color: '#57504A' }}>
                            {a.body}
                          </p>
                        )}
                      </div>
                      {isUnread && (
                        <span className="w-2 h-2 rounded-full mt-1.5 shrink-0" style={{ background: color }} />
                      )}
                    </div>
                    {/* Action row — Voir clients / Envoyer campagne, resolved by alert type */}
                    <div className="mt-2 ml-12 flex items-center gap-2 flex-wrap">
                      <button
                        type="button"
                        onClick={() => { setOpen(false); navigate(actions.customersUrl); }}
                        className="inline-flex items-center gap-1 text-[11px] font-semibold rounded-full px-2.5 py-1 transition"
                        style={{ background: 'var(--flc-paper2, #F5F4F1)', color: 'var(--flc-ink, #171412)', border: '1px solid var(--flc-line, #E9E5E0)' }}
                      >
                        <Users size={11} /> Voir les clients
                      </button>
                      <button
                        type="button"
                        onClick={() => { setOpen(false); navigate(actions.campaignUrl); }}
                        className="inline-flex items-center gap-1 text-[11px] font-semibold rounded-full px-2.5 py-1 text-white transition"
                        style={{ background: color, border: `1px solid ${color}` }}
                      >
                        <Send size={11} /> {actions.campaignLabel}
                        <ChevronRight size={11} style={{ opacity: 0.8 }} />
                      </button>
                    </div>
                  </div>
                );
              })
            )}
          </div>
          {alerts.length > 0 && (
            <div className="px-4 py-2 border-t text-center" style={{ borderColor: 'var(--flc-line, #EFE9E0)', background: 'var(--flc-paper2, #FAFAF8)' }}>
              <p className="text-[10px]" style={{ color: '#8D857D' }}>
                {alerts.length} résumé{alerts.length > 1 ? 's' : ''} · Cliquez sur une carte pour voir le détail
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default NotificationBell;
