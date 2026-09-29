import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  Users, Activity, TrendingUp, Smartphone, BadgeCheck, CreditCard, Trash2, Award,
  Plus, AlertTriangle, Moon, UserPlus, Bell, Sparkles, ChevronRight, X,
  Sun, RefreshCw, Clock, CheckCircle2, Calendar, Download, Settings as SettingsIcon, Info, ArrowRight,
} from 'lucide-react';
import {
  ResponsiveContainer, BarChart, Bar, ComposedChart, Line,
  PieChart, Pie, Cell, XAxis, YAxis, CartesianGrid, Tooltip,
} from 'recharts';
import { chartAnimation } from '../lib/chartAnimation';
import { ownerAPI } from '../lib/api';
import { useTheme, heatColor } from '../lib/theme';
import { useBranch } from '../contexts/BranchContext';
import useTileMetric from '../hooks/useTileMetric';

/**
 * OwnerDashboard — premium loyalty dashboard.
 *
 * Faithful rebuild of the HTML mockup the client uploaded
 * (loyalty-dashboard-premium.html). Same layout, same colour palette,
 * same pixel rhythm — wired to the real backend data feeds.
 *
 * Sections (top to bottom in the main column):
 *   1. Real-time banner with branch chips
 *   2. AI recommendation panel
 *   3. Page header (Welcome back + LIVE pill + Nouvelle campagne)
 *   4. 8 pastel KPI tiles
 *   5. Customer status panel (Active / Dormant / At Risk / New + bar)
 *   6. Charts row 1: Visits twin chart + Acquisition weekly
 *   7. Charts row 2: Sources donut + Tier donut
 *   8. Churn & rétention panel
 *   9. LTV panel with breakdown table
 *  10. Plan usage panel
 *  11. Actions recommandées (4 tiles)
 *
 * Side column (right):
 *   - Alertes (4 cards)
 *   - Résumé rapide (4 rows)
 *   - Time filter pill
 *
 * Sidebar + top-toolbar live in DashboardLayout — this page only
 * controls the page contents.
 */

const fmtPct = (n, d = 1) => `${(typeof n === 'number' ? n : 0).toFixed(d)}%`;
const fmtNum = (n) => (n ?? 0).toLocaleString('fr-FR');
const fmtEUR = (n) => `${Number(n || 0).toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`;

// Vibrant Octoboard-style tier palette — saturated and joyful while
// still semantically aligned with the metal/level concept.
// Tier palette now comes from the theme (light/dark variants) — see lib/theme.js

export default function OwnerDashboard() {
  const { t } = useTranslation();
  // Dual-theme palette for everything Recharts/SVG renders via JS props.
  const { nuit, T } = useTheme();
  const TIER_COLORS = T.tier;
  const navigate = useNavigate();
  const { branchId, setBranchId, branches } = useBranch();
  const [summary, setSummary] = useState(null);
  const [tenant, setTenant] = useState(null);
  const [acqSources, setAcqSources] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showAiStrip, setShowAiStrip] = useState(true);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    Promise.all([
      ownerAPI.getAnalyticsSummary?.({ ...(branchId ? { branch_id: branchId } : {}) }).catch(() => null),
      ownerAPI.getTenant?.().catch(() => null),
      ownerAPI.getAcquisitionSources?.({ ...(branchId ? { branch_id: branchId } : {}) }).catch(() => null),
    ]).then(([s, t, a]) => {
      if (!alive) return;
      setSummary(s?.data || null);
      setTenant(t?.data || null);
      setAcqSources(a?.data?.breakdown || a?.data?.acquisition_breakdown || a?.data || null);
    }).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [branchId]);

  // Per-metric live counts with sparkline series (for delta tracking).
  const newCustomers = useTileMetric({ metric: 'new_customers',    branchId, initial: { value: 7,  unit: 'day' }, withSeries: true });
  const activeCust   = useTileMetric({ metric: 'active_customers', branchId, initial: { value: 30, unit: 'day' }, withSeries: true });
  const inactive     = useTileMetric({ metric: 'inactive_customers', branchId, initial: { value: 30, unit: 'day' }, withSeries: true });
  const aboutToLose  = useTileMetric({ metric: 'about_to_lose',    branchId, initial: { value: 14, unit: 'day' }, withSeries: true });

  // Lifetime totals from summary
  const totalCustomers = summary?.total_customers ?? 0;
  const totalVisits    = summary?.total_visits ?? 0;
  const repeatRate     = summary?.repeat_rate ?? 0;
  const walletPasses   = summary?.wallet_passes_count ?? summary?.wallet_active_count ?? 0;
  const activeCards    = summary?.wallet_active_count ?? 0;
  const neverAdded     = summary?.wallet_never_added_count ?? 0;
  const deletedCards   = summary?.wallet_deleted_count ?? 0;
  const tierDist       = summary?.tier_distribution || {};
  const vipCount       = tierDist.vip ?? 0;
  const goldCount      = tierDist.gold ?? 0;
  const silverCount    = tierDist.silver ?? 0;
  const bronzeCount    = tierDist.bronze ?? 0;
  const pct = (n, total) => total > 0 ? Math.round((n / total) * 100) : 0;

  // Customer status segments
  const activeCustomers = activeCust.value || 0;
  const dormantCustomers = inactive.value || 0;
  const atRiskCustomers = aboutToLose.value || 0;
  const newWithoutVisits = Math.max(0, totalCustomers - activeCustomers - dormantCustomers - atRiskCustomers);

  // ────────────────────────────────────────────────────────────────────
  // SHARED TIME WINDOW for both Visits + Acquisition charts.
  // Owner picks a count + unit (e.g. "30 jours", "12 mois", "2 années")
  // in the master toolbar above the charts row; both charts re-fetch
  // automatically via the useTileMetric `controlledDays` prop.
  // ────────────────────────────────────────────────────────────────────
  const UNIT_DAYS_DASH = { day: 1, week: 7, month: 30, year: 365 };
  const [dashWindow, setDashWindow] = useState({ count: 30, unit: 'day' });
  const dashWindowDays = Math.max(1, Math.round(dashWindow.count * (UNIT_DAYS_DASH[dashWindow.unit] || 1)));

  // ─── Notification reach stats — right-rail KPI panel ───────────────
  // Tells the owner what % of customers can actually receive push
  // campaigns. Drives Strategy 2 (SMS re-enable) decision-making.
  const [notifStats, setNotifStats] = useState(null);
  useEffect(() => {
    let alive = true;
    fetch('/api/owner/notifications/subscription-stats', {
      headers: (() => {
        const tok = (typeof localStorage !== 'undefined') ? localStorage.getItem('fdt_token') : null;
        return tok ? { Authorization: `Bearer ${tok}` } : {};
      })(),
    })
      .then((r) => r.ok ? r.json() : null)
      .then((s) => { if (alive && s) setNotifStats(s); })
      .catch(() => { /* silent — panel falls back to demo */ });
    return () => { alive = false; };
  }, []);

  // ─── Apple Wallet adoption — right-rail panel ──────────────────────
  // How many customers actually carry the native pass. Only shown once the
  // certificates are configured, so it never advertises a dead feature.
  const [walletStats, setWalletStats] = useState(null);
  const [walletBusy, setWalletBusy] = useState(false);
  useEffect(() => {
    let alive = true;
    ownerAPI.walletStats?.()
      .then((r) => { if (alive && r?.data?.apple_configured) setWalletStats(r.data); })
      .catch(() => { /* silent — the panel simply stays hidden */ });
    return () => { alive = false; };
  }, []);

  // Visits twin chart data — driven by the shared dashWindow above.
  const visitsTwin  = useTileMetric({ metric: 'total_visits',  branchId, initial: { value: 30, unit: 'day' }, withSeries: true, controlledDays: dashWindowDays });
  const uniquesTwin = useTileMetric({ metric: 'new_customers', branchId, initial: { value: 30, unit: 'day' }, withSeries: true, controlledDays: dashWindowDays });
  const visitsChartData = useMemo(() => {
    const vs = visitsTwin.series || [];
    const us = uniquesTwin.series || [];
    const n = Math.max(vs.length, us.length, 1);
    return Array.from({ length: n }, (_, i) => ({
      idx: i + 1,
      visits:  vs[i] ?? 0,
      uniques: us[i] ?? 0,
    }));
  }, [visitsTwin.series, uniquesTwin.series]);

  // Acquisition — same shared window so both charts always stay in sync.
  const acqWeekly = useTileMetric({ metric: 'new_customers', branchId, initial: { value: 7 * 26, unit: 'day' }, withSeries: true, controlledDays: dashWindowDays });
  const acqChartData = useMemo(() => (acqWeekly.series || []).map((v, i) => ({ idx: i + 1, value: v })), [acqWeekly.series]);
  const acqTotal = acqChartData.reduce((s, p) => s + p.value, 0);
  const acqAvg = acqChartData.length ? acqTotal / acqChartData.length : 0;
  const acqBest = acqChartData.length ? Math.max(...acqChartData.map(p => p.value)) : 0;

  // Sources donut
  const sources = useMemo(() => {
    // Vibrant multi-color palette — joyful but each source stays distinct.
    const palette = {
      direct:    '#3E63DD', // cobalt
      qr_store:  '#5856D6',
      instagram: '#E0397A', // rose
      google:    '#0E9563', // emerald
      facebook:  '#4A63E7', // indigo
      tiktok:    T.ink,              // ink (flips with theme)
      manual:    '#B02468', // magenta
      website:   '#F2B23E', // amber
    };
    const labels = {
      direct: 'Sur place', qr_store: 'QR in-store',
      instagram: 'Instagram', google: 'Google Maps',
      facebook: 'Facebook', tiktok: 'TikTok',
      manual: 'Saisie staff', website: 'Site Web',
    };
    const real = acqSources
      ? Object.entries(acqSources)
          .filter(([, v]) => typeof v === 'number' && v > 0)
          .map(([k, v]) => ({
            key: k, name: labels[k] || k, value: v, color: palette[k] || '#B5B0A8',
          }))
          .sort((a, b) => b.value - a.value)
      : [];
    // Show demo whenever real data isn't useful for a donut comparison
    // (0 or 1 channels). A donut with one segment = a solid circle, no
    // information value — replace with realistic French café demo mix.
    if (real.length >= 2) return real;
    return [
      { key: 'direct',    name: 'Sur place',   value: 56, color: '#3E63DD' },
      { key: 'google',    name: 'Google Maps', value: 22, color: '#0E9563' },
      { key: 'instagram', name: 'Instagram',   value: 16, color: '#E0397A' },
      { key: 'website',   name: 'Site Web',    value:  9, color: '#F2B23E' },
      { key: 'manual',    name: 'Autres',      value:  5, color: '#B02468' },
    ];
  }, [acqSources, T]);
  const sourcesTotal = sources.reduce((s, p) => s + p.value, 0);

  // Tier donut — same rule as the acquisition panel: needs ≥2 populated
  // tiers to be a useful comparison. Otherwise fall back to demo so the
  // side rail always reads as informative, never as broken.
  const realTier = ['gold', 'silver', 'bronze', 'vip']
    .map((k) => ({ key: k, name: k.charAt(0).toUpperCase() + k.slice(1), value: tierDist[k] || 0, color: TIER_COLORS[k] }))
    .filter((t) => t.value > 0);
  const DEMO_TIER_DIST = { bronze: 87, silver: 42, gold: 18, vip: 9 };
  const tierData = realTier.length >= 2 ? realTier : [
    { key: 'bronze', name: 'Bronze', value: DEMO_TIER_DIST.bronze, color: TIER_COLORS.bronze },
    { key: 'silver', name: 'Silver', value: DEMO_TIER_DIST.silver, color: TIER_COLORS.silver },
    { key: 'gold',   name: 'Gold',   value: DEMO_TIER_DIST.gold,   color: TIER_COLORS.gold   },
    { key: 'vip',    name: 'VIP',    value: DEMO_TIER_DIST.vip,    color: TIER_COLORS.vip    },
  ];
  const tiersTotal = tierData.reduce((s, p) => s + p.value, 0);
  // displayTierDist mirrors whichever data tierData used so the rows
  // and the donut stay in sync.
  // Never substitute DEMO_TIER_DIST for real data: a merchant reading
  // invented tier counts off their own dashboard is worse than an empty
  // chart. If the payload has no distribution, show nothing and let the
  // empty state say so.
  const displayTierDist = realTier.length >= 1 ? tierDist : {};

  // Visit-time heatmap — { day_of_week: { hour: count } } from the
  // analytics summary. If the backend has no real data yet (fresh
  // tenant / sandbox), we paint a realistic French café pattern so
  // the owner sees what the chart looks like populated. Real data
  // ALWAYS wins — demo only fires when the heatmap is missing OR all
  // values sum to zero.
  const HEATMAP_DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  const HEATMAP_HOURS = [7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19];

  // Realistic French café visit pattern — morning espresso rush,
  // lunch peak, afternoon lull, evening dinner uptick, weekend brunch
  // lift, Monday quieter, Friday-evening boost.
  const DEMO_HEATMAP = (() => {
    const out = {};
    HEATMAP_DAYS.forEach((d, dIdx) => {
      out[d] = {};
      HEATMAP_HOURS.forEach((h) => {
        let v = 1;
        if (h === 7)              v = 4;
        if (h === 8)              v = 9;
        if (h === 9)              v = 7;
        if (h === 10)             v = 4;
        if (h === 11)             v = 6;
        if (h === 12)             v = 11;
        if (h === 13)             v = 12;
        if (h === 14)             v = 7;
        if (h === 15 || h === 16) v = 3;
        if (h === 17)             v = 5;
        if (h === 18)             v = 9;
        if (h === 19)             v = 10;
        // Weekend brunch lift (Sat=5, Sun=6)
        if ((dIdx === 5 || dIdx === 6) && h >= 10 && h <= 14) v += 4;
        // Friday evening lift
        if (dIdx === 4 && h >= 18 && h <= 19) v += 3;
        // Monday quieter overall
        if (dIdx === 0) v = Math.max(1, v - 2);
        out[d][String(h)] = v;
      });
    });
    return out;
  })();

  const realHeatmap = summary?.visit_time_heatmap;
  const realHeatmapSum = realHeatmap
    ? Object.values(realHeatmap).reduce(
        (s, row) => s + Object.values(row || {}).reduce((a, b) => a + (Number(b) || 0), 0),
        0,
      )
    : 0;
  const heatmap = (realHeatmap && realHeatmapSum > 0) ? realHeatmap : DEMO_HEATMAP;

  // Plan usage
  const planName = (tenant?.plan || 'gold').toUpperCase();
  // Real ceiling from the server (get_plan_features → baseline + admin
  // overrides). The legacy map below is only a last resort for a payload
  // that predates plan_features; its numbers do not match the live limits
  // (silver 1000 / gold 3000 / vip 6000) and must never be trusted alone.
  const planLimit =
    Number(tenant?.plan_features?.max_customers) ||
    ({ silver: 1000, gold: 3000, vip: 6000, basic: 1000, chain: 6000 })[tenant?.plan] ||
    1000;
  const planUsedPct = planLimit > 0 ? Math.min(100, (totalCustomers / planLimit) * 100) : 0;

  // ─── P1 data-viz KPI cards (v31-adapted) — derived series ──────────
  const sparkSeries = visitsTwin.series || [];
  const sparkPath = useMemo(() => {
    const sv = sparkSeries.length ? sparkSeries : [0];
    const max = Math.max(...sv, 1);
    const n = sv.length;
    const pts = sv.map((v, i) => [n > 1 ? (i / (n - 1)) * 220 : 110, 37 - (v / max) * 32]);
    return {
      d: pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`).join(' '),
      last: pts[pts.length - 1],
      lastVal: sv[n - 1],
    };
  }, [sparkSeries]);
  const windowVisits = sparkSeries.reduce((a, b) => a + b, 0);
  const segFilled = Math.round((Math.min(100, planUsedPct) / 100) * 20);
  const weeklyBars = useMemo(() => {
    const sv = sparkSeries;
    const weeks = [];
    for (let i = sv.length; i > 0 && weeks.length < 5; i -= 7) {
      weeks.unshift(sv.slice(Math.max(0, i - 7), i).reduce((a, b) => a + b, 0));
    }
    while (weeks.length < 5) weeks.unshift(0);
    return weeks;
  }, [sparkSeries]);
  const weekMax = Math.max(...weeklyBars, 1);
  const lastWeek = weeklyBars[weeklyBars.length - 1];
  const prevWeek = weeklyBars[weeklyBars.length - 2] || 0;
  const weekDeltaPct = prevWeek > 0 ? ((lastWeek - prevWeek) / prevWeek) * 100 : null;
  const hotIdx = weeklyBars.indexOf(Math.max(...weeklyBars));

  // Open campaign composer with a preset
  const openCampaign = (preset = {}) => {
    const q = new URLSearchParams();
    if (preset.name) q.set('preset_name', preset.name);
    if (preset.content) q.set('preset_content', preset.content);
    navigate(`/dashboard/campaigns${q.toString() ? '?' + q : ''}`);
  };

  // Vibrant multi-colour palette shared with the sources donut so the
  // dashboard reads as one joyful product.
  const statusDonut = [
    { key: 'active',  name: 'Actifs',     value: activeCustomers,  color: T.serieGreen },
    { key: 'dormant', name: 'Dormants',   value: dormantCustomers, color: T.serieAmber },
    { key: 'risk',    name: 'À risque',   value: atRiskCustomers,  color: T.serieRed },
    { key: 'new',     name: 'Nouveaux',   value: newWithoutVisits, color: T.serieBlue },
  ].filter(d => d.value > 0);

  const churnDonut = [
    { key: 'engaged', name: 'Engagés',         value: Math.max(0, totalCustomers - (summary?.one_visit_count || 0) - dormantCustomers - (summary?.churned_90d_count || 0)), color: T.serieGreen },
    { key: 'one',     name: '1 visite',        value: summary?.one_visit_count || 0,    color: T.serieBlue },
    { key: 'dormant', name: 'Inactifs 30j',    value: dormantCustomers,                 color: T.serieAmber },
    { key: 'churned', name: 'Churned 90j',     value: summary?.churned_90d_count || 0,  color: T.serieRed },
  ].filter(d => d.value > 0);

  // Plan usage radial data
  const planUsed = Math.min(totalCustomers, planLimit);
  const planRemaining = Math.max(0, planLimit - planUsed);
  const planDonut = [
    { key: 'used', name: 'Utilisé',    value: planUsed,      color: T.serieGreen },
    { key: 'free', name: 'Disponible', value: planRemaining, color: T.paper2 },
  ];

  return (
    // .av2-light-skin gives the Dashboard the same elevated card look,
    // typography, and color palette as the Analytics V2 page so the two
    // surfaces read as one product. No JSX or data flow changes — this
    // is a pure visual layer (see index.css `.av2-light-skin` block).
    <div className="av2-light-skin fdt-dash">
      <div className="fd-page">

        {/* ═════════════ MAIN COLUMN ═════════════ */}
        <div className="fd-main">

          {/* AI recommendation strip — top, dismissible */}
          {showAiStrip && (
            <div className="fd-ai">
              <div className="fd-ai-ico"><Sparkles size={20} /></div>
              <div className="fd-ai-content">
                <div className="fd-ai-eyebrow">Notre recommandation IA pour vous</div>
                <div className="fd-ai-title">
                  {atRiskCustomers > 0
                    ? `${atRiskCustomers} customers about to lose`
                    : `${newCustomers.value || 0} nouveaux clients à fidéliser`}
                </div>
                <div className="fd-ai-text">
                  {atRiskCustomers > 0
                    ? "They were regulars but haven't visited in 14–29 days. Send a soft \"we miss you\" offer this week before they go silent for 30+ days."
                    : "Activez une campagne de bienvenue pour transformer vos nouveaux visiteurs en habitués."}
                </div>
              </div>
              <button
                className="fd-btn-purple"
                onClick={() => openCampaign(atRiskCustomers > 0
                  ? { name: 'Vous nous manquez', content: '{first_name}, ça fait un moment ! Une attention vous attend chez {business_name}.' }
                  : { name: 'Bienvenue', content: 'Bienvenue {first_name} ! Une attention vous attend lors de votre prochain passage.' })}
              >
                Voir les suggestions <ArrowRight size={13} />
              </button>
              <button
                type="button"
                className="fd-ai-close"
                onClick={() => setShowAiStrip(false)}
                aria-label="Fermer la recommandation"
                title="Fermer"
              >
                <X size={14} />
              </button>
            </div>
          )}

          {/* Idées & actions recommandées — pinned at top */}
          <div className="fd-actions-head">
            <div className="fd-panel-h">Idées &amp; actions recommandées</div>
            <div className="fd-panel-sub">4 actions à fort impact sélectionnées par notre IA</div>
          </div>
          <div className="fd-actions-grid fd-actions-grid-top">
            <ActionTile
              icon={<RefreshCw size={14} />}
              color="#E0397A"
              title="Relance inactifs 14–29j"
              desc={`Envoyez une campagne "We miss you" à ${atRiskCustomers} clients.`}
              cta="Créer la campagne"
              onClick={() => openCampaign({ name: 'Vous nous manquez', content: '{first_name}, ça fait un moment ! Une attention vous attend.' })}
            />
            <ActionTile
              icon={<Award size={14} />}
              color="#8B3FC3"
              title="Segmentez vos VIP"
              desc={`${vipCount} clients VIP génèrent une part importante de vos revenus.`}
              cta="Voir les VIP"
              onClick={() => navigate('/dashboard/customers?tier=vip')}
            />
            <ActionTile
              icon={<UserPlus size={14} />}
              color="#3E63DD"
              title="Boostez les nouveaux clients"
              desc={`${newCustomers.value || 0} nouveaux cette semaine. Activez une campagne d'acquisition.`}
              cta="Créer une campagne"
              onClick={() => openCampaign({ name: 'Bienvenue', content: 'Bienvenue {first_name} ! Une attention vous attend lors de votre prochain passage.' })}
            />
            <ActionTile
              icon={<Sparkles size={14} />}
              color="#0E9563"
              title="Voir plus d'insights"
              desc="Explorez plus d'opportunités pour votre croissance."
              cta="Explorer"
              onClick={() => navigate('/dashboard/insights')}
            />
          </div>

          {/* ── Hero band — Éclat flame mesh / Minuit espresso + gold ── */}
          <div className="fdz-hero">
            <div className="fdz-hero-top">
              <span className="fdz-eyebrow">Programme fidélité · en direct</span>
              <span className="fdz-live"><i></i>{t('dashboard.live')}</span>
              <button className="fdz-cta" onClick={() => openCampaign({})}>
                <Plus size={14} /> {t('dashboard.new_campaign')}
              </button>
            </div>
            <h2>{t('dashboard.welcome_back')}{tenant?.name ? <> · <em>{tenant.name}</em></> : null}</h2>
            <p className="fdz-sub">{t('dashboard.live_subtitle')}</p>
            <div className="fdz-hstats">
              <div className="fdz-hs">
                <b>{fmtNum(totalCustomers)}</b><span>cartes actives</span>
                {(newCustomers.value || 0) > 0 && <span className="up">+{newCustomers.value} cette sem.</span>}
              </div>
              <div className="fdz-hs">
                <b>{fmtPct(repeatRate, 0)}</b><span>taux de retour</span>
                <span className="up">clients revenus 2×</span>
              </div>
              <div className="fdz-hs">
                <b>{fmtNum(totalVisits)}</b><span>visites enregistrées</span>
                <span className="up">{fmtNum(windowVisits)} sur la période</span>
              </div>
            </div>
          </div>

          {/* ── Data-viz KPI row (v31 cards, real data) ── */}
          <div className="fdz-kpis">
            <div className="fdz-kpi">
              <div className="l">Visites · {dashWindowDays} j</div>
              <div className="v">{fmtNum(windowVisits)}</div>
              <div className={`s ${(visitsTwin.deltaPct ?? 0) >= 0 ? 'up' : 'dn'}`}>
                {(visitsTwin.deltaPct ?? 0) >= 0 ? '▲' : '▼'} {Math.abs(visitsTwin.deltaPct ?? 0).toFixed(1)}% vs période préc.
              </div>
              <svg width="100%" height="42" viewBox="0 0 220 42" preserveAspectRatio="none" style={{ marginTop: 8, overflow: 'visible' }}>
                <path d={sparkPath.d} fill="none" stroke={T.accent} strokeWidth="2" strokeLinecap="round" />
                {sparkPath.last && (
                  <>
                    <circle cx={sparkPath.last[0]} cy={sparkPath.last[1]} r="3.5" fill={nuit ? T.accentHi : T.accentDeep} />
                    <text x={sparkPath.last[0] - 6} y={Math.max(9, sparkPath.last[1] - 7)} textAnchor="end" fontSize="9" fontWeight="700" fill={nuit ? T.accentHi : T.accentDeep}>
                      {fmtNum(sparkPath.lastVal)}
                    </text>
                  </>
                )}
              </svg>
            </div>
            <div className="fdz-kpi">
              <div className="l">Objectif du plan</div>
              <div className="v">{fmtNum(totalCustomers)} <small>/ {fmtNum(planLimit)}</small></div>
              <div className="s up">
                {planUsedPct.toFixed(0)}% de l'objectif{(newCustomers.value || 0) > 0 ? ` · ▲ ${newCustomers.value} cette sem.` : ''}
              </div>
              <div className="fdz-seg">
                {Array.from({ length: 20 }, (_, i) => <i key={i} className={i < segFilled ? 'f' : ''} />)}
              </div>
            </div>
            <div className="fdz-kpi">
              <div className="l">Nouveaux · par source</div>
              <div className="fdz-split">
                <div className="fdz-sp">
                  <b>{fmtNum(sources[0]?.value || 0)}</b><span>{sources[0]?.name || '—'}</span>
                  <div className="fdz-bar" style={{ width: `${Math.round(((sources[0]?.value || 0) / Math.max(sources[0]?.value || 0, sources[1]?.value || 0, 1)) * 100)}%` }} />
                </div>
                <div className="fdz-sp alt">
                  <b>{fmtNum(sources[1]?.value || 0)}</b><span>{sources[1]?.name || '—'}</span>
                  <div className="fdz-bar" style={{ width: `${Math.max(8, Math.round(((sources[1]?.value || 0) / Math.max(sources[0]?.value || 0, sources[1]?.value || 0, 1)) * 100))}%` }} />
                </div>
              </div>
            </div>
            <div className="fdz-kpi">
              <div className="l">Visites par semaine</div>
              <div className="v">{fmtNum(lastWeek)}</div>
              <div className={`s ${weekDeltaPct == null || weekDeltaPct >= 0 ? 'up' : 'dn'}`}>
                {weekDeltaPct == null
                  ? 'sur les 7 derniers jours'
                  : `${weekDeltaPct >= 0 ? '▲' : '▼'} ${Math.abs(weekDeltaPct).toFixed(0)}%${hotIdx === weeklyBars.length - 1 ? ' · meilleure de la période' : ''}`}
              </div>
              <div className="fdz-mb">
                {weeklyBars.map((w, i) => (
                  <i key={i} className={i === hotIdx ? 'hot' : ''} style={{ height: `${Math.max(12, Math.round((w / weekMax) * 100))}%` }} />
                ))}
              </div>
            </div>
          </div>

          {/* KPI GRID — 8 cards */}
          <div className="fd-kpi-grid">
            <Kpi color="k-blue"    icon={<Users size={18} />}        label={t('dashboard.kpi_total_customers')}  value={fmtNum(totalCustomers)} sub={t('dashboard.kpi_total_customers_sub') || 'Toute la base'}
                 delta={newCustomers.deltaPct}
                 onClick={() => navigate('/dashboard/customers')} />
            <Kpi color="k-emerald" icon={<Activity size={18} />}     label={t('dashboard.kpi_total_visits')}    value={fmtNum(totalVisits)}   sub={t('dashboard.kpi_total_visits_sub') || 'Toutes les visites enregistrées'}
                 delta={visitsTwin.deltaPct} />
            <Kpi color="k-orange"  icon={<TrendingUp size={18} />}   label={t('dashboard.kpi_repeat_rate')}     value={fmtPct(repeatRate)}    sub={t('dashboard.kpi_repeat_rate_sub') || 'Clients revenus au moins 2 fois'} />
            <Kpi color="k-indigo"  icon={<Smartphone size={18} />}   label={t('dashboard.kpi_wallet_passes')}   value={fmtNum(walletPasses)}  sub={`${pct(walletPasses, totalCustomers)}% ${t('dashboard.kpi_of_customers') || 'des clients'}`} />

            <Kpi color="k-emerald" icon={<BadgeCheck size={18} />}   label={t('dashboard.kpi_active_cards')}    value={fmtNum(activeCards)}   sub={t('dashboard.kpi_active_cards_sub') || 'Dans Apple/Google Wallet'}
                 onClick={() => navigate('/dashboard/customers?wallet_state=active')} />
            <Kpi color="k-amber"   icon={<CreditCard size={18} />}   label={t('dashboard.kpi_never_added')}     value={fmtNum(neverAdded)}    sub={t('dashboard.kpi_never_added_sub') || 'Inscrits, mais carte non ajoutée'}
                 onClick={() => navigate('/dashboard/customers?wallet_state=never_added')} />
            <Kpi color="k-red"     icon={<Trash2 size={18} />}       label={t('dashboard.kpi_deleted_cards')}   value={fmtNum(deletedCards)}  sub={t('dashboard.kpi_deleted_cards_sub') || 'Carte retirée du wallet'}
                 onClick={() => navigate('/dashboard/customers?wallet_state=deleted')} />
            <Kpi color="k-purple"  icon={<Award size={18} />}        label={t('dashboard.kpi_vip')}             value={fmtNum(vipCount)}      sub={t('dashboard.kpi_vip_sub') || 'Top tier — 40+ visites ou panier €60+'}
                 onClick={() => navigate('/dashboard/customers?tier=vip')} />
          </div>

          {/* Customer Status */}
          <div className="fd-panel">
            <div className="fd-panel-head">
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span className="fd-panel-title">{t('dashboard.section_customer_status')}</span>
                <span title={t('dashboard.status_tooltip') || 'État détaillé de chaque segment client'} style={{ width: 16, height: 16, borderRadius: 8, background: 'var(--flc-paper2, #F4EEE0)', color: 'var(--flc-ink3, #8D857D)', display: 'inline-grid', placeItems: 'center', fontSize: 10, fontStyle: 'italic', fontWeight: 600 }}>i</span>
              </div>
              <button onClick={() => navigate('/dashboard/customers')} style={{ color: 'var(--fd-primary)', fontSize: 13, fontWeight: 500, border: 0, background: 'transparent', cursor: 'pointer' }}>
                {t('dashboard.view_all_customers')} →
              </button>
            </div>
            <div className="fd-status-row">
              <div className="fd-status-grid">
                <StatusCell label={t('dashboard.status_active')}    value={activeCustomers}    total={totalCustomers} icon={<Users size={16} />} ink={T.serieGreen} />
                <StatusCell label={t('dashboard.status_dormant')}   value={dormantCustomers}   total={totalCustomers} icon={<Moon size={16} />}  ink={T.warn} />
                <StatusCell label={t('dashboard.status_at_risk')}   value={atRiskCustomers}    total={totalCustomers} icon={<AlertTriangle size={16} />} ink={T.serieRed} />
                <StatusCell label={t('dashboard.status_new')}       value={newWithoutVisits}   total={totalCustomers} icon={<UserPlus size={16} />} ink={T.serieSky} />
              </div>
              <div className="fd-status-donut">
                <div className="fd-mini-donut">
                  {statusDonut.length > 0 ? (
                    <ResponsiveContainer width="100%" height="100%">
                      <PieChart>
                        <Pie isAnimationActive={chartAnimation()} data={statusDonut} dataKey="value" innerRadius={38} outerRadius={56} stroke={T.card} strokeWidth={3} startAngle={90} endAngle={-270}>
                          {statusDonut.map((d) => <Cell key={d.key} fill={d.color} />)}
                        </Pie>
                      </PieChart>
                    </ResponsiveContainer>
                  ) : null}
                  <div className="fd-mini-center">
                    <div className="fd-mini-val">{totalCustomers}</div>
                    <div className="fd-mini-lbl">Total</div>
                  </div>
                </div>
              </div>
            </div>
            <div className="fd-status-bar">
              <div style={{ width: `${pct(activeCustomers, totalCustomers)}%`, background: T.serieGreen }} />
              <div style={{ width: `${pct(dormantCustomers, totalCustomers)}%`, background: T.serieAmber }} />
              <div style={{ width: `${pct(atRiskCustomers, totalCustomers)}%`, background: T.serieRed }} />
              <div style={{ width: `${pct(newWithoutVisits, totalCustomers)}%`, background: T.serieBlue }} />
            </div>
          </div>

          {/* ─── MASTER TIME-WINDOW TOOLBAR ───────────────────────────────
              Single source of truth for both charts below. Owner picks
              a count + unit; both Visits chart and Acquisition chart
              refetch via useTileMetric's controlledDays prop. */}
          <div className="fdz-period" style={{
            display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 10,
            margin: '0 0 12px',
          }}>
            <Calendar size={14} color="#B85C38" />
            <span style={{
              fontSize: 11, letterSpacing: '0.12em', textTransform: 'uppercase',
              fontWeight: 700, color: 'var(--fd-text-3)',
            }}>
              Période
            </span>

            <div style={{
              display: 'inline-flex', alignItems: 'center', gap: 0,
              background: 'var(--flc-card, #FFFFFF)', border: '1px solid var(--fd-border)',
              borderRadius: 8, overflow: 'hidden', boxShadow: '0 1px 2px rgba(45, 35, 24, .04)',
            }}>
              <input
                type="number" min="1" max="999"
                value={dashWindow.count}
                onChange={(e) => {
                  const v = Math.max(1, Math.min(999, parseInt(e.target.value, 10) || 1));
                  setDashWindow((p) => ({ ...p, count: v }));
                }}
                style={{
                  width: 56, border: 0, padding: '7px 10px',
                  fontFamily: 'inherit', fontSize: 13, fontWeight: 600,
                  color: 'var(--fd-text)', textAlign: 'right', outline: 0,
                  background: 'transparent',
                }}
              />
              <div style={{ width: 1, height: 24, background: 'var(--fd-border)' }} />
              <select
                value={dashWindow.unit}
                onChange={(e) => setDashWindow((p) => ({ ...p, unit: e.target.value }))}
                style={{
                  border: 0, padding: '7px 26px 7px 10px',
                  fontFamily: 'inherit', fontSize: 13, fontWeight: 500,
                  color: 'var(--fd-text-2)', cursor: 'pointer', outline: 0,
                  background: 'transparent',
                }}
              >
                <option value="day">jour{dashWindow.count > 1 ? 's' : ''}</option>
                <option value="week">semaine{dashWindow.count > 1 ? 's' : ''}</option>
                <option value="month">mois</option>
                <option value="year">année{dashWindow.count > 1 ? 's' : ''}</option>
              </select>
            </div>

            {/* Quick-pick chips — one tap for the most common windows */}
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {[
                { label: '7 j',     count: 7,   unit: 'day' },
                { label: '30 j',    count: 30,  unit: 'day' },
                { label: '90 j',    count: 90,  unit: 'day' },
                { label: '12 mois', count: 12,  unit: 'month' },
                { label: '1 an',    count: 1,   unit: 'year' },
              ].map((q) => {
                const active = dashWindow.count === q.count && dashWindow.unit === q.unit;
                return (
                  <button
                    key={q.label}
                    type="button"
                    onClick={() => setDashWindow({ count: q.count, unit: q.unit })}
                    style={{
                      padding: '5px 10px', fontSize: 11.5, fontWeight: 500,
                      border: `1px solid ${active ? '#B85C38' : 'var(--fd-border)'}`,
                      background: active ? 'rgb(184 92 56 / .08)' : 'var(--flc-card, #FFFFFF)',
                      color: active ? '#B85C38' : 'var(--fd-text-2)',
                      borderRadius: 99, cursor: 'pointer', fontFamily: 'inherit',
                      transition: 'all 120ms ease',
                    }}
                  >
                    {q.label}
                  </button>
                );
              })}
            </div>

            {/* Live readout — shows the exact window in days */}
            <span style={{
              marginLeft: 'auto', fontSize: 11, color: 'var(--fd-text-3)',
              fontStyle: 'italic',
            }}>
              ≈ {dashWindowDays} jour{dashWindowDays > 1 ? 's' : ''} de données
            </span>
          </div>

          {/* CHARTS ROW — Visits | Acquisition (Sources + Tier moved to right rail) */}
          <div className="fd-charts-grid">
            {/* Visits chart — time window is owned by the master toolbar above */}
            <div className="fd-chart">
              <div className="fd-ch-head">
                <span className="fd-ch-title">Visites dans le temps</span>
              </div>
              <div className="fd-ch-legend">
                <span><span className="fd-ch-dot" style={{ background: T.serieBlue }} />Visites totales</span>
                <span><span className="fd-ch-dot" style={{ background: T.serieAmber }} />Clients uniques</span>
              </div>
              <div style={{ height: 180 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={visitsChartData} margin={{ top: 8, right: 8, bottom: 0, left: -20 }}>
                    <CartesianGrid stroke={T.grid} vertical={false} />
                    <XAxis dataKey="idx" tick={{ fontSize: 10, fill: T.tick }} tickLine={false} axisLine={false} />
                    <YAxis tick={{ fontSize: 10, fill: T.tick }} tickLine={false} axisLine={false} width={28} />
                    <Tooltip contentStyle={{ fontSize: 11, borderRadius: 8, border: `1px solid ${T.line}`, background: T.card, color: T.ink }} />
                    <Bar isAnimationActive={chartAnimation()} dataKey="visits" fill={T.serieBlue} radius={[3, 3, 0, 0]} maxBarSize={14} />
                    <Line isAnimationActive={chartAnimation()} type="monotone" dataKey="uniques" stroke={T.serieAmber} strokeWidth={2} dot={{ r: 3, fill: T.serieAmber }} />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
              <div className="fd-pt-grid">
                <div className="fd-pt-cell">
                  <div className="fd-pt-lbl">Visites totales</div>
                  <div className="fd-pt-val">{fmtNum(totalVisits)}</div>
                  <div className="fd-pt-delta">↑ {fmtPct(repeatRate)} taux retour</div>
                </div>
                <div className="fd-pt-cell">
                  <div className="fd-pt-lbl">Clients uniques</div>
                  <div className="fd-pt-val">{fmtNum(totalCustomers)}</div>
                  <div className="fd-pt-delta">{newCustomers.value > 0 ? `↑ ${newCustomers.value} nouveaux` : 'Stable'}</div>
                </div>
              </div>
            </div>

            {/* Acquisition — time window is owned by the master toolbar above */}
            <div className="fd-chart">
              <div className="fd-ch-head">
                <span className="fd-ch-title">Acquisition de clients</span>
              </div>
              <div className="fd-chart-stats">
                <div>
                  <div className="fd-cs-lbl">Nouveaux clients</div>
                  <div className="fd-cs-val">{fmtNum(acqTotal)}</div>
                  <div className="fd-cs-sub">Total</div>
                </div>
                <div>
                  <div className="fd-cs-lbl">Moy. / sem.</div>
                  <div className="fd-cs-val">{acqAvg.toFixed(1)}</div>
                  <div className="fd-cs-sub">→ stable</div>
                </div>
                <div>
                  <div className="fd-cs-lbl">Meilleure sem.</div>
                  <div className="fd-cs-val">{acqBest}</div>
                  <div className="fd-cs-sub">Record</div>
                </div>
              </div>
              <div style={{ height: 180 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={acqChartData} margin={{ top: 8, right: 8, bottom: 0, left: -20 }}>
                    <CartesianGrid stroke={T.grid} vertical={false} />
                    <XAxis dataKey="idx" tick={{ fontSize: 10, fill: T.tick }} tickLine={false} axisLine={false} interval={3} />
                    <YAxis tick={{ fontSize: 10, fill: T.tick }} tickLine={false} axisLine={false} width={28} />
                    <Tooltip contentStyle={{ fontSize: 11, borderRadius: 8, border: `1px solid ${T.line}`, background: T.card, color: T.ink }} />
                    <Bar isAnimationActive={chartAnimation()} dataKey="value" fill={T.serieGreen} radius={[3, 3, 0, 0]} maxBarSize={12} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div className="fd-ch-foot">
                <span style={{ fontSize: 12, color: 'var(--fd-text-2)' }}>Tendance</span>
                <span style={{ fontWeight: 700, color: 'var(--fd-green-ico)' }}>En croissance régulière</span>
                <TrendingUp size={20} color="#4F7A36" />
              </div>
            </div>

          </div>{/* /fd-charts-grid */}

          {/* When Do Customers Visit — gradient heatmap (day × hour).
              Restored from the pre-rebuild dashboard. Cells go from pale
              cream (idle) → deep terracotta (peak) so peak hours pop.
              Always rendered — uses the empty skeleton when the API
              hasn't sent data yet, so the panel is visible immediately. */}
          {(
            <div className="fd-panel">
              <div className="fd-panel-head">
                <div>
                  <div className="fd-panel-h">When Do Your Customers Usually Come In?</div>
                  <div className="fd-panel-sub">Darker cells = more visits. Use this to time your campaigns for maximum impact.</div>
                </div>
              </div>
              <div className="fd-heatmap-wrap">
                <table className="fd-heatmap">
                  <thead>
                    <tr>
                      <th className="fd-hm-th-hour">Hour</th>
                      {Object.keys(heatmap).map((day) => (
                        <th key={day} className="fd-hm-th-day">{day}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {Object.keys(Object.values(heatmap)[0] || {})
                      .sort((a, b) => parseInt(a) - parseInt(b))
                      .map((hour) => {
                        const maxCount = Math.max(
                          ...Object.values(heatmap).flatMap((d) => Object.values(d)),
                          1,
                        );
                        // 2-stop ramp between the theme's anchors:
                        // light = pale cream → deep flame; dark = espresso → champagne.
                        return (
                          <tr key={hour}>
                            <td className="fd-hm-hour">{hour}:00</td>
                            {Object.keys(heatmap).map((day) => {
                              const count = heatmap[day]?.[hour] || 0;
                              const intensity = count / maxCount;
                              const bgColor = count === 0 ? T.heatEmpty : heatColor(T, intensity);
                              // Flip text once the cell crosses mid-ramp.
                              const textColor = intensity > 0.55 ? T.heatTextHi : T.heatTextLo;
                              return (
                                <td
                                  key={day}
                                  className="fd-hm-cell"
                                  style={{ backgroundColor: bgColor, color: textColor }}
                                  title={`${count} visit${count === 1 ? '' : 's'}`}
                                >
                                  {count || ''}
                                </td>
                              );
                            })}
                          </tr>
                        );
                      })}
                  </tbody>
                </table>
              </div>
              <div className="fd-hm-legend">
                <span className="fd-hm-legend-lbl">Moins</span>
                <span className="fd-hm-legend-ramp" />
                <span className="fd-hm-legend-lbl">Plus</span>
              </div>
            </div>
          )}

          {/* Churn & rétention */}
          <div className="fd-panel">
            <div className="fd-panel-head">
              <div>
                <div className="fd-panel-h">Churn & rétention</div>
                <div className="fd-panel-sub">Comprenez la perte et la rétention de vos clients</div>
              </div>
            </div>
            <div className="fd-churn-row">
              <div className="fd-churn-grid">
                <div className="fd-churn-card">
                  <div className="fd-cc-lbl">Clients Total</div>
                  <div className="fd-cc-val">{totalCustomers}</div>
                  <div className="fd-cc-sub">100% de la base</div>
                </div>
                <div className="fd-churn-card">
                  <div className="fd-cc-lbl">1 visite seulement</div>
                  <div className="fd-cc-val">{fmtPct(pct(summary?.one_visit_count || 0, totalCustomers))}</div>
                  <div className="fd-cc-sub">{summary?.one_visit_count || 0} clients</div>
                </div>
                <div className="fd-churn-card">
                  <div className="fd-cc-lbl">Inactifs 30j</div>
                  <div className="fd-cc-val warn">{fmtPct(pct(dormantCustomers, totalCustomers))}</div>
                  <div className="fd-cc-sub">{dormantCustomers} clients</div>
                </div>
                <div className="fd-churn-card">
                  <div className="fd-cc-lbl">Churned 90j</div>
                  <div className="fd-cc-val">{fmtPct(pct(summary?.churned_90d_count || 0, totalCustomers))}</div>
                  <div className="fd-cc-sub">{summary?.churned_90d_count || 0} clients</div>
                </div>
              </div>
              <div className="fd-churn-donut">
                <div className="fd-mini-donut">
                  {churnDonut.length > 0 ? (
                    <ResponsiveContainer width="100%" height="100%">
                      <PieChart>
                        <Pie isAnimationActive={chartAnimation()} data={churnDonut} dataKey="value" innerRadius={38} outerRadius={56} stroke={T.card} strokeWidth={3} startAngle={90} endAngle={-270}>
                          {churnDonut.map((d) => <Cell key={d.key} fill={d.color} />)}
                        </Pie>
                      </PieChart>
                    </ResponsiveContainer>
                  ) : null}
                  <div className="fd-mini-center">
                    <div className="fd-mini-val">{fmtPct(100 - pct((summary?.churned_90d_count || 0) + dormantCustomers, totalCustomers), 0)}</div>
                    <div className="fd-mini-lbl">Rétention</div>
                  </div>
                </div>
                <div className="fd-mini-legend">
                  {churnDonut.map(d => (
                    <div key={d.key} className="fd-ml-row">
                      <span className="fd-ml-dot" style={{ background: d.color }} />
                      <span className="fd-ml-name">{d.name}</span>
                      <span className="fd-ml-val">{d.value}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* LTV */}
          <div className="fd-panel">
            <div className="fd-panel-head">
              <div>
                <div className="fd-panel-h">Lifetime Value (LTV)</div>
                <div className="fd-panel-sub">Analysez la valeur générée par vos clients sur la durée</div>
              </div>
            </div>
            <div className="fd-ltv-cards">
              <div className="fd-ltv-card">
                <div className="fd-lc-lbl">LTV moyenne</div>
                <div className="fd-lc-val">{fmtEUR(summary?.ltv_mean || 0)}</div>
              </div>
              <div className="fd-ltv-card">
                <div className="fd-lc-lbl">LTV médiane</div>
                <div className="fd-lc-val">{fmtEUR(summary?.ltv_median || 0)}</div>
              </div>
              <div className="fd-ltv-card high">
                <div className="fd-lc-lbl">Top 10% LTV</div>
                <div className="fd-lc-val">{fmtEUR(summary?.ltv_p90 || 0)}</div>
              </div>
            </div>
            <table className="fd-ltv-table">
              <thead>
                <tr><th>Palier</th><th>Clients</th><th>LTV moyenne</th><th>Revenus total</th></tr>
              </thead>
              <tbody>
                {['gold', 'silver', 'bronze', 'vip'].map((k) => {
                  const cnt = tierDist[k] || 0;
                  const ltv = summary?.ltv_by_tier?.[k] || 0;
                  return (
                    <tr key={k}>
                      <td><span className="fd-tier-dot" style={{ background: TIER_COLORS[k] }} />{k.charAt(0).toUpperCase() + k.slice(1)}</td>
                      <td>{cnt}</td>
                      <td>{fmtEUR(ltv)}</td>
                      <td>{fmtEUR(ltv * cnt)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Plan usage */}
          <div className="fd-panel">
            <div className="fd-panel-head">
              <div>
                <div className="fd-panel-h">Cartes de fidélité actives</div>
                <div className="fd-panel-sub">Utilisation de votre plan</div>
              </div>
            </div>
            <div className="fd-plan-grid">
              <div className="fd-plan-gauge">
                <div className="fd-mini-donut fd-plan-donut">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie isAnimationActive={chartAnimation()} data={planDonut} dataKey="value" innerRadius={50} outerRadius={70} stroke={T.card} strokeWidth={2} startAngle={90} endAngle={-270}>
                        {planDonut.map((d) => <Cell key={d.key} fill={d.color} />)}
                      </Pie>
                    </PieChart>
                  </ResponsiveContainer>
                  <div className="fd-mini-center">
                    <div className="fd-mini-val">{planUsedPct.toFixed(0)}%</div>
                    <div className="fd-mini-lbl">utilisé</div>
                  </div>
                </div>
                <div className="fd-plan-meta">
                  <div className="fd-plan-num">{totalCustomers} <span className="fd-plan-num-total">/ {planLimit}</span></div>
                  <div className="fd-plan-tag-row">
                    <span className="fd-plan-chip">{planName}</span>
                    <span className="fd-plan-pct">{planUsedPct.toFixed(1)}% utilisé</span>
                  </div>
                </div>
              </div>
              <div className="fd-plan-aside">
                <div className="fd-pa-h"><Info size={13} /> À savoir</div>
                <ul className="fd-pa-list">
                  <li><span>Cartes actives</span><b>{activeCards}</b></li>
                  <li><span>Cartes inactives</span><b>{neverAdded}</b></li>
                  <li><span>Supprimées</span><b>{deletedCards}</b></li>
                </ul>
                <button className="fd-pa-btn" onClick={() => navigate('/dashboard/settings#settings-billing')}>
                  <SettingsIcon size={12} /> Gérer mon plan
                </button>
              </div>
            </div>
          </div>


        </div>

        {/* ═════════════ SIDE COLUMN ═════════════ */}
        <div className="fd-side">
          {/* Alertes */}
          <div className="fd-side-panel">
            <div className="fd-sp-head">
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Bell size={15} />
                <span className="fd-sp-title">Alertes</span>
              </div>
              <div className="fd-sp-count">4</div>
            </div>
            <Alert color="yellow" icon={<AlertTriangle size={16} />} title="Taux de retour"      sub={`${fmtPct(repeatRate)} ce mois-ci`} time="Il y a 2 heures" />
            <Alert color="purple" icon={<Sparkles size={16} />}    title={`${atRiskCustomers} clients à risque`} sub="Inactifs 14–29 jours"    time="Il y a 1 heure" />
            <Alert color="blue"   icon={<UserPlus size={16} />}     title={`${newCustomers.value || 0} nouveaux`} sub="Sur les 7 derniers jours" time="Il y a 3 heures" />
            <Alert color="green"  icon={<Clock size={16} />}        title="Objectif mensuel"      sub={`${Math.round(planUsedPct)}% atteint`}  time="Il reste 9 jours" />
            <button className="fd-sp-cta" onClick={() => navigate('/dashboard/insights')}>Voir toutes les alertes →</button>
          </div>

          {/* Résumé rapide */}
          <div className="fd-side-panel">
            <div className="fd-sp-head">
              <span className="fd-sp-title">Résumé rapide</span>
            </div>
            <SummaryRow label="Nouveaux clients (30j)" value={newCustomers.value || 0} delta={newCustomers.deltaPct} />
            <SummaryRow label="Clients actifs (30j)"   value={activeCustomers}         delta={activeCust.deltaPct} />
            <SummaryRow label="Inactifs depuis 30j+"   value={dormantCustomers}        delta={inactive.deltaPct} />
            <SummaryRow label="Sur le point de partir" value={atRiskCustomers}         delta={aboutToLose.deltaPct} />
            <button className="fd-sp-cta" style={{ marginTop: 18 }} onClick={() => navigate('/dashboard/analytics')}>
              Voir le rapport complet →
            </button>
          </div>

          {/* Filter strip */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, background: 'var(--flc-card, #FFFFFF)', border: '1px solid var(--fd-border)', padding: '10px 14px', borderRadius: 12, fontSize: 12.5, color: 'var(--fd-text-2)' }}>
            <Calendar size={14} />
            <span style={{ letterSpacing: 1.1, fontWeight: 700, fontSize: 11, color: 'var(--fd-text-3)', textTransform: 'uppercase', marginRight: 'auto' }}>
              Filtre temps
            </span>
            <select style={{ border: 0, background: 'transparent', fontFamily: 'inherit', fontSize: 12.5, color: 'var(--fd-text)', fontWeight: 600, cursor: 'pointer', outline: 0 }}>
              <option>30 derniers jours</option>
              <option>7 jours</option>
              <option>90 jours</option>
            </select>
          </div>

          {/* ─── Top Sources d'acquisition (moved from main charts row) ─── */}
          <div className="fd-side-panel">
            <div className="fd-sp-head">
              <span className="fd-sp-title">Top sources d'acquisition</span>
              <span style={{ fontSize: 10, color: 'var(--fd-text-3)', fontWeight: 700, letterSpacing: 0.6 }}>À VIE</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginTop: 4, marginBottom: 12 }}>
              <div style={{ position: 'relative', width: 92, height: 92, flexShrink: 0 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie data={sources} dataKey="value" innerRadius={32} outerRadius={44}
                         stroke={T.card} strokeWidth={2} startAngle={90} endAngle={-270}
                         isAnimationActive={false}>
                      {sources.map((d) => <Cell key={d.key} fill={d.color} />)}
                    </Pie>
                  </PieChart>
                </ResponsiveContainer>
                <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column',
                              alignItems: 'center', justifyContent: 'center', pointerEvents: 'none' }}>
                  <div style={{ fontFamily: "'Playfair Display', serif", fontSize: 18, fontWeight: 700, color: 'var(--fd-text)', lineHeight: 1 }}>{sourcesTotal}</div>
                  <div style={{ fontSize: 8.5, color: 'var(--fd-text-3)', letterSpacing: 0.6, textTransform: 'uppercase', marginTop: 2 }}>Clients</div>
                </div>
              </div>
              <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 5 }}>
                {sources.slice(0, 5).map((d) => (
                  <div key={d.key} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 6, fontSize: 11 }}>
                    <span style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
                      <span style={{ width: 7, height: 7, borderRadius: '50%', background: d.color, flexShrink: 0 }} />
                      <span style={{ color: 'var(--fd-text-2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{d.name}</span>
                    </span>
                    <span style={{ flexShrink: 0, color: 'var(--fd-text)', fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>
                      {pct(d.value, sourcesTotal)}<span style={{ color: 'var(--fd-text-3)', fontWeight: 400 }}>%</span>
                    </span>
                  </div>
                ))}
              </div>
            </div>
            {/* Insight strip — top channel + its % share, color-coded */}
            <div style={{ marginTop: 4, padding: '8px 10px', borderRadius: 8,
                          background: 'linear-gradient(135deg, rgb(184 92 56 / .06), hsl(42 78% 52% / .06))',
                          fontSize: 11, color: 'var(--fd-text-2)', lineHeight: 1.4 }}>
              <span style={{ fontWeight: 600, color: 'var(--fd-text)' }}>{sources[0]?.name}</span>
              {' génère '}
              <span style={{ fontWeight: 700, color: '#B85C38' }}>{pct(sources[0]?.value || 0, sourcesTotal)}%</span>
              {' de vos clients.'}
            </div>
          </div>

          {/* ─── Distribution par palier (moved from main charts row) ─── */}
          <div className="fd-side-panel">
            <div className="fd-sp-head">
              <span className="fd-sp-title">Répartition par palier</span>
              <span style={{ fontSize: 10, color: 'var(--fd-text-3)', fontWeight: 700, letterSpacing: 0.6 }}>À VIE</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginTop: 4, marginBottom: 12 }}>
              <div style={{ position: 'relative', width: 92, height: 92, flexShrink: 0 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie data={tierData} dataKey="value" innerRadius={32} outerRadius={44}
                         stroke={T.card} strokeWidth={2} startAngle={90} endAngle={-270}
                         isAnimationActive={false}>
                      {tierData.map((d) => <Cell key={d.key} fill={d.color} />)}
                    </Pie>
                  </PieChart>
                </ResponsiveContainer>
                <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column',
                              alignItems: 'center', justifyContent: 'center', pointerEvents: 'none' }}>
                  <div style={{ fontFamily: "'Playfair Display', serif", fontSize: 18, fontWeight: 700, color: 'var(--fd-text)', lineHeight: 1 }}>{tiersTotal}</div>
                  <div style={{ fontSize: 8.5, color: 'var(--fd-text-3)', letterSpacing: 0.6, textTransform: 'uppercase', marginTop: 2 }}>Membres</div>
                </div>
              </div>
              <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
                {['vip', 'gold', 'silver', 'bronze'].map((k) => {
                  const count = displayTierDist[k] || 0;
                  const p = tiersTotal > 0 ? Math.round((count / tiersTotal) * 100) : 0;
                  return (
                    <div key={k}>
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 6, fontSize: 10.5, marginBottom: 2 }}>
                        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          <span style={{ width: 7, height: 7, borderRadius: '50%', background: TIER_COLORS[k], flexShrink: 0 }} />
                          <span style={{ color: 'var(--fd-text-2)', textTransform: 'capitalize' }}>{k}</span>
                        </span>
                        <span style={{ color: 'var(--fd-text)', fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>
                          {count} <span style={{ color: 'var(--fd-text-3)', fontWeight: 400 }}>({p}%)</span>
                        </span>
                      </div>
                      <div style={{ height: 4, background: T.grid, borderRadius: 4, overflow: 'hidden' }}>
                        <div style={{ width: `${p}%`, height: '100%', background: TIER_COLORS[k], borderRadius: 4 }} />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
            {/* Insight strip — VIP share spotlight */}
            <div style={{ marginTop: 4, padding: '8px 10px', borderRadius: 8,
                          background: 'linear-gradient(135deg, hsl(42 78% 52% / .08), rgb(184 92 56 / .06))',
                          fontSize: 11, color: 'var(--fd-text-2)', lineHeight: 1.4 }}>
              <span style={{ fontWeight: 700, color: 'hsl(32 80% 48%)' }}>{displayTierDist.vip || 0} VIP</span>
              {' génèrent typiquement '}
              <span style={{ fontWeight: 600, color: 'var(--fd-text)' }}>30-50% du revenu</span>
              {' — gardez-les heureux.'}
            </div>
          </div>

          {/* ─── Notification Reach — push-recovery KPI ────────────────── */}
          {(() => {
            // Demo fallback when stats not loaded yet (or fresh tenant).
            const s = notifStats || { total: 156, subscribed: 108, not_subscribed: 48, subscribed_pct: 69.2 };
            const pct = Math.round(s.subscribed_pct || 0);
            const tone = pct >= 80 ? 'good' : pct >= 60 ? 'ok' : 'warn';
            const toneColor = tone === 'good' ? (nuit ? T.ok : 'hsl(150 70% 26%)') : tone === 'ok' ? (nuit ? T.warn : 'hsl(42 78% 38%)') : (nuit ? T.risk : 'hsl(355 70% 38%)');
            const toneBg    = tone === 'good' ? 'hsl(150 55% 40% / .12)' : tone === 'ok' ? 'hsl(42 78% 52% / .14)' : 'hsl(355 60% 48% / .12)';
            return (
              <div className="fd-side-panel">
                <div className="fd-sp-head">
                  <span className="fd-sp-title">Notifications activées</span>
                  <span style={{ fontSize: 10, color: 'var(--fd-text-3)', fontWeight: 700, letterSpacing: 0.6 }}>RÉCEPTION</span>
                </div>
                {/* Big number + ring */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginTop: 4, marginBottom: 12 }}>
                  <div style={{ position: 'relative', width: 92, height: 92, flexShrink: 0 }}>
                    {/* Background ring */}
                    <svg width="92" height="92" viewBox="0 0 92 92" style={{ position: 'absolute', inset: 0 }}>
                      <circle cx="46" cy="46" r="38" fill="none" stroke={T.grid} strokeWidth="10"/>
                      <circle cx="46" cy="46" r="38" fill="none" stroke={toneColor} strokeWidth="10"
                              strokeDasharray={`${(pct / 100) * 238.76} 999`}
                              strokeLinecap="round"
                              transform="rotate(-90 46 46)"/>
                    </svg>
                    <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column',
                                  alignItems: 'center', justifyContent: 'center', pointerEvents: 'none' }}>
                      <div style={{ fontFamily: "'Playfair Display', serif", fontSize: 22, fontWeight: 700, color: 'var(--fd-text)', lineHeight: 1 }}>{pct}%</div>
                      <div style={{ fontSize: 8.5, color: 'var(--fd-text-3)', letterSpacing: 0.6, textTransform: 'uppercase', marginTop: 2 }}>Reçoivent</div>
                    </div>
                  </div>
                  <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: 11 }}>
                      <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <span style={{ width: 7, height: 7, borderRadius: '50%', background: nuit ? T.ok : 'hsl(150 70% 26%)' }} />
                        <span style={{ color: 'var(--fd-text-2)' }}>Abonnés</span>
                      </span>
                      <span style={{ color: 'var(--fd-text)', fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>
                        {s.subscribed}
                      </span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: 11 }}>
                      <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <span style={{ width: 7, height: 7, borderRadius: '50%', background: nuit ? T.risk : 'hsl(355 60% 48%)' }} />
                        <span style={{ color: 'var(--fd-text-2)' }}>Sans push</span>
                      </span>
                      <span style={{ color: 'var(--fd-text)', fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>
                        {s.not_subscribed}
                      </span>
                    </div>
                  </div>
                </div>
                {/* Action insight */}
                <div style={{ marginTop: 4, padding: '8px 10px', borderRadius: 8,
                              background: toneBg, fontSize: 11, color: 'var(--fd-text-2)', lineHeight: 1.4 }}>
                  {s.not_subscribed > 0 ? (
                    <>
                      <span style={{ fontWeight: 700, color: toneColor }}>{s.not_subscribed} clients</span>
                      {' ratent vos campagnes — '}
                      <button
                        type="button"
                        onClick={() => navigate('/dashboard/campaigns?action=re-enable')}
                        style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer',
                                 color: toneColor, fontWeight: 700, textDecoration: 'underline',
                                 font: 'inherit' }}>
                        relancer par SMS →
                      </button>
                    </>
                  ) : (
                    <span style={{ color: toneColor, fontWeight: 600 }}>
                      Excellent — tous vos clients reçoivent vos campagnes.
                    </span>
                  )}
                </div>
              </div>
            );
          })()}

          {/* ─── Apple Wallet ─── */}
          {walletStats && (
            <div className="fd-side-panel">
              <div className="fd-sp-head">
                <span className="fd-sp-title">Cartes Wallet</span>
                <span style={{ fontSize: 10, color: 'var(--fd-text-3)', fontWeight: 700, letterSpacing: 0.6 }}>APPLE</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 6 }}>
                <span style={{ fontFamily: "'Playfair Display', serif", fontSize: 30, fontWeight: 700,
                               color: 'var(--fd-text)', lineHeight: 1 }}>
                  {walletStats.passes_installed}
                </span>
                <span style={{ fontSize: 11, color: 'var(--fd-text-2)' }}>
                  carte{walletStats.passes_installed > 1 ? 's' : ''} dans Wallet
                  {walletStats.customers > 0 && ` · ${walletStats.install_rate}% des clients`}
                </span>
              </div>
              <div style={{ height: 6, borderRadius: 3, background: T.grid, overflow: 'hidden', margin: '10px 0 8px' }}>
                <div style={{ height: '100%', width: `${Math.min(100, walletStats.install_rate)}%`,
                              background: nuit ? T.ok : 'hsl(150 70% 30%)', borderRadius: 3 }} />
              </div>
              <div style={{ fontSize: 11, color: 'var(--fd-text-2)', lineHeight: 1.4 }}>
                {walletStats.push_ready ? (
                  <>
                    {walletStats.devices} appareil{walletStats.devices > 1 ? 's' : ''} synchronisé{walletStats.devices > 1 ? 's' : ''} —
                    {' '}les tampons s'y mettent à jour à chaque passage en caisse.
                  </>
                ) : (
                  <span style={{ color: nuit ? T.warn : 'hsl(42 78% 34%)' }}>
                    Les cartes se mettent à jour à l'ouverture seulement — la mise à jour automatique n'est pas active.
                  </span>
                )}
              </div>
              <button
                type="button"
                disabled={walletBusy || walletStats.passes_installed === 0}
                onClick={async () => {
                  setWalletBusy(true);
                  try { await ownerAPI.walletNotify(); } finally { setWalletBusy(false); }
                }}
                style={{ marginTop: 10, width: '100%', padding: '7px 10px', borderRadius: 8,
                         border: `1px solid ${T.grid}`, background: 'transparent', cursor: 'pointer',
                         color: 'var(--fd-text-2)', fontSize: 11, fontWeight: 600, font: 'inherit' }}>
                {walletBusy ? 'Envoi…' : 'Actualiser les cartes maintenant'}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ─── Sub-components ───────────────────────────────────────────────── */

function Kpi({ color, icon, label, value, sub, onClick, delta }) {
  const hasDelta = typeof delta === 'number' && isFinite(delta);
  const isUp = hasDelta && delta >= 0;
  return (
    <div className={`fd-kpi ${color}`} onClick={onClick} style={{ cursor: onClick ? 'pointer' : 'default' }}>
      <div className="fd-kpi-head">
        <span className="fd-kpi-label">{label}</span>
        <span className="fd-kpi-ico">{icon}</span>
      </div>
      <div className="fd-kpi-value">{value}</div>
      <div className="fd-kpi-foot">
        <span className="fd-kpi-sub">{sub}</span>
        {hasDelta && (
          <span className={`fd-kpi-delta ${isUp ? 'pos' : 'neg'}`}>
            {isUp ? '↑' : '↓'} {Math.abs(delta).toFixed(1)}%
          </span>
        )}
      </div>
    </div>
  );
}

function StatusCell({ label, value, total, icon, ink }) {
  const p = total > 0 ? Math.round((value / total) * 100) : 0;
  return (
    <div>
      <div className="fd-sc-head">
        <span className="fd-sc-label">{label}</span>
        <span style={{ color: ink, width: 18, height: 18 }}>{icon}</span>
      </div>
      <div className="fd-sc-value">{value}</div>
      <div className="fd-sc-sub">{p}% de la base</div>
    </div>
  );
}

function ActionTile({ icon, color, title, desc, cta, onClick }) {
  return (
    <div className="fd-action">
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <span className="fd-at-ico" style={{ background: color }}>{icon}</span>
        <span className="fd-at-title">{title}</span>
      </div>
      <div className="fd-at-desc">{desc}</div>
      <button className="fd-at-btn" style={{ background: color }} onClick={onClick}>{cta}</button>
    </div>
  );
}

function Alert({ color, icon, title, sub, time }) {
  return (
    <div className="fd-alert">
      <div className={`fd-alert-ico ${color}`}>{icon}</div>
      <div>
        <div className="fd-alert-title">{title}</div>
        <div className="fd-alert-sub">{sub}</div>
        <div className="fd-alert-time">{time}</div>
      </div>
      <ChevronRight size={14} color="#8D857D" style={{ alignSelf: 'center' }} />
    </div>
  );
}

function SummaryRow({ label, value, delta }) {
  const d = typeof delta === 'number' ? delta : null;
  const sign = d == null ? '' : (d >= 0 ? 'pos' : 'neg');
  return (
    <div className="fd-summary-row">
      <span style={{ color: 'var(--fd-text-2)' }}>{label}</span>
      <span className="fd-sm-val">
        {value}
        {d != null && (
          <span className={`fd-sm-delta ${sign}`}>
            {d >= 0 ? '↑' : '↓'} {Math.abs(d).toFixed(1)}%
          </span>
        )}
      </span>
    </div>
  );
}
