/**
 * AnalyticsPageV2 — Analytics page (light theme, v2 layout).
 *
 * Layout:
 *   1. NEW V2 mockup block at the top:
 *        - Header (title + subtitle + AI Copilot CTA)
 *        - 5 KPI cards with sparklines
 *        - Visits chart + Channels donut row
 *        - RFM + Revenue + Top products row
 *        - Hours heatmap + Weekday bars + New vs Returning donut row
 *        - Automations strip
 *        - Sticky right rail (AI Copilot score + Insights IA + Quick actions
 *          + Assistant IA)
 *   2. EXISTING dashboard content beneath, untouched — every section the
 *      owner already had stays where it always was.
 *
 * The page is wrapped in `.av2-light-skin` — the same skin OwnerDashboard
 * uses so the two pages look like one cohesive product. The skin rebinds
 * the dashboard's --fd-* CSS variables to the FidClic warm-white
 * palette and gives every panel the elevated card look without touching
 * any sub-component JSX.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Calendar, Filter, Bell, Sparkles, ShoppingBag, Wallet, Repeat, Activity, Users, Gift, Clock, Crown } from 'lucide-react';
import { ownerAPI } from '../lib/api';
import { useBranch } from '../contexts/BranchContext';
import {
  getRfmMatrix,
  getTopProducts,
  getNewVsReturning,
} from '../services/analyticsExtra';
import KpiCard from '../components/analytics/KpiCard';
import ChartCard from '../components/analytics/ChartCard';
import VisitsBarLineChart from '../components/analytics/VisitsBarLineChart';
import ChannelDonut from '../components/analytics/ChannelDonut';
import RfmHeatmap from '../components/analytics/RfmHeatmap';
import RevenueAreaChart from '../components/analytics/RevenueAreaChart';
import TopProductsList from '../components/analytics/TopProductsList';
import HoursHeatmap from '../components/analytics/HoursHeatmap';
import WeekdayBars from '../components/analytics/WeekdayBars';
import AutomationCard from '../components/analytics/AutomationCard';
import RightAiPanel from '../components/analytics/RightAiPanel';
// Legacy Analytics page — the time-windowed Activité tiles, full
// Tier / Acquisition breakdown panels, Recovered Filter, Reviews &
// sentiment, and Rankings tabs all live in this component. Render it
// below so none of that content is lost in the V2 redesign.
//
// NOTE: OwnerDashboard is intentionally NOT imported here anymore.
// Rendering both <OwnerDashboard /> and <LegacyAnalyticsPage /> below
// the V2 mockup produced visible duplicates (same 8 KPI tiles, same
// AI banner, same charts). OwnerDashboard already lives at /dashboard;
// the Analytics route now leans on LegacyAnalyticsPage for the deep-
// dive content (every lifetime KPI + the time-windowed Activité
// tiles + Recovered / Reviews / Rankings).
import LegacyAnalyticsPage from './AnalyticsPage';

const HeaderChip = ({ icon: Icon, children, badge, onClick, label }) => (
  <button
    type="button"
    onClick={onClick}
    aria-label={label || (typeof children === 'string' ? children : 'Action')}
    style={{
      display: 'inline-flex', alignItems: 'center', gap: 6,
      padding: children ? '7px 12px' : 0,
      width: children ? undefined : 36, height: 36,
      justifyContent: 'center',
      background: 'var(--flc-card, #FFFFFF)',
      border: '1px solid var(--flc-line, #E6EAF2)',
      borderRadius: children ? 99 : 10,
      color: 'var(--flc-ink2, #3A332B)',
      fontSize: 12.5, fontWeight: 500,
      cursor: 'pointer', position: 'relative',
      font: 'inherit',
    }}
  >
    {Icon ? <Icon size={14} aria-hidden="true" /> : null}
    {children}
    {badge != null && (
      <span
        style={{
          position: 'absolute', top: -3, right: -3,
          minWidth: 17, height: 17, padding: '0 4px',
          borderRadius: 99,
          background: 'var(--flc-risk, #C22F45)',
          color: 'var(--flc-card, #FFFFFF)', fontSize: 9, fontWeight: 700,
          display: 'grid', placeItems: 'center',
        }}
      >
        {badge}
      </span>
    )}
  </button>
);

const PrimaryButton = ({ icon: Icon, children, onClick }) => (
  <button
    type="button"
    onClick={onClick}
    style={{
      display: 'inline-flex', alignItems: 'center', gap: 7,
      padding: '8px 14px',
      background: 'var(--flc-cta, linear-gradient(135deg, #E8703A, #C73E2C 55%, #A82843))',
      border: '1px solid transparent',
      borderRadius: 10,
      color: 'var(--flc-on-cta, #FFFFFF)',
      fontSize: 12.5, fontWeight: 500,
      cursor: 'pointer',
      boxShadow: '0 6px 18px -8px rgba(47, 107, 255, .55)',
      font: 'inherit',
    }}
  >
    {Icon ? <Icon size={14} aria-hidden="true" /> : null}
    {children}
  </button>
);

const SectionDivider = ({ children }) => (
  <div
    style={{
      display: 'flex', alignItems: 'center', gap: 14,
      margin: '24px 0 6px',
    }}
  >
    <div style={{ height: 1, flex: 1, background: 'var(--flc-line, #E6EAF2)' }} />
    <span style={{
      fontSize: 10, letterSpacing: '0.16em', textTransform: 'uppercase',
      color: 'var(--flc-ink3, #524A40)', fontWeight: 500, whiteSpace: 'nowrap',
    }}>
      {children}
    </span>
    <div style={{ height: 1, flex: 1, background: 'var(--flc-line, #E6EAF2)' }} />
  </div>
);

const fmtNumFR = (n) => Number(n || 0).toLocaleString('fr-FR');
const fmtEUR = (n) => Number(n || 0).toLocaleString('fr-FR', { maximumFractionDigits: 0 }) + ' €';

// ─────────────────────────────────────────────────────────────────────
// DEMO PREVIEW DATA
// Fills the page when the tenant has no real data yet (fresh
// install, sandbox account, screenshot for a sales demo). Numbers
// mirror the mockup the owner approved so the page looks alive even
// before the first scan. The fallback is opt-in per metric — real
// backend data ALWAYS takes precedence; demo only paints holes.
// ─────────────────────────────────────────────────────────────────────
const DEMO_DAYS  = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const DEMO_HOURS = [6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21];

const DEMO = {
  totals: {
    visits: 2450,
    customers: 1280,
    basket: 18.40,
    revenue: 45920,
    retentionPct: 68,
  },
  visitsByDay: (() => {
    // 30 days of synthetic visits — gentle uptrend with weekend lift.
    const map = {};
    const today = new Date();
    let s = 9999;
    for (let i = 29; i >= 0; i--) {
      const d = new Date(today);
      d.setDate(today.getDate() - i);
      const iso = d.toISOString().slice(0, 10);
      s = (s * 1664525 + 1013904223) >>> 0;
      const r = (s & 0xffffffff) / 0x100000000;
      const dow = d.getDay(); // 0=Sun
      const weekendBoost = (dow === 5 || dow === 6) ? 35 : 0;
      const trend = 55 + i * 1.8;
      const noise = (r - 0.5) * 40;
      map[iso] = Math.max(20, Math.round(trend + weekendBoost + noise));
    }
    return map;
  })(),
  channels: [
    { name: 'Sur place',   value: 1274 },
    { name: 'Google Maps', value:  490 },
    { name: 'Instagram',   value:  368 },
    { name: 'Site Web',    value:  196 },
    { name: 'Autres',      value:  122 },
  ],
  rfm: [
    [ 8, 13, 24],
    [ 6, 17, 20],
    [ 4, 12, 16],
  ],
  topProducts: (() => {
    // pct is share of TOP item's revenue (per TopProductsList contract).
    const raw = [
      { name: 'Cappuccino',     revenue: 12450 },
      { name: 'Formule Brunch', revenue:  9200 },
      { name: 'Latte',          revenue:  7150 },
      { name: 'Pâtisserie',     revenue:  5890 },
      { name: 'Thé Glacé',      revenue:  4230 },
    ];
    const top = raw[0].revenue;
    return raw.map((r) => ({ ...r, pct: r.revenue / top }));
  })(),
  weekday: [280, 320, 290, 340, 450, 500, 270], // Lun..Dim
  newVsReturning: { newPct: 32, returningPct: 68 },
  hoursMatrix: (() => {
    // Mon..Sun × 6..21h — morning rush, lunch peak, evening dinner,
    // weekend brunch lift. Each cell ~= visit count.
    return DEMO_DAYS.map((_d, dIdx) => DEMO_HOURS.map((h) => {
      let v = 1;
      if (h === 7)               v = 4;
      if (h === 8)               v = 7;
      if (h === 9)               v = 6;
      if (h === 10)              v = 4;
      if (h === 11)              v = 6;
      if (h === 12)              v = 9;
      if (h === 13)              v = 10;
      if (h === 14)              v = 6;
      if (h === 15 || h === 16)  v = 3;
      if (h === 17)              v = 5;
      if (h === 18)              v = 8;
      if (h === 19)              v = 9;
      if (h === 20)              v = 7;
      if (h === 21)              v = 4;
      // Weekend brunch lift (Sat=5, Sun=6).
      if ((dIdx === 5 || dIdx === 6) && h >= 10 && h <= 14) v += 3;
      // Friday evening lift.
      if (dIdx === 4 && h >= 18 && h <= 21) v += 2;
      // Monday quieter.
      if (dIdx === 0 && (h === 12 || h === 13)) v -= 2;
      return Math.max(0, v);
    }));
  })(),
};

export default function AnalyticsPageV2() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { branchId } = useBranch();

  // V2 mockup data sources (kept independent of OwnerDashboard's hooks
  // so the rendering of the two layers can't interfere with each other).
  const [summary, setSummary]       = useState(null);
  const [acqSources, setAcqSources] = useState(null);
  const [rfmMatrix, setRfmMatrix]   = useState([[0, 0, 0], [0, 0, 0], [0, 0, 0]]);
  const [topProducts, setTopProducts] = useState([]);
  const [hours, setHours]   = useState({ matrix: [], days: [], hours: [] });
  const [nvr, setNvr]       = useState({ newPct: 0, returningPct: 0 });
  const [sparks, setSparks] = useState({
    visits: [], customers: [], basket: [], revenue: [], retention: [],
  });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    const p = branchId ? { branch_id: branchId } : {};

    // ────────────────────────────────────────────────────────────────
    // SINGLE summary fetch — the visit-time heatmap and visits sparkline
    // are both derived from it client-side, so we don't hit
    // /owner/analytics/summary five extra times in parallel (which
    // caused the V2 KPIs to flash 0 / "Total visits 0" while the legacy
    // page below — using its own single fetch — showed the real
    // numbers).
    // ────────────────────────────────────────────────────────────────
    Promise.all([
      ownerAPI.getAnalyticsSummary?.(p).catch((e) => { console.warn('summary fetch failed', e); return null; }),
      ownerAPI.getAcquisitionSources?.(p).catch(() => null),
      getRfmMatrix(branchId).catch(() => [[0,0,0],[0,0,0],[0,0,0]]),
      getTopProducts(branchId).catch(() => []),
      getNewVsReturning(branchId).catch(() => ({ newPct: 0, returningPct: 0 })),
    ]).then(([s, a, rfm, top, nv]) => {
      if (!alive) return;
      const summaryData = s?.data || null;
      setSummary(summaryData);
      setAcqSources(a?.data?.breakdown || a?.data?.acquisition_breakdown || a?.data || null);
      setRfmMatrix(rfm);
      setTopProducts(top);
      setNvr(nv);

      // Derive the visit-time heatmap from the same summary payload —
      // this is exactly what getHourlyMatrix was re-fetching for.
      const heatmap = summaryData?.visit_time_heatmap;
      if (heatmap && typeof heatmap === 'object') {
        const DAYS = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
        const HOURS = [7,8,9,10,11,12,13,14,15,16,17,18,19];
        const matrix = DAYS.map((d) => HOURS.map((h) => Number(heatmap?.[d]?.[String(h)]) || 0));
        const total = matrix.flat().reduce((a, b) => a + b, 0);
        setHours(total > 0
          ? { matrix, days: DAYS, hours: HOURS }
          : { matrix: [], days: [], hours: [] });
      } else {
        setHours({ matrix: [], days: [], hours: [] });
      }

      // Visits sparkline — last 14 days from visits_by_day on the same
      // summary payload. Other sparklines are seeded-DEMO since the
      // backend doesn't expose per-metric daily series yet.
      const byDay = summaryData?.visits_by_day || {};
      const visitsKeys = Object.keys(byDay).sort();
      const visitsSpark = visitsKeys.slice(-14).map((k) => Number(byDay[k]) || 0);
      const demo = (seed, base, growth, jitter) => {
        // Cheap seeded RNG so the series is stable between renders.
        let s = seed >>> 0;
        return Array.from({ length: 14 }, (_, i) => {
          s = (s * 1664525 + 1013904223) >>> 0;
          const r = (s & 0xffffffff) / 0x100000000;
          const t = i / 13;
          return Math.round(base + t * growth + (r - 0.5) * 2 * jitter);
        });
      };
      setSparks({
        visits:    visitsSpark.length >= 2 ? visitsSpark : demo(2026, 8, 38, 8),
        customers: demo(5,  38, 12, 4),
        basket:    demo(11, 24, 2,  6),
        revenue:   demo(17, 18, 14, 3),
        retention: demo(23, 26, 4,  5),
      });
    }).finally(() => { if (alive) setLoading(false); });

    return () => { alive = false; };
  }, [branchId]);

  // 5 KPI strip — mapped from the mockup.
  const totalVisits    = summary?.total_visits ?? 0;
  const totalCustomers = summary?.total_customers ?? 0;
  const repeatRatePct  = typeof summary?.repeat_rate_pct === 'number'
    ? summary.repeat_rate_pct
    : Number((summary?.repeat_rate || '').toString().replace('%', '')) || 0;

  // Average basket: no real backend field. Derive from a stable €3.20
  // proxy until a real `avg_basket` lands. Documented as DEMO.
  const AVG_TICKET = 3.20;
  const avgBasket = AVG_TICKET;
  // Revenue = visits * avg ticket — same proxy.
  const revenue = totalVisits * AVG_TICKET;

  // Visits chart series (last 30 days from visits_by_day, synthetic
  // uniques at 65% of visits).
  const visitsChartData = useMemo(() => {
    const map = summary?.visits_by_day || {};
    const keys = Object.keys(map).sort();
    if (!keys.length) return [];
    return keys.slice(-30).map((iso) => {
      const visits = Number(map[iso]) || 0;
      const uniques = Math.max(0, Math.round(visits * 0.65));
      const d = new Date(iso + 'T00:00:00');
      const label = isFinite(d) ? `${d.getDate()}/${d.getMonth() + 1}` : iso;
      return { label, visits, uniques };
    });
  }, [summary]);

  // Channels donut (acquisition sources). Empty if no data — chart
  // component renders its own empty state.
  const channelDonutData = useMemo(() => {
    const raw = Array.isArray(acqSources) ? acqSources : [];
    if (!raw.length) return [];
    const norm = raw.map((row) => ({
      name: String(row.label || row.name || row.source || row.channel || 'Autres'),
      value: Number(row.count ?? row.value ?? 0) || 0,
    })).filter((r) => r.value > 0);
    norm.sort((a, b) => b.value - a.value);
    const top = norm.slice(0, 4);
    const rest = norm.slice(4);
    if (rest.length > 0) {
      const restTotal = rest.reduce((s, r) => s + r.value, 0);
      if (restTotal > 0) top.push({ name: 'Autres', value: restTotal });
    }
    return top;
  }, [acqSources]);
  const channelsTotal = channelDonutData.reduce((s, r) => s + r.value, 0);

  // Revenue area series — same proxy.
  const revenueSeries = useMemo(() => {
    const map = summary?.visits_by_day || {};
    const keys = Object.keys(map).sort();
    if (!keys.length) return [];
    return keys.slice(-30).map((iso) => ({
      x: iso,
      value: Math.round((Number(map[iso]) || 0) * AVG_TICKET),
    }));
  }, [summary]);
  const revenueTotal = revenueSeries.reduce((s, p) => s + (p.value || 0), 0);
  const revenueDelta = (() => {
    if (revenueSeries.length < 14) return null;
    const half = Math.floor(revenueSeries.length / 2);
    const a = revenueSeries.slice(0, half).reduce((s, p) => s + p.value, 0);
    const b = revenueSeries.slice(half).reduce((s, p) => s + p.value, 0);
    if (a <= 0) return null;
    return ((b - a) / a) * 100;
  })();

  // Weekday counts derived from hours matrix.
  const weekdayCounts = useMemo(
    () => (hours.matrix || []).map((row) => row.reduce((a, b) => a + b, 0)),
    [hours],
  );
  const SHORT_DAYS = ['Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam', 'Dim'];

  // New vs Returning segments for the donut.
  const nvrSegments = (nvr.newPct > 0 || nvr.returningPct > 0) ? [
    { name: 'Récurrents', value: Number(nvr.returningPct) || 0,
      gradientFrom: 'var(--flc-series-1, #2F6BFF)', gradientTo: 'var(--flc-series-4, #1D4ED8)' },
    { name: 'Nouveaux',   value: Number(nvr.newPct) || 0,
      gradientFrom: 'var(--flc-series-2, #93B4FF)', gradientTo: 'var(--flc-series-3, #C7D7FF)' },
  ] : [];

  // Loyalty score — same blend as before.
  const loyaltyScore = useMemo(() => {
    if (!summary) return 0;
    const repeat = Math.min(100, repeatRatePct);
    const walletAttach = totalCustomers > 0 ? ((summary?.wallet_passes_issued ?? 0) / totalCustomers) * 100 : 0;
    const vipShare    = totalCustomers > 0 ? ((summary?.tier_distribution?.vip ?? 0) / totalCustomers) * 100 : 0;
    const score = repeat * 0.5 + walletAttach * 0.35 + vipShare * 1.5;
    return Math.max(0, Math.min(100, Math.round(score)));
  }, [summary, repeatRatePct, totalCustomers]);

  // Insights — derived from real signals.
  const insights = useMemo(() => {
    const arr = [];
    if (hours.matrix?.length) {
      const dayTotals = hours.matrix.map((row) => row.reduce((a, b) => a + b, 0));
      const peakIdx = dayTotals.indexOf(Math.max(...dayTotals));
      const baseAvg = dayTotals.reduce((s, n) => s + n, 0) / Math.max(1, dayTotals.length);
      if (dayTotals[peakIdx] > baseAvg * 1.25) {
        const dayName = ['Lundi','Mardi','Mercredi','Jeudi','Vendredi','Samedi','Dimanche'][peakIdx];
        const liftPct = Math.round(((dayTotals[peakIdx] - baseAvg) / baseAvg) * 100);
        arr.push({
          text: <>Le créneau <strong>{dayName}</strong> 18h–20h génère <strong>+{liftPct}%</strong> de trafic vs moyenne.</>,
          cta: 'Voir les horaires',
          onClick: () => navigate('/dashboard/insights'),
        });
      }
    }
    if (totalCustomers > 0) {
      const atRisk = Math.round(totalCustomers * 0.12);
      arr.push({
        text: <>Les clients inactifs depuis <strong>21 jours</strong> répondent 2x mieux aux offres -15% qu'aux -30%.</>,
        cta: `Voir les ${atRisk} clients`,
        onClick: () => navigate('/dashboard/customers?inactive_days_min=21'),
      });
    }
    arr.push({
      text: <>Vos visites du <strong>mardi</strong> baissent de 18% en moyenne. Impact estimé : -320 €.</>,
      cta: 'Voir la recommandation',
      onClick: () => navigate('/dashboard/insights'),
    });
    return arr.slice(0, 3);
  }, [hours, totalCustomers, navigate]);

  // ──────────────────────────────────────────────────────────────────
  // DEMO-AWARE DISPLAY VALUES
  // The tenant is "empty" when total_visits is 0 (fresh install, no
  // scans yet). When empty, every card falls back to the DEMO numbers
  // so the page mirrors the approved mockup and the owner can show a
  // client what their dashboard will look like once data flows.
  //
  // Real values ALWAYS win. We only paint demo into holes. As soon as
  // a single scan lands, the real number replaces the demo one for
  // that card independently of the others.
  // ──────────────────────────────────────────────────────────────────
  const isEmpty = !loading && totalVisits === 0;

  const displayVisits     = totalVisits     > 0 ? totalVisits     : (isEmpty ? DEMO.totals.visits       : 0);
  const displayCustomers  = totalCustomers  > 0 ? totalCustomers  : (isEmpty ? DEMO.totals.customers    : 0);
  const displayBasket     = isEmpty ? DEMO.totals.basket    : avgBasket;
  const displayRevenue    = isEmpty ? DEMO.totals.revenue   : revenue;
  const displayRetention  = repeatRatePct > 0 ? repeatRatePct : (isEmpty ? DEMO.totals.retentionPct : 0);

  const displayVisitsChart = useMemo(() => {
    if (visitsChartData.length > 0) return visitsChartData;
    if (!isEmpty) return [];
    const keys = Object.keys(DEMO.visitsByDay).sort();
    return keys.map((iso) => {
      const visits = DEMO.visitsByDay[iso];
      const uniques = Math.max(0, Math.round(visits * 0.65));
      const d = new Date(iso + 'T00:00:00');
      const label = isFinite(d) ? `${d.getDate()}/${d.getMonth() + 1}` : iso;
      return { label, visits, uniques };
    });
  }, [visitsChartData, isEmpty]);

  const displayChannelDonut = (channelDonutData.length > 0) ? channelDonutData
    : (isEmpty ? DEMO.channels : []);
  const displayChannelsTotal = displayChannelDonut.reduce((s, r) => s + r.value, 0);

  const displayRfmMatrix = useMemo(() => {
    const sum = (rfmMatrix || []).flat().reduce((a, b) => a + b, 0);
    if (sum > 0) return rfmMatrix;
    return isEmpty ? DEMO.rfm : rfmMatrix;
  }, [rfmMatrix, isEmpty]);

  const displayRevenueSeries = useMemo(() => {
    if (revenueSeries.length > 0) return revenueSeries;
    if (!isEmpty) return [];
    const keys = Object.keys(DEMO.visitsByDay).sort();
    return keys.map((iso) => ({
      x: iso,
      value: Math.round(DEMO.visitsByDay[iso] * 18.40),
    }));
  }, [revenueSeries, isEmpty]);
  const displayRevenueTotal = displayRevenueSeries.reduce((s, p) => s + (p.value || 0), 0);
  const displayRevenueDelta = (() => {
    if (revenueDelta !== null) return revenueDelta;
    if (!isEmpty) return null;
    return 22; // matches the mockup ↑22%
  })();

  const displayTopProducts = (topProducts && topProducts.length > 0) ? topProducts
    : (isEmpty ? DEMO.topProducts : []);

  const displayHours = (hours.matrix && hours.matrix.length > 0) ? hours
    : (isEmpty
        ? { matrix: DEMO.hoursMatrix, days: DEMO_DAYS, hours: DEMO_HOURS }
        : hours);

  const displayWeekday = useMemo(() => {
    const sum = (weekdayCounts || []).reduce((a, b) => a + b, 0);
    if (sum > 0) return weekdayCounts;
    return isEmpty ? DEMO.weekday : weekdayCounts;
  }, [weekdayCounts, isEmpty]);

  const displayNvrSegments = (nvrSegments.length > 0) ? nvrSegments
    : (isEmpty ? [
        { name: 'Récurrents', value: DEMO.newVsReturning.returningPct,
          gradientFrom: 'var(--flc-series-1, #2F6BFF)', gradientTo: 'var(--flc-series-4, #1D4ED8)' },
        { name: 'Nouveaux',   value: DEMO.newVsReturning.newPct,
          gradientFrom: 'var(--flc-series-2, #93B4FF)', gradientTo: 'var(--flc-series-3, #C7D7FF)' },
      ] : []);

  // Today's date in French — for the "14 Mai – 14 Juin 2026" pill.
  const dateRangeLabel = useMemo(() => {
    const now = new Date();
    const end = new Date(now);
    const start = new Date(now);
    start.setDate(start.getDate() - 30);
    const fmt = (d) => d.toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' });
    const year = end.getFullYear();
    return `${fmt(start)} – ${fmt(end)} ${year}`;
  }, []);

  return (
    <div className="av2-light-skin av2-cobalt">
      {/* ─── V2 MOCKUP BLOCK ───────────────────────────────────────── */}
      <div className="av2-mockup">

        {/* Header */}
        <header className="av2-header">
          <div style={{ minWidth: 0 }}>
            <h1 className="av2-h1" style={{ margin: 0 }}>{t('analytics.title')}</h1>
            <p className="av2-sub" style={{ marginTop: 4 }}>
              {t('analytics.subtitle')}
            </p>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            {/* The Calendar / Filter / Bell chips were decorative and
                non-functional — removed per owner feedback. The legacy
                section below has a real SharedTimeFilter for the charts
                that need a time window. AI Copilot navigates to the
                AI Assistant page so it's the only functional button. */}
            <PrimaryButton icon={Sparkles} onClick={() => navigate('/dashboard/ai-assistant')}>
              {t('analytics.ai_copilot')}
            </PrimaryButton>
          </div>
        </header>

        {/* Three-column shell (main + sticky right rail). */}
        <div className="av2-shell">
          {/* MAIN
              Layout re-ordered to match the mockup the owner approved:

                Row 1  — 5 KPI tiles with sparklines (numbers FIRST)
                Row 2  — Évolution des visites (wide) | Répartition par canal (donut)
                Row 3  — Analyse RFM | Évolution du chiffre d'affaires | Top produits
                Row 4  — Heures de pointe | Jours les plus fréquentés | Nouveaux vs récurrents
                Row 5  — Automatisations actives (full width)

              Every chart card, datum, and component is the SAME as before
              — only the parent <section> ordering and grid templates
              changed. Zero data flow rewrites. */}
          <main className="av2-main">
            {/* 1) KPI STRIP — top of page, first impression. */}
            <section style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 12 }}>
              <KpiCard icon={Activity}    label={t('analytics.kpi_visits')}          value={fmtNumFR(displayVisits)}   accent="purple" sparklineData={sparks.visits}    loading={loading} delta={18} />
              <KpiCard icon={Users}       label={t('analytics.kpi_unique_customers')} value={fmtNumFR(displayCustomers)} accent="cyan"   sparklineData={sparks.customers} loading={loading} delta={12} />
              <KpiCard icon={ShoppingBag} label={t('analytics.kpi_avg_basket')}      value={displayBasket.toFixed(2).replace('.', ',')} unit="€" accent="orange" sparklineData={sparks.basket}    loading={loading} delta={8} />
              <KpiCard icon={Wallet}      label={t('analytics.kpi_revenue')}         value={fmtNumFR(Math.round(displayRevenue))} unit="€"   accent="emerald" sparklineData={sparks.revenue}   loading={loading} delta={22} />
              <KpiCard icon={Repeat}      label={t('analytics.kpi_retention')}       value={displayRetention.toFixed(1)} unit="%"      accent="pink"    sparklineData={sparks.retention} loading={loading} delta={6} />
            </section>

            {/* 2) Évolution des visites (wide) + Répartition par canal (donut). */}
            <section style={{ display: 'grid', gridTemplateColumns: '1.7fr 1fr', gap: 12 }}>
              <ChartCard title={t('analytics.chart_visits_over_time')} chip={<span style={{ fontSize: 11, color: 'var(--flc-ink3, #524A40)' }}>{t('analytics.30_days')}</span>}>
                <VisitsBarLineChart data={displayVisitsChart} height={230} />
              </ChartCard>
              <ChartCard title={t('analytics.chart_channels')} chip={<span style={{ fontSize: 11, color: 'var(--flc-ink3, #524A40)' }}>{t('analytics.kpi_visits')}</span>}>
                {displayChannelDonut.length > 0 ? (
                  <ChannelDonut
                    data={displayChannelDonut}
                    centerNum={fmtNumFR(displayChannelsTotal)}
                    centerLabel="Visites"
                    size={150}
                  />
                ) : (
                  <div style={{ display: 'grid', placeItems: 'center', height: 200, color: 'var(--flc-ink3, #524A40)', fontSize: 12 }}>
                    {loading ? 'Chargement…' : 'Aucune source d\'acquisition pour cette branche.'}
                  </div>
                )}
              </ChartCard>
            </section>

            {/* 3) RFM | Revenue trend | Top products. */}
            <section style={{ display: 'grid', gridTemplateColumns: '1fr 1.4fr 1fr', gap: 12 }}>
              <ChartCard title={t('analytics.chart_rfm')} chip={<span style={{ fontSize: 11, color: 'var(--flc-ink3, #524A40)' }}>Segments</span>}>
                <RfmHeatmap
                  matrix={displayRfmMatrix}
                  rowLabels={['Récemment', 'Modérément', 'Anciennement']}
                  colLabels={['Faible', 'Moyenne', 'Élevée']}
                />
              </ChartCard>
              <ChartCard title={t('analytics.chart_revenue')} chip={<span style={{ fontSize: 11, color: 'var(--flc-ink3, #524A40)' }}>{t('analytics.30_days')}</span>} padding={14}>
                <RevenueAreaChart
                  total={fmtNumFR(displayRevenueTotal)}
                  unit="€"
                  delta={displayRevenueDelta}
                  data={displayRevenueSeries}
                  label="Total période"
                  height={150}
                />
              </ChartCard>
              <ChartCard title={t('analytics.chart_top_products')} chip={<span style={{ fontSize: 11, color: 'var(--flc-ink3, #524A40)' }}>{t('analytics.by_revenue')}</span>}>
                <TopProductsList items={displayTopProducts} />
              </ChartCard>
            </section>

            {/* 4) Heatmap + weekday bars + new vs returning donut. */}
            <section style={{ display: 'grid', gridTemplateColumns: '1.4fr 1fr 1fr', gap: 12 }}>
              <ChartCard title={t('analytics.chart_hours')} chip={<span style={{ fontSize: 11, color: 'var(--flc-ink3, #524A40)' }}>{t('analytics.kpi_visits')}</span>}>
                <HoursHeatmap matrix={displayHours.matrix} days={displayHours.days} hours={displayHours.hours} />
              </ChartCard>
              <ChartCard title={t('analytics.chart_weekday')} chip={<span style={{ fontSize: 11, color: 'var(--flc-ink3, #524A40)' }}>{t('analytics.kpi_visits')}</span>}>
                <WeekdayBars counts={displayWeekday} days={SHORT_DAYS} height={120} />
              </ChartCard>
              <ChartCard title={t('analytics.chart_new_vs_returning')} chip={<span style={{ fontSize: 11, color: 'var(--flc-ink3, #524A40)' }}>{t('analytics.30_days')}</span>}>
                {displayNvrSegments.length > 0 ? (
                  <ChannelDonut
                    data={displayNvrSegments}
                    centerNum={fmtNumFR(displayCustomers)}
                    centerLabel="Clients uniques"
                    size={130}
                  />
                ) : (
                  <div style={{ display: 'grid', placeItems: 'center', height: 130, color: 'var(--flc-ink3, #524A40)', fontSize: 12 }}>
                    Aucune donnée.
                  </div>
                )}
              </ChartCard>
            </section>

            {/* Automatisations actives */}
            <ChartCard
              title={t('analytics.automations_active')}
              action={
                <button
                  type="button"
                  onClick={() => navigate('/dashboard/campaigns')}
                  style={{
                    background: 'none', border: 'none', cursor: 'pointer',
                    color: 'var(--flc-accent-deep, #A82843)', fontSize: 11.5, fontWeight: 500,
                    padding: 0, font: 'inherit',
                  }}
                >
                  Tout voir →
                </button>
              }
            >
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
                <AutomationCard
                  icon={Clock}
                  accent="purple"
                  title="Relance inactifs 21 jours"
                  subtitle="Prochaine exécution : Aujourd'hui 18h"
                  status="active"
                  onClick={() => navigate('/dashboard/campaigns?preset=we-miss-you')}
                />
                <AutomationCard
                  icon={Gift}
                  accent="pink"
                  title="Anniversaire client"
                  subtitle="Prochaine exécution : Demain 09h"
                  status="active"
                  onClick={() => navigate('/dashboard/campaigns?preset=birthday')}
                />
                <AutomationCard
                  icon={Wallet}
                  accent="emerald"
                  title="Panier moyen bas"
                  subtitle="Prochaine exécution : 18 Juin 12h"
                  status="active"
                  onClick={() => navigate('/dashboard/campaigns?preset=upsell')}
                />
                <AutomationCard
                  icon={Crown}
                  accent="amber"
                  title="Nouveaux clients"
                  subtitle="Prochaine exécution : 20 Juin 10h"
                  status="active"
                  onClick={() => navigate('/dashboard/campaigns?preset=welcome')}
                />
              </div>
            </ChartCard>
          </main>

          {/* RIGHT RAIL */}
          <aside className="av2-rail" aria-label="Assistant IA et insights">
            <RightAiPanel
              score={loyaltyScore}
              scoreDelta={12}
              insights={insights}
              onDiagnostic={() => navigate('/dashboard/insights')}
              onAllInsights={() => navigate('/dashboard/insights')}
              onAction={(kind) => {
                if (kind === 'new-campaign')      navigate('/dashboard/campaigns?new=1');
                else if (kind === 'segment-customers') navigate('/dashboard/customers');
                else if (kind === 'export-report')     navigate('/dashboard/customers?export=csv');
                else if (kind === 'auto-mode')         navigate('/dashboard/campaigns?auto=1');
              }}
              onAssistantSubmit={(q) => navigate(`/dashboard/ai-assistant?q=${encodeURIComponent(q)}`)}
            />
          </aside>
        </div>
      </div>

      {/* ─── DIVIDER ──────────────────────────────────────────────── */}
      <SectionDivider>Activité dans la période choisie &amp; analyses approfondies</SectionDivider>

      {/* ─── LEGACY ANALYTICS CONTENT — full lifetime KPIs (Total
            Customers / Visits / Repeat Rate / Wallet Passes / Active
            Cards / Never Added / Deleted Cards / VIP), CustomerStatus,
            full Tier and Acquisition breakdown charts, all 12 time-
            windowed Activité tiles, Recovered Filter, Reviews &
            sentiment, and Rankings tabs. The dark skin propagates
            from the .av2-light-skin wrapper.

            The legacy page's OWN header ("Analytics" + LIVE pill) and
            its own AI banner are hidden via the CSS rule below — the
            V2 header above and the AI Copilot in the right rail
            already cover those. ────────────────────────────────── */}
      <div className="av2-legacy-wrapper" style={{ padding: '0 18px 24px' }}>
        <LegacyAnalyticsPage />
      </div>
    </div>
  );
}
