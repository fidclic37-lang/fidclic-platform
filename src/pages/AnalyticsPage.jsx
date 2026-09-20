import React, { useEffect, useMemo, useState } from 'react';
import { ownerAPI } from '../lib/api';
import NumberInput from '../components/NumberInput';
import { PageHeader, C as C_PS } from '../components/PageShell';
import {
  LineChart, Line, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts';
import {
  Users, TrendingUp, Award, Smartphone, Gift, Calendar,
  Activity, X, Trophy, ArrowDown, ArrowUp, CreditCard,
  AlertCircle, Send, Megaphone, Clock, Building2, Star,
  MessageSquare, ThumbsUp, ThumbsDown,
} from 'lucide-react';
import TierBadge from '../components/TierBadge';
import LoadingDistraction from '../components/LoadingDistraction';
import { useBranch } from '../contexts/BranchContext';
import VisitsWithCampaignsChart from '../components/VisitsWithCampaignsChart';
import CustomerStatusKPI from '../components/CustomerStatusKPI';
import ColorfulKpiTile from '../components/ColorfulKpiTile';
import AiRecommendationBanner from '../components/AiRecommendationBanner';
import VisitsTwinChart from '../components/VisitsTwinChart';
import AcquisitionDonut from '../components/AcquisitionDonut';
import TierDonut from '../components/TierDonut';
import WeeklyAcquisitionPanel from '../components/WeeklyAcquisitionPanel';
import useTileMetric from '../hooks/useTileMetric';
import { Trash2, UserPlus2, RefreshCcw, Repeat as RepeatIcon, BadgeCheck } from 'lucide-react';

// Tier identity colours — metals, like the badges: bronze, silver, gold, platinum (VIP).
const TIER_COLORS = { bronze: '#B87333', silver: '#9CA3AF', gold: '#D4A017', vip: '#7F8FA6' };
const ACQ_COLORS = ['#2F6BFF', '#8FB0FF', '#C7D7FF', '#DCE3EF', '#5B8DEF', '#A9C2FF', '#E6EAF2'];

// ─────────────────────────────────────────────────────────────────────
// DEMO REVIEW ANALYTICS — paints the "Customer reviews & sentiment"
// section when the tenant has zero reviews so a fresh demo tenant
// shows a realistic picture (avg rating, distribution, topic breakdown,
// recent feed) instead of an empty-state hint. Real data ALWAYS wins;
// the AnalyticsPage only falls back to this when total_reviews is 0.
// ─────────────────────────────────────────────────────────────────────
const DEMO_REVIEW_ANALYTICS = {
  total_reviews: 184,
  average_rating: 8.4,
  negative_review_rate_pct: 7,
  sentiment_score: 62,
  review_velocity: { last_30d: 38, prev_30d: 31, delta_pct: 23 },
  rating_distribution: {
    '10': 58, '9': 41, '8': 27, '7': 18, '6': 12,
    '5': 9,  '4': 7,  '3': 6,  '2': 4,  '1': 2,
  },
  topic_breakdown: [
    { topic: 'staff',       count: 92, avg_rating: 9.1, positive_pct: 84, negative_pct: 6,  mention_pct: 50 },
    { topic: 'cleanliness', count: 64, avg_rating: 8.7, positive_pct: 76, negative_pct: 9,  mention_pct: 35 },
    { topic: 'speed',       count: 71, avg_rating: 7.9, positive_pct: 62, negative_pct: 18, mention_pct: 39 },
    { topic: 'price',       count: 38, avg_rating: 7.2, positive_pct: 51, negative_pct: 24, mention_pct: 21 },
    { topic: 'wait_time',   count: 27, avg_rating: 6.4, positive_pct: 33, negative_pct: 41, mention_pct: 15 },
  ],
  recent: [
    { id: 'r1', customer_name: 'Marie L.',   rating: 10, sentiment: 'Très positif', topics: ['staff', 'cleanliness'],
      text: 'Service au top, équipe ultra accueillante. Le cappuccino est devenu mon rituel du matin.',
      created_at: new Date(Date.now() - 1 * 86400000).toISOString() },
    { id: 'r2', customer_name: 'Thomas R.',  rating: 9,  sentiment: 'Positif', topics: ['speed', 'price'],
      text: 'Toujours rapide même en heure de pointe. Rapport qualité-prix imbattable dans le quartier.',
      created_at: new Date(Date.now() - 2 * 86400000).toISOString() },
    { id: 'r3', customer_name: 'Sophie M.',  rating: 8,  sentiment: 'Positif', topics: ['staff'],
      text: 'Très bon accueil, ambiance chaleureuse. Je recommande la formule brunch du week-end.',
      created_at: new Date(Date.now() - 3 * 86400000).toISOString() },
    { id: 'r4', customer_name: 'Karim B.',   rating: 4,  sentiment: 'Négatif', topics: ['wait_time'],
      text: 'Attente trop longue au comptoir samedi midi (15 min). À part ça la qualité est là.',
      created_at: new Date(Date.now() - 4 * 86400000).toISOString() },
    { id: 'r5', customer_name: 'Élise D.',   rating: 9,  sentiment: 'Positif', topics: ['cleanliness', 'staff'],
      text: 'Toujours impeccable, et le barista connaît ma commande par cœur. Petit plus qui change tout.',
      created_at: new Date(Date.now() - 5 * 86400000).toISOString() },
    { id: 'r6', customer_name: 'Yann P.',    rating: 7,  sentiment: 'Neutre', topics: ['price'],
      text: 'Bon café, prix un peu élevé pour un latte. Mais le programme fidélité compense.',
      created_at: new Date(Date.now() - 6 * 86400000).toISOString() },
    { id: 'r7', customer_name: 'Aïcha S.',   rating: 10, sentiment: 'Très positif', topics: ['staff', 'speed'],
      text: 'L\'équipe est adorable et le service est rapide. Mon spot préféré pour bosser le matin.',
      created_at: new Date(Date.now() - 7 * 86400000).toISOString() },
    { id: 'r8', customer_name: 'Mathieu V.', rating: 3,  sentiment: 'Très négatif', topics: ['speed', 'wait_time'],
      text: 'Commande oubliée 2 fois en 1 mois. Dommage car le produit est bon.',
      created_at: new Date(Date.now() - 9 * 86400000).toISOString() },
  ],
};

// ------------------------------------------------------------------
// Reusable "Send Campaign" button — plants on every metric / chart card.
// Clicking opens a composer pre-filled with the given segment descriptor.
// The parent wires in openComposer(segment, presetName, presetContent).
// ------------------------------------------------------------------
const SendCampaignButton = ({ label = 'Send campaign', onClick, compact = false, icon: Icon = Send }) => (
  <button
    type="button"
    onClick={(e) => {
      e.stopPropagation();
      onClick && onClick();
    }}
    className={
      compact
        ? 'inline-flex items-center gap-1 text-[11px] px-2 py-1 bg-[#2F6BFF]/10 text-[#2F6BFF] rounded-full hover:bg-[#2F6BFF] hover:text-white transition'
        : 'inline-flex items-center gap-1.5 text-xs px-3 py-1.5 bg-[#2F6BFF]/10 text-[#2F6BFF] rounded-full hover:bg-[#2F6BFF] hover:text-white transition font-medium'
    }
    title="Send a campaign to this segment"
  >
    <Icon size={compact ? 11 : 13} />
    {label}
  </button>
);

// ------------------------------------------------------------------
// LiveMetricTile — fetches its number from /owner/analytics/metric,
// owns its own period picker, and re-fetches on change.
// ------------------------------------------------------------------
const LiveMetricTile = ({
  icon, title, accent, tone,
  metric, branchId,
  initial = { value: 30, unit: 'day' },
  sublabel,
  onDrill,
  disablePicker = false,
  // When set, the tile uses this shared day window instead of its own
  // period state. Used by the shared filter for the "Activité" section.
  controlledDays = null,
}) => {
  // Fetch with series so the tile can render a sparkline + delta badge.
  const { value, loading, days, period, setPeriod, series, deltaPct } = useTileMetric({
    metric, branchId, initial, withSeries: true, controlledDays,
  });
  const delta = typeof deltaPct === 'number'
    ? { value: deltaPct, sign: deltaPct > 0.5 ? 'up' : deltaPct < -0.5 ? 'down' : 'flat' }
    : null;
  return (
    <ColorfulKpiTile
      icon={icon}
      title={title}
      accent={accent}
      tone={tone}
      value={(value ?? 0).toLocaleString()}
      sublabel={typeof sublabel === 'function' ? sublabel(days, value) : sublabel}
      loading={loading}
      onClick={onDrill ? () => onDrill(days, value) : undefined}
      period={(disablePicker || controlledDays != null) ? null : period}
      onPeriodChange={(disablePicker || controlledDays != null) ? undefined : setPeriod}
      trend={series}
      delta={delta}
    />
  );
};

// Static variant — value comes from page state, no network, no picker.
const StaticMetricTile = ({ icon, title, accent, value, sublabel, onDrill }) => (
  <ColorfulKpiTile
    icon={icon}
    title={title}
    accent={accent}
    value={(value ?? 0).toLocaleString()}
    sublabel={typeof sublabel === 'function' ? sublabel(0, value) : sublabel}
    onClick={onDrill ? () => onDrill(0, value) : undefined}
  />
);

// Router — picks live vs. static, so callers stay clean.
const MetricTile = ({ staticValue, ...rest }) =>
  staticValue != null
    ? <StaticMetricTile {...rest} value={staticValue} />
    : <LiveMetricTile {...rest} />;

/**
 * SharedTimeFilter — one control that drives every tile in the
 * "Activité dans la période choisie" section plus the two charts.
 *
 * Three modes:
 *   • preset — chips: 7j / 30j / 90j / 6 mois / 1 an
 *   • custom — owner types N + unit (jours / semaines / mois / années)
 *   • since  — calendar date; window = today − chosen date
 */
const SharedTimeFilter = ({ value, onChange, sharedDays }) => {
  const PRESETS = [
    { key: '7d',   label: '7 jours',  v: 7,   u: 'day' },
    { key: '30d',  label: '30 jours', v: 30,  u: 'day' },
    { key: '90d',  label: '90 jours', v: 90,  u: 'day' },
    { key: '6m',   label: '6 mois',   v: 6,   u: 'month' },
    { key: '1y',   label: '1 an',     v: 1,   u: 'year' },
  ];
  const set = (partial) => onChange({ ...value, ...partial });
  const UNITS = [
    { v: 'day', label: 'jours' }, { v: 'week', label: 'semaines' },
    { v: 'month', label: 'mois' }, { v: 'year', label: 'années' },
  ];
  return (
    <div className="ftf mb-3">
      <div className="ftf-left">
        <span className="ftf-label">Période</span>
        <div className="ftf-pills">
          {PRESETS.map((p) => {
            const active = value.mode === 'preset' && value.value === p.v && value.unit === p.u;
            return (
              <button key={p.key} type="button" className={`ftf-pill ${active ? 'on' : ''}`}
                      onClick={() => onChange({ mode: 'preset', value: p.v, unit: p.u, sinceDate: '' })}>
                {p.label}
              </button>
            );
          })}
        </div>
      </div>
      <div className="ftf-right">
        <div className={`ftf-group ${value.mode === 'custom' ? 'on' : ''}`} title="Fenêtre sur mesure">
          <input
            type="number" min="1" max="999"
            value={value.mode === 'custom' ? value.value : ''}
            placeholder="30"
            onChange={(e) => {
              const n = Math.max(1, parseInt(e.target.value, 10) || 1);
              onChange({ ...value, mode: 'custom', value: n, sinceDate: '' });
            }}
            className="ftf-num" aria-label="Nombre"
          />
          <i className="ftf-sep" />
          <select
            value={value.unit}
            onChange={(e) => onChange({ ...value, mode: 'custom', unit: e.target.value, sinceDate: '' })}
            className="ftf-unit" aria-label="Unité"
          >
            {UNITS.map((u) => <option key={u.v} value={u.v}>{u.label}</option>)}
          </select>
        </div>
        <div className={`ftf-group ${value.mode === 'since' ? 'on' : ''}`} title="Depuis une date">
          <span className="ftf-mini">depuis</span>
          <input
            type="date"
            value={value.sinceDate || ''}
            max={new Date().toISOString().slice(0, 10)}
            onChange={(e) => onChange({ ...value, mode: 'since', sinceDate: e.target.value })}
            className="ftf-date" aria-label="Depuis la date"
          />
        </div>
        <span className="ftf-readout">≈ {sharedDays} j</span>
      </div>
    </div>
  );
};

// ------------------------------------------------------------------
// KPI card with optional Send Campaign CTA in top-right corner.
// ------------------------------------------------------------------
const KPICard = ({
  icon: Icon, title, value, sublabel, onClick, accent = '#2F6BFF',
  segment, openComposer, presetName, presetContent,
}) => (
  <div
    onClick={onClick}
    className={`relative bg-white p-3 rounded-xl border border-[#DCE3EF] ${
      onClick ? 'cursor-pointer hover:shadow-md transition' : ''
    }`}
  >
    {segment && openComposer && (
      <div className="absolute top-1.5 right-1.5">
        <SendCampaignButton
          compact
          label="Send"
          onClick={() => openComposer(segment, presetName, presetContent)}
        />
      </div>
    )}
    <div className="flex items-center gap-3">
      <div
        className="w-9 h-9 rounded-full flex items-center justify-center text-white flex-shrink-0"
        style={{ background: accent }}
      >
        <Icon size={17} />
      </div>
      <div className="min-w-0 pr-5">
        <p className="text-[10px] text-[#334155] uppercase tracking-wide font-semibold truncate">{title}</p>
        <p className="text-lg font-bold text-[#0F172A] leading-tight">{value}</p>
        {sublabel && <p className="text-[10.5px] text-[#64748B] mt-0.5 truncate">{sublabel}</p>}
      </div>
    </div>
  </div>
);

// ------------------------------------------------------------------
// ChartCard with optional Send CTA
// ------------------------------------------------------------------
const ChartCard = ({ title, hint, children, segment, openComposer, presetName, presetContent }) => (
  <div className="bg-white p-4 rounded-xl border border-[#DCE3EF]">
    <div className="flex items-start justify-between gap-2 mb-0.5">
      <h2
        className="text-base font-semibold text-[#0F172A]"
        style={{ fontFamily: 'Cormorant Garamond' }}
      >
        {title}
      </h2>
      {segment && openComposer && (
        <SendCampaignButton
          label="Send campaign"
          onClick={() => openComposer(segment, presetName, presetContent)}
        />
      )}
    </div>
    {hint && <p className="text-[10.5px] text-[#64748B] mt-0.5 mb-2">{hint}</p>}
    {children}
  </div>
);

// ------------------------------------------------------------------
// Campaign composer modal — used for every "Send campaign" CTA.
// ------------------------------------------------------------------
const CampaignComposer = ({ segment, presetName, presetContent, onClose, onSent }) => {
  const [name, setName] = useState(presetName || '');
  const [content, setContent] = useState(presetContent || '');
  const [sending, setSending] = useState(false);
  const [preview, setPreview] = useState(null);
  const [scheduleMode, setScheduleMode] = useState('now'); // now | later
  const [runAt, setRunAt] = useState('');
  const [recurrence, setRecurrence] = useState('');

  useEffect(() => {
    setName(presetName || '');
    setContent(presetContent || '');
  }, [presetName, presetContent]);

  useEffect(() => {
    // Preview count for this segment
    (async () => {
      try {
        // For most segments we don't have a preview endpoint, so skip.
        // If segment is tier-based, we could call preview-segment, but it's optional UX.
        setPreview(null);
      } catch (e) { /* ignore */ }
    })();
  }, [segment]);

  const send = async () => {
    if (!name.trim() || !content.trim()) {
      alert('Merci de remplir le sujet et le message.');
      return;
    }
    setSending(true);
    try {
      if (scheduleMode === 'later') {
        if (!runAt) {
          alert('Choisissez une date d\'envoi.');
          setSending(false);
          return;
        }
        await ownerAPI.scheduleCampaign({
          name,
          content,
          run_at: new Date(runAt).toISOString(),
          segment,
          recurrence: recurrence || null,
        });
        alert(recurrence ? `Campagne programmée en récurrence (${recurrence}) ✓` : 'Campagne programmée ✓');
      } else {
        const res = await ownerAPI.sendCampaignToGroup({
          name,
          content,
          segment,
        });
        alert(`Campagne envoyée à ${res.data.targeted_count ?? 0} clients ✓`);
      }
      onSent && onSent();
      onClose();
    } catch (e) {
      alert('Erreur: ' + (e?.response?.data?.detail || e?.message || 'envoi impossible'));
    } finally {
      setSending(false);
    }
  };

  return (
    <div
      className="fixed inset-0 bg-black/50 z-[60] flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl max-w-2xl w-full max-h-[90vh] overflow-auto p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center mb-4">
          <div>
            <h3 className="text-2xl font-bold text-[#0F172A]" style={{ fontFamily: 'Cormorant Garamond' }}>
              <Megaphone className="inline mr-2 text-[#2F6BFF]" size={22} /> Composer une campagne
            </h3>
            <p className="text-xs text-[#64748B] mt-1">
              Cible : <span className="font-medium text-[#2F6BFF]">{segmentLabel(segment)}</span>
              {preview != null && <span className="ml-2">({preview} destinataires)</span>}
            </p>
          </div>
          <button onClick={onClose} className="text-[#94A3B8] hover:text-[#0F172A]"><X size={22} /></button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="block text-xs font-semibold text-[#334155] uppercase mb-1">Sujet</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Ex : Offre spéciale {first_name} 🎁"
              className="w-full px-3 py-2 border border-[#DCE3EF] rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2F6BFF]"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold text-[#334155] uppercase mb-1">Message</label>
            <textarea
              rows={6}
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder="Bonjour {first_name}, il te reste {points_to_next_reward} points pour débloquer ta récompense chez {business_name} !"
              className="w-full px-3 py-2 border border-[#DCE3EF] rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2F6BFF] font-['Manrope']"
            />
            <p className="text-[11px] text-[#64748B] mt-1">
              Variables : <code>{'{first_name}'}</code>, <code>{'{name}'}</code>, <code>{'{tier}'}</code>, <code>{'{points_to_next_reward}'}</code>, <code>{'{points}'}</code>, <code>{'{business_name}'}</code>
            </p>
          </div>

          <div className="p-3 bg-[#F5F7FB] rounded-lg border border-[#DCE3EF]">
            <div className="flex items-center gap-4 mb-2">
              <label className="inline-flex items-center gap-1 text-sm">
                <input type="radio" checked={scheduleMode === 'now'} onChange={() => setScheduleMode('now')} />
                Envoyer maintenant
              </label>
              <label className="inline-flex items-center gap-1 text-sm">
                <input type="radio" checked={scheduleMode === 'later'} onChange={() => setScheduleMode('later')} />
                Programmer plus tard
              </label>
            </div>
            {scheduleMode === 'later' && (
              <div className="flex flex-wrap gap-3 items-center">
                <input
                  type="datetime-local"
                  value={runAt}
                  onChange={(e) => setRunAt(e.target.value)}
                  className="px-2 py-1 border border-[#DCE3EF] rounded"
                />
                <select
                  value={recurrence}
                  onChange={(e) => setRecurrence(e.target.value)}
                  className="px-2 py-1 border border-[#DCE3EF] rounded text-sm"
                >
                  <option value="">Une seule fois</option>
                  <option value="daily">Quotidien</option>
                  <option value="weekly">Hebdomadaire</option>
                  <option value="monthly">Mensuel</option>
                </select>
              </div>
            )}
          </div>

          <div className="flex justify-end gap-3 pt-2">
            <button
              onClick={onClose}
              className="px-4 py-2 border border-[#DCE3EF] text-[#0F172A] rounded-lg hover:bg-[#F5F7FB]"
            >
              Annuler
            </button>
            <button
              disabled={sending}
              onClick={send}
              className="px-5 py-2 bg-[#2F6BFF] text-white rounded-lg font-medium hover:bg-[#1D4ED8] disabled:opacity-50 inline-flex items-center gap-2"
            >
              {scheduleMode === 'later' ? <Clock size={16} /> : <Send size={16} />}
              {sending ? 'Envoi…' : scheduleMode === 'later' ? 'Programmer' : 'Envoyer maintenant'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

function segmentLabel(segment) {
  if (!segment) return 'Tous les clients';
  switch (segment.type) {
    case 'all': return 'Tous les clients';
    case 'tier': return `Tier ${segment.value}`;
    case 'inactive_days': return `Inactifs ${segment.value || 30} j`;
    case 'recovered': return 'Clients récupérés';
    case 'top_paying_n': return `Top ${segment.n || 20} gros payeurs`;
    case 'least_paying_n': return `${segment.n || 20} plus faibles payeurs`;
    case 'max_visits_n': return `Top ${segment.n || 20} visites`;
    case 'least_visits_n': return `${segment.n || 20} plus faibles en visites`;
    case 'birthday_month': return `Anniversaires en ${segment.value}`;
    case 'birthday_today': return 'Anniversaires aujourd\'hui';
    case 'acquisition': return `Source: ${segment.value}`;
    case 'one_visit_only': return 'Clients 1 visite seulement';
    default: return 'Segment personnalisé';
  }
}

// ------------------------------------------------------------------
// Columns for the drill-down modal when listing customers
// ------------------------------------------------------------------
const CUSTOMER_DRILL_COLUMNS = [
  { key: 'name', label: 'Customer' },
  { key: 'email', label: 'Email' },
  { key: 'tier', label: 'Tier', render: (v) => <TierBadge tier={v} /> },
  { key: 'visits', label: 'Visits' },
  { key: 'total_amount_paid', label: 'Spent', render: (v) => `€${(v ?? 0).toFixed(0)}` },
  { key: 'last_visit_date', label: 'Last visit', render: (v) => v ? new Date(v).toLocaleDateString() : '—' },
];

// ------------------------------------------------------------------
// Page
// ------------------------------------------------------------------
const AnalyticsPage = () => {
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [analytics, setAnalytics] = useState(null);
  const [summary, setSummary] = useState(null);
  const [cardsFilled, setCardsFilled] = useState(null);
  const [highestPaying, setHighestPaying] = useState([]);
  const [recovered, setRecovered] = useState(null);
  const [acquisition, setAcquisition] = useState([]);
  const [reviewAnalytics, setReviewAnalytics] = useState(null);

  // Branch selector — drives every API call below
  // App-wide branch context (item #18) — picking a branch on dashboard filters every page.
  const { branchId: branchIdRaw, setBranchId: setBranchIdGlobal, branches: branchesCtx, setBranches: setBranchesCtx } = useBranch();
  const branchId = branchIdRaw || '';
  const setBranchId = (id) => setBranchIdGlobal(id || null);
  const branches = branchesCtx;
  const setBranches = setBranchesCtx;

  // TWO independent time filters:
  //  - chartsFilter: drives Visites dans le temps + Acquisition de clients
  //  - tilesFilter:  drives every tile in "Activité dans la période choisie"
  // Same UI control (SharedTimeFilter) is rendered above each section.
  // mode = 'preset' | 'custom' | 'since'.
  const [chartsFilter, setChartsFilter] = useState({ mode: 'preset', value: 30, unit: 'day', sinceDate: '' });
  const [tilesFilter,  setTilesFilter ] = useState({ mode: 'preset', value: 30, unit: 'day', sinceDate: '' });
  const filterToDays = (f) => {
    if (f.mode === 'since' && f.sinceDate) {
      const ms = Date.now() - new Date(f.sinceDate).getTime();
      return Math.max(1, Math.ceil(ms / (1000 * 60 * 60 * 24)));
    }
    const UNIT_DAYS = { day: 1, week: 7, month: 30, year: 365 };
    return Math.max(1, Math.round((Number(f.value) || 1) * (UNIT_DAYS[f.unit] || 1)));
  };
  const chartsDays = useMemo(() => filterToDays(chartsFilter), [chartsFilter]);
  const tilesDays  = useMemo(() => filterToDays(tilesFilter),  [tilesFilter]);

  const [recoveryInactiveDays, setRecoveryInactiveDays] = useState(30);
  const [recoveryWindowDays, setRecoveryWindowDays] = useState(30);
  const [rankingMode, setRankingMode] = useState('top_paying'); // top_paying | least_paying | max_visits | least_visits

  // Custom threshold for "Inactive customers" KPI. Default 30 days — owner can change it.
  const [inactiveThreshold, setInactiveThreshold] = useState(30);
  const [inactiveDraft, setInactiveDraft] = useState('30');
  // Time-range for the "About to lose" KPI — owner picks any window.
  const [aboutToLoseRange, setAboutToLoseRange] = useState({ min: 14, max: 29 });
  // Period preset for the whole page — 7/30/90 days or "all time". Applied everywhere a window makes sense.
  const [periodDays, setPeriodDays] = useState(30);
  // Free-typing buffer for the custom-period input. Decoupled from periodDays so
  // the user can clear the field and type a new number without it snapping to 1
  // on every keystroke. Only commits to periodDays on blur / Enter.
  const [periodDraft, setPeriodDraft] = useState('30');

  const [drill, setDrill] = useState(null); // { title, rows }
  const [drillLoading, setDrillLoading] = useState(false);
  const [composer, setComposer] = useState(null); // { segment, presetName, presetContent }

  const openComposer = (segment, presetName, presetContent) => {
    setComposer({ segment, presetName: presetName || '', presetContent: presetContent || '' });
  };

  // Build the param object for every API call, adding branch + period scope.
  // Always pass period_days so changing the period filter actually re-scopes
  // the data (the previous `!== 30` short-circuit caused the period selector
  // to silently fall back to whatever the backend's default was).
  const params = (extra = {}) => ({
    ...(branchId ? { branch_id: branchId } : {}),
    ...(periodDays ? { period_days: periodDays } : {}),
    ...extra,
  });

  // Commit typed period value: clamp to 1..730 and sync the preset highlight.
  const commitPeriodDraft = () => {
    const trimmed = (periodDraft || '').trim();
    if (trimmed === '') {
      // Empty → restore to the last committed value
      setPeriodDraft(String(periodDays));
      return;
    }
    const n = Math.max(1, Math.min(730, Math.round(Number(trimmed) || 0)));
    if (!n) {
      setPeriodDraft(String(periodDays));
      return;
    }
    setPeriodDays(n);
    setPeriodDraft(String(n));
  };
  const commitInactiveDraft = () => {
    const trimmed = (inactiveDraft || '').trim();
    if (trimmed === '') {
      setInactiveDraft(String(inactiveThreshold));
      return;
    }
    const n = Math.max(1, Math.min(730, Math.round(Number(trimmed) || 0)));
    if (!n) {
      setInactiveDraft(String(inactiveThreshold));
      return;
    }
    setInactiveThreshold(n);
    setInactiveDraft(String(n));
  };

  // Click-to-drill helper used by every KPI card.
  const drillCustomers = async (title, filters) => {
    setDrill({ title, rows: [], columns: CUSTOMER_DRILL_COLUMNS });
    setDrillLoading(true);
    try {
      const res = await ownerAPI.getCustomers(params(filters));
      setDrill({ title, rows: res.data || [], columns: CUSTOMER_DRILL_COLUMNS });
    } catch (e) {
      setDrill({ title, rows: [], columns: CUSTOMER_DRILL_COLUMNS, error: e?.message || 'Failed to load' });
    } finally {
      setDrillLoading(false);
    }
  };

  useEffect(() => {
    (async () => {
      try {
        const r = await ownerAPI.getBranches();
        setBranches(r.data || []);
      } catch (e) { /* no branches — owner on basic plan, fine */ }
    })();
  }, []);

  const loadAll = async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const results = await Promise.allSettled([
        ownerAPI.getAnalytics(params()),
        ownerAPI.getAnalyticsSummary(params()),
        ownerAPI.getCardsFilled(params()),
        ownerAPI.getHighestPaying(params()),
        ownerAPI.getAcquisitionSources(params()),
        ownerAPI.getReviewAnalytics(params()),
      ]);
      const [a, s, cf, hp, acq, rv] = results;
      if (a.status === 'fulfilled') setAnalytics(a.value.data);
      if (s.status === 'fulfilled') setSummary(s.value.data);
      if (cf.status === 'fulfilled') setCardsFilled(cf.value.data);
      if (hp.status === 'fulfilled') setHighestPaying(hp.value.data || []);
      if (acq.status === 'fulfilled') setAcquisition(acq.value.data?.sources || []);
      if (rv.status === 'fulfilled') {
        // If the backend reports zero reviews (fresh tenant / sandbox),
        // paint demo analytics so the section reads as populated. Real
        // data ALWAYS wins — demo only fires when total_reviews is 0.
        const real = rv.value.data;
        if (real && (real.total_reviews ?? 0) === 0) {
          setReviewAnalytics(DEMO_REVIEW_ANALYTICS);
        } else {
          setReviewAnalytics(real);
        }
      }
      const allFailed = results.every((r) => r.status === 'rejected');
      if (allFailed) {
        const first = results[0];
        setLoadError(first.reason?.response?.status
          ? `Error ${first.reason.response.status}: ${first.reason.response.data?.detail || first.reason.message}`
          : first.reason?.message || 'Failed to load analytics');
      }
    } catch (e) {
      setLoadError(e?.message || 'Failed to load analytics');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadAll(); /* eslint-disable-line react-hooks/exhaustive-deps */ }, [branchId, periodDays]);

  useEffect(() => {
    (async () => {
      try {
        const r = await ownerAPI.getRecovered(params({
          inactive_days: recoveryInactiveDays,
          window_days: recoveryWindowDays,
        }));
        setRecovered(r.data);
      } catch (e) { /* ignore */ }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recoveryInactiveDays, recoveryWindowDays, branchId]);

  const totalCustomers = analytics?.total_customers ?? summary?.total_customers ?? 0;
  const totalVisits = analytics?.total_visits ?? 0;
  const repeatRate = analytics?.repeat_rate_pct ?? 0;
  const walletPasses = analytics?.wallet_passes_issued ?? 0;
  const activeCustomers = summary?.active_customers ?? 0;
  const newThisWeek = summary?.new_this_week ?? 0;
  const cardsFilledTotal = cardsFilled?.total_cards_filled ?? 0;
  const cardsFilledThisMonth = cardsFilled?.cards_filled_this_month ?? 0;
  // New summary-backed KPIs
  const newToday = summary?.new_today_count ?? 0;
  const inactiveCount = summary?.inactive_count ?? 0;
  const aboutToLoseCount = summary?.about_to_lose_count ?? 0;
  const cardsFilledToday = summary?.cards_filled_today ?? 0;
  // New KPIs from this batch
  const rewardsRedeemedToday = summary?.rewards_redeemed_today ?? 0;
  const rewardsRedeemedMonth = summary?.rewards_redeemed_month ?? 0;
  const birthdaysThisMonth = summary?.birthdays_this_month_count ?? 0;
  const vipCount = summary?.vip_count ?? 0;
  const inactivePct = totalCustomers ? Math.round((inactiveCount / totalCustomers) * 100) : 0;
  const aboutToLosePct = totalCustomers ? Math.round((aboutToLoseCount / totalCustomers) * 100) : 0;

  const tierData = useMemo(() => {
    const td = analytics?.tier_distribution || {};
    return [
      { name: 'Bronze', value: td.bronze || 0, key: 'bronze' },
      { name: 'Silver', value: td.silver || 0, key: 'silver' },
      { name: 'Gold', value: td.gold || 0, key: 'gold' },
      { name: 'VIP', value: td.vip || 0, key: 'vip' },
    ];
  }, [analytics]);

  const visitsByDay = useMemo(() => {
    if (!analytics?.visits_by_day) return [];
    return Object.entries(analytics.visits_by_day)
      .map(([date, count]) => ({ date, count }))
      .sort((a, b) => a.date.localeCompare(b.date))
      .slice(-30);
  }, [analytics]);

  const newCustomersByWeek = useMemo(() => {
    const w = analytics?.new_customers_by_week || {};
    return Object.entries(w).map(([week, count]) => ({ week, count }));
  }, [analytics]);

  // imported components
  // (NumberInput is imported at top)
  const acquisitionChart = useMemo(
    () => (acquisition || []).map((a) => ({
      name: a.label || (a.source || 'unknown').replace(/_/g, ' '),
      value: a.count || 0,
      raw: a.source,
      pct: a.percentage || 0,
    })),
    [acquisition]
  );

  // Lifetime acquisition total — sum of all per-channel counts. Used for
  // the "X customers acquired all-time" headline above the per-channel KPIs.
  const acquisitionTotal = useMemo(
    () => (acquisition || []).reduce((sum, a) => sum + (a.count || 0), 0),
    [acquisition]
  );

  // Per-source styling — consistent colors across the chart and the KPI tiles.
  const SOURCE_STYLE = {
    instagram: { color: '#5B8DEF', bg: 'rgba(47,107,255,0.08)', icon: '📸' },
    facebook:  { color: '#8FB0FF', bg: 'rgba(47,107,255,0.08)', icon: '👥' },
    tiktok:    { color: '#DCE3EF', bg: 'rgba(220,227,239,0.5)',    icon: '🎵' },
    qr_store:  { color: '#2F6BFF', bg: 'rgba(184,92,56,0.10)',   icon: '📍' },
  };

  const rankedCustomers = useMemo(() => {
    const list = [...(highestPaying || [])];
    switch (rankingMode) {
      case 'top_paying':
        return list.sort((a, b) => (b.total_amount_paid || 0) - (a.total_amount_paid || 0)).slice(0, 20);
      case 'least_paying':
        return list
          .filter((c) => (c.total_amount_paid || 0) > 0)
          .sort((a, b) => (a.total_amount_paid || 0) - (b.total_amount_paid || 0))
          .slice(0, 20);
      case 'max_visits':
        return list.sort((a, b) => (b.total_visits || 0) - (a.total_visits || 0)).slice(0, 20);
      case 'least_visits':
        return list
          .filter((c) => (c.total_visits || 0) > 0)
          .sort((a, b) => (a.total_visits || 0) - (b.total_visits || 0))
          .slice(0, 20);
      default:
        return list.slice(0, 20);
    }
  }, [highestPaying, rankingMode]);

  const rankingSegment = useMemo(() => {
    switch (rankingMode) {
      case 'top_paying': return { type: 'top_paying_n', n: 20 };
      case 'least_paying': return { type: 'least_paying_n', n: 20 };
      case 'max_visits': return { type: 'max_visits_n', n: 20 };
      case 'least_visits': return { type: 'least_visits_n', n: 20 };
      default: return { type: 'all' };
    }
  }, [rankingMode]);

  const rankingPreset = useMemo(() => {
    switch (rankingMode) {
      case 'top_paying':
        return {
          name: 'Merci pour votre fidélité, {first_name} 🙏',
          content: 'En tant que client privilégié ({tier}), profitez d\'une attention spéciale lors de votre prochaine visite chez {business_name}.',
        };
      case 'least_paying':
        return {
          name: 'On vous a préparé quelque chose, {first_name}',
          content: 'Un geste pour votre prochaine visite chez {business_name} : {points_to_next_reward} points vous séparent de votre récompense.',
        };
      case 'max_visits':
        return {
          name: 'Vous êtes un(e) habitué(e), {first_name} 🌟',
          content: 'Bravo pour vos {visits} visites ! Une récompense VIP vous attend chez {business_name}.',
        };
      case 'least_visits':
        return {
          name: 'Revenez bientôt, {first_name}',
          content: 'Il te reste {points_to_next_reward} points pour débloquer ta récompense chez {business_name}. À tout de suite !',
        };
      default:
        return {};
    }
  }, [rankingMode]);

  if (loading) {
    return (
      <div className="py-12 px-4">
        <LoadingDistraction
          title="Chargement des analytics"
          message="On agrège vos visites, vos clients et vos tendances…"
        />
      </div>
    );
  }

  if (loadError && !analytics) {
    return (
      <div className="max-w-xl mx-auto mt-12 rounded-2xl p-8 text-center"
           style={{ background: 'white', border: `1px solid ${C_PS.hairline}`, boxShadow: '0 1px 2px rgba(28,25,23,0.04)' }}>
        <AlertCircle className="mx-auto mb-3" size={32} style={{ color: C_PS.terracotta }} />
        <h2 className="text-2xl font-bold mb-2" style={{ color: C_PS.terracotta, fontFamily: 'Cormorant Garamond' }}>
          Analytics failed to load
        </h2>
        <p className="text-sm mb-5" style={{ color: C_PS.inkMute }}>{loadError}</p>
        <button
          onClick={loadAll}
          className="px-5 py-2.5 rounded-full text-sm font-semibold text-white shadow-md hover:-translate-y-0.5 transition-all"
          style={{ background: `linear-gradient(135deg, ${C_PS.ochre}, ${C_PS.terracotta})` }}
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* Branch banner now lives in DashboardLayout (globally for every owner
          page). We don't re-render it here — that was creating the duplicate
          stacked banner the client flagged on the screenshot. */}

      {/* Editorial-serif Analytics title with green Live pill + date range
          on the right. The only place we re-introduce Cormorant Garamond
          in the dashboard — gives the analytics page one piece of identity
          without flooding the rest of the chrome. */}
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <div>
          <h1
            className="ft-serif-title text-[22px] md:text-[26px] flex items-center gap-2"
            style={{ color: 'var(--ink)', lineHeight: 1.05 }}
          >
            <span>Analytics</span>
            <span
              className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[9px] uppercase"
              style={{
                background: 'var(--tone-success-fill)', color: 'var(--tone-success-ink)',
                letterSpacing: '0.12em', fontWeight: 600, fontFamily: 'Inter, sans-serif',
              }}
            >
              <span className="w-1 h-1 rounded-full" style={{ background: 'var(--tone-success-line)' }} />
              Live
            </span>
          </h1>
          <p className="text-[11.5px] mt-0.5" style={{ color: 'var(--ink-mute)' }}>
            Chaque chiffre est live. Cliquez sur n'importe quel KPI pour voir la liste de clients correspondante.
          </p>
        </div>
        <button
          onClick={() => openComposer({ type: 'all' }, 'Message à toute ma base', 'Bonjour {first_name}, une nouveauté à partager chez {business_name}…')}
          className="ft-btn ft-btn-primary"
        >
          <Megaphone size={14} /> Nouvelle campagne
        </button>
      </div>

      {/* Premium AI recommendation panel — surfaces the highest-priority
          proactive alert as a one-line "do this next" with a CTA into the
          campaign composer. Stays hidden when nothing's urgent. */}
      <AiRecommendationBanner onOpenComposer={openComposer ? ({ segment, presetName, presetContent }) => openComposer(segment, presetName, presetContent) : undefined} />

      {/* ═════════════════════════════════════════════════════════════════
          1) TIME-INDEPENDENT KPIs — lifetime tiles (no period picker).
          ═════════════════════════════════════════════════════════════════ */}
      <div>
        <div className="flex items-baseline justify-between mb-2">
          <h3 className="text-[13px] font-bold text-[#0F172A]" style={{ fontFamily: 'Cormorant Garamond' }}>
            Vue d'ensemble — depuis le début
          </h3>
          <span className="text-[10px] uppercase tracking-widest font-bold text-[#64748B]">Totaux lifetime · pas de filtre temps</span>
        </div>
        {/* Lifetime row 1 — base totals, every tile tone-tagged for vivid colour */}
        <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <ColorfulKpiTile
            icon={Users}
            title="Total Customers"
            value={totalCustomers.toLocaleString()}
            sublabel={`Toute la base · cliquez pour la liste${branchId ? ' (cette boutique)' : ''}`}
            tone="info"
            onClick={() => drillCustomers('All customers', {})}
            topRight={<SendCampaignButton compact label="Send" onClick={() => openComposer({ type: 'all' }, 'Un message pour toi, {first_name}', 'Merci de faire partie de la famille {business_name} ! Une surprise vous attend lors de votre prochain passage.')} />}
          />
          <ColorfulKpiTile
            icon={Activity}
            title="Total Visits"
            value={totalVisits.toLocaleString()}
            sublabel="Toutes les visites enregistrées"
            tone="info"
            onClick={() => drillCustomers('Customers with ≥ 1 visit', { min_visits: 1 })}
          />
          <ColorfulKpiTile
            icon={TrendingUp}
            title="Repeat Rate"
            value={`${repeatRate.toFixed(1)}%`}
            sublabel="Clients revenus au moins 2 fois"
            tone="success"
            onClick={() => drillCustomers('Repeat customers (≥ 2 visits)', { min_visits: 2 })}
          />
          <ColorfulKpiTile
            icon={Smartphone}
            title="Wallet Passes"
            value={walletPasses.toLocaleString()}
            sublabel={`${totalCustomers ? Math.round((walletPasses / totalCustomers) * 100) : 0}% des clients`}
            tone="info"
            onClick={() => drillCustomers('Wallet pass holders', { has_wallet_pass: true })}
          />
        </section>

        {/* Lifetime row 2 — wallet-card states + VIP + birthdays */}
        <section className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-3">
          <ColorfulKpiTile
            icon={BadgeCheck}
            title="Active Cards"
            value={(summary?.wallet_active_count ?? 0).toLocaleString()}
            sublabel="Dans Apple/Google Wallet"
            tone="info"
            onClick={() => drillCustomers('Active wallet cards', { wallet_state: 'active' })}
          />
          <ColorfulKpiTile
            icon={CreditCard}
            title="Never Added"
            value={(summary?.wallet_never_added_count ?? 0).toLocaleString()}
            sublabel="Inscrits, mais carte non ajoutée"
            tone="neutral"
            onClick={() => drillCustomers('Never added to wallet', { wallet_state: 'never_added' })}
          />
          <ColorfulKpiTile
            icon={Trash2}
            title="Deleted Cards"
            value={(summary?.wallet_deleted_count ?? 0).toLocaleString()}
            sublabel="Carte retirée du wallet"
            tone="danger"
            onClick={() => drillCustomers('Deleted wallet cards', { wallet_state: 'deleted' })}
          />
          <ColorfulKpiTile
            icon={Award}
            title="VIP Customers"
            value={vipCount.toLocaleString()}
            sublabel="Top tier — 40+ visites ou panier €60+"
            tone="info"
            onClick={() => drillCustomers('VIP customers', { tier: 'vip' })}
          />
        </section>
      </div>

      {/* ═════════════════════════════════════════════════════════════════
          3) CUSTOMER STATUS — configurable customer-status KPIs (live).
          ═════════════════════════════════════════════════════════════════ */}
      <CustomerStatusKPI />

      {/* ═════════════════════════════════════════════════════════════════
          4) TIME-DEPENDENT KPIs — each tile owns its own period picker.
          ═════════════════════════════════════════════════════════════════ */}
      <div>
        <div className="flex items-baseline justify-between mb-2 gap-3 flex-wrap">
          <h3 className="text-[13px] font-bold text-[#0F172A]" style={{ fontFamily: 'Cormorant Garamond' }}>
            Activité dans la période choisie
          </h3>
          <span className="text-[10px] uppercase tracking-widest font-bold text-[#64748B]">
            {tilesDays} jour{tilesDays === 1 ? '' : 's'}
          </span>
        </div>

        {/* Filter B — controls every tile in the section. Independent of
            the charts filter above so the owner can compare windows. */}
        <SharedTimeFilter value={tilesFilter} onChange={setTilesFilter} sharedDays={tilesDays} />


        <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <MetricTile controlledDays={tilesDays}
            icon={UserPlus2} title="Nouveaux clients" tone="info"
            metric="new_customers" branchId={branchId}
            initial={{ value: 7, unit: 'day' }}
            sublabel={(d) => `Inscrits sur les ${d} derniers jours`}
            onDrill={(d) => drillCustomers(`Nouveaux clients (${d}j)`, { created_within_days: d })}
          />
          <MetricTile controlledDays={tilesDays}
            icon={Award} title="Clients actifs" tone="success"
            metric="active_customers" branchId={branchId}
            initial={{ value: 30, unit: 'day' }}
            sublabel={(d) => `Visite dans les ${d} derniers jours`}
            onDrill={(d) => drillCustomers(`Clients actifs (${d}j)`, { active_within_days: d })}
          />
          <MetricTile controlledDays={tilesDays}
            icon={AlertCircle} title="Inactifs" tone="warning"
            metric="inactive_customers" branchId={branchId}
            initial={{ value: 30, unit: 'day' }}
            sublabel={(d) => `Pas vus depuis ${d} jours · à reconquérir`}
            onDrill={(d) => drillCustomers(`Inactifs ≥ ${d}j`, { inactive_days_min: d })}
          />
          <MetricTile controlledDays={tilesDays}
            icon={Clock} title="Sur le point de partir" tone="danger"
            metric="about_to_lose" branchId={branchId}
            initial={{ value: 14, unit: 'day' }}
            sublabel={(d) => `Silencieux depuis ${d}–${d * 2} jours`}
            onDrill={(d) => drillCustomers(`Sur le point de partir (${d}–${d * 2}j)`, { inactive_days_min: d, inactive_days_max: d * 2 })}
          />
        </section>

        <section className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-3">
          <MetricTile controlledDays={tilesDays}
            icon={CreditCard} title="Cartes complétées" accent="#2F6BFF"
            metric="cards_filled" branchId={branchId}
            initial={{ value: 1, unit: 'month' }}
            sublabel={(d) => `Récompenses débloquées · ${d}j`}
            onDrill={() => drillCustomers('Clients ayant rempli une carte', { cards_filled: true })}
          />
          <MetricTile controlledDays={tilesDays}
            icon={RefreshCcw} title="Clients récupérés" accent="#2F6BFF"
            metric="recovered" branchId={branchId}
            initial={{ value: 30, unit: 'day' }}
            sublabel={(d) => `Revenus après ${d}j de silence`}
            onDrill={() =>
              setDrill({
                title: 'Clients récupérés',
                rows: recovered?.customers || [],
                columns: [
                  { key: 'name', label: 'Customer' },
                  { key: 'email', label: 'Email' },
                  { key: 'tier', label: 'Tier', render: (v) => <TierBadge tier={v} /> },
                  { key: 'last_inactive_date', label: 'Gap started', render: (v) => v ? new Date(v).toLocaleDateString() : '—' },
                  { key: 'returned_date', label: 'Returned', render: (v) => v ? new Date(v).toLocaleDateString() : '—' },
                ],
              })
            }
          />
          <MetricTile controlledDays={tilesDays}
            icon={Gift} title="Récompenses utilisées" accent="#2F6BFF"
            metric="rewards_redeemed" branchId={branchId}
            initial={{ value: 30, unit: 'day' }}
            sublabel={(d) => `Récompenses sur ${d} jours`}
            onDrill={async (d) => {
              try {
                const res = await ownerAPI.listRedeemedRewards({ ...(branchId ? { branch_id: branchId } : {}), days: d });
                setDrill({
                  title: `Récompenses utilisées (${d}j)`,
                  rows: res.data?.redemptions || [],
                  columns: [
                    { key: 'customer_name', label: 'Customer' },
                    { key: 'reward_name', label: 'Reward' },
                    { key: 'reward_value_eur', label: 'Value (€)', render: (v) => v ? `€${Number(v).toFixed(2)}` : '—' },
                    { key: 'branch_id', label: 'Branch' },
                    { key: 'redeemed_at', label: 'Redeemed', render: (v) => v ? new Date(v).toLocaleString() : '—' },
                  ],
                });
              } catch (e) { alert('Failed: ' + (e?.response?.data?.detail || e.message)); }
            }}
          />
          <MetricTile controlledDays={tilesDays}
            icon={Calendar} title="Premières visites" accent="#2F6BFF"
            metric="first_time_today" branchId={branchId}
            initial={{ value: 1, unit: 'day' }}
            sublabel={(d) => `Inscrits sur les ${d} derniers jours`}
            onDrill={(d) => drillCustomers(`Premières inscriptions (${d}j)`, { created_within_days: d })}
          />
        </section>

        <section className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-3">
          <MetricTile controlledDays={tilesDays}
            icon={Trophy} title="Loyal" accent="#2F6BFF"
            metric="loyal_customers" branchId={branchId}
            initial={{ value: 30, unit: 'day' }}
            sublabel={(d) => `≥ seuil "Loyal" sur ${d}j`}
            onDrill={() => drillCustomers('Loyal customers', { loyalty_bucket: 'loyal' })}
          />
          <MetricTile controlledDays={tilesDays}
            icon={RepeatIcon} title="Réguliers" accent="#2F6BFF"
            metric="regular_customers" branchId={branchId}
            initial={{ value: 30, unit: 'day' }}
            sublabel={(d) => `≥ seuil "Régulier" sur ${d}j`}
            onDrill={() => drillCustomers('Regular customers', { loyalty_bucket: 'regular' })}
          />
          <MetricTile controlledDays={tilesDays}
            icon={Activity} title="Visites totales" accent="#2F6BFF"
            metric="total_visits" branchId={branchId}
            initial={{ value: 30, unit: 'day' }}
            sublabel={(d) => `Visites enregistrées sur ${d}j`}
            onDrill={(d) => drillCustomers(`Customers visited last ${d}d`, { active_within_days: d })}
          />
          <MetricTile controlledDays={tilesDays}
            icon={Calendar} title="Anniversaires ce mois" accent="#2F6BFF"
            metric="birthdays_this_month_static"
            branchId={branchId}
            staticValue={birthdaysThisMonth}
            initial={{ value: 1, unit: 'month' }}
            sublabel={() => 'Mois en cours · pas filtrable'}
            disablePicker
            onDrill={() => drillCustomers('Birthdays this month', { has_birthday_this_month: true })}
          />
        </section>
      </div>

      {/* ═════════════════════════════════════════════════════════════════
          2) GRAPHS + PIE CHARTS — Visites · Acquisition · Donuts · Tier+Acq.
          ═════════════════════════════════════════════════════════════════ */}
      {/* Filter A — charts only (Visites + Acquisition). */}
      <div className="flex items-baseline justify-between gap-3 flex-wrap mt-1 mb-0.5">
        <h3 className="text-[12px] font-bold text-[#0F172A]" style={{ fontFamily: 'Cormorant Garamond' }}>
          Fenêtre de temps — Visites · Acquisition
        </h3>
        <span className="text-[10px] uppercase tracking-widest font-bold text-[#64748B]">
          {chartsDays} jour{chartsDays === 1 ? '' : 's'}
        </span>
      </div>
      <SharedTimeFilter value={chartsFilter} onChange={setChartsFilter} sharedDays={chartsDays} />

      {/* Visits chart + Acquisition chart — driven by chartsFilter. */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <VisitsTwinChart controlledDays={chartsDays} />
        <WeeklyAcquisitionPanel controlledDays={chartsDays} />
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <AcquisitionDonut />
        <TierDonut />
      </div>

      {/* Row 3 — tier + acquisition, each tier / source wired to a send CTA */}
      <section className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <ChartCard title="Customer Tier Distribution" hint="How your loyalty tiers are spread. Click any tier to see its customers.">
          <div className="grid grid-cols-3 gap-2 mb-4">
            {tierData.map((t) => (
              <button
                key={t.key}
                type="button"
                onClick={() => drillCustomers(`${t.name} tier customers`, { tier: t.key })}
                className="flex flex-col items-center gap-1 p-2 rounded-lg border border-[#DCE3EF] bg-[#F5F7FB] hover:bg-[#2F6BFF]/5 hover:border-[#2F6BFF] transition cursor-pointer text-left"
                title={`Click to view ${t.name} customers`}
              >
                <div className="flex items-center gap-2">
                  <span className="w-3 h-3 rounded-full" style={{ background: TIER_COLORS[t.key] }}></span>
                  <span className="text-xs font-semibold text-[#0F172A]">{t.name}</span>
                </div>
                <span className="text-lg font-bold">{t.value}</span>
                <span className="text-[10px] text-[#64748B]">
                  {totalCustomers ? `${Math.round((t.value / totalCustomers) * 100)}%` : '—'} · click to view
                </span>
                <SendCampaignButton
                  compact
                  label={`Send to ${t.name}`}
                  onClick={() => openComposer(
                    { type: 'tier', value: t.key },
                    `Offre exclusive ${t.name} pour {first_name}`,
                    `Parce que vous êtes ${t.name}, voici une attention spéciale de {business_name}. Il te reste {points_to_next_reward} points pour ta prochaine récompense.`
                  )}
                />
              </button>
            ))}
          </div>
          {/* Donut + side legend. The previous pie drew its labels on top of
              the slices and the legend, so nothing was readable. */}
          <div className="flex items-center gap-6">
            <div className="shrink-0" style={{ width: 200, height: 200 }}>
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={tierData.filter((t) => t.value > 0)}
                    cx="50%"
                    cy="50%"
                    innerRadius={62}
                    outerRadius={94}
                    paddingAngle={2}
                    dataKey="value"
                    stroke="#FFFFFF"
                    strokeWidth={2}
                    isAnimationActive={false}
                    onClick={(data) => data && drillCustomers(`${data.name} tier customers`, { tier: data.key })}
                    style={{ cursor: 'pointer' }}
                  >
                    {tierData.filter((t) => t.value > 0).map((t, i) => (
                      <Cell key={i} fill={TIER_COLORS[t.key] || '#9CA3AF'} />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{ background: '#FFFFFF', border: '1px solid #DCE3EF', borderRadius: 8, padding: '4px 8px', fontSize: 11 }}
                    formatter={(v, n) => [`${v} clients`, n]}
                  />
                </PieChart>
              </ResponsiveContainer>
            </div>
            <div className="flex-1 min-w-0 space-y-2">
              {tierData.map((t) => {
                const pct = totalCustomers ? Math.round((t.value / totalCustomers) * 100) : 0;
                return (
                  <button key={t.key} type="button"
                          onClick={() => drillCustomers(`${t.name} tier customers`, { tier: t.key })}
                          className="w-full text-left" title={`Click to view ${t.name} customers`}>
                    <div className="flex items-center justify-between text-xs">
                      <span className="flex items-center gap-2 text-[#0F172A] font-semibold">
                        <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: TIER_COLORS[t.key] }} />
                        {t.name}
                      </span>
                      <span className="text-[#64748B]"><span className="text-[#0F172A] font-semibold">{t.value}</span> · {pct}%</span>
                    </div>
                    <div className="mt-1 h-1.5 rounded-full bg-[#EEF2F9] overflow-hidden">
                      <div className="h-full rounded-full" style={{ width: `${pct}%`, background: TIER_COLORS[t.key] }} />
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        </ChartCard>

        <ChartCard title="Acquisition Sources" hint="Lifetime customers acquired through each channel — all-time totals.">
          {/* Lifetime headline */}
          <div className="flex items-baseline gap-3 mb-4 pb-4 border-b border-[#DCE3EF]">
            <p className="text-3xl font-bold text-[#0F172A]" style={{ fontFamily: 'Cormorant Garamond' }}>
              {acquisitionTotal}
            </p>
            <p className="text-sm text-[#334155]">customers acquired across all channels (all-time)</p>
          </div>

          {/* Per-channel KPI tiles — count + percentage. Click to drill into customer list. */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
            {acquisitionChart.map((a) => {
              const style = SOURCE_STYLE[a.raw] || { color: '#64748B', bg: '#F5F7FB', icon: '•' };
              return (
                <button
                  key={a.raw}
                  type="button"
                  onClick={() => drillCustomers(
                    `Customers acquired via ${a.name}`,
                    { source: a.raw }
                  )}
                  className="text-left p-3 rounded-lg border border-[#DCE3EF] hover:border-[#2F6BFF] hover:shadow-sm transition"
                  style={{ backgroundColor: style.bg }}
                >
                  <div className="flex items-center gap-1.5 mb-1">
                    <span className="text-base">{style.icon}</span>
                    <span className="text-[11px] font-bold uppercase tracking-wider" style={{ color: style.color }}>
                      {a.name}
                    </span>
                  </div>
                  <p className="text-2xl font-bold text-[#0F172A] leading-tight">
                    {a.value}
                    <span className="text-sm text-[#64748B] font-normal"> customers</span>
                  </p>
                  <p className="text-[11px] mt-0.5 font-semibold" style={{ color: style.color }}>
                    {a.pct}% of total
                  </p>
                </button>
              );
            })}
          </div>

          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={acquisitionChart} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" stroke="var(--flc-line, #DCE3EF)" />
              <XAxis type="number" stroke="var(--flc-ink3, #334155)" />
              <YAxis type="category" dataKey="name" stroke="var(--flc-ink3, #334155)" width={110} />
              <Tooltip
                formatter={(value, _name, p) => [`${value} customers (${p?.payload?.pct || 0}%)`, 'Acquired']}
              />
              <Bar dataKey="value" radius={[0, 8, 8, 0]}>
                {acquisitionChart.map((row, i) => (
                  <Cell key={i} fill={(SOURCE_STYLE[row.raw] || {}).color || ACQ_COLORS[i % ACQ_COLORS.length]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
      </section>


      {/* Visits-by-day with campaign send markers (clickable for details).
          The two range-selectable charts (acquisition history + visits over
          time) are now placed up top inside the main analytics grid — no
          longer duplicated here. */}
      <VisitsWithCampaignsChart />

      {/* Row 4b — Customer reviews & sentiment */}
      <section
        className="rounded-xl p-4 space-y-3 relative overflow-hidden"
        style={{
          background: `radial-gradient(circle at 100% 0%, color-mix(in srgb, var(--flc-accent-2, #5B8DEF) 9%, transparent) 0%, transparent 55%), radial-gradient(circle at 0% 100%, color-mix(in srgb, var(--flc-accent, #2F6BFF) 7%, transparent) 0%, transparent 60%), var(--flc-card, #FFFFFF)`,
          border: '1px solid color-mix(in srgb, var(--flc-accent, #2F6BFF) 27%, transparent)',
          boxShadow: '0 6px 18px -10px #2F6BFF66',
        }}
      >
        <div className="relative flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h3 className="text-base font-bold" style={{ fontFamily: 'Cormorant Garamond', color: 'var(--flc-ink2, #334155)' }}>
              Customer reviews & sentiment
            </h3>
            <p className="text-xs max-w-3xl mt-1" style={{ color: 'var(--flc-ink2, #334155)' }}>
              Every rating is /10. Customers leave ratings on their wallet card after a visit.
              Sentiment and topics are computed from the review text on submit — numbers stay up to date
              automatically whenever a new review is posted.
            </p>
          </div>
          {reviewAnalytics?.total_reviews != null && (
            <div className="flex items-center gap-2 text-xs text-[#334155]">
              <MessageSquare size={14} /> {reviewAnalytics.total_reviews} review{reviewAnalytics.total_reviews === 1 ? '' : 's'} total
            </div>
          )}
        </div>

        {reviewAnalytics && reviewAnalytics.total_reviews === 0 ? (
          <p className="text-sm text-[#64748B] italic">
            No reviews yet. Once customers start rating visits from their wallet card, the KPIs will appear here.
          </p>
        ) : reviewAnalytics ? (
          <>
            {/* 4 headline KPIs with meanings */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
              <KPICard
                icon={Star}
                title="Average rating"
                value={reviewAnalytics.average_rating != null ? `${reviewAnalytics.average_rating}/10` : '—'}
                sublabel="The mean rating across every review."
                accent="#93B4FF"
                onClick={() => drillCustomers('All reviewers', {})}
                segment={{ type: 'all' }}
                openComposer={openComposer}
                presetName="Merci pour votre avis, {first_name}"
                presetContent="Merci d'avoir noté votre visite chez {business_name}. Continuez à nous partager votre expérience — on vous réserve une petite surprise !"
              />
              <KPICard
                icon={ThumbsDown}
                title="Negative review rate"
                value={`${reviewAnalytics.negative_review_rate_pct}%`}
                sublabel="% of reviews at 1–4 / 10. Leading indicator of churn."
                accent="#2F6BFF"
                onClick={async () => {
                  try {
                    const r = await ownerAPI.listReviews(params({ max_rating: 4, limit: 200 }));
                    setDrill({
                      title: 'Negative reviews (1–4 / 10)',
                      rows: r.data?.reviews || [],
                      columns: [
                        { key: 'customer_name', label: 'Customer' },
                        { key: 'rating', label: 'Rating', render: (v) => `${v}/10` },
                        { key: 'sentiment', label: 'Sentiment' },
                        { key: 'topics', label: 'Topics', render: (v) => (v || []).join(', ') || '—' },
                        { key: 'text', label: 'Text', render: (v) => v || '—' },
                        { key: 'created_at', label: 'When', render: (v) => v ? new Date(v).toLocaleDateString() : '—' },
                      ],
                    });
                  } catch (e) { alert('Failed: ' + e.message); }
                }}
                segment={{ type: 'all' }}
                openComposer={openComposer}
                presetName="On peut mieux faire, {first_name}"
                presetContent="Merci pour votre retour. Nous prenons note et aimerions vous inviter à revenir chez {business_name} — une attention vous attend."
              />
              <KPICard
                icon={ThumbsUp}
                title="Sentiment score"
                value={`${reviewAnalytics.sentiment_score > 0 ? '+' : ''}${reviewAnalytics.sentiment_score}`}
                sublabel="Positive % minus negative %. -100 = all bad, +100 = all good."
                accent="#2F6BFF"
                onClick={async () => {
                  try {
                    const r = await ownerAPI.listReviews(params({ sentiment: 'negative', limit: 200 }));
                    setDrill({
                      title: 'Negative-sentiment reviews',
                      rows: r.data?.reviews || [],
                      columns: [
                        { key: 'customer_name', label: 'Customer' },
                        { key: 'rating', label: 'Rating', render: (v) => `${v}/10` },
                        { key: 'text', label: 'Text', render: (v) => v || '—' },
                        { key: 'topics', label: 'Topics', render: (v) => (v || []).join(', ') || '—' },
                      ],
                    });
                  } catch (e) { alert('Failed: ' + e.message); }
                }}
                segment={{ type: 'all' }}
                openComposer={openComposer}
                presetName="Vos retours comptent, {first_name}"
                presetContent="Votre expérience chez {business_name} compte. Dites-nous ce qu'on peut améliorer — on vous offre un petit geste à votre prochaine visite."
              />
              <KPICard
                icon={TrendingUp}
                title="Review velocity"
                value={`${reviewAnalytics.review_velocity.last_30d}`}
                sublabel={
                  reviewAnalytics.review_velocity.delta_pct >= 0
                    ? `+${reviewAnalytics.review_velocity.delta_pct}% vs. the 30 days before (${reviewAnalytics.review_velocity.prev_30d})`
                    : `${reviewAnalytics.review_velocity.delta_pct}% vs. the 30 days before (${reviewAnalytics.review_velocity.prev_30d})`
                }
                accent="#1D4ED8"
                onClick={async () => {
                  try {
                    const r = await ownerAPI.listReviews(params({ limit: 30 }));
                    setDrill({
                      title: 'Recent reviews (last 30)',
                      rows: r.data?.reviews || [],
                      columns: [
                        { key: 'customer_name', label: 'Customer' },
                        { key: 'rating', label: 'Rating', render: (v) => `${v}/10` },
                        { key: 'sentiment', label: 'Sentiment' },
                        { key: 'text', label: 'Text', render: (v) => v || '—' },
                        { key: 'created_at', label: 'When', render: (v) => v ? new Date(v).toLocaleDateString() : '—' },
                      ],
                    });
                  } catch (e) { alert('Failed: ' + e.message); }
                }}
                segment={{ type: 'all' }}
                openComposer={openComposer}
                presetName="Gardez le cap, {first_name}"
                presetContent="Nous adorons vos retours chez {business_name}. Un petit mot après votre prochaine visite ?"
              />
            </div>

            {/* Rating distribution + topic breakdown side by side */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 pt-2">
              {/* Rating distribution (1-10 histogram) */}
              <div className="border border-[#DCE3EF] rounded-lg p-4">
                <p className="text-sm font-bold text-[#0F172A] mb-2 flex items-center gap-2">
                  <Star size={14} /> Rating distribution
                </p>
                <p className="text-xs text-[#64748B] mb-3">
                  How many reviews landed at each score. Bars show share of total.
                </p>
                <div className="space-y-1">
                  {(() => {
                    const dist = reviewAnalytics.rating_distribution || {};
                    const max = Math.max(1, ...Object.values(dist).map(v => +v || 0));
                    return [10, 9, 8, 7, 6, 5, 4, 3, 2, 1].map((n) => {
                      const v = dist[String(n)] || 0;
                      const pct = Math.round((v / max) * 100);
                      const color = n >= 8 ? '#2F6BFF' : n >= 5 ? '#8FB0FF' : '#C7D7FF';
                      return (
                        <div key={n} className="flex items-center gap-2 text-xs">
                          <span className="w-6 text-right font-semibold text-[#0F172A]">{n}</span>
                          <div className="flex-1 bg-[#F5F7FB] rounded h-4 overflow-hidden">
                            <div className="h-full rounded" style={{ width: `${pct}%`, backgroundColor: color }} />
                          </div>
                          <span className="w-8 text-right text-[#334155]">{v}</span>
                        </div>
                      );
                    });
                  })()}
                </div>
              </div>

              {/* Topic breakdown */}
              <div className="border border-[#DCE3EF] rounded-lg p-4">
                <p className="text-sm font-bold text-[#0F172A] mb-2 flex items-center gap-2">
                  <Activity size={14} /> Topic / theme breakdown
                </p>
                <p className="text-xs text-[#64748B] mb-3">
                  Which themes customers mention and the average rating per theme. Lets you see
                  <em> why</em> ratings move — not just that they did.
                </p>
                {(reviewAnalytics.topic_breakdown || []).length === 0 ? (
                  <p className="text-xs text-[#64748B] italic">No text mentions to cluster yet.</p>
                ) : (
                  <div className="space-y-2">
                    {reviewAnalytics.topic_breakdown.map((t) => {
                      const label = {
                        speed: '⚡ Service speed',
                        cleanliness: '🧼 Cleanliness',
                        staff: '🤝 Staff friendliness',
                        price: '💶 Price / value',
                        wait_time: '⏱ Wait time',
                      }[t.topic] || t.topic;
                      const avgColor = t.avg_rating >= 8 ? '#16A34A' : t.avg_rating >= 6 ? '#1D4ED8' : '#E11D48';
                      return (
                        <div key={t.topic} className="p-2 rounded bg-[#F5F7FB] border border-[#DCE3EF]">
                          <div className="flex items-center justify-between text-xs">
                            <span className="font-semibold text-[#0F172A]">{label}</span>
                            <span style={{ color: avgColor }} className="font-bold">{t.avg_rating}/10 · {t.count} mention{t.count === 1 ? '' : 's'}</span>
                          </div>
                          <div className="mt-1 flex h-1.5 rounded overflow-hidden">
                            <div style={{ width: `${t.positive_pct}%`, backgroundColor: '#16A34A' }} />
                            <div style={{ width: `${100 - t.positive_pct - t.negative_pct}%`, backgroundColor: '#CBD5E1' }} />
                            <div style={{ width: `${t.negative_pct}%`, backgroundColor: '#E11D48' }} />
                          </div>
                          <p className="text-[10px] text-[#64748B] mt-1">
                            {t.positive_pct}% positive · {t.negative_pct}% negative · {t.mention_pct}% of reviews mention this
                          </p>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>

            {/* Recent reviews feed */}
            {(reviewAnalytics.recent || []).length > 0 && (
              <div className="border border-[#DCE3EF] rounded-lg p-4">
                <p className="text-sm font-bold text-[#0F172A] mb-2">Most recent reviews</p>
                <div className="space-y-2">
                  {reviewAnalytics.recent.map((r) => (
                    <div key={r.id} className="p-3 rounded bg-[#F5F7FB] border border-[#DCE3EF] flex items-start gap-3">
                      <div className={`shrink-0 w-12 h-12 rounded-full flex items-center justify-center font-bold text-white`}
                           style={{ backgroundColor: r.rating >= 8 ? '#16A34A' : r.rating >= 5 ? '#5B8DEF' : '#E11D48' }}>
                        {r.rating}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap text-xs">
                          <span className="font-semibold text-[#0F172A]">{r.sentiment}</span>
                          {r.topics?.length > 0 && (
                            <span className="text-[#64748B]">· {r.topics.join(', ')}</span>
                          )}
                          <span className="text-[#64748B] ml-auto">
                            {r.created_at ? new Date(r.created_at).toLocaleDateString() : ''}
                          </span>
                        </div>
                        {r.text && <p className="text-sm text-[#0F172A] mt-1">"{r.text}"</p>}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        ) : (
          <p className="text-sm text-[#64748B]">Loading review data…</p>
        )}
      </section>

      {/* Row 5 — Ranking Tabs */}
      <section
        className="rounded-xl p-4 relative overflow-hidden"
        style={{
          background: `radial-gradient(circle at 100% 0%, color-mix(in srgb, var(--flc-info, #2F6BFF) 9%, transparent) 0%, transparent 55%), radial-gradient(circle at 0% 100%, color-mix(in srgb, var(--flc-ok, #16A34A) 7%, transparent) 0%, transparent 60%), var(--flc-card, #FFFFFF)`,
          border: '1px solid color-mix(in srgb, var(--flc-info, #2F6BFF) 27%, transparent)',
          boxShadow: '0 6px 18px -10px #6BA4D955',
        }}
      >
        <div className="relative flex flex-wrap items-center justify-between gap-3 mb-4">
          <h3 className="text-base font-bold" style={{ fontFamily: 'Cormorant Garamond', color: 'var(--flc-info, #1D4ED8)' }}>
            Customer Ranking
          </h3>
          <div className="flex flex-wrap gap-2">
            {[
              { key: 'top_paying', label: 'Top Paying', icon: Trophy },
              { key: 'least_paying', label: 'Least Paying', icon: ArrowDown },
              { key: 'max_visits', label: 'Max Visits', icon: ArrowUp },
              { key: 'least_visits', label: 'Least Visits', icon: ArrowDown },
            ].map((t) => {
              const Icon = t.icon;
              const active = rankingMode === t.key;
              return (
                <button
                  key={t.key}
                  onClick={() => setRankingMode(t.key)}
                  className={`px-3 py-1.5 rounded-full text-sm font-medium flex items-center gap-1.5 transition-colors ${
                    active
                      ? 'bg-[#2F6BFF] text-white'
                      : 'bg-[#F5F7FB] text-[#334155] hover:bg-[#DCE3EF]'
                  }`}
                >
                  <Icon size={14} />
                  {t.label}
                </button>
              );
            })}
            <SendCampaignButton
              label="Send to this ranking"
              onClick={() => openComposer(rankingSegment, rankingPreset.name, rankingPreset.content)}
            />
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse text-sm">
            <thead>
              <tr className="border-b border-[#DCE3EF] text-[#334155]">
                <th className="py-2 px-3">#</th>
                <th className="py-2 px-3">Customer</th>
                <th className="py-2 px-3">Email</th>
                <th className="py-2 px-3">Tier</th>
                <th className="py-2 px-3 text-right">Visits</th>
                <th className="py-2 px-3 text-right">Spent</th>
              </tr>
            </thead>
            <tbody>
              {rankedCustomers.length === 0 ? (
                <tr><td colSpan={6} className="py-6 text-center text-[#64748B]">No customers to rank yet.</td></tr>
              ) : (
                rankedCustomers.map((c, i) => (
                  <tr key={c.id || i} className="border-b border-[#DCE3EF] hover:bg-[#F5F7FB]">
                    <td className="py-2 px-3 text-[#64748B]">{i + 1}</td>
                    <td className="py-2 px-3 font-medium text-[#0F172A]">{c.name || '—'}</td>
                    <td className="py-2 px-3 text-[#334155] text-xs">{c.email || '—'}</td>
                    <td className="py-2 px-3"><TierBadge tier={c.tier} /></td>
                    <td className="py-2 px-3 text-right">{c.total_visits ?? 0}</td>
                    <td className="py-2 px-3 text-right">€{(c.total_amount_paid ?? 0).toFixed(2)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* Drill-down modal */}
      {drill && (
        <div
          className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"
          onClick={() => setDrill(null)}
        >
          <div
            className="bg-white rounded-xl max-w-5xl w-full max-h-[85vh] overflow-auto p-6"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex justify-between items-center mb-4">
              <h3 className="text-2xl font-bold text-[#0F172A]" style={{ fontFamily: 'Cormorant Garamond' }}>
                {drill.title}
              </h3>
              <button onClick={() => setDrill(null)} className="text-[#94A3B8] hover:text-[#0F172A]">
                <X size={22} />
              </button>
            </div>
            {drillLoading ? (
              <p className="text-[#334155] py-8 text-center">Loading customers…</p>
            ) : drill.error ? (
              <p className="text-[#2F6BFF] py-8 text-center">Error: {drill.error}</p>
            ) : (!drill.rows || drill.rows.length === 0) ? (
              <p className="text-[#334155] py-8 text-center">No matching records.</p>
            ) : (
              <table className="w-full text-left border-collapse text-sm">
                <thead>
                  <tr className="border-b border-[#DCE3EF] text-[#334155]">
                    {drill.columns.map((c) => (
                      <th key={c.key} className="py-2 px-3">{c.label}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {drill.rows.map((r, i) => (
                    <tr key={i} className="border-b border-[#DCE3EF]">
                      {drill.columns.map((c) => (
                        <td key={c.key} className="py-2 px-3 text-[#0F172A]">
                          {c.render ? c.render(r[c.key]) : (r[c.key] ?? '—')}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}

      {/* Campaign composer */}
      {composer && (
        <CampaignComposer
          segment={composer.segment}
          presetName={composer.presetName}
          presetContent={composer.presetContent}
          onClose={() => setComposer(null)}
          onSent={loadAll}
        />
      )}
      {/* Row 4 — Recovered Filter */}
      <section
        className="rounded-xl p-4 relative overflow-hidden"
        style={{
          background: `radial-gradient(circle at 100% 0%, color-mix(in srgb, var(--flc-ok, #16A34A) 10%, transparent) 0%, transparent 55%), radial-gradient(circle at 0% 100%, color-mix(in srgb, var(--flc-ok, #16A34A) 7%, transparent) 0%, transparent 60%), var(--flc-card, #FFFFFF)`,
          border: '1px solid color-mix(in srgb, var(--flc-ok, #16A34A) 27%, transparent)',
          boxShadow: '0 6px 18px -10px #6FA89C55',
        }}
      >
        <div className="relative flex flex-wrap items-start justify-between gap-3 mb-2">
          <h3 className="text-base font-bold" style={{ fontFamily: 'Cormorant Garamond', color: 'var(--flc-ok, #1D4ED8)' }}>
            Customize Recovered Customers Filter
          </h3>
          <SendCampaignButton
            label="Send to this filtered group"
            onClick={() => openComposer(
              { type: 'recovered', inactive_days: recoveryInactiveDays, window_days: recoveryWindowDays },
              'Bon retour parmi nous, {first_name} !',
              'Merci de revenir chez {business_name}. Il te reste {points_to_next_reward} points pour ta prochaine récompense.'
            )}
          />
        </div>
        <p className="text-sm text-[#334155] mb-4">
          "Customers who were quiet for X days and came back in the last Y days"
        </p>
        <div className="flex flex-wrap items-center gap-6">
          <div className="flex items-center gap-2">
            <label className="text-sm text-[#334155]">Inactive for</label>
            <NumberInput
              min={1}
              max={730}
              emptyValue={30}
              value={recoveryInactiveDays}
              onChange={(n) => setRecoveryInactiveDays(n || 30)}
              className="w-20 px-2 py-1 border border-[#DCE3EF] rounded text-center"
            />
            <span className="text-sm text-[#334155]">days,</span>
          </div>
          <div className="flex items-center gap-2">
            <label className="text-sm text-[#334155]">came back in last</label>
            <NumberInput
              min={1}
              max={730}
              emptyValue={30}
              value={recoveryWindowDays}
              onChange={(n) => setRecoveryWindowDays(n || 30)}
              className="w-20 px-2 py-1 border border-[#DCE3EF] rounded text-center"
            />
            <span className="text-sm text-[#334155]">days</span>
          </div>
          <div className="ml-auto flex items-center gap-3 text-sm text-[#0F172A] font-medium">
            <span>
              <span className="text-[#2F6BFF] font-bold">{recovered?.count ?? 0}</span> customers match
              {' '}
              <span className="text-[#64748B]">({recovered?.percentage ?? 0}% of base)</span>
            </span>
            <button
              type="button"
              disabled={!recovered?.count}
              onClick={() =>
                setDrill({
                  title: `Recovered customers — inactive ${recoveryInactiveDays}d, returned within ${recoveryWindowDays}d`,
                  rows: recovered?.customers || [],
                  columns: [
                    { key: 'name', label: 'Customer' },
                    { key: 'email', label: 'Email' },
                    { key: 'tier', label: 'Tier', render: (v) => <TierBadge tier={v} /> },
                    { key: 'total_visits', label: 'Visits' },
                    { key: 'total_amount_paid', label: 'Spent', render: (v) => `€${(v || 0).toFixed(0)}` },
                    { key: 'last_inactive_date', label: 'Gap started', render: (v) => v ? new Date(v).toLocaleDateString() : '—' },
                    { key: 'returned_date', label: 'Returned', render: (v) => v ? new Date(v).toLocaleDateString() : '—' },
                  ],
                })
              }
              className="px-3 py-1.5 rounded-lg border text-sm font-semibold transition disabled:opacity-40"
              style={{ borderColor: '#2F6BFF', color: '#2F6BFF' }}
              title="Show the list of customers that match the filter above"
            >
              View the {recovered?.count ?? 0} customer{recovered?.count === 1 ? '' : 's'}
            </button>
          </div>
        </div>
      </section>

    </div>
  );
};

export default AnalyticsPage;
