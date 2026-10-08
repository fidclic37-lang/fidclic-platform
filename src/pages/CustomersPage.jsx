import React, { useState, useEffect } from 'react';
import { Search, UserCircle, Filter, MapPin, Award, Hash, X, Download, Map, Clock, Gift, Calendar, TrendingDown, Zap, Megaphone, Smartphone, CreditCard, Trash2, Repeat } from 'lucide-react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import api, { ownerAPI } from '../lib/api';
import TierBadge from '../components/TierBadge';
import { PageHeader, C as C_PS } from '../components/PageShell';
import LoadingDistraction from '../components/LoadingDistraction';
import { useBranch } from '../contexts/BranchContext';

// Pre-built segments that power one-click targeting. Server-side fields map to
// the extended GET /api/owner/customers filters.
// NOTE: the big_spenders pill is special — its label and behaviour come from
// the tenant's configured big-spender rule in Settings. See the runtime
// label override + dedicated /api/owner/big-spenders fetch below.
const QUICK_SEGMENTS = [
  { key: 'vip',          label: 'VIPs',                 icon: Award,      serverParams: { tier: 'vip' } },
  { key: 'big_spenders', label: 'Big spenders',         icon: Zap,        serverParams: null /* uses /api/owner/big-spenders */ },
  { key: 'loyal_5',      label: 'Loyal (5+ visits)',    icon: Award,      serverParams: { min_visits: 5 } },
  { key: 'birthday',     label: 'Birthday this month',  icon: Calendar,   serverParams: { has_birthday_this_month: true } },
  { key: 'one_and_done', label: 'One-and-done',         icon: TrendingDown, serverParams: { max_visits: 1 } },
  { key: 'dormant',      label: 'Dormant (30d+)',       icon: Clock,      serverParams: { inactive_days_min: 30 } },
  { key: 'at_risk',      label: 'At risk (14–29d)',     icon: Clock,      serverParams: { inactive_days_min: 14, inactive_days_max: 29 } },
  { key: 'lunch',        label: 'Lunch regulars',       icon: Clock,      serverParams: { time_segment: 'lunch' } },
  { key: 'evening',      label: 'Evening regulars',     icon: Clock,      serverParams: { time_segment: 'evening' } },
  { key: 'weekend',      label: 'Weekend regulars',     icon: Calendar,   serverParams: { time_segment: 'weekend' } },
  { key: 'weekday',      label: 'Weekday regulars',     icon: Calendar,   serverParams: { time_segment: 'weekday' } },
  { key: 'redeemed',     label: 'Has redeemed reward',  icon: Gift,       serverParams: { redeemed_reward: true } },
];

// URL param → human-readable banner label + icon. Drives the "filter active"
// pill at the top of the page when a tile from the dashboard navigated here
// with ?wallet_state=active (etc.).
const URL_FILTER_LABELS = {
  wallet_state: {
    active:       { label: 'Active wallet cards',           icon: Smartphone, color: '#6FA89C' },
    deleted:      { label: 'Cards deleted by customer',     icon: Trash2,     color: '#F08C7A' },
    never_added:  { label: 'Customers without wallet card', icon: CreditCard, color: '#E3A869' },
  },
  loyalty_bucket: {
    loyal:        { label: 'Loyal customers',               icon: Award,      color: '#B85C38' },
    regular:      { label: 'Regular customers',             icon: Repeat,     color: '#D77FA0' },
  },
};

export default function CustomersPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { branchId } = useBranch();
  const [allCustomers, setAllCustomers] = useState([]);
  const [filteredCustomers, setFilteredCustomers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  // The "filter pill" we show at the top when arriving via a Dashboard tile
  const [urlFilterPill, setUrlFilterPill] = useState(null);   // { label, icon, color, clear }

  // Filter state. Initialize searchQuery from URL ?q= or ?barcode_id= so
  // the global toolbar search lands the user with their query pre-filled.
  const [searchQuery, setSearchQuery] = useState(() => {
    try {
      const sp = new URLSearchParams(window.location.search);
      return sp.get('q') || sp.get('barcode_id') || '';
    } catch { return ''; }
  });
  // Also re-sync if URL changes (back/forward, or a fresh search submit).
  React.useEffect(() => {
    const q = searchParams.get('q') || searchParams.get('barcode_id') || '';
    if (q) setSearchQuery(q);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);
  const [tierFilter, setTierFilter] = useState('All');
  const [minVisits, setMinVisits] = useState('');
  const [maxVisits, setMaxVisits] = useState('');
  const [minAmountPaid, setMinAmountPaid] = useState('');
  const [postalCode, setPostalCode] = useState('');
  const [minTotalSpent, setMinTotalSpent] = useState('');
  const [sourceFilter, setSourceFilter] = useState('All');
  // Subscription filter — added to target customers who can/can't receive push.
  // 'All' | 'Subscribed' | 'NotSubscribed'
  const [subscriptionFilter, setSubscriptionFilter] = useState('All');
  // Map of customer_id → bool (has push subscription) — fetched once on mount.
  const [subscriptionMap, setSubscriptionMap] = useState({});
  const [activeQuickSegment, setActiveQuickSegment] = useState(null); // which pill is pressed
  // Saved segments (owner's custom combos)
  const [savedSegments, setSavedSegments] = useState([]);
  const [savingSegment, setSavingSegment] = useState(false);
  const [segmentName, setSegmentName] = useState('');

  // Re-fetch customers with the current server-side filter set. Used both on
  // mount (no filters) and whenever a quick-pick segment toggles.
  const fetchCustomers = async (serverParams = {}) => {
    try {
      setLoading(true);
      // Inject the global branch filter — picking a branch on the layout bar
      // automatically filters the customer list across the platform.
      const params = { ...serverParams };
      if (branchId && !params.branch_id) params.branch_id = branchId;
      const res = await ownerAPI.getCustomers(params);
      setAllCustomers(res.data || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // Big-spender definition lives in Settings (tier_definitions). Loaded here
  // so the pill label and behaviour stay in sync with whatever the owner saved.
  const [bigSpenderDef, setBigSpenderDef] = useState(null);

  // Read URL search params and convert them to server-side filter params.
  // Used when the user arrives via a Dashboard tile (e.g. "Active Cards" →
  // /dashboard/customers?wallet_state=active).
  const readUrlFilters = () => {
    const out = {};
    let pill = null;
    const ws = searchParams.get('wallet_state');
    if (ws && URL_FILTER_LABELS.wallet_state[ws]) {
      out.wallet_state = ws;
      pill = { ...URL_FILTER_LABELS.wallet_state[ws], clear: () => clearUrlFilter('wallet_state') };
    }
    const lb = searchParams.get('loyalty_bucket');
    if (lb && URL_FILTER_LABELS.loyalty_bucket[lb]) {
      out.loyalty_bucket = lb;
      pill = pill || { ...URL_FILTER_LABELS.loyalty_bucket[lb], clear: () => clearUrlFilter('loyalty_bucket') };
    }
    const tier = searchParams.get('tier');
    if (tier) {
      out.tier = tier;
      pill = pill || {
        label: `Tier · ${tier.charAt(0).toUpperCase() + tier.slice(1)}`,
        icon: Award, color: '#B85C38',
        clear: () => clearUrlFilter('tier'),
      };
    }
    const cwd = searchParams.get('created_within_days');
    if (cwd) {
      out.created_within_days = parseInt(cwd, 10);
      pill = pill || {
        label: `Joined in last ${cwd} days`,
        icon: Calendar, color: '#5B8DEF',
        clear: () => clearUrlFilter('created_within_days'),
      };
    }
    return { params: out, pill };
  };

  const clearUrlFilter = (key) => {
    const next = new URLSearchParams(searchParams);
    next.delete(key);
    setSearchParams(next, { replace: true });
    // The effect below picks up the change and re-fetches.
  };

  // Re-run on EVERY change to the URL search string OR the global branch
  // selector — both drive what the customer list filters down to.
  useEffect(() => {
    const { params, pill } = readUrlFilters();
    setUrlFilterPill(pill);
    fetchCustomers(params);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams, branchId]);

  // One-shot loaders (saved segments + big-spender def) — only on mount.
  useEffect(() => {
    (async () => {
      try {
        const r = await ownerAPI.listSavedSegments();
        setSavedSegments(r.data?.segments || []);
      } catch (_e) { /* non-fatal */ }
    })();
    (async () => {
      try {
        const r = await api.get('/owner/tier-definitions');
        setBigSpenderDef({
          min_amount: Number(r.data?.big_spender_min_amount ?? 500),
          min_avg_ticket: Number(r.data?.big_spender_min_avg_ticket ?? 0),
        });
      } catch (_e) { setBigSpenderDef({ min_amount: 500, min_avg_ticket: 0 }); }
    })();
  }, []);

  const applyQuickSegment = async (seg) => {
    // Tap the same pill again to clear it — restores full list.
    if (activeQuickSegment === seg.key) {
      setActiveQuickSegment(null);
      fetchCustomers();
      return;
    }
    setActiveQuickSegment(seg.key);
    // Special case: big_spenders uses the configured definition from Settings
    // rather than a hardcoded threshold.
    if (seg.key === 'big_spenders') {
      try {
        setLoading(true);
        const r = await api.get('/owner/big-spenders');
        setAllCustomers(r.data?.big_spenders || []);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
      return;
    }
    fetchCustomers(seg.serverParams || {});
  };

  // Persist the current filter combo as a named segment.
  const saveCurrentAsSegment = async () => {
    const name = (segmentName || '').trim() || window.prompt('Name this segment (e.g. "VIPs in Paris"):');
    if (!name) return;
    try {
      setSavingSegment(true);
      const filters = {
        tier: tierFilter !== 'All' ? tierFilter.toLowerCase() : undefined,
        min_visits: minVisits ? Number(minVisits) : undefined,
        max_visits: maxVisits ? Number(maxVisits) : undefined,
        min_amount: minAmountPaid ? Number(minAmountPaid) : undefined,
        postal_codes: postalCode ? postalCode.split(',').map(s => s.trim()).filter(Boolean) : undefined,
        source: sourceFilter !== 'All' ? sourceFilter : undefined,
        quick_segment: activeQuickSegment || undefined,
      };
      const res = await ownerAPI.createSavedSegment({ name, filters });
      setSavedSegments((cur) => [res.data, ...cur]);
      setSegmentName('');
    } catch (e) {
      alert('Failed to save: ' + (e?.response?.data?.detail || e.message));
    } finally {
      setSavingSegment(false);
    }
  };

  const loadSavedSegment = (seg) => {
    const f = seg.filters || {};
    setTierFilter(f.tier ? f.tier.charAt(0).toUpperCase() + f.tier.slice(1) : 'All');
    setMinVisits(f.min_visits ?? '');
    setMaxVisits(f.max_visits ?? '');
    setMinAmountPaid(f.min_amount ?? '');
    setPostalCode(Array.isArray(f.postal_codes) ? f.postal_codes.join(',') : '');
    setSourceFilter(f.source || 'All');
    if (f.quick_segment) {
      const q = QUICK_SEGMENTS.find(s => s.key === f.quick_segment);
      if (q) applyQuickSegment(q); else fetchCustomers();
    } else {
      setActiveQuickSegment(null);
      fetchCustomers();
    }
  };

  const deleteSavedSegment = async (id) => {
    if (!window.confirm('Delete this saved segment?')) return;
    try {
      await ownerAPI.deleteSavedSegment(id);
      setSavedSegments((cur) => cur.filter(s => s.id !== id));
    } catch (e) { alert('Failed: ' + (e?.response?.data?.detail || e.message)); }
  };

  // Send a campaign to whoever is currently filtered on the page.
  const sendCampaignToFiltered = () => {
    if (!filteredCustomers.length) { alert('No customers in the current view.'); return; }
    if (!window.confirm(`Send a campaign to ${filteredCustomers.length} filtered customer(s)?`)) return;
    const activeLabel = activeQuickSegment
      ? (QUICK_SEGMENTS.find(s => s.key === activeQuickSegment)?.label || 'Segment')
      : 'Ciblage clients';
    try {
      sessionStorage.setItem('campaignHandoff', JSON.stringify({
        customer_ids: filteredCustomers.map(c => c.id),
        // Ship one real customer so the composer's phone preview can resolve
        // {first_name} etc. instead of falling back to the generic sample.
        preview_customer: filteredCustomers[0] || null,
        suggested_name: activeLabel,
        suggested_message: 'Bonjour {first_name}, une attention pour vous chez {business_name} — à très vite !',
        source: 'push',
      }));
    } catch (_e) {}
    navigate('/dashboard/campaigns');
  };

  // Apply filters
  useEffect(() => {
    let filtered = [...allCustomers];

    // Search filter (name, email, barcode_id)
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      filtered = filtered.filter(
        (customer) =>
          customer.name.toLowerCase().includes(query) ||
          customer.email.toLowerCase().includes(query) ||
          customer.barcode_id.toLowerCase().includes(query)
      );
    }

    // Tier filter (case-insensitive — backend uses lowercase, UI uses Title-case)
    if (tierFilter !== 'All') {
      const t = tierFilter.toLowerCase();
      filtered = filtered.filter((customer) => (customer.tier || '').toLowerCase() === t);
    }

    // Min visits
    if (minVisits !== '') {
      const min = parseInt(minVisits, 10);
      filtered = filtered.filter((customer) => customer.visits >= min);
    }

    // Max visits
    if (maxVisits !== '') {
      const max = parseInt(maxVisits, 10);
      filtered = filtered.filter((customer) => customer.visits <= max);
    }

    // Min amount paid
    if (minAmountPaid !== '') {
      const min = parseFloat(minAmountPaid);
      filtered = filtered.filter((customer) => customer.total_amount_paid >= min);
    }

    // Postal code filter (supports comma-separated values)
    if (postalCode.trim()) {
      const codes = postalCode.split(',').map((code) => code.trim().toLowerCase());
      filtered = filtered.filter((customer) =>
        codes.includes(customer.postal_code.toLowerCase())
      );
    }

    // Min total spent
    if (minTotalSpent !== '') {
      const min = parseFloat(minTotalSpent);
      filtered = filtered.filter((customer) => (customer.total_amount_paid || 0) >= min);
    }

    // Source filter — only the 4 allowed sources
    if (sourceFilter !== 'All') {
      const sourceMap = {
        'QR in store': 'qr_store',
        'Instagram': 'instagram',
        'Facebook': 'facebook',
        'TikTok': 'tiktok',
      };
      const sourceValue = sourceMap[sourceFilter];
      filtered = filtered.filter((customer) => customer.acquisition_source === sourceValue);
    }

    // Subscription filter — push notification status (drives re-enable campaigns).
    if (subscriptionFilter !== 'All') {
      const wantSubscribed = subscriptionFilter === 'Subscribed';
      filtered = filtered.filter((customer) => {
        const has = !!subscriptionMap[customer.id];
        return wantSubscribed ? has : !has;
      });
    }

    setFilteredCustomers(filtered);
  }, [allCustomers, searchQuery, tierFilter, minVisits, maxVisits, minAmountPaid, postalCode, minTotalSpent, sourceFilter, subscriptionFilter, subscriptionMap]);

  // Fetch the subscription map once on mount. Backend exposes per-customer
  // subscription status via /api/owner/notifications/subscription-map.
  // If endpoint doesn't exist (older backend), filter just shows all.
  useEffect(() => {
    let alive = true;
    fetch('/api/owner/notifications/subscription-map', {
      headers: (() => {
        const tok = (typeof localStorage !== 'undefined') ? localStorage.getItem('fdt_token') : null;
        return tok ? { Authorization: `Bearer ${tok}` } : {};
      })(),
    })
      .then((r) => r.ok ? r.json() : null)
      .then((d) => { if (alive && d?.map) setSubscriptionMap(d.map); })
      .catch(() => { /* silent — filter is just not useful */ });
    return () => { alive = false; };
  }, []);

  const clearFilters = () => {
    setSearchQuery('');
    setTierFilter('All');
    setMinVisits('');
    setMaxVisits('');
    setMinAmountPaid('');
    setPostalCode('');
    setMinTotalSpent('');
    setSourceFilter('All');
  };

  const getInitials = (name) => {
    return name
      .split(' ')
      .map((n) => n[0])
      .join('')
      .toUpperCase()
      .slice(0, 2);
  };

  const getRelativeDate = (dateString) => {
    if (!dateString) return 'Never';

    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now - date;
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

    if (diffDays === 0) return 'Today';
    if (diffDays === 1) return 'Yesterday';
    if (diffDays < 7) return `${diffDays} days ago`;
    if (diffDays < 30) return `${Math.floor(diffDays / 7)} weeks ago`;
    if (diffDays < 365) return `${Math.floor(diffDays / 30)} months ago`;
    return `${Math.floor(diffDays / 365)} years ago`;
  };

  const getTierBadgeColor = (tier) => {
    switch (tier) {
      case 'Gold':
        return { bg: '#E3A86920', text: '#B85C38' };
      case 'Silver':
        return { bg: '#F3F3F2', text: '#57504A' };
      case 'Bronze':
        return { bg: 'var(--flc-paper2, #F5F4F1)', text: 'var(--flc-ink3, #57504A)' };
      default:
        return { bg: '#E9E5E0', text: '#57504A' };
    }
  };

  const getSourceBadge = (source) => {
    const badges = {
      'qr_store': { emoji: '📱', label: 'QR in store', bg: 'color-mix(in srgb, var(--flc-accent, #C73E2C) 10%, var(--flc-card, #FFFFFF))' },
      'instagram': { emoji: '📸', label: 'Instagram', bg: 'color-mix(in srgb, var(--flc-risk, #C22F45) 10%, var(--flc-card, #FFFFFF))' },
      'facebook': { emoji: '👥', label: 'Facebook', bg: 'color-mix(in srgb, var(--flc-info, #3568B8) 10%, var(--flc-card, #FFFFFF))' },
      'tiktok': { emoji: '🎵', label: 'TikTok', bg: 'color-mix(in srgb, var(--flc-ok, #0F8B58) 10%, var(--flc-card, #FFFFFF))' },
    };
    return badges[source] || { emoji: '—', label: '—', bg: 'var(--flc-paper2, #F3F3F2)' };
  };

  const exportToCSV = () => {
    const headers = ['Name', 'Email', 'Phone', 'Postal Code', 'Tier', 'Total Visits', 'Points', 'Total Spent', 'Source', 'Join Date'];
    const rows = filteredCustomers.map((c) => {
      const sourceBadge = getSourceBadge(c.acquisition_source);
      // Join Date — the backend customer object has `created_at`
      // (the field set when a customer joins). The previous code looked
      // for `c.join_date` which doesn't exist, so the column was always
      // blank. Accept both names so future schema renames don't break it.
      const joinedAt = c.created_at || c.join_date || c.member_since;
      return [
        c.name,
        c.email,
        c.phone || '',
        c.postal_code || '',
        c.tier || '',
        c.visits || 0,
        c.points || (c.visits || 0) * 10,
        (c.total_amount_paid || 0).toFixed(2),
        sourceBadge.label,
        joinedAt ? new Date(joinedAt).toLocaleDateString() : '',
      ];
    });

    const csv = [
      headers.join(','),
      ...rows.map((row) =>
        row
          .map((cell) => {
            if (typeof cell === 'string' && (cell.includes(',') || cell.includes('"') || cell.includes('\n'))) {
              return `"${cell.replace(/"/g, '""')}"`;
            }
            return cell;
          })
          .join(',')
      ),
    ].join('\n');

    const blob = new Blob([csv], { type: 'text/csv' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `customers_${new Date().toISOString().split('T')[0]}.csv`;
    a.click();
    window.URL.revokeObjectURL(url);
  };

  if (loading) {
    return (
      <div className="py-12 px-4">
        <LoadingDistraction title={t('customers.loading')} message={t('customers.loading')} />
      </div>
    );
  }

  if (error) {
    return (
      <div
        className="p-8"
        style={{ backgroundColor: 'var(--flc-card, #FAFAF8)' }}
      >
        <p style={{ color: '#B85C38' }}>{t('common.error')}: {error}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Database"
        title={t('customers.title')}
        description={t('customers.subtitle')}
        role="business_owner"
        actions={
          <div className="flex gap-2">
            <button
              onClick={() => window.location.href = '/dashboard/map'}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-full text-sm font-semibold text-white transition-all shadow-md hover:-translate-y-0.5"
              style={{ background: `linear-gradient(135deg, ${C_PS.ochre}, ${C_PS.terracotta})` }}
            >
              <Map size={16} /> {t('nav.customer_map')}
            </button>
            <button
              onClick={exportToCSV}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-full text-sm font-semibold transition-all hover:-translate-y-0.5"
              style={{ background: 'var(--flc-card, #FFFFFF)', border: `1px solid ${C_PS.hairline}`, color: C_PS.inkSoft }}
            >
              <Download size={16} /> {t('customers.export_csv')}
            </button>
          </div>
        }
      />

      {/* URL filter pill — visible when the user arrived from a dashboard tile */}
      {urlFilterPill && (() => {
        const Icon = urlFilterPill.icon || Filter;
        return (
          <div
            className="flex items-center justify-between gap-3 px-4 py-3 rounded-xl border-2"
            style={{
              background: `linear-gradient(135deg, white 0%, ${urlFilterPill.color}12 100%)`,
              borderColor: urlFilterPill.color + '55',
              boxShadow: `0 6px 18px -10px ${urlFilterPill.color}77`,
            }}
          >
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-lg flex items-center justify-center"
                   style={{ background: urlFilterPill.color, color: 'white' }}>
                <Icon size={16} />
              </div>
              <div>
                <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: urlFilterPill.color }}>
                  Filter applied
                </p>
                <p className="text-sm font-bold" style={{ color: '#171412' }}>
                  {urlFilterPill.label} · {filteredCustomers.length} customer{filteredCustomers.length === 1 ? '' : 's'}
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={() => urlFilterPill.clear && urlFilterPill.clear()}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold transition hover:bg-white"
              style={{ background: 'var(--flc-card, #FFFFFF)', border: `1px solid ${urlFilterPill.color}55`, color: urlFilterPill.color }}
            >
              <X size={12} /> Clear filter
            </button>
          </div>
        );
      })()}

      {/* Search Bar */}
      <div className="mb-6">
        <div
          className="flex items-center gap-3 px-4 py-3 rounded-lg border"
          style={{
            backgroundColor: 'var(--flc-paper2, #F5F4F1)',
            borderColor: 'var(--flc-line, #E9E5E0)',
          }}
        >
          <Search size={20} style={{ color: '#57504A' }} />
          <input
            type="text"
            placeholder={t('customers.search_placeholder')}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="flex-1 bg-transparent outline-none"
            style={{
              color: '#171412',
              fontFamily: 'Manrope',
              fontSize: '14px',
            }}
          />
        </div>
      </div>

      {/* Quick-pick segments — one click to isolate a marketing target */}
      <div className="mb-6 p-4 rounded-lg border bg-white" style={{ borderColor: 'var(--flc-line, #E9E5E0)' }}>
        <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
          <div className="flex items-center gap-2">
            <Zap size={18} style={{ color: '#B85C38' }} />
            <span className="font-bold text-[#171412]">Quick segments</span>
            <span className="text-xs text-[#8D857D]">One click → isolate a marketing target, then send a campaign</span>
          </div>
          <button
            onClick={sendCampaignToFiltered}
            disabled={!filteredCustomers.length}
            className="px-3 py-1.5 rounded-lg text-sm font-bold text-white flex items-center gap-2 disabled:opacity-40"
            style={{ backgroundColor: '#B85C38' }}
          >
            <Megaphone size={14} />
            Send campaign to {filteredCustomers.length}
          </button>
        </div>
        <div className="flex flex-wrap gap-2">
          {QUICK_SEGMENTS.map((seg) => {
            const Icon = seg.icon;
            const active = activeQuickSegment === seg.key;
            // Big-spenders pill: show the live threshold from Settings.
            const dynamicLabel = (seg.key === 'big_spenders' && bigSpenderDef)
              ? `Big spenders €${bigSpenderDef.min_amount}+${bigSpenderDef.min_avg_ticket > 0 ? ` (avg €${bigSpenderDef.min_avg_ticket}+)` : ''}`
              : seg.label;
            return (
              <button
                key={seg.key}
                type="button"
                onClick={() => applyQuickSegment(seg)}
                className={`px-3 py-1.5 rounded-full text-sm font-semibold flex items-center gap-1.5 border transition ${
                  active
                    ? 'bg-[#B85C38] text-white border-[#B85C38]'
                    : 'bg-white text-[#57504A] border-[#E9E5E0] hover:border-[#B85C38]'
                }`}
              >
                <Icon size={13} />
                {dynamicLabel}
              </button>
            );
          })}
          {activeQuickSegment && (
            <button
              type="button"
              onClick={() => { setActiveQuickSegment(null); fetchCustomers(); }}
              className="px-3 py-1.5 rounded-full text-sm font-semibold border border-[#E9E5E0] text-[#57504A] hover:bg-[#FEF2F0]"
            >
              <X size={12} className="inline -mt-0.5 mr-1" /> Clear
            </button>
          )}
        </div>

        {/* Saved segments — owner's custom combos */}
        <div className="mt-4 pt-3 border-t border-[#E9E5E0]">
          <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
            <span className="text-xs font-bold text-[#57504A] uppercase tracking-wider">Saved segments</span>
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={segmentName}
                onChange={(e) => setSegmentName(e.target.value)}
                placeholder="Name this filter combo…"
                className="px-2 py-1 text-xs border border-[#E9E5E0] rounded"
              />
              <button
                onClick={saveCurrentAsSegment}
                disabled={savingSegment}
                className="px-2 py-1 text-xs rounded border border-[#B85C38] text-[#B85C38] font-bold hover:bg-[#FEF2F0] disabled:opacity-40"
              >
                {savingSegment ? 'Saving…' : '+ Save current'}
              </button>
            </div>
          </div>
          {savedSegments.length === 0 ? (
            <p className="text-xs text-[#8D857D] italic">
              Tune any filter combination and click "Save current" to reuse it later.
            </p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {savedSegments.map((s) => (
                <div key={s.id} className="flex items-center gap-1 border border-[#E9E5E0] rounded-full pl-3 pr-1 py-0.5 bg-[#FAFAF8]">
                  <button onClick={() => loadSavedSegment(s)} className="text-xs font-semibold text-[#171412]">
                    {s.name}
                  </button>
                  <button onClick={() => deleteSavedSegment(s.id)} className="text-[#8D857D] hover:text-red-600 p-1" title="Delete">
                    <X size={10} />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Filter Section */}
      <div
        className="mb-6 p-4 rounded-lg border"
        style={{
          backgroundColor: 'var(--flc-paper2, #F5F4F1)',
          borderColor: 'var(--flc-line, #E9E5E0)',
        }}
      >
        <div className="flex items-center gap-2 mb-4">
          <Filter size={18} style={{ color: '#B85C38' }} />
          <span
            style={{
              color: '#171412',
              fontWeight: '600',
              fontFamily: 'Manrope',
              fontSize: '14px',
            }}
          >
            Filters
          </span>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-7 gap-4 mb-4">
          {/* Tier Filter */}
          <div>
            <label
              className="block text-sm mb-2"
              style={{
                color: '#57504A',
                fontFamily: 'Manrope',
                fontSize: '12px',
              }}
            >
              Tier
            </label>
            <select
              value={tierFilter}
              onChange={(e) => setTierFilter(e.target.value)}
              className="w-full px-3 py-2 rounded border text-sm outline-none"
              style={{
                backgroundColor: 'var(--flc-card, #FAFAF8)',
                borderColor: 'var(--flc-line, #E9E5E0)',
                color: '#171412',
                fontFamily: 'Manrope',
              }}
            >
              <option>All</option>
              <option>Bronze</option>
              <option>Silver</option>
              <option>Gold</option>
              <option>VIP</option>
            </select>
          </div>

          {/* Subscription Filter — push notifications status */}
          <div>
            <label
              className="block text-sm mb-2"
              style={{
                color: '#57504A',
                fontFamily: 'Manrope',
                fontSize: '12px',
              }}
            >
              🔔 Notifications
            </label>
            <select
              value={subscriptionFilter}
              onChange={(e) => setSubscriptionFilter(e.target.value)}
              className="w-full px-3 py-2 rounded border text-sm outline-none"
              style={{
                backgroundColor: 'var(--flc-card, #FAFAF8)',
                borderColor: 'var(--flc-line, #E9E5E0)',
                color: '#171412',
                fontFamily: 'Manrope',
              }}
              title="Filter customers by whether they receive push notifications"
            >
              <option value="All">All</option>
              <option value="Subscribed">Reçoivent (subscribed)</option>
              <option value="NotSubscribed">Sans push (not subscribed)</option>
            </select>
          </div>

          {/* Source Filter */}
          <div>
            <label
              className="block text-sm mb-2"
              style={{
                color: '#57504A',
                fontFamily: 'Manrope',
                fontSize: '12px',
              }}
            >
              Source
            </label>
            <select
              value={sourceFilter}
              onChange={(e) => setSourceFilter(e.target.value)}
              className="w-full px-3 py-2 rounded border text-sm outline-none"
              style={{
                backgroundColor: 'var(--flc-card, #FAFAF8)',
                borderColor: 'var(--flc-line, #E9E5E0)',
                color: '#171412',
                fontFamily: 'Manrope',
              }}
            >
              <option>All</option>
              <option>QR in store</option>
              <option>Instagram</option>
              <option>Facebook</option>
              <option>TikTok</option>
            </select>
          </div>

          {/* Min Visits */}
          <div>
            <label
              className="block text-sm mb-2"
              style={{
                color: '#57504A',
                fontFamily: 'Manrope',
                fontSize: '12px',
              }}
            >
              Min Visits
            </label>
            <input
              type="number"
              placeholder="0"
              value={minVisits}
              onChange={(e) => setMinVisits(e.target.value)}
              className="w-full px-3 py-2 rounded border text-sm outline-none"
              style={{
                backgroundColor: 'var(--flc-card, #FAFAF8)',
                borderColor: 'var(--flc-line, #E9E5E0)',
                color: '#171412',
                fontFamily: 'Manrope',
              }}
            />
          </div>

          {/* Min Amount Paid */}
          <div>
            <label
              className="block text-sm mb-2"
              style={{
                color: '#57504A',
                fontFamily: 'Manrope',
                fontSize: '12px',
              }}
            >
              Min Amount (EUR)
            </label>
            <input
              type="number"
              placeholder="0"
              value={minAmountPaid}
              onChange={(e) => setMinAmountPaid(e.target.value)}
              className="w-full px-3 py-2 rounded border text-sm outline-none"
              style={{
                backgroundColor: 'var(--flc-card, #FAFAF8)',
                borderColor: 'var(--flc-line, #E9E5E0)',
                color: '#171412',
                fontFamily: 'Manrope',
              }}
            />
          </div>

          {/* Postal Code */}
          <div>
            <label
              className="block text-sm mb-2"
              style={{
                color: '#57504A',
                fontFamily: 'Manrope',
                fontSize: '12px',
              }}
            >
              Postal Code
            </label>
            <input
              type="text"
              placeholder="37000"
              value={postalCode}
              onChange={(e) => setPostalCode(e.target.value)}
              className="w-full px-3 py-2 rounded border text-sm outline-none"
              style={{
                backgroundColor: 'var(--flc-card, #FAFAF8)',
                borderColor: 'var(--flc-line, #E9E5E0)',
                color: '#171412',
                fontFamily: 'Manrope',
              }}
            />
          </div>
        </div>

        {/* Clear Filters Button */}
        <button
          onClick={clearFilters}
          className="px-4 py-2 rounded text-sm font-medium transition-colors hover:opacity-80"
          style={{
            backgroundColor: '#B85C38',
            color: '#FAFAF8',
            fontFamily: 'Manrope',
          }}
        >
          Clear Filters
        </button>
      </div>

      {/* Customer Count */}
      <div className="mb-4">
        <p
          style={{
            color: '#57504A',
            fontFamily: 'Manrope',
            fontSize: '14px',
          }}
        >
          Showing <strong>{filteredCustomers.length}</strong> of{' '}
          <strong>{allCustomers.length}</strong> customers
        </p>
      </div>

      {/* Customer Table — uses the premium surface primitives:
          subtle hairline + soft row hover, no zebra striping (which read as
          'spreadsheet from 2010'), warm-but-soft avatar. */}
      <div className="ft-card overflow-hidden">
        <div style={{ background: 'var(--surface-sunken)' }}>
          <div className="grid gap-4 px-6 py-3"
            style={{
              color: 'var(--ink-mute)',
              fontSize: 10.5,
              fontWeight: 600,
              letterSpacing: '0.12em',
              textTransform: 'uppercase',
              gridTemplateColumns: '3fr 2fr 1fr 1fr 1fr 1fr 1.2fr 1.2fr 1fr',
              borderBottom: '1px solid var(--hairline)',
            }}
          >
            <div>Customer</div>
            <div>Barcode ID</div>
            <div className="text-center">Visits</div>
            <div className="text-center">Tier</div>
            <div>Postal Code</div>
            <div>Source</div>
            <div className="text-right">Amount Paid</div>
            <div className="text-right">Total Spent</div>
            <div>Last Visit</div>
          </div>
        </div>

        <div style={{ background: 'var(--surface-card)' }}>
          {filteredCustomers.length === 0 ? (
            <div className="px-6 py-12 text-center" style={{ color: 'var(--ink-mute)', fontSize: 13.5 }}>
              No customers found matching your filters.
            </div>
          ) : (
            filteredCustomers.map((customer, idx) => (
              <div
                key={customer.id}
                className="grid gap-4 px-6 py-3.5 transition-colors"
                style={{
                  borderTop: idx === 0 ? 'none' : '1px solid var(--hairline)',
                  background: 'var(--surface-card)',
                  gridTemplateColumns: '3fr 2fr 1fr 1fr 1fr 1fr 1.2fr 1.2fr 1fr',
                  cursor: 'default',
                }}
                onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--surface-sunken)'; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = 'var(--surface-card)'; }}
              >
                {/* Customer Name, Email, Phone */}
                <div className="flex items-center gap-3">
                  <div
                    className="w-9 h-9 rounded-full flex items-center justify-center text-[13px]"
                    style={{
                      background: 'color-mix(in srgb, var(--flc-accent, #C73E2C) 16%, var(--flc-card, #FFFFFF))',
                      color: 'var(--brand-deep)',
                      fontWeight: 500,
                      letterSpacing: '0.01em',
                    }}
                  >
                    {getInitials(customer.name)}
                  </div>
                  <div className="min-w-0">
                    <p className="text-[13.5px] truncate" style={{ color: 'var(--ink)', fontWeight: 500 }}>
                      {customer.name}
                    </p>
                    <p className="text-[11.5px] truncate" style={{ color: 'var(--ink-mute)' }}>
                      {customer.email || customer.phone || '—'}
                    </p>
                  </div>
                </div>

                {/* Barcode ID — clickable, opens the customer's actual card.
                    The barcode was printed as dead text, so checking what a
                    client sees meant copying the code by hand and typing the
                    /card/ URL. It is the single most repeated action when
                    testing or when a client asks "what does my card say?". */}
                <div className="flex items-center font-mono"
                  style={{ color: 'var(--ink-soft)', fontSize: 12 }}
                >
                  <a
                    href={`/card/${customer.barcode_id}?vue=commerce`}
                    target="_blank"
                    rel="noopener noreferrer"
                    onClick={(e) => e.stopPropagation()}
                    title="Ouvrir la carte de ce client dans un nouvel onglet"
                    style={{ color: 'inherit', textDecoration: 'underline', textUnderlineOffset: 3 }}
                  >
                    {customer.barcode_id}
                  </a>
                </div>

                {/* Visits */}
                <div
                  className="flex items-center justify-center"
                  style={{ color: 'var(--ink)', fontSize: 13.5, fontWeight: 500 }}
                >
                  {customer.visits}
                </div>

                {/* Tier */}
                <div className="flex items-center justify-center">
                  <TierBadge tier={customer.tier} size="sm" />
                </div>

                {/* Postal Code */}
                <div className="flex items-center gap-1" style={{ color: 'var(--ink-mute)', fontSize: 12.5 }}>
                  <MapPin size={13} />
                  {customer.postal_code}
                </div>

                {/* Source Badge */}
                <div className="flex items-center">
                  {(() => {
                    const badge = getSourceBadge(customer.acquisition_source);
                    return (
                      <span className="ft-badge" style={{ background: badge.bg, color: 'var(--ink)' }}>
                        {badge.emoji} {badge.label}
                      </span>
                    );
                  })()}
                </div>

                {/* Amount Paid */}
                <div
                  className="text-right flex items-center justify-end"
                  style={{ color: 'var(--ink)', fontSize: 13, fontWeight: 500 }}
                >
                  €{customer.total_amount_paid.toFixed(2)}
                </div>

                {/* Total Spent */}
                <div
                  className="text-right flex items-center justify-end"
                  style={{ color: 'var(--brand-deep)', fontSize: 13, fontWeight: 500 }}
                >
                  €{(customer.total_amount_paid || 0).toFixed(2)}
                </div>

                {/* Last Visit */}
                <div className="flex items-center" style={{ color: 'var(--ink-mute)', fontSize: 12 }}>
                  {getRelativeDate(customer.last_visit_date)}
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
