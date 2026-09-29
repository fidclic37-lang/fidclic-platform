import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Users, User, Gift, Euro, Settings2, Share2, Trophy, BarChart3, ChevronDown, Eye,
  ChevronRight, ArrowRight, Loader2, X, Check, Download, Info,
} from 'lucide-react';
import { ownerAPI } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';

/**
 * Parrainage — the referral programme's dashboard, built to the approved
 * mockup and wired to /api/owner/referrals/*.
 *
 * Every number is counted from real referral_redemptions rows: an untouched
 * programme reads zero and says so, and nothing on this page is demo data.
 *
 * Two definitions were settled with the merchant and are surfaced rather than
 * assumed:
 *   • "CA généré via parrainage" is every filleul's whole spend since joining,
 *     for the life of the programme — so the card says "depuis le début" and
 *     deliberately does not move with the date filter.
 *   • The breakdown splits parrains into Clients réguliers / Étudiants /
 *     Nouveaux clients / Autres, étudiant being declared at signup.
 */
const KPI_ICONS = { users: Users, user: User, gift: Gift, euro: Euro };
const TONE = {
  teal:   { bg: '#E7F7EE', fg: '#0F8B58', dot: '#10B981' },
  blue:   { bg: '#EAF1FF', fg: '#1D4ED8', dot: '#2F6BFF' },
  amber:  { bg: '#FFF3E3', fg: '#B45309', dot: '#F59E0B' },
  violet: { bg: '#F3EEFF', fg: '#6D28D9', dot: '#8B5CF6' },
};
/* Avatars carry the customer's tier — the merchant asked for the colour to
   mean something rather than be decoration. */
const TIER = {
  bronze: { bg: '#FBEADC', fg: '#A45C21', label: 'Bronze' },
  silver: { bg: '#EEF1F6', fg: '#5B6577', label: 'Argent' },
  gold:   { bg: '#FDF2D0', fg: '#A8791A', label: 'Or' },
  vip:    { bg: '#EFE8FF', fg: '#6D28D9', label: 'VIP' },
};
const RANK = ['#E9B949', '#B9C2CF', '#D08A50'];   // 1st, 2nd, 3rd

const MONTHS = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.'];
const ymd = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const dayLabel = (iso) => { const d = new Date(iso); return `${d.getDate()} ${MONTHS[d.getMonth()]}`; };
const fullDate = (iso) => { const d = new Date(iso); return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`; };
const nf = (n) => (n ?? 0).toLocaleString('fr-FR');

const Avatar = ({ initials, tier, size = 34 }) => {
  const t = TIER[tier] || TIER.bronze;
  return (
    <span
      className="inline-flex shrink-0 items-center justify-center rounded-full font-bold"
      style={{ width: size, height: size, background: t.bg, color: t.fg, fontSize: size * 0.36 }}
      title={t.label}
    >
      {initials}
    </span>
  );
};

const Panel = ({ title, icon: Icon, action, children, className = '' }) => (
  <section className={`rounded-2xl border border-[#E6EEFB] bg-white p-5 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)] ${className}`}>
    <header className="mb-4 flex items-center justify-between gap-3">
      <h2 className="flex items-center gap-2 text-[15px] font-bold text-[#0B1C3F]">
        {Icon && <Icon size={17} className="text-[#E9B949]" />}
        {title}
      </h2>
      {action}
    </header>
    {children}
  </section>
);

const SeeAll = ({ onClick, label = 'Voir tous' }) => (
  <button type="button" onClick={onClick}
          className="inline-flex shrink-0 items-center gap-1 text-[12.5px] font-semibold text-[#2F6BFF] transition hover:underline">
    {label} <ArrowRight size={13} />
  </button>
);

/* ── KPI ──────────────────────────────────────────────────────────────── */
const KpiCard = ({ card, showCaption }) => {
  const Icon = KPI_ICONS[card.icon] || Users;
  const t = TONE[card.tone] || TONE.blue;
  const up = (card.delta_pct ?? 0) >= 0;
  return (
    <div className="flex items-start gap-3.5 rounded-2xl border border-[#E6EEFB] bg-white p-4 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
      <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl"
            style={{ background: t.bg, color: t.fg }}>
        <Icon size={22} />
      </span>
      <div className="min-w-0">
        <p className="text-[25px] font-bold leading-none tracking-tight text-[#0B1C3F] tabular-nums">
          {card.unit === '€' ? `${nf(card.value)} €` : nf(card.value)}
        </p>
        <p className="mt-1 text-[12.5px] leading-tight text-[#64748B]">{card.label}</p>
        {card.delta_pct === null || card.delta_pct === undefined ? (
          <p className="mt-2 text-[11px] leading-tight text-[#94A3B8]">
            {card.note || 'pas encore de période précédente'}
          </p>
        ) : (
          <div className="mt-2">
            <span className="inline-flex items-center gap-0.5 rounded-md px-1.5 py-0.5 text-[11.5px] font-semibold"
                  style={up ? { background: '#E7F7EE', color: '#0F8B58' } : { background: '#FEECEC', color: '#C0392B' }}>
              {up ? '↑' : '↓'} {up ? '+' : ''}{card.delta_pct}%
            </span>
            {showCaption && (
              <span className="mt-1 block text-[11px] leading-tight text-[#94A3B8]">vs période précédente</span>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

/* ── the curve ────────────────────────────────────────────────────────── */
const EvolutionChart = ({ series }) => {
  const W = 660, H = 210, PAD_L = 34, PAD_B = 26, PAD_T = 10, PAD_R = 8;
  const points = series || [];
  const max = Math.max(4, ...points.map((p) => p.cumulative));
  // A round ceiling so the gridline labels read 0 / 10 / 20 …, as in the design.
  const step = max <= 8 ? 2 : max <= 20 ? 5 : Math.ceil(max / 4 / 10) * 10;
  const top = Math.ceil(max / step) * step;
  const innerW = W - PAD_L - PAD_R, innerH = H - PAD_T - PAD_B;
  const x = (i) => PAD_L + (points.length <= 1 ? innerW / 2 : (i / (points.length - 1)) * innerW);
  const y = (v) => PAD_T + innerH - (v / top) * innerH;
  const line = points.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.cumulative).toFixed(1)}`).join(' ');
  const area = points.length
    ? `${line} L${x(points.length - 1).toFixed(1)},${(PAD_T + innerH).toFixed(1)} L${x(0).toFixed(1)},${(PAD_T + innerH).toFixed(1)} Z`
    : '';
  const ticks = [];
  for (let v = 0; v <= top; v += step) ticks.push(v);
  // Four date labels across the axis, like the design.
  const labelIdx = points.length <= 1 ? [0]
    : [0, Math.round((points.length - 1) / 3), Math.round(((points.length - 1) * 2) / 3), points.length - 1];

  if (!points.length) {
    return <p className="py-14 text-center text-[13px] text-[#94A3B8]">Aucun parrainage sur cette période.</p>;
  }
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height: 210 }} role="img"
         aria-label="Évolution cumulée des parrainages">
      <defs>
        <linearGradient id="prGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#2F6BFF" stopOpacity="0.28" />
          <stop offset="100%" stopColor="#2F6BFF" stopOpacity="0.02" />
        </linearGradient>
      </defs>
      {ticks.map((v) => (
        <g key={v}>
          <line x1={PAD_L} x2={W - PAD_R} y1={y(v)} y2={y(v)} stroke="#EEF3FB" strokeWidth="1" />
          <text x={PAD_L - 8} y={y(v) + 4} textAnchor="end" fontSize="11" fill="#94A3B8">{v}</text>
        </g>
      ))}
      {area && <path d={area} fill="url(#prGrad)" />}
      <path d={line} fill="none" stroke="#2F6BFF" strokeWidth="2.2" strokeLinejoin="round" strokeLinecap="round" />
      {points.map((p, i) => (
        <circle key={p.date} cx={x(i)} cy={y(p.cumulative)} r="3" fill="#fff" stroke="#2F6BFF" strokeWidth="2">
          <title>{`${fullDate(p.date)} — ${p.cumulative} parrainage${p.cumulative > 1 ? 's' : ''}`}</title>
        </circle>
      ))}
      {labelIdx.map((i) => (
        <text key={i} x={x(i)} y={H - 6} textAnchor={i === 0 ? 'start' : i === points.length - 1 ? 'end' : 'middle'}
              fontSize="11" fill="#94A3B8">
          {dayLabel(points[i].date)}
        </text>
      ))}
    </svg>
  );
};

/* ── the donut ────────────────────────────────────────────────────────── */
const Breakdown = ({ total, segments }) => {
  const R = 52, C = 2 * Math.PI * R;
  let offset = 0;
  return (
    <div className="flex flex-wrap items-center gap-6">
      <div className="relative shrink-0">
        <svg width="150" height="150" viewBox="0 0 150 150" role="img" aria-label="Répartition des parrainages">
          <circle cx="75" cy="75" r={R} fill="none" stroke="#EEF3FB" strokeWidth="20" />
          {segments.filter((s) => s.count > 0).map((s) => {
            const len = total ? (s.count / total) * C : 0;
            const el = (
              <circle key={s.key} cx="75" cy="75" r={R} fill="none"
                      stroke={TONE[s.tone]?.dot || '#2F6BFF'} strokeWidth="20"
                      strokeDasharray={`${len} ${C - len}`} strokeDashoffset={-offset}
                      transform="rotate(-90 75 75)" />
            );
            offset += len;
            return el;
          })}
        </svg>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-[22px] font-bold leading-none text-[#0B1C3F] tabular-nums">{nf(total)}</span>
          <span className="text-[11px] leading-tight text-[#64748B]">parrainages</span>
        </div>
      </div>
      <ul className="min-w-[210px] flex-1 space-y-3">
        {segments.map((s) => (
          <li key={s.key} className="flex items-center gap-2.5 text-[13px]">
            <span className="h-3 w-3 shrink-0 rounded-full" style={{ background: TONE[s.tone]?.dot }} />
            <span className="min-w-0 flex-1 truncate text-[#334155]">{s.label}</span>
            <span className="shrink-0 font-bold text-[#0B1C3F] tabular-nums">{s.pct}%</span>
          </li>
        ))}
      </ul>
    </div>
  );
};

/* ── modals ───────────────────────────────────────────────────────────── */
const Modal = ({ title, onClose, children, footer }) => {
  useEffect(() => {
    const key = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-[#0B1C3F]/25 sm:items-center sm:p-6" onClick={onClose}>
      <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-t-2xl bg-white shadow-2xl sm:rounded-2xl"
           onClick={(e) => e.stopPropagation()}>
        <header className="flex items-center justify-between border-b border-[#E6EEFB] px-5 py-4">
          <h3 className="text-[15px] font-bold text-[#0B1C3F]">{title}</h3>
          <button type="button" onClick={onClose} aria-label="Fermer" className="text-[#94A3B8] hover:text-[#0B1C3F]">
            <X size={18} />
          </button>
        </header>
        <div className="px-5 py-4">{children}</div>
        {footer && <div className="border-t border-[#E6EEFB] px-5 py-3.5">{footer}</div>}
      </div>
    </div>
  );
};

const NumberField = ({ label, hint, value, onChange, min = 0, max = 10000 }) => (
  <label className="block">
    <span className="mb-1.5 block text-[12.5px] font-semibold text-[#334155]">{label}</span>
    <input
      type="number" value={value} min={min} max={max}
      onChange={(e) => onChange(Math.max(min, Math.min(max, Number(e.target.value) || 0)))}
      className="w-full rounded-xl border border-[#E6EEFB] bg-white px-3 py-2.5 text-[13px] text-[#0B1C3F] outline-none focus:border-[#2F6BFF]"
    />
    {hint && <span className="mt-1 block text-[11.5px] leading-snug text-[#94A3B8]">{hint}</span>}
  </label>
);

const SettingsModal = ({ config, enabled, onClose, onSaved }) => {
  const [form, setForm] = useState({ ...config, enabled });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const save = async () => {
    setSaving(true); setError('');
    try {
      await ownerAPI.saveReferralConfig({
        enabled: form.enabled,
        referrer_reward_points: form.referrer_reward_points,
        referee_reward_points: form.referee_reward_points,
        minimum_visits_to_earn: form.minimum_visits_to_earn,
      });
      onSaved();
    } catch (e) {
      setError(e?.response?.data?.detail || "L'enregistrement n'a pas abouti.");
    } finally { setSaving(false); }
  };
  return (
    <Modal title="Paramètres du programme" onClose={onClose}
           footer={(
             <div className="flex items-center justify-between gap-3">
               {error ? <span className="text-[12px] text-[#C0392B]">{error}</span> : <span />}
               <button type="button" onClick={save} disabled={saving}
                       className="inline-flex items-center gap-2 rounded-xl bg-[#2F6BFF] px-4 py-2.5 text-[13px] font-semibold text-white disabled:opacity-60">
                 {saving ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />} Enregistrer
               </button>
             </div>
           )}>
      <button type="button" onClick={() => setForm((f) => ({ ...f, enabled: !f.enabled }))}
              className="mb-4 flex w-full items-center gap-3 rounded-xl border border-[#E6EEFB] p-3.5 text-left">
        <span className="min-w-0 flex-1">
          <span className="block text-[13.5px] font-bold text-[#0B1C3F]">Programme de parrainage</span>
          <span className="block text-[12px] text-[#64748B]">
            {form.enabled ? 'Actif — vos clients peuvent parrainer.' : 'Inactif — aucun parrainage ne sera enregistré.'}
          </span>
        </span>
        <span className={`relative h-6 w-11 shrink-0 rounded-full transition ${form.enabled ? 'bg-[#2F6BFF]' : 'bg-[#DFE6F1]'}`}>
          <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all ${form.enabled ? 'left-[22px]' : 'left-0.5'}`} />
        </span>
      </button>
      <div className="grid gap-4 sm:grid-cols-2">
        <NumberField label="Points pour le parrain" value={form.referrer_reward_points}
                     hint="Crédités une fois le parrainage validé."
                     onChange={(v) => setForm((f) => ({ ...f, referrer_reward_points: v }))} />
        <NumberField label="Points pour le filleul" value={form.referee_reward_points}
                     hint="Crédités dès l'inscription."
                     onChange={(v) => setForm((f) => ({ ...f, referee_reward_points: v }))} />
      </div>
      <div className="mt-4">
        <NumberField label="Visites du filleul avant validation" min={1} max={20}
                     value={form.minimum_visits_to_earn}
                     hint="En dessous de ce nombre, le parrainage reste « En attente » et le parrain n'est pas encore crédité."
                     onChange={(v) => setForm((f) => ({ ...f, minimum_visits_to_earn: v }))} />
      </div>
    </Modal>
  );
};

/* ── How it works ─────────────────────────────────────────────────────────
   There is no link to copy and no second QR to print, so there is nothing to
   "share": the card every customer already carries IS the invitation. This
   explains that in four steps, because a merchant who does not understand it
   cannot explain it to their customers either. */
const HowModal = ({ onClose }) => (
  <Modal title="Comment marche le parrainage" onClose={onClose}>
    <p className="mb-4 text-[12.5px] leading-snug text-[#64748B]">
      Rien à imprimer, rien à copier. La carte de fidélité de vos clients est déjà l'invitation :
      son QR code ouvre la page d'inscription pour quiconque la scanne.
    </p>
    <ol className="space-y-3">
      {[
        ["Un client montre sa carte", "Son QR code est celui qu'il utilise déjà en caisse."],
        ["Un proche le scanne", "Son téléphone ouvre le formulaire d'inscription, qui affiche le prénom du parrain."],
        ["Il crée sa carte", "Le parrainage est enregistré. Aucun point n'est encore versé."],
        ["Il vient une première fois", "Parrain et filleul sont crédités, une seule fois — une visite, ça ne se falsifie pas."],
      ].map(([title, sub], i) => (
        <li key={title} className="flex gap-3">
          <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[#EAF1FF] text-[12px] font-bold text-[#2F6BFF]">
            {i + 1}
          </span>
          <span>
            <span className="block text-[13px] font-semibold text-[#0B1C3F]">{title}</span>
            <span className="block text-[12px] leading-snug text-[#64748B]">{sub}</span>
          </span>
        </li>
      ))}
    </ol>
    <p className="mt-4 flex items-start gap-1.5 rounded-xl bg-[#F6F9FF] p-3 text-[11.5px] leading-snug text-[#475569]">
      <Info size={13} className="mt-px shrink-0 text-[#2F6BFF]" />
      Le téléphone du parrain garde sa carte : c'est ainsi qu'on sait qu'il n'est pas un nouveau
      venu. S'il change de téléphone, son numéro le ramène à sa carte existante — il n'est donc
      jamais son propre filleul.
    </p>
  </Modal>
);

/* ── "Voir un exemple" ─────────────────────────────────────────────────────
   A programme nobody has used yet is an empty page, which tells a merchant
   nothing about what it will do for them. This renders the same page from a
   worked example instead — the shape is exactly what the endpoint returns, so
   nothing else in the component changes, and NOTHING is written anywhere: no
   customers, no parrainages, no counting against the plan. The banner stays on
   screen the whole time so the figures can never be mistaken for real ones. */
const EXAMPLE = (() => {
  const day = (n) => { const d = new Date(); d.setDate(d.getDate() - n); return d.toISOString(); };
  const curve = [1, 1, 2, 3, 3, 5, 6, 8, 9, 11, 13, 14, 16, 18, 20, 22, 23, 25, 28, 30,
                 32, 34, 37, 40, 43, 46, 49, 51, 54, 56];
  return {
    example: true,
    enabled: true,
    config: { referrer_reward_points: 50, referee_reward_points: 25, minimum_visits_to_earn: 2 },
    cards: [
      { key: 'referrals', label: 'Parrainages réalisés', icon: 'users', tone: 'teal', value: 56, delta_pct: 42 },
      { key: 'active', label: 'Parrains actifs', icon: 'user', tone: 'blue', value: 28, delta_pct: 35 },
      { key: 'points', label: 'Points offerts', icon: 'gift', tone: 'amber', value: 1240, delta_pct: 28 },
      { key: 'revenue', label: 'CA généré via parrainage', icon: 'euro', tone: 'violet',
        value: 280, unit: '€', all_time: true, note: 'depuis le début', delta_pct: null },
    ],
    series: curve.map((c, i) => ({
      date: day(29 - i).slice(0, 10), cumulative: c, count: c - (curve[i - 1] ?? 0),
    })),
    breakdown: {
      total: 56,
      segments: [
        { key: 'reguliers', label: 'Clients réguliers', tone: 'blue', count: 29, pct: 52 },
        { key: 'etudiants', label: 'Étudiants', tone: 'teal', count: 16, pct: 28 },
        { key: 'nouveaux', label: 'Nouveaux clients', tone: 'amber', count: 8, pct: 15 },
        { key: 'autres', label: 'Autres', tone: 'violet', count: 3, pct: 5 },
      ],
    },
    top_parrains: [
      { customer_id: 'x1', name: 'Sophie L.', full_name: 'Sophie Lambert', initials: 'SL', tier: 'gold', filleuls: 12, points: 240 },
      { customer_id: 'x2', name: 'Yassine K.', full_name: 'Yassine Kaddour', initials: 'YK', tier: 'vip', filleuls: 9, points: 180 },
      { customer_id: 'x3', name: 'Camille R.', full_name: 'Camille Roux', initials: 'CR', tier: 'silver', filleuls: 7, points: 140 },
      { customer_id: 'x4', name: 'Lucas M.', full_name: 'Lucas Marin', initials: 'LM', tier: 'silver', filleuls: 6, points: 120 },
      { customer_id: 'x5', name: 'Inès B.', full_name: 'Inès Bouchard', initials: 'IB', tier: 'bronze', filleuls: 5, points: 100 },
    ],
    recent: [
      ['Sophie L.', 'SL', 'gold', 'Emma D.', 'ED', 'validated', 'Validé', 'QR code', 0],
      ['Yassine K.', 'YK', 'vip', 'Nicolas P.', 'NP', 'validated', 'Validé', 'Lien partagé', 1],
      ['Camille R.', 'CR', 'silver', 'Léa T.', 'LT', 'validated', 'Validé', 'Réseaux sociaux', 2],
      ['Lucas M.', 'LM', 'silver', 'Thomas G.', 'TG', 'pending', 'En attente', 'QR code', 3],
      ['Inès B.', 'IB', 'bronze', 'Sarah M.', 'SM', 'validated', 'Validé', 'Lien partagé', 4],
    ].map(([pn, pi, pt, fn, fi, st, sl, src, ago], i) => ({
      id: `ex${i}`, at: day(ago),
      parrain: { name: pn, initials: pi, tier: pt },
      filleul: { name: fn, initials: fi, tier: 'bronze' },
      status: st, status_label: sl, reward_points: 50, source: 'qr', source_label: src,
    })),
    total_referrals: 56,
  };
})();

/* ── page ─────────────────────────────────────────────────────────────── */
const RANGES = [
  { key: 7, label: '7 derniers jours' },
  { key: 30, label: '30 derniers jours' },
  { key: 90, label: '90 derniers jours' },
  { key: 365, label: '12 derniers mois' },
];

export default function ReferralPage() {
  const { user } = useAuth();
  const owner = user?.role === 'business_owner';
  const [days, setDays] = useState(30);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);
  const [allRecent, setAllRecent] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [demo, setDemo] = useState(false);

  const range = useMemo(() => {
    const end = new Date(); const start = new Date();
    start.setDate(end.getDate() - (days - 1));
    return { from: ymd(start), to: ymd(end) };
  }, [days]);

  const load = useCallback(() => {
    setLoading(true); setError('');
    ownerAPI.referralOverview(range)
      .then(({ data: d }) => setData(d))
      .catch((e) => setError(e?.response?.data?.detail || 'Impossible de charger le parrainage.'))
      .finally(() => setLoading(false));
  }, [range]);
  useEffect(() => { load(); }, [load]);

  const exportCsv = async () => {
    if (demo) return;          // the example is not yours to export
    setExporting(true);
    try {
      const { data: blob } = await ownerAPI.referralExport(range);
      const url = URL.createObjectURL(new Blob([blob], { type: 'text/csv;charset=utf-8' }));
      const a = document.createElement('a');
      a.href = url; a.download = `fidclic-parrainage-${range.from}-${range.to}.csv`;
      document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
    } catch { setError("L'export n'a pas abouti."); } finally { setExporting(false); }
  };

  // The example stands in for the payload wholesale, so every panel below
  // reads it without knowing the difference.
  const view = demo ? EXAMPLE : data;
  const cards = view?.cards || [];
  const recent = view?.recent || [];
  const shown = allRecent ? recent : recent.slice(0, 5);
  const growing = (cards[0]?.delta_pct ?? 0) > 0;

  return (
    <div className="pr">
      {/* header */}
      <header className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2.5">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-[#2F6BFF] text-[15px] font-bold text-white">7</span>
            <span className="rounded-lg bg-[#EAF1FF] px-2.5 py-1 text-[12.5px] font-semibold text-[#2F6BFF]">7 / 10</span>
            <h1 className="text-[23px] font-bold leading-tight text-[#0B1C3F]">Parrainage</h1>
          </div>
          <p className="mt-1 pl-[46px] text-[13px] text-[#64748B]">
            Suivez vos parrains, leurs filleuls et les récompenses générées.
          </p>
          <nav className="mt-1.5 flex items-center gap-1.5 pl-[46px] text-[12.5px] text-[#94A3B8]">
            <span>Campagnes</span> <ChevronRight size={13} /> <span className="text-[#475569]">Parrainage</span>
          </nav>
        </div>
        <div className="flex flex-wrap items-center gap-2.5">
          <button type="button" onClick={() => setDemo((v) => !v)}
                  className={`inline-flex items-center gap-2 rounded-xl border px-4 py-2.5 text-[13px] font-semibold transition ${
                    demo ? 'border-[#C7DBFF] bg-[#EAF1FF] text-[#1D4ED8]'
                         : 'border-[#E6EEFB] bg-white text-[#0B1C3F] hover:border-[#2F6BFF] hover:text-[#2F6BFF]'}`}>
            <Eye size={15} /> {demo ? "Revenir à mes données" : "Voir un exemple"}
          </button>
          {/* The programme's settings are the whole shop's: the owner's. */}
          {owner && (
            <button type="button" onClick={() => setSettingsOpen(true)}
                    className="inline-flex items-center gap-2 rounded-xl border border-[#E6EEFB] bg-white px-4 py-2.5 text-[13px] font-semibold text-[#0B1C3F] transition hover:border-[#2F6BFF] hover:text-[#2F6BFF]">
              <Settings2 size={15} /> Paramètres du programme
            </button>
          )}
          <button type="button" onClick={() => setShareOpen(true)}
                  className="inline-flex items-center gap-2 rounded-xl bg-[#2F6BFF] px-4 py-2.5 text-[13px] font-semibold text-white transition hover:bg-[#2559DB]">
            <Share2 size={15} /> Comment ça marche
          </button>
        </div>
      </header>

      {error && <p className="mb-4 rounded-xl bg-[#FEECEC] px-4 py-2.5 text-[12.5px] text-[#C0392B]">{error}</p>}

      {demo && (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[#C7DBFF] bg-[#EAF1FF] px-4 py-3">
          <p className="text-[12.5px] text-[#1D4ED8]">
            <strong>Exemple</strong> — ces chiffres illustrent ce que la page affichera. Aucune donnée
            n'a été créée dans votre compte.
          </p>
          <button type="button" onClick={() => setDemo(false)}
                  className="shrink-0 rounded-lg bg-[#2F6BFF] px-3 py-1.5 text-[12px] font-semibold text-white">
            Revenir à mes données
          </button>
        </div>
      )}

      {view && !view.enabled && !demo && (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[#FDE3C2] bg-[#FFF8EF] px-4 py-3">
          <p className="text-[12.5px] text-[#92400E]">
            Le programme de parrainage est <strong>inactif</strong> — les chiffres ci-dessous portent sur
            les parrainages déjà enregistrés, mais aucun nouveau ne sera compté.
          </p>
          {owner && (
            <button type="button" onClick={() => setSettingsOpen(true)}
                    className="shrink-0 rounded-lg bg-[#B45309] px-3 py-1.5 text-[12px] font-semibold text-white">
              Activer
            </button>
          )}
        </div>
      )}

      {loading && !data && (
        <div className="flex items-center justify-center gap-2 rounded-2xl border border-[#E6EEFB] bg-white py-20 text-[13px] text-[#64748B]">
          <Loader2 size={16} className="animate-spin" /> Chargement du parrainage…
        </div>
      )}

      {view && (
        <>
          {/* the four figures */}
          <div className="mb-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {cards.map((c, i) => <KpiCard key={c.key} card={c} showCaption={i === 0} />)}
          </div>

          <div className="grid items-start gap-4 xl:grid-cols-[1.75fr_1fr]">
            <div className="grid gap-4">
              <Panel
                title="Évolution des parrainages"
                action={(
                  <div className="relative">
                    <select value={days} onChange={(e) => setDays(Number(e.target.value))}
                            className="appearance-none rounded-xl border border-[#E6EEFB] bg-white py-2 pl-3 pr-8 text-[12.5px] font-medium text-[#334155] outline-none focus:border-[#2F6BFF]">
                      {RANGES.map((r) => <option key={r.key} value={r.key}>{r.label}</option>)}
                    </select>
                    <ChevronDown size={14} className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
                  </div>
                )}
              >
                <EvolutionChart series={view.series} />
              </Panel>

              <Panel title="Répartition des parrainages">
                {view.breakdown.total === 0 ? (
                  <p className="py-10 text-center text-[13px] text-[#94A3B8]">
                    Aucun parrainage sur cette période — la répartition apparaîtra dès le premier.
                  </p>
                ) : (
                  <Breakdown total={view.breakdown.total} segments={view.breakdown.segments} />
                )}
              </Panel>
            </div>

            <div className="grid gap-4">
              <Panel title="Top parrains" icon={Trophy} action={<SeeAll onClick={exportCsv} label="Voir tous" />}>
                {view.top_parrains.length === 0 && (
                  <p className="py-8 text-center text-[13px] text-[#94A3B8]">Pas encore de parrain sur cette période.</p>
                )}
                <ul className="space-y-1">
                  {view.top_parrains.map((p, i) => (
                    <li key={p.customer_id} className="flex items-center gap-3 py-2">
                      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-bold"
                            style={i < 3 ? { background: RANK[i], color: '#fff' } : { background: '#EEF3FB', color: '#64748B' }}>
                        {i + 1}
                      </span>
                      <Avatar initials={p.initials} tier={p.tier} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[13.5px] font-semibold text-[#0B1C3F]">{p.name}</span>
                        <span className="block text-[11.5px] text-[#94A3B8]">
                          {p.filleuls} filleul{p.filleuls > 1 ? 's' : ''}
                        </span>
                      </span>
                      <span className="shrink-0 text-[13.5px] font-bold text-[#0B1C3F] tabular-nums">
                        {nf(p.points)} points
                      </span>
                    </li>
                  ))}
                </ul>
              </Panel>

              {/* the encouragement card — only when the figures actually earn it */}
              {growing ? (
                <div className="flex items-center gap-4 rounded-2xl border border-[#CDEEDB] bg-[#EAF8F0] p-5">
                  <div className="min-w-0 flex-1">
                    <p className="flex items-center gap-2 text-[15px] font-bold text-[#0F8B58]">
                      <Trophy size={17} className="text-[#E9B949]" /> Félicitations !
                    </p>
                    <p className="mt-1 text-[12.5px] leading-snug text-[#3F6B55]">
                      Votre programme de parrainage génère de plus en plus de nouveaux clients.
                    </p>
                  </div>
                  <BarChart3 size={40} className="shrink-0 text-[#8FD3B0]" />
                </div>
              ) : (
                <div className="flex items-center gap-4 rounded-2xl border border-[#E6EEFB] bg-white p-5">
                  <div className="min-w-0 flex-1">
                    <p className="text-[15px] font-bold text-[#0B1C3F]">Faites connaître le programme</p>
                    <p className="mt-1 text-[12.5px] leading-snug text-[#64748B]">
                      Partagez le lien ou affichez le QR code en boutique pour lancer vos premiers parrainages.
                    </p>
                    <button type="button" onClick={() => setShareOpen(true)}
                            className="mt-2.5 inline-flex items-center gap-1.5 text-[12.5px] font-semibold text-[#2F6BFF] hover:underline">
                      Partager le programme <ArrowRight size={13} />
                    </button>
                  </div>
                  <Share2 size={36} className="shrink-0 text-[#C7DBFF]" />
                </div>
              )}
            </div>
          </div>

          {/* the table */}
          <Panel className="mt-4" title="Derniers parrainages"
                 action={(
                   <span className="flex items-center gap-3">
                     <button type="button" onClick={exportCsv} disabled={exporting}
                             className="inline-flex items-center gap-1.5 text-[12.5px] font-semibold text-[#475569] transition hover:text-[#2F6BFF] disabled:opacity-60">
                       {exporting ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />} Exporter
                     </button>
                     {recent.length > 5 && (
                       <SeeAll onClick={() => setAllRecent((v) => !v)}
                               label={allRecent ? 'Voir moins' : 'Voir tous'} />
                     )}
                   </span>
                 )}>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] border-collapse">
                <thead>
                  <tr className="border-b border-[#EEF3FB] text-left">
                    {['Date', 'Parrain', 'Filleul', 'Statut', 'Récompense', 'Source'].map((h) => (
                      <th key={h} className="px-3 py-2.5 text-[12px] font-semibold text-[#64748B]">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {shown.length === 0 && (
                    <tr><td colSpan={6} className="px-3 py-12 text-center">
                      <p className="text-[13.5px] font-semibold text-[#0B1C3F]">Aucun parrainage sur cette période</p>
                      <p className="mt-1 text-[12.5px] text-[#64748B]">
                        Partagez le programme pour que vos clients commencent à parrainer.
                      </p>
                    </td></tr>
                  )}
                  {shown.map((r) => (
                    <tr key={r.id} className="border-b border-[#F4F7FC] last:border-b-0 transition hover:bg-[#FAFCFF]">
                      <td className="whitespace-nowrap px-3 py-3 text-[12.5px] text-[#475569]">
                        {r.at ? fullDate(r.at) : '—'}
                      </td>
                      <td className="px-3 py-3">
                        <span className="flex items-center gap-2.5">
                          <Avatar initials={r.parrain.initials} tier={r.parrain.tier} size={28} />
                          <span className="truncate text-[13px] font-medium text-[#0B1C3F]">{r.parrain.name}</span>
                        </span>
                      </td>
                      <td className="px-3 py-3">
                        <span className="flex items-center gap-2.5">
                          <Avatar initials={r.filleul.initials} tier={r.filleul.tier} size={28} />
                          <span className="truncate text-[13px] font-medium text-[#0B1C3F]">{r.filleul.name}</span>
                        </span>
                      </td>
                      <td className="px-3 py-3">
                        <span className="inline-flex rounded-md px-2.5 py-1 text-[11.5px] font-semibold"
                              style={r.status === 'validated'
                                ? { background: '#E7F7EE', color: '#0F8B58' }
                                : { background: '#FFF3E3', color: '#B45309' }}>
                          {r.status_label}
                        </span>
                      </td>
                      <td className="whitespace-nowrap px-3 py-3">
                        <span className="flex items-center gap-1.5 text-[12.5px] text-[#334155]">
                          <Gift size={14} className="text-[#F59E0B]" /> {nf(r.reward_points)} points
                        </span>
                      </td>
                      <td className="whitespace-nowrap px-3 py-3 text-[12.5px] text-[#475569]">{r.source_label}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </>
      )}

      {settingsOpen && data && owner && (
        <SettingsModal config={view.config} enabled={view.enabled}
                       onClose={() => setSettingsOpen(false)}
                       onSaved={() => { setSettingsOpen(false); load(); }} />
      )}
      {shareOpen && <HowModal onClose={() => setShareOpen(false)} />}
    </div>
  );
}
