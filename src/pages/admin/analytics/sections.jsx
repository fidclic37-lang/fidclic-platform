import React from 'react';
import {
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, BarChart, Bar, Cell, LabelList, PieChart, Pie, Line, Area, ComposedChart,
} from 'recharts';
import { MapPin, Euro, Target, TrendingUp, PieChart as PieIcon } from 'lucide-react';
import { Donut, nf } from '../../crm/ui';

/* Sections shown both on the super admin's Dashboard and in Analytics
   (user, 2026-10-01) — one component, one set of figures (the same
   backend helpers, features/admin_analytics.py). Each page passes its own
   Card / Head so the section keeps that page's look. */

const eur = (v, dec = 0) => `€${Number(v || 0).toLocaleString('fr-FR', { minimumFractionDigits: dec, maximumFractionDigits: dec })}`;
const eurAuto = (v) => eur(v, Number(v) % 1 ? 2 : 0);
const MONTHS = ['Janv', 'Févr', 'Mars', 'Avr', 'Mai', 'Juin', 'Juil', 'Août', 'Sept', 'Oct', 'Nov', 'Déc'];
export const SOURCE_COLORS = { 'QR Store': '#8B5CF6', Instagram: '#F43F5E', Facebook: '#2F6BFF', 'Site web': '#F59E0B', TikTok: '#94A3B8', Autres: '#CBD5E1' };

export function CitiesSection({ rows, Card, Head }) {
  const max = Math.max(1, ...rows.map((c) => c.count));
  return (
    <Card>
      <Head icon={MapPin} title="Répartition par ville" sub="Nombre de commerces par ville." />
      <ul className="space-y-2">
        {rows.map((c) => (
          <li key={c.label} className="grid grid-cols-[120px_1fr_72px] items-center gap-2 text-[12.5px]">
            <span className="truncate text-[#475569]">{c.label}</span>
            <span className="h-2.5 overflow-hidden rounded-sm bg-[#EEF2F8]"><span className="block h-full rounded-sm bg-[#2F6BFF]" style={{ width: `${(c.count / max) * 100}%` }} /></span>
            <span className="text-right text-[#64748B]">{nf(c.count)} ({c.pct}%)</span>
          </li>
        ))}
        {!rows.length && <li className="text-[12.5px] text-[#94A3B8]">Aucune donnée pour le moment.</li>}
      </ul>
    </Card>
  );
}

/* Amounts only — the percentages are on « Répartition des abonnements ». */
export function RevenueSection({ revenue, Card, Head }) {
  const rows = revenue.rows;
  return (
    <Card>
      <Head icon={Euro} title="Répartition du chiffre d'affaires" sub="CA par plan d'abonnement." />
      <div className="flex flex-wrap items-center gap-5">
        <div className="relative h-[180px] w-[180px] shrink-0">
          <ResponsiveContainer>
            <PieChart>
              <Pie data={rows.length ? rows : [{ amount: 1 }]} dataKey="amount" innerRadius={58} outerRadius={86} paddingAngle={rows.length > 1 ? 2 : 0} stroke="none" isAnimationActive={false}>
                {(rows.length ? rows : [{}]).map((r, i) => <Cell key={i} fill={r.color || '#EEF2F8'} />)}
              </Pie>
            </PieChart>
          </ResponsiveContainer>
          <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
            <span className="text-[20px] font-bold text-[#0B1C3F]">{eur(revenue.total)}</span><span className="text-[12.5px] text-[#64748B]">CA total</span>
          </div>
        </div>
        <ul className="min-w-[150px] flex-1 space-y-3">
          {rows.map((r) => (
            <li key={r.key} className="flex items-start gap-3">
              <span className="mt-1 h-4 w-4 shrink-0 rounded" style={{ background: r.color }} />
              <span><span className="block text-[14px] text-[#0B1C3F]">{r.label}</span><strong className="block text-[15px] text-[#0B1C3F]">{eurAuto(r.amount)}</strong></span>
            </li>
          ))}
          {!rows.length && <li className="text-[12.5px] text-[#94A3B8]">Aucun achat enregistré sur la période.</li>}
        </ul>
      </div>
    </Card>
  );
}

export function SourcesSection({ rows, Card, Head }) {
  return (
    <Card>
      <Head icon={Target} title="Sources d'acquisition clients" sub="Nombre de clients finaux acquis par source." />
      <div className="h-[220px]">
        {rows.length ? (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={rows} margin={{ top: 22, right: 8, left: -18, bottom: 0 }}>
              <CartesianGrid stroke="#EEF2F7" vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 11.5, fill: '#475569' }} axisLine={false} tickLine={false} />
              <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: '#64748B' }} axisLine={false} tickLine={false} />
              <Tooltip formatter={(v) => [`${nf(v)} clients`, '']} separator="" cursor={{ fill: '#F4F7FC' }} />
              <Bar dataKey="count" radius={[6, 6, 0, 0]} maxBarSize={56}>
                {rows.map((s) => <Cell key={s.label} fill={SOURCE_COLORS[s.label] || '#2F6BFF'} />)}
                <LabelList dataKey="count" position="top" style={{ fontSize: 13, fontWeight: 700, fill: '#0B1C3F' }} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        ) : <p className="pt-16 text-center text-[12.5px] text-[#94A3B8]">Aucun nouveau client sur la période.</p>}
      </div>
    </Card>
  );
}

/* Moved from the Dashboard (user, 2026-10-01). */
export function EvolutionSection({ rows, months, setMonths, Card, Head }) {
  return (
    <Card>
      <Head icon={TrendingUp} title="Évolution de la plateforme" right={
        <select aria-label="Durée" value={months} onChange={(e) => setMonths(Number(e.target.value))} className="h-8 rounded-lg border border-[#DCE3EE] bg-white px-2 text-[12px]"><option value={6}>6 derniers mois</option><option value={12}>12 derniers mois</option></select>} />
      <div className="mb-1 flex flex-wrap justify-end gap-3 text-[12px] text-[#475569]">
        {[['#2F6BFF', 'Commerces (échelle de droite)'], ['#10B981', 'Clients'], ['#8B5CF6', 'Visites']].map(([c, l]) => <span key={l} className="flex items-center gap-1.5"><i className="h-2 w-2 rounded-full" style={{ background: c }} />{l}</span>)}
      </div>
      <div className="h-[230px]">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={rows.map((m) => ({ ...m, m: MONTHS[Number(m.month.slice(5, 7)) - 1] }))} margin={{ top: 8, right: 4, left: -10, bottom: 0 }}>
            <defs><linearGradient id="evoV" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#8B5CF6" stopOpacity={0.18} /><stop offset="100%" stopColor="#8B5CF6" stopOpacity={0} /></linearGradient></defs>
            <CartesianGrid stroke="#EEF2F7" vertical={false} />
            <XAxis dataKey="m" tick={{ fontSize: 11, fill: '#64748B' }} axisLine={false} tickLine={false} />
            <YAxis yAxisId="l" tick={{ fontSize: 11, fill: '#64748B' }} axisLine={false} tickLine={false} tickFormatter={(v) => (v >= 1000 ? `${Math.round(v / 1000)}K` : v)} />
            <YAxis yAxisId="r" orientation="right" tick={{ fontSize: 11, fill: '#2F6BFF' }} axisLine={false} tickLine={false} allowDecimals={false} />
            <Tooltip formatter={(v, k) => [nf(v), { commerces: 'Commerces', clients: 'Clients', visites: 'Visites' }[k]]} />
            <Area yAxisId="l" type="monotone" dataKey="visites" stroke="#8B5CF6" strokeWidth={2} fill="url(#evoV)" dot={{ r: 2.5 }} />
            <Line yAxisId="l" type="monotone" dataKey="clients" stroke="#10B981" strokeWidth={2} dot={{ r: 2.5 }} />
            <Line yAxisId="r" type="monotone" dataKey="commerces" stroke="#2F6BFF" strokeWidth={2} dot={{ r: 2.5 }} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}

/* Moved from the Dashboard (user, 2026-10-01); Analytics keeps its sector
   bars too. */
export function SectorsDonutSection({ rows, total, Card, Head }) {
  return <Card><Head icon={PieIcon} title="Répartition des commerces par secteur" /><Donut rows={rows} center={nf(total)} sub="commerces" /></Card>;
}
