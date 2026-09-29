import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { PieChart, Pie, Cell, ResponsiveContainer } from 'recharts';
import { ArrowUp, ArrowDown, ChevronRight, X, Loader2 } from 'lucide-react';
import { chartAnimation } from '../../lib/chartAnimation';

/* The CRM's shared pieces — the approved super-admin mockups' blue design. */

export const BLUE = '#2F6BFF';
export const nf = (n) => (n ?? 0).toLocaleString('fr-FR');
export const STAGE_TONE = {
  nouveau: ['#F1F5F9', '#475569'], a_contacter: ['#EAF1FF', '#2F6BFF'], contacte: ['#FFF4DB', '#D97706'],
  rdv: ['#F3E8FF', '#9333EA'], proposition: ['#FFF1E6', '#EA580C'], essai: ['#E0F7FA', '#0891B2'],
  signe: ['#E7F7EE', '#0F8B58'], perdu: ['#FDECEF', '#E11D48'],
};
export const CHART = ['#2F6BFF', '#10B981', '#8B5CF6', '#F59E0B', '#F43F5E', '#94A3B8', '#0EA5E9', '#EC4899'];
const AVATAR = ['#8B5CF6', '#2F6BFF', '#10B981', '#F59E0B', '#EF4444', '#0EA5E9', '#EC4899', '#475569'];

export const shortDate = (iso) => (iso ? new Date(iso).toLocaleDateString('fr-FR') : '—');
export const dayTime = (iso) => {
  if (!iso) return '';
  const d = new Date(iso); const today = new Date();
  const t = d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
  if (d.toDateString() === today.toDateString()) return `Aujourd'hui ${t}`;
  const tm = new Date(); tm.setDate(today.getDate() + 1);
  if (d.toDateString() === tm.toDateString()) return `Demain ${t}`;
  const y = new Date(); y.setDate(today.getDate() - 1);
  if (d.toDateString() === y.toDateString()) return `Hier ${t}`;
  return d.toLocaleDateString('fr-FR');
};
export const ago = (iso) => {
  if (!iso) return '';
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (m < 60) return `il y a ${Math.max(1, m)} min`;
  if (m < 1440) return `il y a ${Math.round(m / 60)} h`;
  const d = Math.round(m / 1440);
  return `il y a ${d} jour${d > 1 ? 's' : ''}`;
};

export const Card = ({ children, className = '' }) => (
  <section className={`rounded-2xl border border-[#EDF1F7] bg-white p-4 shadow-[0_1px_2px_rgba(11,28,63,.03)] ${className}`}>{children}</section>
);
export const Head = ({ icon: Icon, title, sub, right, tone = BLUE }) => (
  <header className="mb-3 flex items-start gap-2.5">
    {Icon && <Icon size={19} style={{ color: tone }} className="mt-0.5 shrink-0" />}
    <div className="min-w-0 flex-1">
      <h2 className="text-[15px] font-bold text-[#0B1C3F]">{title}</h2>
      {sub && <p className="text-[12px] text-[#64748B]">{sub}</p>}
    </div>
    {right}
  </header>
);

export function Spark({ series = [], color = BLUE, w = 96, h = 32 }) {
  if (!series.length) return null;
  const max = Math.max(1, ...series); const min = Math.min(...series);
  const pts = series.map((v, i) => [(i / Math.max(1, series.length - 1)) * w, h - 3 - ((v - min) / Math.max(1, max - min)) * (h - 6)]);
  const d = pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
  const id = `sp${color.replace('#', '')}`;
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true">
      <defs><linearGradient id={id} x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor={color} stopOpacity=".25" /><stop offset="1" stopColor={color} stopOpacity="0" /></linearGradient></defs>
      <path d={`${d} L${w},${h} L0,${h} Z`} fill={`url(#${id})`} />
      <path d={d} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

export function Kpi({ icon: Icon, tone, bg, value, label, delta, series }) {
  const up = (delta ?? 0) >= 0;
  return (
    <div className="flex items-center gap-3 rounded-2xl border border-[#EDF1F7] bg-white p-4 shadow-[0_1px_2px_rgba(11,28,63,.03)]">
      <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl" style={{ background: bg, color: tone }}><Icon size={24} /></span>
      <div className="min-w-0 flex-1">
        <p className="text-[22px] font-bold leading-none text-[#0B1C3F]">{typeof value === 'number' ? nf(value) : value}</p>
        <p className="mt-1 text-[12.5px] leading-tight text-[#64748B]">{label}</p>
        {delta !== undefined && delta !== null
          ? <p className={`mt-1 flex items-center gap-0.5 text-[12px] font-medium ${up ? 'text-[#10B981]' : 'text-[#E11D48]'}`}>{up ? <ArrowUp size={12} /> : <ArrowDown size={12} />}{up ? '+' : ''}{delta}%</p>
          : <p className="mt-1 text-[11px] text-[#94A3B8]">—</p>}
      </div>
      <div className="hidden shrink-0 self-end 2xl:block"><Spark series={series} color={tone} w={80} /></div>
    </div>
  );
}

export function Donut({ rows = [], center, sub }) {
  const data = rows.filter((r) => r.count > 0);
  return (
    <div className="flex flex-wrap items-center gap-4">
      <div className="relative h-[160px] w-[160px] shrink-0">
        <ResponsiveContainer>
          <PieChart>
            <Pie data={data.length ? data : [{ label: '—', count: 1 }]} dataKey="count" innerRadius={52} outerRadius={78} paddingAngle={data.length > 1 ? 2 : 0} isAnimationActive={chartAnimation()} stroke="none">
              {(data.length ? data : [{}]).map((_, i) => <Cell key={i} fill={data.length ? CHART[i % CHART.length] : '#EEF2F8'} />)}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-[20px] font-bold text-[#0B1C3F]">{center}</span><span className="text-[12px] text-[#64748B]">{sub}</span>
        </div>
      </div>
      <ul className="min-w-[160px] flex-1 space-y-2">
        {rows.map((r, i) => (
          <li key={r.key || r.label} className="flex items-center gap-2 text-[12.5px]">
            <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: r.count ? CHART[data.indexOf(r) % CHART.length] : '#CBD5E1' }} />
            <span className="flex-1 truncate text-[#334155]">{r.label}</span>
            <span className="font-medium text-[#0B1C3F]">{r.pct}%</span>
          </li>
        ))}
        {!rows.length && <li className="text-[12.5px] text-[#94A3B8]">Aucune donnée pour le moment.</li>}
      </ul>
    </div>
  );
}

export function Bars({ rows = [] }) {
  const max = Math.max(1, ...rows.map((r) => r.count));
  return (
    <ul className="space-y-2">
      {rows.map((r) => (
        <li key={r.key || r.label} className="grid grid-cols-[120px_1fr_72px] items-center gap-2 text-[12.5px]">
          <span className="truncate text-[#475569]">{r.label}</span>
          <span className="h-2.5 overflow-hidden rounded-sm bg-[#EEF2F8]"><span className="block h-full rounded-sm bg-[#2F6BFF]" style={{ width: `${(r.count / max) * 100}%` }} /></span>
          <span className="text-right text-[#64748B]">{r.pct}% ({nf(r.count)})</span>
        </li>
      ))}
      {!rows.length && <li className="text-[12.5px] text-[#94A3B8]">Aucune donnée pour le moment.</li>}
    </ul>
  );
}

export const StageBadge = ({ stage, label }) => {
  const [bg, fg] = STAGE_TONE[stage] || STAGE_TONE.nouveau;
  return <span className="inline-flex whitespace-nowrap rounded-md px-2.5 py-1 text-[12px] font-medium" style={{ background: bg, color: fg }}>{label}</span>;
};

export const Avatar = ({ name, size = 26 }) => {
  if (!name) return <span className="text-[12px] text-[#94A3B8]">—</span>;
  const i = [...name].reduce((a, c) => a + c.charCodeAt(0), 0) % AVATAR.length;
  return (
    <span className="inline-flex items-center gap-2">
      <span className="flex shrink-0 items-center justify-center rounded-full text-[11.5px] font-semibold text-white" style={{ width: size, height: size, background: AVATAR[i] }}>
        {name.trim()[0]?.toUpperCase()}
      </span>
      <span className="truncate text-[12.5px] text-[#0B1C3F]">{name}</span>
    </span>
  );
};

export const Logo = ({ name, size = 34 }) => {
  const i = [...(name || '?')].reduce((a, c) => a + c.charCodeAt(0), 0) % AVATAR.length;
  const initials = (name || '?').split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join('').toUpperCase();
  return <span className="flex shrink-0 items-center justify-center rounded-full text-[11px] font-bold text-white" style={{ width: size, height: size, background: `linear-gradient(135deg, ${AVATAR[i]}, #0B1C3F)` }}>{initials}</span>;
};

export const Select = ({ label, value, onChange, children, className = '' }) => (
  <label className={`block ${className}`}>
    {label && <span className="mb-1 block text-[11.5px] text-[#64748B]">{label}</span>}
    <span className="relative block">
      <select value={value} onChange={(e) => onChange(e.target.value)}
              className="h-10 w-full appearance-none rounded-lg border border-[#DCE3EE] bg-white pl-3 pr-8 text-[13px] text-[#0B1C3F] outline-none focus:border-[#2F6BFF]">
        {children}
      </select>
      <svg className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#0B1C3F" strokeWidth="2.5"><path d="m6 9 6 6 6-6" /></svg>
    </span>
  </label>
);

export const inputCls = 'h-10 w-full rounded-lg border border-[#DCE3EE] bg-white px-3 text-[13.5px] text-[#0B1C3F] outline-none focus:border-[#2F6BFF]';

export function Modal({ title, onClose, children, wide }) {
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-[#0B1C3F]/30 sm:items-center sm:p-6" onClick={onClose}>
      <div className={`max-h-[92vh] w-full ${wide ? 'max-w-5xl' : 'max-w-lg'} overflow-y-auto rounded-t-2xl bg-white p-5 shadow-2xl sm:rounded-2xl`} onClick={(e) => e.stopPropagation()}>
        <header className="mb-4 flex items-center justify-between">
          <h3 className="text-[16px] font-bold text-[#0B1C3F]">{title}</h3>
          <button type="button" onClick={onClose} aria-label="Fermer" className="text-[#94A3B8] hover:text-[#0B1C3F]"><X size={18} /></button>
        </header>
        {children}
      </div>
    </div>
  );
}

export const Loading = () => (
  <div className="flex items-center justify-center gap-2 rounded-2xl border border-[#E6EEFB] bg-white py-24 text-[13px] text-[#64748B]"><Loader2 size={16} className="animate-spin" /> Chargement…</div>
);

export function Breadcrumb({ items }) {
  return (
    <nav className="mb-1 flex items-center gap-1.5 text-[13px] text-[#64748B]" aria-label="Fil d'Ariane">
      {items.map(([label, to], i) => (
        <React.Fragment key={label}>
          {i > 0 && <ChevronRight size={13} />}
          {to ? <Link to={to} className="hover:text-[#2F6BFF]">{label}</Link> : <span className="text-[#0B1C3F]">{label}</span>}
        </React.Fragment>
      ))}
    </nav>
  );
}

export function Pager({ page, pages, total, perPage, onPage, onPerPage, what = 'prospects' }) {
  const nums = [];
  for (let i = 1; i <= pages; i += 1) if (i <= 5 || i === pages || Math.abs(i - page) <= 1) nums.push(i);
  const shown = [];
  nums.forEach((n, i) => { if (i && n - nums[i - 1] > 1) shown.push('…'); shown.push(n); });
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2 text-[12.5px]">
      <button type="button" disabled={page <= 1} onClick={() => onPage(page - 1)} className="h-8 w-8 rounded-lg border border-[#DCE3EE] disabled:opacity-40">‹</button>
      {shown.map((n, i) => (n === '…' ? <span key={`e${i}`} className="px-1 text-[#94A3B8]">…</span>
        : <button key={n} type="button" onClick={() => onPage(n)} className={`h-8 min-w-8 rounded-lg px-2 ${n === page ? 'bg-[#2F6BFF] text-white' : 'text-[#0B1C3F] hover:bg-[#F4F7FC]'}`}>{n}</button>))}
      <button type="button" disabled={page >= pages} onClick={() => onPage(page + 1)} className="h-8 w-8 rounded-lg border border-[#DCE3EE] disabled:opacity-40">›</button>
      <span className="ml-2 text-[#64748B]">Affichage de {total ? (page - 1) * perPage + 1 : 0} à {Math.min(total, page * perPage)} sur {nf(total)} {what}</span>
      {onPerPage && (
        <select value={perPage} onChange={(e) => onPerPage(Number(e.target.value))} className="ml-auto h-8 rounded-lg border border-[#DCE3EE] px-2 text-[12.5px]">
          {[10, 20, 50, 100].map((n) => <option key={n} value={n}>{n} par page</option>)}
        </select>
      )}
    </div>
  );
}

export function useToast() {
  const [msg, setMsg] = useState('');
  const say = (m) => { setMsg(m); setTimeout(() => setMsg(''), 3000); };
  const node = (
    <div aria-live="polite" className="pointer-events-none fixed bottom-5 left-1/2 z-[60] -translate-x-1/2 transition-opacity" style={{ opacity: msg ? 1 : 0 }}>
      <span className="inline-flex items-center gap-2 rounded-full bg-[#0B1C3F] px-4 py-2 text-[13px] font-medium text-white shadow-lg">{msg}</span>
    </div>
  );
  return [say, node];
}

export async function downloadBlob(promise, fallback) {
  const { data, headers } = await promise;
  const name = /filename="([^"]+)"/.exec(headers?.['content-disposition'] || '')?.[1] || fallback;
  const url = URL.createObjectURL(data);
  const a = document.createElement('a'); a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}
