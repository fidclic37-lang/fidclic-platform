import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import {
  ArrowUpRight, Eye, AlertTriangle, Crown, ChevronRight, Store, BarChart3, Clock, ArrowDown, Star, PieChart as PieIcon,
  LineChart as LineIcon, Layers, Download, MoreHorizontal, SlidersHorizontal, Loader2, CheckCircle2,
} from 'lucide-react';
import { adminAPI } from '../../lib/api';
import { useAuth } from '../../contexts/AuthContext';
import { can } from '../../lib/perms';
import { Card, Head, Kpi, Donut, Loading, Breadcrumb, Pager, Modal, useToast, downloadBlob, nf, BLUE, CHART } from '../crm/ui';
import { RangePicker, useRange } from './securite/shared';
import { CommerceLogo, openViewAs } from './CommercesPage';

/* Super admin › Insights — built to the approved mockup. The four rules and
   their thresholds live in features/admin_insights.py (editable here in
   « Règles des insights »); every figure is re-computed from dated facts. */

const TYPE = {
  opportunite: { icon: ArrowUpRight, fg: '#0F8B58', dot: '#10B981', bg: '#EFFBF5', border: '#C9EEDB', chip: '#DDF6EA', tab: 'Opportunités' },
  surveiller: { icon: Eye, fg: '#D97706', dot: '#F59E0B', bg: '#FFF8EC', border: '#FBE3BC', chip: '#FFEBC9', tab: 'À surveiller' },
  risque: { icon: AlertTriangle, fg: '#E11D48', dot: '#F43F5E', bg: '#FFF2F4', border: '#FBD3DB', chip: '#FFE0E6', tab: 'Risque' },
  upgrade: { icon: Crown, fg: '#7C3AED', dot: '#8B5CF6', bg: '#F7F2FF', border: '#E3D5FC', chip: '#EDE3FF', tab: 'Upgrade potentiel' },
};
const ORDER = ['opportunite', 'surveiller', 'risque', 'upgrade'];
const KPI_STYLE = {
  analyses: [Store, '#2F6BFF', '#EAF1FF'], croissance: [BarChart3, '#10B981', '#E7F7EE'], stable: [Clock, '#2F6BFF', '#EAF1FF'],
  baisse: [ArrowDown, '#E11D48', '#FDECEF'], upgrade: [Star, '#2F6BFF', '#EAF1FF'],
};
const PRIO = { haute: ['#FFE4E6', '#E11D48'], moyenne: ['#FFF4DB', '#D97706'] };

function InsightBadge({ type, label }) {
  const t = TYPE[type];
  const I = type === 'opportunite' ? CheckCircle2 : t.icon;
  return <span className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-md px-2 py-1 text-[12px] font-medium" style={{ background: t.chip, color: t.fg }}><I size={13} /> {label}</span>;
}

export default function InsightsPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [range, setRange] = useRange();
  const [type, setType] = useState('opportunite');
  const [sector, setSector] = useState('');
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(10);
  const [d, setD] = useState(null);
  const [err, setErr] = useState('');
  const [picked, setPicked] = useState([]);
  const [menu, setMenu] = useState(null);
  const [modal, setModal] = useState(null);
  const [busy, setBusy] = useState(false);
  const [say, toast] = useToast();
  const table = useRef(null);

  const load = useCallback(() => {
    setBusy(true);
    adminAPI.insightsBoard({ ...range, type, sector, page, per_page: perPage })
      .then(({ data }) => { setD(data); setErr(''); })
      .catch((e) => setErr(e?.response?.data?.detail || 'Impossible de charger les insights.'))
      .finally(() => setBusy(false));
  }, [range, type, sector, page, perPage]);
  useEffect(() => { load(); }, [load]);

  if (!d) return err ? <p className="rounded-xl bg-[#FEF2F2] px-4 py-3 text-[13.5px] text-[#B91C1C]">{err}</p> : <Loading />;
  const pickType = (k) => { setType(k); setPage(1); setPicked([]); };
  const openType = (k) => { pickType(k); setTimeout(() => table.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50); };
  const rows = d.rows;
  const allPicked = rows.length > 0 && rows.every((r) => picked.includes(r.id));
  const pick = (id) => setPicked((x) => (x.includes(id) ? x.filter((i) => i !== id) : [...x, id]));
  const pickAll = () => setPicked((x) => (allPicked ? x.filter((i) => !rows.some((r) => r.id === i)) : [...new Set([...x, ...rows.map((r) => r.id)])]));
  const exportCsv = () => downloadBlob(adminAPI.insightsExport(picked.length ? { ...range, ids: picked.join(',') } : { ...range, type, sector }), 'insights.csv');
  const day = (s) => new Date(`${s}T12:00:00`).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' });
  const maxSector = Math.max(1, ...d.sectors.map((s) => s.count));

  return (
    <div className="crm">
      <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <Breadcrumb items={[['Super Admin', '/admin'], ['Insights']]} />
          <h1 className="text-[28px] font-bold leading-tight tracking-[-0.01em] text-[#0B1C3F]">Insights</h1>
          <p className="text-[15px] text-[#475569]">Détectez automatiquement les opportunités, les risques et les actions à mener.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {busy && <Loader2 size={16} className="animate-spin text-[#94A3B8]" />}
          {can(user, 'insights', 'edit') && (
            <button type="button" onClick={() => setModal({ type: 'rules' })} className="inline-flex h-11 items-center gap-2 rounded-xl border border-[#DCE3EE] bg-white px-3 text-[13px] text-[#475569]"><SlidersHorizontal size={15} /> Règles des insights</button>
          )}
          <RangePicker value={range} onChange={(v) => { setRange(v); setPage(1); }} />
        </div>
      </header>

      {/* 1 — the four kinds of insight */}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {d.cards.map((c) => { const t = TYPE[c.key]; const I = t.icon; return (
          <button key={c.key} type="button" onClick={() => openType(c.key)} className="flex items-start gap-3 rounded-2xl border p-4 text-left transition hover:shadow-md" style={{ background: t.bg, borderColor: t.border }}>
            <span className="grid h-12 w-12 shrink-0 place-items-center rounded-xl" style={{ background: t.chip, color: t.fg }}><I size={24} /></span>
            <span className="min-w-0 flex-1">
              <span className="block text-[15px] font-semibold" style={{ color: t.fg }}>{c.label}</span>
              <span className="block text-[24px] font-bold leading-tight text-[#0B1C3F]">{nf(c.count)}</span>
              <span className="block text-[13px] leading-snug text-[#475569]">{c.sub}</span>
            </span>
            <ChevronRight size={20} className="mt-3 shrink-0" style={{ color: t.fg }} />
          </button>); })}
      </div>

      {/* 2 — figures */}
      <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {d.kpis.map((k) => { const [I, tone, bg] = KPI_STYLE[k.key]; return <Kpi key={k.key} icon={I} tone={tone} bg={bg} value={k.value} label={k.label} delta={k.delta} />; })}
      </div>

      {/* 3 — breakdown, trend, sectors */}
      <div className="mt-4 grid gap-4 xl:grid-cols-[1fr_1.35fr_1fr]">
        <Card>
          <Head icon={PieIcon} title="Répartition des insights" />
          <Donut rows={d.distribution} colors={ORDER.map((k) => TYPE[k].dot)} counts center={nf(d.total)} sub="insights" />
        </Card>
        <Card>
          <Head icon={LineIcon} title="Tendance du nombre d'insights" />
          <div className="mb-1 flex flex-wrap justify-center gap-4 text-[12px] text-[#475569]">
            {ORDER.map((k) => <span key={k} className="flex items-center gap-1.5"><i className="h-2 w-2 rounded-full" style={{ background: TYPE[k].dot }} />{TYPE[k].tab}</span>)}
          </div>
          <div className="h-[200px]">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={d.trend.map((x) => ({ ...x, j: day(x.day) }))} margin={{ top: 8, right: 8, left: -24, bottom: 0 }}>
                <CartesianGrid stroke="#EEF2F7" vertical={false} />
                <XAxis dataKey="j" tick={{ fontSize: 11, fill: '#64748B' }} axisLine={false} tickLine={false} minTickGap={24} />
                <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: '#64748B' }} axisLine={false} tickLine={false} />
                <Tooltip formatter={(v, k) => [v, TYPE[k]?.tab || k]} />
                {ORDER.map((k) => <Line key={k} type="monotone" dataKey={k} stroke={TYPE[k].dot} strokeWidth={2} dot={{ r: 2.5 }} />)}
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <Card>
          <Head icon={Layers} title="Top secteurs avec le plus d'insights" />
          <ul className="space-y-2.5">
            {d.sectors.map((s, i) => (
              <li key={s.label} className="grid grid-cols-[minmax(0,130px)_1fr_64px] items-center gap-2 text-[12.5px]">
                <span className="flex min-w-0 items-center gap-2 text-[#475569]"><i className="h-2 w-2 shrink-0 rounded-full" style={{ background: s.label === 'Autres' ? '#CBD5E1' : CHART[i % CHART.length] }} /><span className="truncate">{s.label}</span></span>
                <span className="h-2.5 overflow-hidden rounded-full bg-[#EEF2F8]"><span className="block h-full rounded-full" style={{ width: `${(s.count / maxSector) * 100}%`, background: s.label === 'Autres' ? '#94A3B8' : CHART[i % CHART.length] }} /></span>
                <span className="text-right text-[#64748B]">{nf(s.count)} ({s.pct}%)</span>
              </li>
            ))}
            {!d.sectors.length && <li className="text-[12.5px] text-[#94A3B8]">Aucun insight pour le moment.</li>}
          </ul>
        </Card>
      </div>

      {/* 4 — the list */}
      <div ref={table} className="scroll-mt-4">
        <Card className="mt-4">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            {ORDER.map((k) => { const t = TYPE[k]; const on = type === k; return (
              <button key={k} type="button" onClick={() => pickType(k)} className="rounded-full px-4 py-1.5 text-[13px] font-medium transition"
                      style={on ? { background: t.dot, color: '#fff' } : { background: t.bg, color: t.fg }}>{t.tab} ({nf(d.counts[k])})</button>); })}
            <span className="ml-auto flex flex-wrap items-center gap-2">
              <select value={sector} onChange={(e) => { setSector(e.target.value); setPage(1); }} className="h-10 rounded-lg border border-[#DCE3EE] bg-white px-3 text-[13px] text-[#0B1C3F]">
                <option value="">Tous les secteurs</option>{d.sector_options.map((s) => <option key={s}>{s}</option>)}
              </select>
              <button type="button" onClick={exportCsv} className="inline-flex h-10 items-center gap-1.5 rounded-lg border border-[#2F6BFF] px-3 text-[13px] font-medium text-[#2F6BFF]"><Download size={15} /> Exporter (CSV){picked.length ? ` · ${picked.length}` : ''}</button>
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1080px] text-[12.5px]">
              <thead><tr className="border-b border-[#EDF1F7] text-left text-[#64748B]">
                <th className="w-8 px-2 py-2"><input type="checkbox" aria-label="Tout sélectionner" checked={allPicked} onChange={pickAll} className="h-4 w-4 accent-[#2F6BFF]" /></th>
                {['Commerce', 'Secteur', 'Ville', 'Insight', 'Détails', 'Recommandation', 'Priorité'].map((h) => <th key={h} className="px-2 py-2 font-medium">{h}</th>)}
                <th className="w-14 px-2 py-2 text-center font-medium">Actions</th>
              </tr></thead>
              <tbody>
                {rows.map((r) => { const [pb, pf] = PRIO[r.priority] || PRIO.moyenne; return (
                  <tr key={r.id} className="border-b border-[#F4F7FC] hover:bg-[#FAFCFF]">
                    <td className="px-2 py-2"><input type="checkbox" aria-label={`Sélectionner ${r.name}`} checked={picked.includes(r.id)} onChange={() => pick(r.id)} className="h-4 w-4 accent-[#2F6BFF]" /></td>
                    <td className="px-2 py-2"><button type="button" onClick={() => navigate(`/admin/commerces/${r.tenant_id}`)} className="flex items-center gap-2.5 text-left"><CommerceLogo c={r} size={30} /><span className="font-semibold text-[#0B1C3F] hover:text-[#2F6BFF]">{r.name}</span></button></td>
                    <td className="px-2 py-2 text-[#475569]">{r.sector || '—'}</td>
                    <td className="px-2 py-2 text-[#475569]">{r.city || '—'}</td>
                    <td className="px-2 py-2"><InsightBadge type={r.type} label={r.type_label} /></td>
                    <td className="px-2 py-2 text-[#475569]">{r.details}</td>
                    <td className="px-2 py-2 text-[#475569]">{r.recommendation}</td>
                    <td className="px-2 py-2"><span className="inline-block min-w-[70px] rounded-md px-2 py-1 text-center text-[12px] font-medium" style={{ background: pb, color: pf }}>{r.priority_label}</span></td>
                    <td className="relative px-2 py-2 text-center">
                      <button type="button" aria-label={`Actions pour ${r.name}`} onClick={() => setMenu(menu === r.id ? null : r.id)} className="rounded-md p-1 text-[#2F6BFF] hover:bg-[#EAF1FF]"><MoreHorizontal size={16} /></button>
                      {menu === r.id && (
                        <>
                          <div className="fixed inset-0 z-10" onClick={() => setMenu(null)} />
                          <div className="absolute right-2 top-9 z-20 w-52 overflow-hidden rounded-xl border border-[#DCE3EE] bg-white py-1 text-left text-[12.5px] shadow-lg">
                            <button type="button" onClick={() => { setMenu(null); navigate(`/admin/commerces/${r.tenant_id}`); }} className="block w-full px-3 py-2 text-left hover:bg-[#F4F7FC]">Ouvrir la fiche du commerce</button>
                            {can(user, 'commerces') && <button type="button" onClick={() => { setMenu(null); openViewAs(r.tenant_id, say); }} className="block w-full px-3 py-2 text-left hover:bg-[#F4F7FC]">Accéder au compte</button>}
                          </div>
                        </>
                      )}
                    </td>
                  </tr>); })}
                {!rows.length && <tr><td colSpan={9} className="py-10 text-center text-[#64748B]">Aucun commerce dans « {TYPE[type].tab} » pour le moment.</td></tr>}
              </tbody>
            </table>
          </div>
          <Pager page={d.page} pages={d.pages} total={d.rows_total} perPage={perPage} what="insights" onPage={setPage} onPerPage={(n) => { setPerPage(n); setPage(1); }} />
        </Card>
      </div>

      {toast}
      {modal?.type === 'rules' && <RulesModal rules={d.rules} onClose={() => setModal(null)} onDone={() => { setModal(null); say('Règles enregistrées.'); load(); }} />}
    </div>
  );
}

function RulesModal({ rules, onClose, onDone }) {
  const [f, setF] = useState({ ...rules });
  const [err, setErr] = useState('');
  const num = (k) => ({ value: f[k], onChange: (e) => setF({ ...f, [k]: e.target.value }), className: 'h-9 w-20 rounded-lg border border-[#DCE3EE] px-2', type: 'number', min: 0 });
  const save = async () => {
    try {
      await adminAPI.saveInsightRules(Object.fromEntries(Object.entries(f).map(([k, v]) => [k, Number(v)])));
      onDone();
    } catch (e) { setErr(e?.response?.data?.detail?.[0]?.msg || e?.response?.data?.detail || 'Enregistrement impossible.'); }
  };
  const row = 'flex flex-wrap items-center gap-2';
  const tag = (k) => <span className="w-36 font-medium" style={{ color: TYPE[k].fg }}>{TYPE[k].tab === 'Opportunités' ? 'Opportunité' : TYPE[k].tab}</span>;
  return (
    <Modal title="Règles des insights" onClose={onClose}>
      <p className="mb-3 text-[13px] text-[#475569]">Chaque commerce est vérifié chaque jour avec ces règles. Les quotas sont ceux de son offre (cartes et notifications du mois).</p>
      <div className="space-y-2.5 text-[13.5px]">
        <label className={row}>{tag('opportunite')} cartes du mois ≥ <input {...num('opportunity_min')} max={100} /> % de la limite</label>
        <label className={row}>{tag('upgrade')} cartes ou notifications ≥ <input {...num('upgrade_min')} max={100} /> % du quota</label>
        <label className={row}>{tag('surveiller')} aucune notification depuis <input {...num('watch_days')} min={1} /> jours</label>
        <label className={row}>{tag('risque')} visites en baisse d'au moins <input {...num('risk_drop')} max={100} /> % sur 30 jours</label>
        <label className={`${row} pl-[152px] text-[12.5px] text-[#64748B]`}>si le commerce avait au moins <input {...num('risk_min_visits')} /> visites avant</label>
        <label className={`${row} pt-1`}><span className="w-36 text-[#475569]">Croissance / baisse</span> au-delà de ± <input {...num('growth_band')} max={100} /> % de visites</label>
      </div>
      {err && <p className="mt-2 text-[13px] text-[#C0392B]">{String(err)}</p>}
      <button type="button" onClick={save} className="mt-4 w-full rounded-lg py-2.5 text-[13.5px] font-semibold text-white" style={{ background: BLUE }}>Enregistrer</button>
    </Modal>
  );
}
