import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  Store, Users, CreditCard, Megaphone, Euro, CalendarDays, ChevronDown, PieChart as PieIcon, Sparkles, ChevronRight, TrendingDown, Rocket, Clock, Building2, Trophy, Activity, Send, UserPlus, PauseCircle, PlayCircle, Inbox, ArrowUp, ArrowDown, CircleAlert,
} from 'lucide-react';
import { adminAPI } from '../../lib/api';
import { Card, Head, Kpi, Donut, Loading, Modal, nf, BLUE } from '../crm/ui';
import { PlanPill, CommerceLogo } from './CommercesPage';
import { CitiesSection, RevenueSection, SourcesSection } from './analytics/sections';
import CommerceListModal from './CommerceListModal';

/* Super admin › Dashboard — built to the approved mockup. */

const PERIODS = [['7', '7 derniers jours'], ['30', '30 derniers jours'], ['90', '90 derniers jours'], ['365', '12 derniers mois'], ['custom', 'Personnalisé…']];
const iso = (d) => d.toISOString().slice(0, 10);
const frDate = (s) => new Date(`${s}T12:00:00`).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric' });
const OPP_ICON = { limit: [CreditCard, '#F59E0B', '#FFF4DB'], campaign: [Megaphone, '#F97316', '#FFEDD5'], falling: [TrendingDown, '#8B5CF6', '#F3EEFF'],
  upgrade: [Rocket, '#10B981', '#E7F7EE'], trial: [Clock, '#2F6BFF', '#EAF1FF'], franchise: [Building2, '#7C3AED', '#F3EEFF'] };
const ACT_ICON = { signup: [UserPlus, '#10B981', '#E7F7EE'], campaign: [Send, '#2F6BFF', '#EAF1FF'], plan: [Sparkles, '#8B5CF6', '#F3EEFF'],
  clients: [Users, '#10B981', '#E7F7EE'], suspend: [PauseCircle, '#E11D48', '#FDECEF'], reactivate: [PlayCircle, '#10B981', '#E7F7EE'], request: [Inbox, '#7C3AED', '#F3EEFF'] };
const ago = (s) => {
  const m = Math.round((Date.now() - new Date(s).getTime()) / 60000);
  if (m < 60) return `il y a ${Math.max(1, m)} min`;
  if (m < 1440) return `il y a ${Math.round(m / 60)} h`;
  const d = Math.round(m / 1440);
  return `il y a ${d} jour${d > 1 ? 's' : ''}`;
};

export default function AdminDashboardPage() {
  const navigate = useNavigate();
  const [period, setPeriod] = useState('30');
  const [custom, setCustom] = useState({ from: iso(new Date(Date.now() - 30 * 86400000)), to: iso(new Date()) });
  const [d, setD] = useState(null);
  const [err, setErr] = useState('');
  const [open, setOpen] = useState(false);
  const [modal, setModal] = useState(null);
  const [list, setList] = useState(null);       // the businesses behind a figure

  const range = () => (period === 'custom' ? custom : { from: iso(new Date(Date.now() - Number(period) * 86400000)), to: iso(new Date()) });
  const listRange = useMemo(() => range(), [period, custom]); // eslint-disable-line react-hooks/exhaustive-deps
  const load = useCallback(() => {
    adminAPI.dashboard(range()).then(({ data }) => { setErr(''); setD(data); }).catch((e) => setErr(e?.response?.data?.detail || 'Impossible de charger le tableau de bord.'));
  }, [period, custom]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [load]);

  if (!d) return err ? <p className="rounded-xl bg-[#FEF2F2] px-4 py-3 text-[13.5px] text-[#B91C1C]">{err}</p> : <Loading />;
  const K = Object.fromEntries(d.kpis.map((k) => [k.key, k]));
  const S = Object.fromEntries(d.status_cards.map((k) => [k.key, k]));
  const oppTotal = d.opportunities.reduce((a, o) => a + o.count, 0);
  // The figures (user, 2026-10-01): Commerces = en essai + abonnés only;
  // Impayé (stopped paying or suspended) in place of « Nouveaux ce mois ».
  // Every figure opens the businesses behind it (CommerceListModal).
  const kpis = [
    ['commerces', 'Commerces', Store, '#2F6BFF', '#EAF1FF'], ['impaye', 'Impayé', CircleAlert, '#E11D48', '#FDECEF'],
    ['clients', 'Clients finaux', Users, '#10B981', '#E7F7EE'], ['cartes', 'Cartes actives', CreditCard, '#2F6BFF', '#EAF1FF'],
    ['ca', "Chiffre d'affaires total", Euro, '#F59E0B', '#FFF4DB'], ['mrr', 'MRR', Euro, '#10B981', '#E7F7EE'],
  ];
  const money = (k) => k === 'mrr' || k === 'ca';
  const split = K.commerces.breakdown || {};
  const stop = (fn) => (e) => { e.stopPropagation(); fn(); };
  const feet = {
    commerces: (
      <p className="mt-2 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[11.5px] text-[#475569]">
        <button type="button" onClick={stop(() => setList('essai'))} title="Voir les commerces en essai" className="inline-flex items-center gap-1 rounded hover:text-[#7C3AED]"><i className="h-2 w-2 rounded-full bg-[#8B5CF6]" />{nf(split.essai)} en essai</button>
        <button type="button" onClick={stop(() => setList('abonne'))} title="Voir les commerces abonnés" className="inline-flex items-center gap-1 rounded hover:text-[#0F8B58]"><i className="h-2 w-2 rounded-full bg-[#10B981]" />{nf(split.abonne)} abonnés</button>
      </p>
    ),
    impaye: (
      <p className="mt-2 text-[11.5px] text-[#475569]">{K.impaye.suspendus ? `dont ${nf(K.impaye.suspendus)} suspendu${K.impaye.suspendus > 1 ? 's' : ''} · ` : ''}€{nf(K.impaye.mrr_at_stake)} / mois en jeu</p>
    ),
  };
  const statusCards = [
    ['nouveaux', 'Nouveaux commerces', '#2F6BFF', (c) => <><strong className="text-[24px] text-[#10B981]">+{nf(c.value)}</strong><span className="block text-[12px] text-[#64748B]">ce mois-ci</span></>],
    ['actif', 'Commerces actifs', '#10B981', (c) => <><strong className="text-[24px] text-[#0B1C3F]">{nf(c.value)}</strong><span className="block text-[12px] text-[#64748B]">{c.pct}% du total</span></>],
    ['inactif', 'Commerces inactifs', '#F43F5E', (c) => <><strong className="text-[24px] text-[#E11D48]">{nf(c.value)}</strong><span className="block text-[12px] text-[#64748B]">{c.pct}% du total</span></>],
    ['a_risque', 'À risque', '#F59E0B', (c) => <><strong className="text-[24px] text-[#D97706]">{nf(c.value)}</strong><span className="block text-[12px] text-[#64748B]">{c.pct}% du total</span></>],
    ['resilie', 'Résilié', '#0B1C3F', (c) => <><strong className="text-[24px] text-[#0B1C3F]">{nf(c.value)}</strong><span className="block text-[12px] text-[#64748B]">sur la période · {nf(c.total)} au total</span></>],
    ['non_converti', 'Essais non convertis', '#8B5CF6', (c) => <><strong className="text-[24px] text-[#7C3AED]">{nf(c.value)}</strong><span className="block text-[12px] text-[#64748B]">{c.conversion != null ? `${c.conversion}% de conversion` : 'aucun essai terminé'}</span></>],
  ];
  const badDelta = (k) => ['inactif', 'a_risque', 'resilie', 'non_converti'].includes(k);
  const tip = {
    actif: 'Plus de 25 cartes et 25 scans par semaine (le plus faible des deux décide).',
    a_risque: 'Entre 15 et 25 cartes et scans par semaine.', inactif: 'Moins de 15 cartes ou scans par semaine.',
    resilie: 'Clients qui ont arrêté (marqués à la main) sur la période choisie.',
    non_converti: "Essais terminés sur la période sans abonnement. Le % = essais convertis / essais terminés.",
    nouveaux: 'Commerces inscrits ce mois-ci.',
  };

  return (
    <div className="crm" onClick={() => setOpen(false)}>
      <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-[32px] font-bold leading-tight text-[#0B1C3F]">Dashboard</h1>
          <p className="text-[15px] text-[#475569]">Vue d'ensemble de toute la plateforme FIDCLIC.</p>
        </div>
        <span className="relative" onClick={(e) => e.stopPropagation()}>
          <button type="button" onClick={() => setOpen((v) => !v)} className="inline-flex h-11 items-center gap-2 rounded-xl border border-[#DCE3EE] bg-white px-4 text-[13.5px] text-[#0B1C3F]">
            <CalendarDays size={16} /> {frDate(d.period.from)} - {frDate(d.period.to)} <ChevronDown size={15} />
          </button>
          {open && (
            <span className="absolute right-0 top-full z-30 mt-1 flex w-64 flex-col overflow-hidden rounded-xl border border-[#E6EEFB] bg-white py-1 text-[13px] shadow-lg">
              {PERIODS.map(([k, l]) => <button key={k} type="button" onClick={() => { setPeriod(k); if (k !== 'custom') setOpen(false); }} className={`px-3.5 py-2 text-left hover:bg-[#F4F7FC] ${period === k ? 'font-semibold text-[#2F6BFF]' : ''}`}>{l}</button>)}
              {period === 'custom' && (
                <span className="flex items-center gap-1.5 border-t border-[#EDF1F7] px-3 py-2">
                  <input type="date" value={custom.from} max={custom.to} onChange={(e) => setCustom({ ...custom, from: e.target.value })} className="h-8 min-w-0 flex-1 rounded-lg border border-[#DCE3EE] px-1.5 text-[12px]" />
                  <input type="date" value={custom.to} min={custom.from} onChange={(e) => setCustom({ ...custom, to: e.target.value })} className="h-8 min-w-0 flex-1 rounded-lg border border-[#DCE3EE] px-1.5 text-[12px]" />
                </span>
              )}
            </span>
          )}
        </span>
      </header>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        {kpis.map(([k, l, I, c, bg]) => (
          <div key={k} role="button" tabIndex={0} title="Voir les commerces" onClick={() => setList(k)} onKeyDown={(e) => { if (e.key === 'Enter') setList(k); }}
               className="cursor-pointer rounded-2xl transition hover:ring-2 hover:ring-[#BFD3FF]">
            <Kpi compact icon={I} tone={c} bg={bg} value={money(k) ? `€${nf(Math.round(K[k].value))}` : nf(K[k].value)} label={l} delta={K[k].delta} series={K[k].series || []} foot={feet[k] || null} />
          </div>
        ))}
      </div>

      {/* Sources, plans, chiffre d'affaires, villes — the three Analytics
          sections the user wanted here too (same figures as Analytics). « Évolution
          de la plateforme » and the sector donut moved to Analytics. */}
      <div className="mt-4 grid gap-4 xl:grid-cols-2 min-[1700px]:grid-cols-[1.3fr_1fr_1fr_1fr]">
        <SourcesSection rows={d.sources} Card={Card} Head={Head} />
        <Card><Head icon={PieIcon} title="Répartition par plan" /><Donut rows={d.plans} center={nf(d.total)} sub="commerces" /></Card>
        <RevenueSection revenue={d.revenue} Card={Card} Head={Head} />
        <CitiesSection rows={d.cities} Card={Card} Head={Head} />
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-[repeat(6,minmax(0,1fr))_minmax(250px,1.5fr)]">
        {statusCards.map(([k, l, color, body]) => { const c = S[k]; const max = Math.max(1, ...c.bars); const up = (c.delta ?? 0) >= 0; const bad = badDelta(k) ? up : !up; return (
          <button key={k} type="button" onClick={() => setList(k)} title={tip[k]} className="flex flex-col rounded-2xl border border-[#EDF1F7] bg-white p-3.5 text-left shadow-[0_1px_2px_rgba(11,28,63,.03)] hover:border-[#BFD3FF]">
            <p className="flex min-h-[34px] items-start justify-between gap-1.5 text-[12.5px] font-medium leading-tight text-[#0B1C3F]">{l}
              {c.delta != null && <span className={`inline-flex shrink-0 items-center gap-0.5 rounded-md px-1 py-0.5 text-[10.5px] font-semibold ${bad ? 'bg-[#FDECEF] text-[#E11D48]' : 'bg-[#E7F7EE] text-[#0F8B58]'}`}>{up ? <ArrowUp size={10} /> : <ArrowDown size={10} />}{up ? '+' : ''}{c.delta}%</span>}</p>
            <div className="mt-1">{body(c)}</div>
            <div className="mt-auto flex h-11 items-end gap-[3px] pt-3" title="12 dernières semaines">
              {c.bars.map((v, i) => <span key={i} className="flex-1 rounded-t" style={{ height: `${Math.max(6, (v / max) * 100)}%`, background: color, opacity: 0.35 + (0.65 * (i + 1)) / c.bars.length }} />)}
            </div>
          </button>); })}
        <Card className="border-[#D9C8FF] shadow-[0_0_0_3px_rgba(139,92,246,.06)] sm:col-span-2 lg:col-span-3 xl:col-span-1">
          <Head icon={Sparkles} tone="#8B5CF6" title="Opportunités IA" right={<span className="rounded-full bg-[#FDECEF] px-2.5 py-0.5 text-[12px] font-semibold text-[#E11D48]">{nf(oppTotal)}</span>} />
          <ul className="divide-y divide-[#F1F5F9]">
            {d.opportunities.map((o) => { const [I, c, bg] = OPP_ICON[o.icon] || OPP_ICON.limit; return (
              <li key={o.key}><button type="button" disabled={!o.count} onClick={() => setModal({ type: 'opp', o })} className="flex w-full items-center gap-3 py-2 text-left text-[13px] text-[#334155] disabled:opacity-50">
                <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg" style={{ background: bg, color: c }}><I size={14} /></span>
                <span className="flex-1">{o.label}</span>{o.count > 0 && <ChevronRight size={15} className="text-[#94A3B8]" />}
              </button></li>); })}
          </ul>
          <p className="mt-2 text-[11px] text-[#94A3B8]">Détectées par des règles sur vos données, sans IA générative.</p>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[1.6fr_1fr]">
        <Card>
          <Head icon={Trophy} title="Top 5 commerces par nombre de clients" right={<Link to="/admin/commerces" className="text-[12.5px] text-[#2F6BFF]">Voir tous</Link>} />
          <div className="overflow-x-auto">
            <table className="w-full min-w-[620px] text-[13px]">
              <thead><tr className="border-b border-[#EDF1F7] text-left text-[#64748B]">{['#', 'Commerce', 'Secteur', 'Ville', 'Clients', 'Visites', 'Plan'].map((h) => <th key={h} className="px-2 py-2 font-medium">{h}</th>)}</tr></thead>
              <tbody>{d.top.map((c, i) => (
                <tr key={c.id} onClick={() => navigate(`/admin/commerces/${c.id}`)} className="cursor-pointer border-b border-[#F4F7FC] hover:bg-[#FAFCFF]">
                  <td className="px-2 py-2 text-[#94A3B8]">{i + 1}</td>
                  <td className="px-2 py-2"><span className="flex items-center gap-2.5"><CommerceLogo c={c} size={30} /><span className="font-medium text-[#0B1C3F]">{c.name}</span></span></td>
                  <td className="px-2 py-2 text-[#475569]">{c.sector || '—'}</td><td className="px-2 py-2 text-[#475569]">{c.city || '—'}</td>
                  <td className="px-2 py-2 tabular-nums">{nf(c.clients)}</td><td className="px-2 py-2 tabular-nums">{nf(c.visits)}</td><td className="px-2 py-2"><PlanPill p={c.plan} /></td>
                </tr>))}
                {!d.top.length && <tr><td colSpan={7} className="py-8 text-center text-[#94A3B8]">Aucun commerce.</td></tr>}
              </tbody>
            </table>
          </div>
        </Card>
        <Card>
          <Head icon={Activity} title="Activité récente" right={d.activity.length > 5 && <button type="button" onClick={() => setModal({ type: 'activity' })} className="text-[12.5px] text-[#2F6BFF]">Voir tout</button>} />
          <ActivityList rows={d.activity.slice(0, 5)} navigate={navigate} />
          {!d.activity.length && <p className="py-8 text-center text-[13px] text-[#94A3B8]">Rien sur les 30 derniers jours.</p>}
        </Card>
      </div>

      {list && <CommerceListModal listKey={list} range={listRange} onClose={() => setList(null)} />}
      {modal?.type === 'opp' && (
        <Modal title={modal.o.label} onClose={() => setModal(null)}>
          <ul className="max-h-[60vh] divide-y divide-[#F1F5F9] overflow-y-auto">
            {modal.o.tenants.map((t) => <li key={t.id}><Link to={`/admin/commerces/${t.id}`} className="flex items-center justify-between py-2.5 text-[13.5px] text-[#0B1C3F] hover:text-[#2F6BFF]">{t.name}<ChevronRight size={15} /></Link></li>)}
          </ul>
          {modal.o.count > modal.o.tenants.length && <p className="mt-2 text-[12px] text-[#64748B]">Et {modal.o.count - modal.o.tenants.length} autres.</p>}
        </Modal>
      )}
      {modal?.type === 'activity' && <Modal title="Activité récente — 30 jours" onClose={() => setModal(null)}><ActivityList rows={d.activity} navigate={navigate} /></Modal>}
    </div>
  );
}

function ActivityList({ rows, navigate }) {
  return (
    <ul className="space-y-1.5">
      {rows.map((e, i) => { const [I, c, bg] = ACT_ICON[e.kind] || ACT_ICON.signup; return (
        <li key={`${e.kind}-${e.at}-${i}`}>
          <button type="button" onClick={() => e.tenant_id && navigate(`/admin/commerces/${e.tenant_id}`)} className="flex w-full items-center gap-3 rounded-xl border border-[#F1F5F9] px-3 py-2 text-left hover:bg-[#FAFCFF]">
            <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full" style={{ background: bg, color: c }}><I size={15} /></span>
            <span className="min-w-0 flex-1"><span className="block truncate text-[13px] font-medium text-[#0B1C3F]">{e.title}</span><span className="block truncate text-[12px] text-[#64748B]">{e.sub}{e.detail ? ` — ${e.detail}` : ''}</span></span>
            <span className="shrink-0 text-[11.5px] text-[#94A3B8]">{ago(e.at)}</span>
          </button>
        </li>); })}
    </ul>
  );
}
