import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  BarChart3, Users, Crown, ShoppingBag, Target, TrendingUp, Send,
  MousePointerClick, ShoppingCart, ChevronRight, ArrowRight,
  Loader2, Mail, UserX, Star, FileDown, Info, Zap, Check, X, Gift,
} from 'lucide-react';
import { ownerAPI } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';
import PeriodMenu, { periodDays, validPeriod } from '../components/PeriodMenu';
import InfoTip from '../components/InfoTip';
import ImpactFidClicCard from '../components/ImpactFidClicCard';
import DecimalInput from '../components/DecimalInput';
import { eur } from '../lib/money';

/**
 * Tableau de bord — the home page, built to the approved design.
 *
 * Eleven panels off one payload (/api/owner/home/overview), because they all
 * read the same month of visits and asking eleven times would read those rows
 * eleven times.
 *
 * Nothing here is demo data. A shop that opened yesterday reads zero and says
 * so, the recommendations only appear when the figures support them, and two
 * panels carry a note about what they really mean: "Impact FidClic" counts
 * only visits the platform can tie to something it sent, and the affluence
 * grid covers 8h–20h, so a bar's late trade is reported beside it rather than
 * silently dropped.
 */
const KPI_ICONS = { chart: BarChart3, users: Users, crown: Crown, bag: ShoppingBag, target: Target, star: Star, moon: UserX };
const TONES = {
  blue:   { bg: '#EAF1FF', fg: '#1D4ED8', dot: '#2F6BFF' },
  green:  { bg: '#E7F7EE', fg: '#0F8B58', dot: '#10B981' },
  amber:  { bg: '#FFF7E6', fg: '#B45309', dot: '#F59E0B' },
  violet: { bg: '#F3EEFF', fg: '#6D28D9', dot: '#8B5CF6' },
  slate:  { bg: '#EEF2F8', fg: '#475569', dot: '#94A3B8' },
  rose:   { bg: '#FDECEF', fg: '#E11D48', dot: '#F43F5E' },
};

const MONTHS = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.'];
const nf = (n) => (n ?? 0).toLocaleString('fr-FR');
// 93,10 € — cents keep two digits (lib/money)
const money = eur;
const dayLabel = (iso) => { const d = new Date(iso); return `${d.getDate()} ${MONTHS[d.getMonth()]}`; };
// A point of a series: a day, or an hour for « Aujourd'hui » (it carries its label).
const pointLabel = (q) => q.label || dayLabel(q.date);

/* ── pieces ───────────────────────────────────────────────────────────── */
// Each panel's « ? » (lib/metricHelp), found from its title.
const PANEL_HELP = {
  "Évolution du chiffre d'affaires": 'revenue', 'Nouveaux clients': 'new_clients',
  'Performance des campagnes': 'campaign_perf', 'Produits les plus populaires': 'products',
  "Heures d'affluence": 'hours', 'Statut des clients': 'segmentation', 'Recommandations pour vous': 'recommendations',
};

const Panel = ({ title, action, children, className = '' }) => (
  <section className={`rounded-2xl border border-[#E6EEFB] bg-white p-5 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)] ${className}`}>
    {(title || action) && (
      <header className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h2 className="flex items-center gap-1.5 text-[15px] font-bold text-[#0B1C3F]">
          {title} {PANEL_HELP[title] && <InfoTip k={PANEL_HELP[title]} />}
        </h2>
        {action}
      </header>
    )}
    {children}
  </section>
);

const SeeAll = ({ onClick, label = 'Voir toutes' }) => (
  <button type="button" onClick={onClick}
          className="inline-flex shrink-0 items-center gap-1 text-[12.5px] font-semibold text-[#2F6BFF] hover:underline">
    {label} <ArrowRight size={13} />
  </button>
);

/* One control, three places. Every picker on this page reads and writes the
   same period, so the header, the revenue chart and the new-clients chart can
   never disagree about which period is on screen (components/PeriodMenu). */
const RangePicker = ({ value, onChange, busy = false, lead = false }) => (
  <PeriodMenu value={value} onChange={onChange} busy={busy} lead={lead} />
);

// The figures read big and green (user, 2026-10-02); « Clients inactifs » in
// rose — more of them is bad news. Each card opens what it counts.
const KpiCard = ({ card, onOpen }) => {
  const Icon = KPI_ICONS[card.icon] || BarChart3;
  const t = TONES[card.tone] || TONES.blue;
  const up = (card.delta_pct ?? 0) >= 0;
  const good = card.lower_is_better ? !up : up;
  return (
    <div role="button" tabIndex={0} onClick={() => card.to && onOpen(card.to)} onKeyDown={(e) => { if (e.key === 'Enter' && card.to) onOpen(card.to); }}
         title={card.to ? 'Voir le détail' : undefined}
         className="cursor-pointer rounded-2xl border border-[#E6EEFB] bg-white p-5 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)] transition hover:border-[#BFD3FF] hover:shadow-[0_18px_40px_-28px_rgba(47,107,255,.45)]">
      <div className="mb-3 flex items-center justify-between gap-2">
        <span className="flex h-10 w-10 items-center justify-center rounded-xl"
              style={{ background: t.bg, color: t.fg }}>
          <Icon size={19} />
        </span>
        {card.badge && (
          <span className="inline-flex items-center gap-1 rounded-md bg-[#EAF1FF] px-2 py-0.5 text-[10.5px] font-bold text-[#2F6BFF]">
            <Zap size={10} /> {card.badge}
          </span>
        )}
      </div>
      <p className="flex items-center gap-1 text-[12.5px] text-[#64748B]">{card.label} <InfoTip k={card.key} /></p>
      <p className="mt-1 text-[32px] font-extrabold leading-none tracking-tight tabular-nums" style={{ color: card.lower_is_better ? '#E11D48' : '#0F8B58' }}>
        {card.unit === '€' ? money(card.value) : nf(card.value)}
      </p>
      {card.delta_pct === null || card.delta_pct === undefined ? (
        <p className="mt-2.5 text-[11px] text-[#94A3B8]">pas encore de comparaison</p>
      ) : (
        <div className="mt-2.5">
          <span className="inline-flex items-center gap-0.5 rounded-md px-1.5 py-0.5 text-[11.5px] font-semibold"
                style={good ? { background: '#E7F7EE', color: '#0F8B58' } : { background: '#FEECEC', color: '#C0392B' }}>
            {up ? '↑' : '↓'} {up ? '+' : ''}{card.delta_pct}%
          </span>
          <span className="mt-1 block text-[11px] text-[#94A3B8]">vs période précédente</span>
        </div>
      )}
    </div>
  );
};

/** Line + area, drawn as plain SVG so the shape matches the design exactly. */
const LineChart = ({ series, money: isMoney }) => {
  const W = 620, H = 200, PAD_L = 46, PAD_B = 24, PAD_T = 10, PAD_R = 8;
  const pts = series || [];
  const max = Math.max(1, ...pts.map((p) => p.value));
  const step = Math.pow(10, Math.max(0, String(Math.round(max)).length - 1)) / 2 || 1;
  const top = Math.max(step, Math.ceil(max / step) * step);
  const iw = W - PAD_L - PAD_R, ih = H - PAD_T - PAD_B;
  const x = (i) => PAD_L + (pts.length <= 1 ? iw / 2 : (i / (pts.length - 1)) * iw);
  const y = (v) => PAD_T + ih - (v / top) * ih;
  const line = pts.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(' ');
  const area = pts.length ? `${line} L${x(pts.length - 1).toFixed(1)},${PAD_T + ih} L${x(0).toFixed(1)},${PAD_T + ih} Z` : '';
  const ticks = [0, top / 2, top];
  const idx = pts.length <= 1 ? [0] : [0, Math.round((pts.length - 1) / 3), Math.round((pts.length - 1) * 2 / 3), pts.length - 1];
  if (!pts.length) return <p className="py-12 text-center text-[13px] text-[#94A3B8]">Aucune donnée sur la période.</p>;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height: 200 }}>
      <defs>
        <linearGradient id="dhLine" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#2F6BFF" stopOpacity="0.26" />
          <stop offset="100%" stopColor="#2F6BFF" stopOpacity="0.02" />
        </linearGradient>
      </defs>
      {ticks.map((v) => (
        <g key={v}>
          <line x1={PAD_L} x2={W - PAD_R} y1={y(v)} y2={y(v)} stroke="#EEF3FB" />
          <text x={PAD_L - 8} y={y(v) + 4} textAnchor="end" fontSize="10.5" fill="#94A3B8">
            {isMoney ? `${nf(Math.round(v))} €` : nf(Math.round(v))}
          </text>
        </g>
      ))}
      <path d={area} fill="url(#dhLine)" />
      <path d={line} fill="none" stroke="#2F6BFF" strokeWidth="2.2" strokeLinejoin="round" strokeLinecap="round" />
      {pts.map((p, i) => (
        <circle key={p.date} cx={x(i)} cy={y(p.value)} r="2.6" fill="#fff" stroke="#2F6BFF" strokeWidth="1.8">
          <title>{`${pointLabel(p)} — ${isMoney ? money(p.value) : nf(p.value)}`}</title>
        </circle>
      ))}
      {idx.map((i) => (
        <text key={i} x={x(i)} y={H - 5} fontSize="10.5" fill="#94A3B8"
              textAnchor={i === 0 ? 'start' : i === pts.length - 1 ? 'end' : 'middle'}>
          {pointLabel(pts[i])}
        </text>
      ))}
    </svg>
  );
};

const BarChart = ({ series }) => {
  const W = 620, H = 200, PAD_L = 34, PAD_B = 24, PAD_T = 10, PAD_R = 8;
  const pts = series || [];
  const max = Math.max(1, ...pts.map((p) => p.value));
  const top = Math.max(1, Math.ceil(max / 10) * 10 || max);
  const iw = W - PAD_L - PAD_R, ih = H - PAD_T - PAD_B;
  const bw = pts.length ? Math.max(2, (iw / pts.length) * 0.6) : 0;
  const y = (v) => PAD_T + ih - (v / top) * ih;
  const idx = pts.length <= 1 ? [0] : [0, Math.round((pts.length - 1) / 3), Math.round((pts.length - 1) * 2 / 3), pts.length - 1];
  if (!pts.length) return <p className="py-12 text-center text-[13px] text-[#94A3B8]">Aucune donnée sur la période.</p>;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height: 200 }}>
      {[0, top / 2, top].map((v) => (
        <g key={v}>
          <line x1={PAD_L} x2={W - PAD_R} y1={y(v)} y2={y(v)} stroke="#EEF3FB" />
          <text x={PAD_L - 8} y={y(v) + 4} textAnchor="end" fontSize="10.5" fill="#94A3B8">{nf(Math.round(v))}</text>
        </g>
      ))}
      {pts.map((p, i) => {
        const cx = PAD_L + (i + 0.5) * (iw / pts.length);
        return (
          <rect key={p.date} x={cx - bw / 2} y={y(p.value)} width={bw}
                height={Math.max(0, PAD_T + ih - y(p.value))} rx="2.5" fill="#2F6BFF">
            <title>{`${pointLabel(p)} — ${nf(p.value)}`}</title>
          </rect>
        );
      })}
      {idx.map((i) => (
        <text key={i} x={PAD_L + (i + 0.5) * (iw / pts.length)} y={H - 5} fontSize="10.5" fill="#94A3B8"
              textAnchor={i === 0 ? 'start' : i === pts.length - 1 ? 'end' : 'middle'}>
          {pointLabel(pts[i])}
        </text>
      ))}
    </svg>
  );
};

const Donut = ({ mix, onOpen }) => {
  const R = 54, C = 2 * Math.PI * R;
  let offset = 0;
  const total = mix?.total || 0;
  return (
    <div className="flex flex-wrap items-center gap-6">
      <div className="relative shrink-0">
        <svg width="150" height="150" viewBox="0 0 150 150">
          <circle cx="75" cy="75" r={R} fill="none" stroke="#EEF3FB" strokeWidth="20" />
          {(mix?.slices || []).filter((s) => s.count > 0).map((s) => {
            const len = total ? (s.count / total) * C : 0;
            const el = (
              <circle key={s.key} cx="75" cy="75" r={R} fill="none"
                      stroke={TONES[s.tone]?.dot || '#2F6BFF'} strokeWidth="20"
                      strokeDasharray={`${len} ${C - len}`} strokeDashoffset={-offset}
                      transform="rotate(-90 75 75)" />
            );
            offset += len;
            return el;
          })}
        </svg>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-[22px] font-bold leading-none text-[#0B1C3F] tabular-nums">{nf(total)}</span>
          <span className="text-[11px] text-[#64748B]">Clients</span>
        </div>
      </div>
      <ul className="min-w-[190px] flex-1 space-y-2.5">
        {(mix?.slices || []).map((s) => (
          <li key={s.key}>
            <button type="button" onClick={() => onOpen(`/dashboard/customers?segment=${s.segment}`)} title={`Voir ces ${nf(s.count)} clients`}
                    className="flex w-full items-center gap-2.5 rounded-lg px-1 py-0.5 text-left text-[12.5px] hover:bg-[#F4F7FC]">
              <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: TONES[s.tone]?.dot }} />
              <span className="min-w-0 flex-1 truncate text-[#334155]">{s.label}</span>
              <span className="shrink-0 text-[11.5px] text-[#94A3B8] tabular-nums">{nf(s.count)}</span>
              <span className="w-10 shrink-0 text-right font-bold text-[#0B1C3F] tabular-nums">{s.pct}%</span>
              <ChevronRight size={13} className="shrink-0 text-[#94A3B8]" />
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
};

const GoalModal = ({ current, onClose, onSaved }) => {
  // Text, not a number: the field can be empty while typing (no « 0 » in front).
  const [value, setValue] = useState(current ? String(current) : '');
  const [saving, setSaving] = useState(false);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0B1C3F]/25 p-6" onClick={onClose}>
      <div className="w-full max-w-sm rounded-2xl bg-white shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <header className="flex items-center justify-between border-b border-[#E6EEFB] px-5 py-4">
          <h3 className="text-[15px] font-bold text-[#0B1C3F]">Objectif du mois</h3>
          <button type="button" onClick={onClose} aria-label="Fermer" className="text-[#94A3B8] hover:text-[#0B1C3F]">
            <X size={18} />
          </button>
        </header>
        <div className="px-5 py-4">
          <label className="block">
            <span className="mb-1.5 block text-[12.5px] font-semibold text-[#334155]">
              Objectif de chiffre d'affaires mensuel (€)
            </span>
            <DecimalInput value={value} placeholder="Ex. 5000" autoFocus
                   onChange={(v) => setValue(v.replace(/^0+(?=\d)/, ''))}
                   className="w-full rounded-xl border border-[#E6EEFB] px-3 py-2.5 text-[13px] outline-none focus:border-[#2F6BFF]" />
          </label>
          <p className="mt-2 text-[11.5px] leading-snug text-[#94A3B8]">
            Votre chiffre, pas le nôtre. Le tableau de bord suit votre progression sur le mois en cours.
            Mettez 0 pour retirer l'objectif.
          </p>
        </div>
        <footer className="flex justify-end border-t border-[#E6EEFB] px-5 py-3.5">
          <button type="button" disabled={saving}
                  onClick={async () => {
                    setSaving(true);
                    try { await ownerAPI.setHomeGoal({ monthly_revenue_goal: Math.max(0, Number(value) || 0) }); onSaved(); }
                    finally { setSaving(false); }
                  }}
                  className="inline-flex items-center gap-2 rounded-xl bg-[#2F6BFF] px-4 py-2.5 text-[13px] font-semibold text-white disabled:opacity-60">
            {saving ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />} Enregistrer
          </button>
        </footer>
      </div>
    </div>
  );
};

/* ── page ─────────────────────────────────────────────────────────────── */
export default function DashboardHomePage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  // The period survives a reload and travels in the URL, so a merchant who
  // works on 90 days does not land back on 30 every morning, and a link they
  // send shows what they were looking at. Only a valid period is accepted —
  // « Aujourd'hui », a preset, or one typed up to two years (?days=99999 never
  // reaches the API).
  const [period, setPeriodState] = useState(() => {
    const fromUrl = new URLSearchParams(window.location.search).get('days');
    if (validPeriod(fromUrl)) return fromUrl;
    try {
      const stored = localStorage.getItem('fidclic:dh_days');
      if (validPeriod(stored)) return stored;
    } catch (_e) { /* private window — fall through to the default */ }
    return '30';
  });
  const days = periodDays(period);

  const setDays = useCallback((next) => {
    const value = validPeriod(next) ? String(next) : '30';
    setPeriodState(value);
    try { localStorage.setItem('fidclic:dh_days', value); } catch (_e) { /* ignore */ }
    try {
      const url = new URL(window.location.href);
      url.searchParams.set('days', value);
      window.history.replaceState({}, '', url);
    } catch (_e) { /* ignore */ }
  }, []);

  const [d, setD] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [goalOpen, setGoalOpen] = useState(false);

  const load = useCallback(() => {
    setLoading(true); setError('');
    ownerAPI.homeOverview({ days })
      .then(({ data }) => setD(data))
      .catch((e) => setError(e?.response?.data?.detail || 'Impossible de charger le tableau de bord.'))
      .finally(() => setLoading(false));
  }, [days]);
  useEffect(() => { load(); }, [load]);

  const firstName = useMemo(() => {
    const raw = user?.first_name || user?.name || (user?.email || '').split('@')[0] || '';
    return raw.split(/[\s.]/)[0].replace(/^./, (c) => c.toUpperCase());
  }, [user]);

  const QUICK = [
    { label: 'Créer une campagne', icon: Mail, to: '/dashboard/campaigns' },
    { label: 'Voir mes avis', icon: Star, to: '/dashboard/analytics#avis' },
    { label: 'Exporter un rapport', icon: FileDown, to: '/dashboard/history' },
  ];

  if (loading && !d) {
    return (
      <div key="loading" className="dh flex items-center justify-center gap-2 rounded-2xl border border-[#E6EEFB] bg-white py-24 text-[13px] text-[#64748B]">
        <Loader2 size={16} className="animate-spin" /> Chargement de votre tableau de bord…
      </div>
    );
  }

  return (
    <div className="dh">
      {/* The greeting is the page's title, not a panel: no card, no gradient,
          nothing boxed around it. The name is the only word in brand blue. */}
      <header className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-[11.5px] font-bold uppercase tracking-[0.14em] text-[#94A3B8]">
            Tableau de bord
          </p>
          <h1 className="mt-1 text-[30px] font-bold leading-tight text-[#0B1C3F]">
            {/* a first name is data, never translated (« Demo » read « تجريبي », QA R5 F08) */}
            Bonjour <span className="text-[#2F6BFF]" {...(firstName ? { translate: 'no' } : {})}>{firstName || 'à vous'}</span>{' '}
            <span aria-hidden="true">👋</span>
          </h1>
          <p className="mt-1 text-[13.5px] text-[#64748B]">
            Voici un aperçu de la performance de votre fidélité et de vos dernières actions.
          </p>
        </div>
        <RangePicker value={period} onChange={setDays} busy={loading} lead />
      </header>

      {error && <p className="mb-4 rounded-xl bg-[#FEECEC] px-4 py-2.5 text-[12.5px] text-[#C0392B]">{error}</p>}

      {/* Until the owner saves a reward, the card shows its sector's default
          (« Une séance offerte » for a gym…): ask them to make it theirs. */}
      {d?.reward_setup && (
        <div className="mb-4 flex flex-wrap items-center gap-3.5 rounded-2xl border border-[#FDE7B0] bg-[#FFF8E6] px-5 py-4">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#FFEDC2] text-[#B7791F]">
            <Gift size={19} />
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-[14.5px] font-bold text-[#0B1C3F]">Choisissez votre récompense</p>
            <p className="text-[13px] text-[#64748B]">
              Votre carte propose pour l'instant « {d.reward_setup.reward} ». Gardez-la ou écrivez la vôtre : c'est ce que vos clients voient dans leur Wallet.
            </p>
          </div>
          <button type="button" onClick={() => navigate('/dashboard/card')}
                  className="inline-flex items-center gap-1.5 rounded-full bg-[#2F6BFF] px-4 py-2 text-[13px] font-semibold text-white hover:bg-[#1F57E0]">
            Choisir ma récompense <ArrowRight size={14} />
          </button>
        </div>
      )}

      {/* Cards that left their client's phone in the LAST 24 HOURS — a loss
          the owner must see (user, 2026-10-09), never older than a day
          (2026-10-10); opens exactly those clients in Clients. */}
      {d?.cards_lost?.count > 0 && (
        <div className="mb-4 flex flex-wrap items-center gap-3.5 rounded-2xl border border-[#FCA5A5] bg-[#FEF2F2] px-5 py-4">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#FEE2E2] text-[#B91C1C]">
            <Gift size={19} />
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-[14.5px] font-bold text-[#0B1C3F]">
              {d.cards_lost.count} carte{d.cards_lost.count > 1 ? 's' : ''} supprimée{d.cards_lost.count > 1 ? 's' : ''} ces dernières 24 h
            </p>
            <p className="text-[13px] text-[#64748B]">
              Ces clients n'ont plus leur carte sur leur téléphone. Proposez-leur de la récupérer : un QR en caisse ou un lien par e-mail.
            </p>
          </div>
          <button type="button" onClick={() => navigate(d.cards_lost.href)}
                  className="inline-flex items-center gap-1.5 rounded-full bg-white px-4 py-2 text-[13px] font-semibold text-[#B91C1C] border border-[#FCA5A5] hover:bg-[#FFF5F5]">
            Voir les clients <ArrowRight size={14} />
          </button>
        </div>
      )}

      {/* the four figures */}
      <div className="mb-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {/* Analyses opens on the same period, its card highlighted (?focus=). */}
        {(d?.cards || []).map((c) => <KpiCard key={c.key} card={c} onOpen={(to) => navigate(
          to.startsWith('/dashboard/analytics') ? `${to}${to.includes('?') ? '&' : '?'}period=${period}` : to)} />)}
      </div>

      {/* goal + impact */}
      <div className="mb-4 grid gap-4 lg:grid-cols-2">
        <Panel>
          <div className="flex items-start gap-3.5">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#E7F7EE] text-[#0F8B58]">
              <Target size={19} />
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span>
                  <span className="flex items-center gap-1 text-[12.5px] text-[#64748B]">Objectif du mois <InfoTip k="goal" /></span>
                  <span className="text-[22px] font-bold text-[#0B1C3F] tabular-nums">
                    {d?.goal?.is_set ? money(d.goal.target) : '—'}
                  </span>
                </span>
                {d?.goal?.is_set && (
                  <span className="text-[13px] font-semibold text-[#475569] tabular-nums">
                    {money(d.goal.remaining)} restants
                  </span>
                )}
              </div>
              {d?.goal?.is_set ? (
                <>
                  <div className="mt-2.5 h-2 overflow-hidden rounded-full bg-[#EEF3FB]">
                    <div className="h-full rounded-full bg-[#10B981]" style={{ width: `${d.goal.pct}%` }} />
                  </div>
                  <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                    <span className="text-[12px] font-semibold text-[#0F8B58]">{d.goal.pct}%</span>
                    {d.goal.can_edit !== false && (
                      <button type="button" onClick={() => setGoalOpen(true)}
                              className="inline-flex items-center gap-1 text-[12px] font-semibold text-[#2F6BFF] hover:underline">
                        Modifier mon objectif <ChevronRight size={12} />
                      </button>
                    )}
                  </div>
                </>
              ) : (
                <>
                  {d?.goal?.can_edit === false ? (
                    <p className="mt-1.5 text-[12px] leading-snug text-[#64748B]">
                      {(d?.scope?.ids?.length || 0) > 1
                        ? "Choisissez un établissement dans le menu sous le logo pour voir ou fixer son objectif."
                        : "Aucun objectif fixé pour cet établissement."}
                    </p>
                  ) : (
                    <>
                      <p className="mt-1.5 text-[12px] leading-snug text-[#64748B]">
                        Fixez votre objectif de chiffre d'affaires : le tableau de bord suivra
                        votre progression tout au long du mois.
                      </p>
                      <button type="button" onClick={() => setGoalOpen(true)}
                              className="mt-2.5 rounded-lg bg-[#2F6BFF] px-3.5 py-2 text-[12.5px] font-semibold text-white">
                        Définir un objectif
                      </button>
                    </>
                  )}
                </>
              )}
            </div>
          </div>
        </Panel>

        {/* « Impact FidClic » from the mockup (2026-10-10): not a link; its
            tiles only say what brings the revenue back */}
        <ImpactFidClicCard value={d?.impact?.value} />
      </div>

      {/* the two charts */}
      <div className="mb-4 grid gap-4 lg:grid-cols-2">
        <Panel title="Évolution du chiffre d'affaires" action={<RangePicker value={period} onChange={setDays} busy={loading} />}>
          <p className="mb-2 flex items-center gap-2">
            <button type="button" onClick={() => navigate('/dashboard/analytics')} title="Voir les analyses" className="text-[22px] font-bold text-[#0F8B58] tabular-nums hover:underline">{money(d?.revenue_total)}</button>
            {d?.revenue_delta !== null && d?.revenue_delta !== undefined && (
              <span className={`rounded-md px-1.5 py-0.5 text-[11.5px] font-semibold ${d.revenue_delta >= 0 ? 'bg-[#E7F7EE] text-[#0F8B58]' : 'bg-[#FEECEC] text-[#C0392B]'}`}>
                {d.revenue_delta >= 0 ? '↑ +' : '↓ '}{d.revenue_delta}%
              </span>
            )}
          </p>
          <LineChart series={d?.revenue_series} money />
        </Panel>
        <Panel title="Nouveaux clients" action={<RangePicker value={period} onChange={setDays} busy={loading} />}>
          <p className="mb-2 flex items-center gap-2">
            <button type="button" onClick={() => navigate('/dashboard/customers?segment=new')} title="Voir ces nouveaux clients" className="text-[22px] font-bold text-[#0F8B58] tabular-nums hover:underline">{nf(d?.new_total)}</button>
            {d?.new_delta !== null && d?.new_delta !== undefined && (
              <span className={`rounded-md px-1.5 py-0.5 text-[11.5px] font-semibold ${d.new_delta >= 0 ? 'bg-[#E7F7EE] text-[#0F8B58]' : 'bg-[#FEECEC] text-[#C0392B]'}`}>
                {d.new_delta >= 0 ? '↑ +' : '↓ '}{d.new_delta}%
              </span>
            )}
          </p>
          <BarChart series={d?.new_series} />
        </Panel>
      </div>

      {/* campaigns + products */}
      <div className="mb-4 grid gap-4 lg:grid-cols-2">
        <Panel title="Performance des campagnes"
               action={<SeeAll onClick={() => navigate('/dashboard/campaigns')} />}>
          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
            {[
              { icon: Send, tone: 'blue', value: d?.campaigns?.sent, label: 'Campagnes envoyées' },
              { icon: Users, tone: 'green', value: d?.campaigns?.touched, label: 'Clients touchés' },
              { icon: MousePointerClick, tone: 'violet', value: d?.campaigns?.clicks, label: 'Clics' },
              { icon: ShoppingCart, tone: 'amber', value: d?.campaigns?.sales, label: 'Ventes attribuées' },
            ].map((t) => {
              const Icon = t.icon;
              const tone = TONES[t.tone];
              return (
                <button type="button" key={t.label} onClick={() => navigate('/dashboard/campaigns')} className="rounded-xl p-3 text-center transition hover:brightness-[.97]" style={{ background: tone.bg }}>
                  <Icon size={17} className="mx-auto mb-1.5" style={{ color: tone.fg }} />
                  <p className="text-[18px] font-bold leading-none text-[#0B1C3F] tabular-nums">{nf(t.value)}</p>
                  <p className="mt-1 text-[10.5px] leading-tight" style={{ color: tone.fg }}>{t.label}</p>
                </button>
              );
            })}
          </div>
          <h3 className="mb-2 mt-4 text-[12.5px] font-bold text-[#0B1C3F]">Campagne la plus performante</h3>
          {d?.campaigns?.best ? (
            <div role="button" tabIndex={0} onClick={() => navigate('/dashboard/campaigns')} onKeyDown={(e) => { if (e.key === 'Enter') navigate('/dashboard/campaigns'); }}
                 className="flex cursor-pointer flex-wrap items-center gap-3 rounded-xl border border-[#E6EEFB] p-3 hover:border-[#BFD3FF]">
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="truncate text-[13px] font-semibold text-[#0B1C3F]">{d.campaigns.best.name}</span>
                  <span className="rounded-md bg-[#E7F7EE] px-2 py-0.5 text-[10.5px] font-semibold text-[#0F8B58]">
                    {d.campaigns.best.status === 'sent' ? 'Envoyée' : d.campaigns.best.status}
                  </span>
                </span>
                <span className="mt-2 flex flex-wrap gap-4 text-[11.5px] text-[#64748B]">
                  <span><strong className="text-[#0B1C3F]">{nf(d.campaigns.best.touched)}</strong> touchés</span>
                  <span><strong className="text-[#0B1C3F]">{nf(d.campaigns.best.clicks)}</strong> clics</span>
                  <span><strong className="text-[#0B1C3F]">{nf(d.campaigns.best.sales)}</strong> ventes</span>
                  <span><strong className="text-[#0B1C3F]">{d.campaigns.best.conversion}%</strong> conversion</span>
                </span>
              </span>
            </div>
          ) : (
            <p className="rounded-xl border border-dashed border-[#D9E4F7] px-4 py-5 text-center text-[12.5px] text-[#94A3B8]">
              Aucune campagne envoyée sur la période.
            </p>
          )}
        </Panel>

        <Panel title="Produits les plus populaires"
               action={<SeeAll onClick={() => navigate('/dashboard/analytics')} label="Voir tous" />}>
          {(d?.products || []).length === 0 ? (
            <p className="py-10 text-center text-[12.5px] text-[#94A3B8]">
              Les produits apparaîtront dès que vos scans en enregistreront.
            </p>
          ) : (
            <table className="w-full border-collapse">
              <thead>
                <tr className="border-b border-[#EEF3FB] text-left">
                  {['#', 'Produit', 'Ventes', 'CA généré'].map((h, i) => (
                    <th key={h} className={`py-2 text-[11.5px] font-semibold text-[#64748B] ${i > 1 ? 'text-right' : ''}`}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {d.products.map((p, i) => (
                  <tr key={p.name} className="border-b border-[#F4F7FC] last:border-b-0">
                    <td className="py-2.5">
                      <span className="flex h-5 w-5 items-center justify-center rounded-full bg-[#EAF1FF] text-[10.5px] font-bold text-[#2F6BFF]">
                        {i + 1}
                      </span>
                    </td>
                    <td className="py-2.5 text-[12.5px] font-medium text-[#0B1C3F]">{p.name}</td>
                    <td className="py-2.5 text-right text-[12.5px] tabular-nums text-[#475569]">{nf(p.sales)}</td>
                    <td className="py-2.5 text-right text-[12.5px] font-semibold tabular-nums text-[#0B1C3F]">{money(p.revenue)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>
      </div>

      {/* hours + status */}
      <div className="mb-4 grid gap-4 lg:grid-cols-2">
        <Panel title="Heures d'affluence" action={<SeeAll onClick={() => navigate('/dashboard/analytics')} label="Voir le détail" />}>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[380px] border-separate" style={{ borderSpacing: '3px' }}>
              <thead>
                <tr>
                  <th />
                  {(d?.hours?.slots || []).map((s) => (
                    <th key={s} className="pb-1 text-[10px] font-medium text-[#94A3B8]">{s.replace(/\s/g, '')}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(d?.hours?.weekdays || []).map((wd, r) => (
                  <tr key={wd}>
                    <td className="pr-2 text-right text-[10.5px] font-medium text-[#94A3B8]">{wd}</td>
                    {(d?.hours?.grid?.[r] || []).map((n, c) => {
                      const peak = d?.hours?.peak || 1;
                      const a = n ? 0.15 + (n / peak) * 0.85 : 0;
                      return (
                        <td key={c} className="h-7 rounded"
                            style={{ background: n ? `rgba(47,107,255,${a})` : '#F4F7FC' }}
                            title={`${wd} ${d.hours.slots[c]} — ${n} visite${n > 1 ? 's' : ''}`} />
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-[#94A3B8]">
            <span>Faible affluence</span>
            <span className="h-2 w-24 rounded-full"
                  style={{ background: 'linear-gradient(to right,#F4F7FC,rgba(47,107,255,1))' }} />
            <span>Forte affluence</span>
          </div>
          {d?.hours?.outside > 0 && (
            <p className="mt-2 flex items-start gap-1.5 text-[11px] leading-snug text-[#94A3B8]">
              <Info size={12} className="mt-px shrink-0" />
              La grille couvre {d.hours.covers}. {nf(d.hours.outside)} visite
              {d.hours.outside > 1 ? 's ont' : ' a'} eu lieu en dehors de ces horaires.
            </p>
          )}
        </Panel>

        <Panel title="Statut des clients">
          {d?.status_mix?.total ? <Donut mix={d.status_mix} onOpen={navigate} /> : (
            <p className="py-12 text-center text-[12.5px] text-[#94A3B8]">
              Vos clients apparaîtront ici dès la première inscription.
            </p>
          )}
        </Panel>
      </div>

      {/* recommendations + quick actions */}
      <div className="grid gap-4 lg:grid-cols-[1.6fr_1fr]">
        <Panel title="Recommandations pour vous"
               action={<SeeAll onClick={() => navigate('/dashboard/insights')} label="Voir toutes les recommandations" />}>
          {(d?.recommendations || []).length === 0 ? (
            <p className="py-8 text-center text-[12.5px] text-[#94A3B8]">
              Rien à signaler — tout tourne bien.
            </p>
          ) : (
            <div className="grid gap-3 sm:grid-cols-3">
              {d.recommendations.map((r) => {
                const Icon = KPI_ICONS[r.icon] || Users;
                const t = TONES[r.tone] || TONES.blue;
                return (
                  <div key={r.key} className="flex flex-col rounded-xl border border-[#E6EEFB] p-3.5">
                    <span className="mb-2 flex h-8 w-8 items-center justify-center rounded-lg"
                          style={{ background: t.bg, color: t.fg }}>
                      <Icon size={16} />
                    </span>
                    <p className="text-[12.5px] font-bold leading-snug text-[#0B1C3F]">{r.title}</p>
                    <p className="mt-1 flex-1 text-[11.5px] leading-snug text-[#64748B]">{r.body}</p>
                    <button type="button" onClick={() => navigate(r.to)}
                            className="mt-2.5 rounded-lg border border-[#E6EEFB] px-3 py-1.5 text-[12px] font-semibold text-[#2F6BFF] transition hover:border-[#2F6BFF]">
                      {r.cta}
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </Panel>

        <Panel title="Actions rapides">
          <div className="space-y-1">
            {QUICK.map((q) => {
              const Icon = q.icon;
              return (
                <button key={q.label} type="button" onClick={() => navigate(q.to)}
                        className="flex w-full items-center gap-2.5 rounded-xl px-2 py-2.5 text-left transition hover:bg-[#F4F7FC]">
                  <Icon size={15} className="shrink-0 text-[#2F6BFF]" />
                  <span className="min-w-0 flex-1 truncate text-[12.5px] text-[#334155]">{q.label}</span>
                  <ChevronRight size={14} className="shrink-0 text-[#94A3B8]" />
                </button>
              );
            })}
          </div>
        </Panel>
      </div>

      {goalOpen && (
        <GoalModal current={d?.goal?.target || 0} onClose={() => setGoalOpen(false)}
                   onSaved={() => { setGoalOpen(false); load(); }} />
      )}
    </div>
  );
}
