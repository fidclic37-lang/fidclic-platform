import React, { useCallback, useEffect, useState } from 'react';
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts';
import {
  Store, Users, BarChart3, Euro, ArrowUpRight, ArrowDownRight, Settings, Clock, CalendarClock, UserSquare2, Plus, Crown, Star, Send, CreditCard, Pencil, Loader2, ChevronDown,
} from 'lucide-react';
import { adminAPI } from '../../lib/api';
import { Kpi, Donut, Bars, Loading, Breadcrumb, Modal, nf } from '../crm/ui';
import { RangePicker, useRange } from './securite/shared';
import UsagePanel, { UsageFigures } from './analytics/UsagePanel';
import { CitiesSection, RevenueSection, SourcesSection, EvolutionSection, SectorsDonutSection } from './analytics/sections';
import { CohortsSection, BenchmarksSection, AdoptionSection, PlanMovesSection, GrowthSection, MapSection } from './analytics/deep';

/* Super admin › Analytics global — built to the approved mockup
   (features/admin_analytics.py). « Répartition du chiffre d'affaires » shows
   amounts only: the percentages are on « Répartition des abonnements ».
   Section 6 (cartes actives, notifications, géolocalisation and the three
   usage tabs) comes from the « Gestion des abonnements » mockup
   (analytics/UsagePanel.jsx, features/analytics_usage.py). */

const eur = (v, dec = 0) => `€${Number(v || 0).toLocaleString('fr-FR', { minimumFractionDigits: dec, maximumFractionDigits: dec })}`;
const GRAINS = [['day', 'Jour'], ['week', 'Semaine'], ['month', 'Mois']];
const KIND = {
  commerce: [Plus, '#10B981', 'Commerce', ['#E6F0FF', '#2F6BFF']], abonnement: [Crown, '#F59E0B', 'Abonnement', ['#E7F7EE', '#0F8B58']],
  avis: [Star, '#F59E0B', 'Avis', ['#FFF4DB', '#D97706']], marketing: [Send, '#2F6BFF', 'Marketing', ['#F3EEFF', '#7C3AED']],
  paiement: [CreditCard, '#10B981', 'Paiement', ['#E0F2FE', '#0284C7']], maj: [Pencil, '#2F6BFF', 'Mise à jour', ['#EAF1FF', '#2F6BFF']],
};

const Card = ({ children, className = '' }) => (
  <section className={`rounded-2xl border border-[#EDF1F7] bg-white p-5 shadow-[0_1px_2px_rgba(11,28,63,.03)] ${className}`}>{children}</section>
);
function Head({ icon: I, title, sub, right, tone = '#2F6BFF' }) {
  return (
    <header className="mb-3 flex items-start gap-3">
      <I size={24} className="mt-0.5 shrink-0" style={{ color: tone }} />
      <div className="min-w-0 flex-1"><h2 className="text-[17px] font-bold text-[#0B1C3F]">{title}</h2>{sub && <p className="text-[12.5px] text-[#64748B]">{sub}</p>}</div>
      {right}
    </header>
  );
}
const Delta = ({ v }) => (v === null || v === undefined ? null : (
  <span className={`inline-flex items-center gap-1 rounded-lg px-2.5 py-1 text-[13px] font-semibold ${v >= 0 ? 'bg-[#E7F7EE] text-[#0F8B58]' : 'bg-[#FDECEF] text-[#E11D48]'}`}>
    {v >= 0 ? <ArrowUpRight size={15} /> : <ArrowDownRight size={15} />}{v >= 0 ? '+' : ''}{v}%</span>
));

function tick(iso, grain) {
  const d = new Date(iso);
  return grain === 'month' ? d.toLocaleDateString('fr-FR', { month: 'short', year: 'numeric' }) : d.toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' });
}

function Curve({ points, grain, color, unit, money }) {
  const data = points.map((p) => ({ ...p, t: tick(p.at, grain), full: new Date(p.at).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric' }) }));
  const id = `g${color.slice(1)}`;
  return (
    <div className="h-[220px]">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 10, right: 12, left: money ? 4 : -18, bottom: 0 }}>
          <defs><linearGradient id={id} x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor={color} stopOpacity=".28" /><stop offset="1" stopColor={color} stopOpacity=".02" /></linearGradient></defs>
          <CartesianGrid stroke="#EEF2F7" vertical={false} />
          <XAxis dataKey="t" tick={{ fontSize: 11, fill: '#64748B' }} axisLine={false} tickLine={false} minTickGap={22} />
          <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: '#64748B' }} axisLine={false} tickLine={false} tickFormatter={(v) => (money ? eur(v) : nf(v))} />
          <Tooltip labelFormatter={(_, p) => p?.[0]?.payload?.full || ''} formatter={(v) => [money ? eur(v) : `${nf(v)} ${unit}`, '']} separator="" />
          <Area type="monotone" dataKey="value" stroke={color} strokeWidth={2.5} fill={`url(#${id})`} dot={{ r: 3, fill: color, strokeWidth: 0 }} activeDot={{ r: 5 }} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

export default function AnalyticsGlobalPage() {
  const [range, setRange] = useRange();
  const [grain, setGrain] = useState('day');
  const [d, setD] = useState(null);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const [all, setAll] = useState(null);
  const [months, setMonths] = useState(6);

  const load = useCallback(() => {
    setBusy(true);
    adminAPI.analyticsGlobal({ ...range, grain, months }).then(({ data }) => { setD(data); setErr(''); })
      .catch((e) => setErr(typeof e?.response?.data?.detail === 'string' ? e.response.data.detail : 'Impossible de charger les analytics.'))
      .finally(() => setBusy(false));
  }, [range, grain, months]);
  useEffect(() => { load(); }, [load]);
  const showAll = () => { setAll([]); adminAPI.analyticsActivity({ ...range, limit: 100 }).then(({ data }) => setAll(data.rows)).catch(() => setAll([])); };

  // « Analyses avancées » below each fetch their own data. Returning early
  // while this page's own call is in flight kept them unmounted, so they only
  // started once it answered — six requests queued behind the slowest one
  // instead of running beside it. Only the part that needs `d` waits now.
  const K = d ? Object.fromEntries(d.kpis.map((k) => [k.key, k])) : null;
  const kpis = K ? [['commerces', 'Commerces', Store, '#2F6BFF', '#EAF1FF', nf(K.commerces.value)], ['clients', 'Clients finaux', Users, '#10B981', '#E7F7EE', nf(K.clients.value)],
    ['visites', 'Visites', BarChart3, '#F59E0B', '#FFF4DB', nf(K.visites.value)], ['mrr', 'MRR', Euro, '#8B5CF6', '#F3EEFF', eur(K.mrr.value)],
    ['ca', "Chiffre d'affaires total", Euro, '#2F6BFF', '#EAF1FF', eur(K.ca.value, 2)]] : [];

  return (
    <div className="crm">
      <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <Breadcrumb items={[['Super Admin', '/admin'], ['Analytics']]} />
          <h1 className="text-[30px] font-bold leading-tight tracking-[-0.01em] text-[#0B1C3F]">Analytics global</h1>
          <p className="text-[15px] text-[#475569]">Vue d'ensemble de la performance de la plateforme FIDCLIC.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {busy && <Loader2 size={16} className="animate-spin text-[#94A3B8]" />}
          <RangePicker value={range} onChange={setRange} />
          <span className="relative">
            <select aria-label="Pas des courbes" value={grain} onChange={(e) => setGrain(e.target.value)} className="h-11 appearance-none rounded-xl border border-[#DCE3EE] bg-white pl-4 pr-9 text-[13.5px] text-[#0B1C3F]">
              {GRAINS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select>
            <ChevronDown size={15} className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[#475569]" />
          </span>
        </div>
      </header>
      {!d && (err
        ? <p className="rounded-xl bg-[#FEF2F2] px-4 py-3 text-[13.5px] text-[#B91C1C]">{err}</p>
        : <Loading />)}
      {d && (<>
      {d.grain !== grain && <p className="mb-3 rounded-xl bg-[#EFF5FF] px-4 py-2 text-[12.5px] text-[#1E4FD8]">Sur une période aussi longue, les courbes passent par {GRAINS.find(([k]) => k === d.grain)?.[1].toLowerCase()}.</p>}

      {/* 1 — figures */}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {kpis.map(([k, l, I, tone, bg, v]) => <Kpi key={k} icon={I} tone={tone} bg={bg} value={v} label={l} delta={K[k].delta} series={K[k].series} />)}
      </div>

      {/* 2 — growth · subscriptions */}
      <div className="mt-4 grid gap-4 xl:grid-cols-[1.35fr_1fr]">
        <Card>
          <Head icon={Store} title="Croissance des commerces" sub="Nombre de commerces sur la période (total à chaque date)." right={<Delta v={d.growth.delta} />} />
          <Curve points={d.growth.points} grain={d.grain} color="#2F6BFF" unit="commerces" />
        </Card>
        <Card>
          <Head icon={Settings} title="Répartition des abonnements" sub="Nombre de commerces par plan d'abonnement." />
          <Donut rows={d.plans.rows} colors={d.plans.rows.map((p) => p.color)} counts center={nf(d.plans.total)} sub="commerces" />
        </Card>
      </div>

      {/* 3 — sectors · cities */}
      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Card><Head icon={Clock} title="Répartition par secteur" sub="Nombre de commerces par secteur d'activité." /><Bars rows={d.sectors} /></Card>
        <CitiesSection rows={d.cities} Card={Card} Head={Head} />
      </div>

      {/* 3b — moved from the Dashboard (user, 2026-10-01) */}
      <div className="mt-4 grid gap-4 xl:grid-cols-[1.35fr_1fr]">
        <EvolutionSection rows={d.evolution} months={months} setMonths={setMonths} Card={Card} Head={Head} />
        <SectorsDonutSection rows={d.sectors_donut} total={d.plans.total} Card={Card} Head={Head} />
      </div>

      {/* 4 — MRR · revenue per plan */}
      <div className="mt-4 grid gap-4 xl:grid-cols-[1.35fr_1fr]">
        <Card>
          <Head icon={CalendarClock} title="Revenus récurrents (MRR)" sub="Évolution du revenu mensuel récurrent." right={<Delta v={d.mrr.delta} />} />
          <Curve points={d.mrr.points} grain={d.grain} color="#8B5CF6" money />
        </Card>
        <RevenueSection revenue={d.revenue} Card={Card} Head={Head} />
      </div>

      {/* 5 — acquisition sources · customers */}
      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <SourcesSection rows={d.sources} Card={Card} Head={Head} />
        <Card>
          <Head icon={UserSquare2} title="Clients finaux" sub="Évolution du nombre de clients finaux sur la période." right={<Delta v={d.clients.delta} />} />
          <Curve points={d.clients.points} grain={d.grain} color="#10B981" unit="clients" />
        </Card>
      </div>

      </>)}

      {/* Analyses avancées (user, 2026-10-01) — each section loads on its own */}
      <h2 className="mb-1 mt-8 text-[20px] font-bold text-[#0B1C3F]">Analyses avancées</h2>
      <p className="mb-3 text-[13px] text-[#64748B]">Rétention, comparaisons par secteur, usage des fonctionnalités, mouvements de plans, croissance et carte.</p>
      <CohortsSection Card={Card} Head={Head} />
      <div className="mt-4"><BenchmarksSection Card={Card} Head={Head} /></div>
      <div className="mt-4"><AdoptionSection Card={Card} Head={Head} /></div>
      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <PlanMovesSection range={range} Card={Card} Head={Head} />
        <GrowthSection range={range} Card={Card} Head={Head} />
      </div>
      <div className="mt-4"><MapSection Card={Card} Head={Head} /></div>

      {/* 6 — plan usage (from the « Gestion des abonnements » mockup) */}
      <div className="mt-4"><UsageFigures range={range} /></div>
      <UsagePanel />

      {/* 7 — recent activity — part of this page's own call, like the figures */}
      {d && (
        <Card className="mt-4">
          <Head icon={Clock} title="Activité récente" sub="Dernières actions importantes sur la plateforme."
                right={<button type="button" onClick={showAll} className="rounded-lg border border-[#DCE3EE] px-3 py-1.5 text-[12.5px] font-medium text-[#0B1C3F] hover:border-[#2F6BFF]">Voir tout</button>} />
          <ActivityList rows={d.activity} />
        </Card>
      )}

      {all && <Modal title="Activité récente" onClose={() => setAll(null)} wide>{all.length ? <ActivityList rows={all} /> : <Loading />}</Modal>}
    </div>
  );
}

const ago = (iso) => {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 3600) return `il y a ${Math.max(1, Math.round(s / 60))} min`;
  if (s < 86400) return `il y a ${Math.round(s / 3600)} h`;
  const days = Math.round(s / 86400);
  return days < 30 ? `il y a ${days} j` : new Date(iso).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' });
};

function ActivityList({ rows }) {
  if (!rows.length) return <p className="py-6 text-center text-[13px] text-[#94A3B8]">Aucune activité sur la période.</p>;
  return (
    <ul className="divide-y divide-[#F1F5F9]">
      {rows.map((a, i) => { const [I, c, label, [bg, fg]] = KIND[a.kind] || KIND.maj; return (
        <li key={i} className="grid grid-cols-[28px_1fr_auto_110px] items-center gap-3 py-2.5">
          <span className="grid h-7 w-7 place-items-center rounded-lg text-white" style={{ background: c }}><I size={15} /></span>
          <span className="truncate text-[13.5px] text-[#0B1C3F]">{a.text}</span>
          <span className="whitespace-nowrap text-[12px] text-[#94A3B8]">{ago(a.at)}</span>
          <span className="rounded-md px-2 py-1 text-center text-[12px] font-medium" style={{ background: bg, color: fg }}>{label}</span>
        </li>); })}
    </ul>
  );
}
