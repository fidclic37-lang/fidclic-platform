import React from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Cell, LabelList, LineChart, Line, Legend,
} from 'recharts';
import { ShieldAlert, Eye, Sparkles, Bookmark, FileBarChart, Target, Lightbulb, PieChart as PieIcon, BarChart3, LineChart as LineIcon } from 'lucide-react';
import { Donut, nf } from '../../crm/ui';
import { PlanPill, CommerceLogo } from '../CommercesPage';

/* Shared by the FIDCLIC AI pages (features/admin_ai.py). */

export const AI_ITEMS = [['/admin/ai', 'AI Intelligence', Sparkles], ['/admin/ai/sauvegardes', 'Analyses sauvegardées', Bookmark],
  ['/admin/ai/rapports', 'Rapports automatiques', FileBarChart], ['/admin/ai/precision', 'Précision', Target],
  ['/admin/ai/recommandations', 'Recommandations', Lightbulb]];

export const eur = (v, dec = 0) => `€${Number(v || 0).toLocaleString('fr-FR', { minimumFractionDigits: dec, maximumFractionDigits: dec })}`;
export const day = (iso) => (iso ? new Date(iso).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric' }) : '—');
const LINE_COLORS = ['#E11D48', '#F472B6', '#F59E0B', '#2F6BFF', '#8B5CF6', '#10B981'];

/* The assistant, drawn (no image file). */
export function Robot({ size = 120 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 120 120" aria-hidden="true">
      <defs>
        <linearGradient id="rb-body" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor="#FFFFFF" /><stop offset="1" stopColor="#E6EEFB" /></linearGradient>
        <linearGradient id="rb-face" x1="0" x2="1" y1="0" y2="1"><stop offset="0" stopColor="#12306B" /><stop offset="1" stopColor="#0B1C3F" /></linearGradient>
        <radialGradient id="rb-eye"><stop offset="0" stopColor="#7DF9FF" /><stop offset="1" stopColor="#22D3EE" /></radialGradient>
      </defs>
      <ellipse cx="60" cy="112" rx="30" ry="4" fill="#0B1C3F" opacity=".08" />
      <line x1="60" y1="14" x2="60" y2="24" stroke="#2F6BFF" strokeWidth="3" strokeLinecap="round" />
      <circle cx="60" cy="11" r="5" fill="#2F6BFF" />
      <rect x="22" y="40" width="10" height="22" rx="5" fill="#2F6BFF" />
      <rect x="88" y="40" width="10" height="22" rx="5" fill="#2F6BFF" />
      <rect x="28" y="22" width="64" height="56" rx="24" fill="url(#rb-body)" stroke="#D6E2F5" />
      <rect x="36" y="32" width="48" height="34" rx="15" fill="url(#rb-face)" />
      <ellipse cx="50" cy="48" rx="6" ry="7" fill="url(#rb-eye)" />
      <ellipse cx="70" cy="48" rx="6" ry="7" fill="url(#rb-eye)" />
      <path d="M52 58 Q60 63 68 58" stroke="#7DF9FF" strokeWidth="2.5" fill="none" strokeLinecap="round" />
      <rect x="40" y="80" width="40" height="24" rx="12" fill="url(#rb-body)" stroke="#D6E2F5" />
      <circle cx="60" cy="92" r="4" fill="#2F6BFF" />
      <path d="M40 88 Q26 92 24 80" stroke="#D6E2F5" strokeWidth="7" fill="none" strokeLinecap="round" />
      <path d="M80 88 Q96 84 100 72" stroke="#D6E2F5" strokeWidth="7" fill="none" strokeLinecap="round" />
    </svg>
  );
}

export function AiTabs() {
  const { pathname } = useLocation();
  return (
    <nav className="mb-4 flex gap-1 border-b border-[#E6EEFB]">
      {AI_ITEMS.map(([to, label, I]) => { const on = pathname === to; return (
        <Link key={to} to={to} className={`inline-flex items-center gap-1.5 border-b-2 px-3.5 py-2.5 text-[13px] font-semibold ${on ? 'border-[#2F6BFF] text-[#2F6BFF]' : 'border-transparent text-[#64748B] hover:text-[#334155]'}`}><I size={15} /> {label}</Link>); })}
    </nav>
  );
}

function Spark({ values = [], color }) {
  if (!values.length) return null;
  const w = 110; const h = 30; const max = Math.max(1, ...values);
  const pts = values.map((v, i) => `${(i / Math.max(1, values.length - 1)) * w},${h - 3 - (v / max) * (h - 6)}`).join(' ');
  return <svg width={w} height={h} aria-hidden="true"><polyline points={pts} fill="none" stroke={color} strokeWidth="1.8" strokeLinejoin="round" /></svg>;
}

const LEVEL = { eleve: ['#FFE4E6', '#E11D48', ShieldAlert, 'Élevé'], moyen: ['#FFF4DB', '#D97706', Eye, 'Moyen'], haute: ['#FFE4E6', '#E11D48', null, 'Haute'] };
function LevelPill({ level, label }) {
  const [bg, fg, I, l] = LEVEL[level] || LEVEL.moyen;
  return <span className="inline-flex min-w-[70px] items-center justify-center gap-1 rounded-md px-2 py-1 text-[12px] font-medium" style={{ background: bg, color: fg }}>{I && <I size={13} />} {label || l}</span>;
}

function Commerce({ r }) {
  const navigate = useNavigate();
  return <button type="button" onClick={() => navigate(`/admin/commerces/${r.tenant_id}`)} className="flex items-center gap-2.5 text-left"><CommerceLogo c={r} size={28} /><span className="font-medium text-[#0B1C3F] hover:text-[#2F6BFF]">{r.name}</span></button>;
}

function Action({ r }) {
  const navigate = useNavigate();
  if (!r.action) return null;
  return <button type="button" onClick={() => navigate(`/admin/commerces/${r.tenant_id}?contact=${r.action_kind === 'relance' ? 'relance' : '1'}`)}
                 className="min-w-[96px] rounded-md bg-[#EAF1FF] px-3 py-1.5 text-[12px] font-medium text-[#2F6BFF] hover:bg-[#DCE8FF]">{r.action}</button>;
}

/* The table of an answer, column set by analysis. */
export function ResultTable({ res, onOpen }) {
  const rows = res.rows || [];
  if (!rows.length) return null;
  const th = (h) => <th key={h} className="px-2 py-2 text-left font-medium">{h}</th>;
  const cell = 'px-2 py-2.5 align-middle';
  let head; let body;
  if (res.kind === 'sectors') {
    head = ['#', 'Secteur', 'Commerces', 'Clients', 'Visites', 'Visites / commerce', "Chiffre d'affaires", 'Panier moyen', 'Évolution'];
    body = rows.map((r, i) => (
      <tr key={r.name} className="border-t border-[#F1F5F9]"><td className={cell}>{i + 1}</td><td className={`${cell} font-medium text-[#0B1C3F]`}>{r.name}</td>
        <td className={cell}>{nf(r.commerces)}</td><td className={cell}>{nf(r.clients)}</td><td className={cell}>{nf(r.visites)}</td><td className={cell}>{r.visites_par_commerce}</td>
        <td className={cell}>{eur(r.ca, 2)}</td><td className={cell}>{eur(r.panier, 2)}</td>
        <td className={`${cell} font-medium ${r.evolution === null ? 'text-[#94A3B8]' : r.evolution >= 0 ? 'text-[#0F8B58]' : 'text-[#E11D48]'}`}>{r.evolution === null ? '—' : `${r.evolution >= 0 ? '+' : ''}${r.evolution} %`}</td></tr>));
  } else if (res.kind === 'reco') {
    head = ['#', 'Recommandation', 'Priorité', 'Commerces', 'Impact', ''];
    body = rows.map((r, i) => (
      <tr key={r.name} className="border-t border-[#F1F5F9]"><td className={cell}>{i + 1}</td><td className={`${cell} font-medium text-[#0B1C3F]`}>{r.name}</td>
        <td className={cell}><LevelPill level={r.level === 'eleve' ? 'haute' : 'moyen'} label={r.level === 'eleve' ? 'Haute' : 'Moyenne'} /></td>
        <td className={cell}>{nf(r.count)}</td><td className={cell}>{r.impact}</td>
        <td className={`${cell} text-right`}><button type="button" onClick={() => onOpen?.(r.target)} className="rounded-md bg-[#EAF1FF] px-3 py-1.5 text-[12px] font-medium text-[#2F6BFF]">Voir</button></td></tr>));
  } else {
    const k = res.key;
    const cols = {
      risque: ['Plan', 'Risque', 'Raisons', 'Dernière activité', 'Tendance'],
      limite: ['Plan', 'Limite', 'Utilisation', 'Dernière activité'],
      upgrade: ['Plan', 'Détails', 'Gain MRR', 'Priorité'],
      sans_campagne: ['Plan', 'Dernière campagne', 'Clients', 'Dernière activité', 'Tendance'],
      inactifs: ['Plan', 'Inactif depuis', 'Clients', 'Dernière activité'],
    }[k] || ['Plan'];
    head = ['#', 'Commerce', ...cols, 'Action recommandée'];
    const val = (r, c) => {
      switch (c) {
        case 'Plan': return <PlanPill p={r.plan} />;
        case 'Risque': return <LevelPill level={r.level} label={r.level_label} />;
        case 'Raisons': return <span className="block text-[12px] leading-snug text-[#475569]">{(r.reasons || []).map((x) => <span key={x} className="block">- {x}</span>)}</span>;
        case 'Dernière activité': return day(r.last_activity);
        case 'Tendance': return <Spark values={r.trend} color={r.level === 'eleve' ? '#E11D48' : '#F59E0B'} />;
        case 'Limite': return <span className="capitalize">{r.limit}</span>;
        case 'Utilisation': return (
          <span className="flex min-w-[150px] items-center gap-2"><span className="h-2 flex-1 overflow-hidden rounded-full bg-[#EEF2F8]"><span className="block h-full rounded-full" style={{ width: `${Math.min(100, r.pct)}%`, background: r.pct >= 100 ? '#E11D48' : '#F59E0B' }} /></span>
            <span className="whitespace-nowrap text-[12px] text-[#475569]">{nf(r.used)} / {nf(r.cap)} · {r.pct} %</span></span>);
        case 'Détails': return r.details;
        case 'Gain MRR': return r.gain ? <strong className="text-[#0F8B58]">+{eur(r.gain)}</strong> : '—';
        case 'Priorité': return <LevelPill level={r.level === 'haute' ? 'haute' : 'moyen'} label={r.level_label} />;
        case 'Dernière campagne': return r.last_campaign ? day(r.last_campaign) : <span className="text-[#E11D48]">Jamais</span>;
        case 'Clients': return nf(r.clients);
        case 'Inactif depuis': return r.days !== null && r.days !== undefined ? `${r.days} jours` : '—';
        default: return '';
      }
    };
    body = rows.map((r, i) => (
      <tr key={`${r.tenant_id}-${r.limit || ''}`} className="border-t border-[#F1F5F9]"><td className={cell}>{i + 1}</td><td className={cell}><Commerce r={r} /></td>
        {cols.map((c) => <td key={c} className={cell}>{val(r, c)}</td>)}<td className={`${cell} text-center`}><Action r={r} /></td></tr>));
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[860px] text-[12.5px] text-[#334155]"><thead><tr className="text-[#64748B]">{head.map(th)}</tr></thead><tbody>{body}</tbody></table>
    </div>
  );
}

const Box = ({ icon: I, title, children }) => (
  <section className="rounded-2xl border border-[#EDF1F7] bg-white p-4 shadow-[0_1px_2px_rgba(11,28,63,.03)]">
    <h3 className="mb-3 flex items-center gap-2 text-[15px] font-bold text-[#0B1C3F]"><I size={18} className="text-[#2F6BFF]" /> {title}</h3>{children}
  </section>
);

/* The three charts under an answer. */
export function ResultCharts({ charts }) {
  if (!charts) return null;
  const { donut, bars, lines } = charts;
  const lineData = lines ? lines.days.map((dd, i) => ({ d: new Date(`${dd}T12:00:00`).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' }),
    ...Object.fromEntries(lines.series.map((s) => [s.name, s.values[i]])) })) : [];
  return (
    <div className={`grid gap-4 ${lines ? 'xl:grid-cols-[1fr_1fr_1.5fr]' : 'xl:grid-cols-2'}`}>
      {donut && (
        <Box icon={PieIcon} title={donut.title}>
          <Donut rows={donut.rows.map((r) => ({ ...r, pct: Math.round((r.count / Math.max(1, donut.rows.reduce((a, b) => a + b.count, 0))) * 100) }))}
                 colors={donut.rows.every((r) => r.color) ? donut.rows.map((r) => r.color) : undefined} counts center={nf(donut.center)} sub={donut.sub} />
        </Box>
      )}
      {bars && (
        <Box icon={BarChart3} title={bars.title}>
          {bars.rows.length ? (
            <div className="h-[190px]"><ResponsiveContainer width="100%" height="100%">
              <BarChart data={bars.rows} margin={{ top: 20, right: 8, left: -22, bottom: 4 }}>
                <CartesianGrid stroke="#EEF2F7" vertical={false} />
                <XAxis dataKey="label" tick={{ fontSize: 10.5, fill: '#475569' }} axisLine={false} tickLine={false} interval={0} angle={bars.rows.length > 3 ? -25 : 0}
                       textAnchor={bars.rows.length > 3 ? 'end' : 'middle'} height={bars.rows.length > 3 ? 46 : 24} tickFormatter={(v) => (v.length > 12 ? `${v.slice(0, 11)}…` : v)} />
                <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: '#64748B' }} axisLine={false} tickLine={false} />
                <Tooltip formatter={(v) => [nf(v), '']} separator="" cursor={{ fill: '#F4F7FC' }} />
                <Bar dataKey="count" radius={[6, 6, 0, 0]} maxBarSize={48}>
                  {bars.rows.map((r, i) => <Cell key={r.label} fill={i === 0 ? '#F43F5E' : '#F59E0B'} />)}
                  <LabelList dataKey="count" position="top" style={{ fontSize: 12, fontWeight: 700, fill: '#0B1C3F' }} />
                </Bar>
              </BarChart>
            </ResponsiveContainer></div>
          ) : <p className="py-10 text-center text-[12.5px] text-[#94A3B8]">Aucune donnée.</p>}
        </Box>
      )}
      {lines && (
        <Box icon={LineIcon} title={lines.title}>
          {lines.series.length ? (
            <div className="h-[190px]"><ResponsiveContainer width="100%" height="100%">
              <LineChart data={lineData} margin={{ top: 6, right: 8, left: -14, bottom: 0 }}>
                <CartesianGrid stroke="#EEF2F7" vertical={false} />
                <XAxis dataKey="d" tick={{ fontSize: 11, fill: '#64748B' }} axisLine={false} tickLine={false} minTickGap={24} />
                <YAxis domain={[0, 100]} tickFormatter={(v) => `${v}%`} tick={{ fontSize: 11, fill: '#64748B' }} axisLine={false} tickLine={false} />
                <Tooltip formatter={(v, n) => [`${v} %`, n]} />
                <Legend layout="vertical" align="right" verticalAlign="middle" iconType="circle" wrapperStyle={{ fontSize: 12 }} />
                {lines.series.map((s, i) => <Line key={s.name} type="monotone" dataKey={s.name} stroke={LINE_COLORS[i % LINE_COLORS.length]} strokeWidth={2} dot={{ r: 2 }} />)}
              </LineChart>
            </ResponsiveContainer></div>
          ) : <p className="py-10 text-center text-[12.5px] text-[#94A3B8]">Aucune donnée.</p>}
        </Box>
      )}
    </div>
  );
}
