import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Users, Headphones, CalendarDays, FileText, Handshake, Upload, Plus, Target, Settings2, Zap, Mail, ListChecks,
  Phone, Flame, Search, Download, Filter, Sparkles, Send, UsersRound, CheckSquare, ChevronRight, Activity, Megaphone,
  MoreHorizontal, Loader2,
} from 'lucide-react';
import { crmAPI } from '../../lib/api';
import { useAuth } from '../../contexts/AuthContext';
import { Card, Head, Kpi, Donut, Bars, StageBadge, Avatar, Logo, Select, Loading, Breadcrumb, Pager, useToast, downloadBlob, Modal, nf, dayTime, ago, BLUE, STAGE_TONE, inputCls, StageSteps } from './ui';
import { ImportModal, ProspectModal, TeamModal } from './modals';
import { TaskModal } from './CrmOverviewPage';

/* ROLLBACK COPY — the CRM overview's layout before the 2026-09-30 re-arrangement
   (unrouted; see the commented import in App.jsx). Built to the approved mockup. Every figure is counted
   from the CRM (features/crm.py); businesses on FidClic come in on their own
   with their real stage. */

const PERIODS = [[7, '7 derniers jours'], [30, '30 derniers jours'], [90, '90 derniers jours'], [365, '12 derniers mois']];
const KPI = {
  total: [Users, '#2F6BFF', '#EAF1FF'], contact: [Headphones, '#F59E0B', '#FFF4DB'], rdv: [CalendarDays, '#9333EA', '#F3E8FF'],
  proposition: [FileText, '#2F6BFF', '#EAF1FF'], signe: [Handshake, '#10B981', '#E7F7EE'],
};
const TASK_ICON = { appel: Phone, email: Mail, relance: Send, rdv: CalendarDays, preparation: ListChecks, suivi: CheckSquare };

function Ring({ pct }) {
  const p = Math.max(0, Math.min(100, pct || 0));
  return (
    <svg width="84" height="84" viewBox="0 0 36 36" className="shrink-0">
      <circle cx="18" cy="18" r="15.5" fill="none" stroke="#E7F7EE" strokeWidth="3.5" />
      <circle cx="18" cy="18" r="15.5" fill="none" stroke="#10B981" strokeWidth="3.5" strokeDasharray={`${p} 100`} pathLength="100"
              strokeLinecap="round" transform="rotate(-90 18 18)" />
      <text x="18" y="20.5" textAnchor="middle" fontSize="7.5" fontWeight="700" fill="#0B1C3F">{pct === null || pct === undefined ? '—' : `${pct}%`}</text>
    </svg>
  );
}

export default function CrmOverviewPageV1() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const admin = user?.role === 'super_admin';
  const [days, setDays] = useState(30);
  const [o, setO] = useState(null);
  const [meta, setMeta] = useState(null);
  const [list, setList] = useState(null);
  const [filters, setFilters] = useState({ q: '', sector: '', city: '', stage: '', assigned: '' });
  const [page, setPage] = useState(1);
  const [modal, setModal] = useState(null);
  const [goal, setGoal] = useState('');
  const [ask, setAsk] = useState('');
  const [err, setErr] = useState('');
  const [say, toast] = useToast();

  const load = useCallback(() => {
    const from = new Date(Date.now() - days * 86400000).toISOString();
    crmAPI.overview({ from }).then(({ data }) => setO(data)).catch((e) => setErr(e?.response?.data?.detail || 'Impossible de charger le CRM.'));
    crmAPI.meta().then(({ data }) => setMeta(data)).catch(() => {});
  }, [days]);
  const loadList = useCallback(() => {
    crmAPI.prospects({ ...filters, page, per_page: 6 }).then(({ data }) => setList(data)).catch(() => setList({ rows: [], total: 0, pages: 1 }));
  }, [filters, page]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { loadList(); }, [loadList]);
  const refresh = (m) => { if (m) say(m); load(); loadList(); };

  if (!o) return err ? <p className="rounded-xl bg-[#FEF2F2] px-4 py-3 text-[13.5px] text-[#B91C1C]">{err}</p> : <Loading />;
  const total = o.cards.find((c) => c.key === 'total')?.value || 0;
  const done = async (t) => { await crmAPI.editTask(t.id, { status: 'terminee' }); refresh('Tâche terminée.'); };

  return (
    <div className="crm">
      <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <Breadcrumb items={[['Super Admin', admin ? '/admin' : null], ['CRM de prospection']]} />
          <h1 className="text-[28px] font-bold leading-tight tracking-[-0.01em] text-[#0B1C3F]">Machine de prospection & suivi</h1>
          <p className="text-[15px] text-[#475569]">Trouvez, contactez, suivez et transformez plus de commerces en clients FIDCLIC.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Select value={days} onChange={(v) => setDays(Number(v))} className="w-48">
            {PERIODS.map(([d, l]) => <option key={d} value={d}>{l}</option>)}
          </Select>
          <button type="button" onClick={() => setModal({ type: 'import' })} className="inline-flex h-10 items-center gap-2 rounded-xl border border-[#2F6BFF] bg-white px-4 text-[13.5px] font-medium text-[#2F6BFF]"><Upload size={16} /> Importer des commerces</button>
          <button type="button" onClick={() => setModal({ type: 'add' })} className="inline-flex h-10 items-center gap-2 rounded-xl px-4 text-[13.5px] font-medium text-white" style={{ background: BLUE }}><Plus size={16} /> Ajouter un prospect</button>
        </div>
      </header>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {o.cards.map((c) => { const [I, t, b] = KPI[c.key]; return <Kpi key={c.key} icon={I} tone={t} bg={b} value={c.value} label={c.label} delta={c.delta} series={c.series} />; })}
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[1.25fr_1fr_1fr_1fr]">
        <Card><Head icon={Target} title="Sources de prospection" /><Donut rows={o.sources} center={nf(total)} sub="prospects" /></Card>
        <Card><Head icon={Target} title="Répartition par secteur" /><Bars rows={o.sectors} /></Card>
        <Card><Head icon={Target} title="Répartition par ville" /><Bars rows={o.cities} /></Card>
        <Card>
          <Head icon={Target} title="Objectifs du mois" right={admin && <button type="button" aria-label="Régler l'objectif" onClick={() => { setGoal(String(o.goal.target || '')); setModal({ type: 'goal' }); }} className="text-[#2F6BFF]"><Settings2 size={16} /></button>} />
          <div className="flex items-center gap-4">
            <Ring pct={o.goal.pct} />
            <div><p className="text-[24px] font-bold text-[#0B1C3F]">{nf(o.goal.signed)} / {o.goal.target ? nf(o.goal.target) : '—'}</p><p className="text-[13px] text-[#64748B]">clients signés</p></div>
          </div>
          <p className="mt-3 text-[12px] text-[#64748B]">{o.goal.target ? `Objectif : ${nf(o.goal.target)} nouveaux clients` : 'Aucun objectif fixé pour ce mois.'}</p>
          <div className="mt-1 h-2 overflow-hidden rounded-full bg-[#EEF2F8]"><div className="h-full rounded-full bg-[#2F6BFF]" style={{ width: `${Math.min(100, o.goal.pct || 0)}%` }} /></div>
          <div className="mt-3 grid grid-cols-2 gap-2 text-[12.5px]">
            <p className="flex items-center gap-2"><FileText size={16} className="text-[#2F6BFF]" /><span><strong className="text-[#0B1C3F]">{nf(o.goal.propositions)}</strong> propositions</span></p>
            <p className="flex items-center gap-2"><CalendarDays size={16} className="text-[#9333EA]" /><span><strong className="text-[#0B1C3F]">{nf(o.goal.rdv)}</strong> rendez-vous</span></p>
          </div>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[1fr_300px]">
        <Card>
          <Head icon={Target} title="Pipeline de prospection" right={<button type="button" onClick={() => navigate('/admin/crm/pipeline')} className="rounded-lg border border-[#2F6BFF] px-3 py-1.5 text-[12.5px] font-medium text-[#2F6BFF]">Ouvrir le pipeline</button>} />
          <StageSteps showPct steps={o.funnel.map((s, i) => ({ ...s, value: i ? s.key : '' }))}
                      onPick={(s) => navigate(s.value ? `/admin/crm/prospects?stage=${s.value}` : '/admin/crm/prospects')} />
        </Card>
        <Card>
          <Head icon={Zap} title="Actions rapides" />
          <div className="space-y-2">
            {[[Upload, 'Importer une liste (CSV, PDF…)', () => setModal({ type: 'import' })],
              [Mail, "Lancer une séquence d'emails", () => navigate('/admin/crm/sequences')],
              [ListChecks, 'Créer une tâche de suivi', () => setModal({ type: 'task' })],
              [Phone, 'Planifier des appels', () => navigate('/admin/crm/appels')],
              [Flame, 'Voir les opportunités chaudes', () => navigate('/admin/crm/prospects?stage=proposition')],
              ...(admin ? [[UsersRound, 'Équipe commerciale', () => setModal({ type: 'team' })]] : []),
            ].map(([I, label, fn]) => (
              <button key={label} type="button" onClick={fn} className={`flex w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-left text-[13px] ${label.startsWith('Voir les opp') ? 'border-[#FECDD3] bg-[#FFF5F6] text-[#0B1C3F]' : 'border-[#DCE3EE] text-[#0B1C3F] hover:border-[#2F6BFF]'}`}>
                <I size={17} className={label.startsWith('Voir les opp') ? 'text-[#E11D48]' : 'text-[#2F6BFF]'} /><span className="flex-1">{label}</span><ChevronRight size={15} className="text-[#94A3B8]" />
              </button>
            ))}
          </div>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[1fr_300px]">
        <Card>
          <Head icon={Users} title="Liste des prospects" right={(
            <button type="button" onClick={() => downloadBlob(crmAPI.exportCsv(filters), 'prospects.csv')} className="inline-flex items-center gap-1.5 rounded-lg border border-[#2F6BFF] px-3 py-1.5 text-[12.5px] font-medium text-[#2F6BFF]"><Download size={14} /> Exporter</button>
          )} />
          <div className="mb-3 grid gap-2 md:grid-cols-[1.6fr_1fr_1fr_1fr_1fr_auto] md:items-end">
            <label className="relative"><Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
              <input className={`${inputCls} pl-9`} placeholder="Rechercher un commerce, un contact, une ville…" value={filters.q}
                     onChange={(e) => { setPage(1); setFilters({ ...filters, q: e.target.value }); }} /></label>
            <Select label="Secteur" value={filters.sector} onChange={(v) => { setPage(1); setFilters({ ...filters, sector: v }); }}><option value="">Tous</option>{(meta?.sectors || []).map((s) => <option key={s}>{s}</option>)}</Select>
            <Select label="Ville" value={filters.city} onChange={(v) => { setPage(1); setFilters({ ...filters, city: v }); }}><option value="">Toutes</option>{(meta?.cities || []).map((s) => <option key={s}>{s}</option>)}</Select>
            <Select label="Statut" value={filters.stage} onChange={(v) => { setPage(1); setFilters({ ...filters, stage: v }); }}><option value="">Tous</option>{(meta?.stages || []).map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}</Select>
            <Select label="Assigné à" value={filters.assigned} onChange={(v) => { setPage(1); setFilters({ ...filters, assigned: v }); }}><option value="">Tous</option><option value="none">Personne</option>{(meta?.users || []).map((u) => <option key={u.email} value={u.email}>{u.name}</option>)}</Select>
            <button type="button" onClick={() => navigate('/admin/crm/prospects')} className="inline-flex h-10 items-center gap-1.5 rounded-lg border border-[#2F6BFF] px-3 text-[12.5px] font-medium text-[#2F6BFF]"><Filter size={14} /> Filtres</button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[980px] text-[12.5px]">
              <thead><tr className="border-b border-[#EDF1F7] text-left text-[#64748B]">
                {['Nom du commerce', 'Secteur', 'Ville', 'Contact', 'Téléphone', 'Statut', 'Dernière action', 'Prochaine action', 'Assigné à'].map((h) => <th key={h} className="px-2 py-2 font-medium">{h}</th>)}</tr></thead>
              <tbody>
                {!list && <tr key="loading"><td colSpan={9} className="py-8 text-center text-[#64748B]"><Loader2 size={15} className="mr-1 inline animate-spin" /> Chargement…</td></tr>}
                {list?.rows.map((p) => (
                  <tr key={p.id} onClick={() => navigate(`/admin/crm/prospects?open=${p.id}`)} className="cursor-pointer border-b border-[#F4F7FC] hover:bg-[#FAFCFF]">
                    <td className="px-2 py-2"><span className="flex items-center gap-2.5"><Logo name={p.name} size={30} /><span className="font-semibold text-[#0B1C3F]">{p.name}</span></span></td>
                    <td className="px-2 py-2 text-[#475569]">{p.sector || '—'}</td>
                    <td className="px-2 py-2 text-[#475569]">{p.city || '—'}</td>
                    <td className="px-2 py-2 text-[#475569]">{p.contact_name || '—'}</td>
                    <td className="px-2 py-2 text-[#475569]">{p.phone || '—'}</td>
                    <td className="px-2 py-2"><StageBadge stage={p.stage} label={p.stage_label} /></td>
                    <td className="px-2 py-2 text-[#475569]">{p.last_action ? <>{p.last_action.label}<br /><span className="text-[11px] text-[#94A3B8]">{new Date(p.last_action.at).toLocaleDateString('fr-FR')}</span></> : '—'}</td>
                    <td className="px-2 py-2 text-[#475569]">{p.next_action ? <>{p.next_action.label}<br /><span className="text-[11px] text-[#94A3B8]">{new Date(p.next_action.due_at).toLocaleDateString('fr-FR')}</span></> : '—'}</td>
                    <td className="px-2 py-2"><Avatar name={p.assigned_name} /></td>
                  </tr>
                ))}
                {list && !list.rows.length && <tr><td colSpan={9} className="py-10 text-center text-[#64748B]">Aucun prospect. Importez une liste ou ajoutez-en un.</td></tr>}
              </tbody>
            </table>
          </div>
          {list && <Pager page={page} pages={list.pages} total={list.total} perPage={6} onPage={setPage} />}
        </Card>
        <Card>
          <Head icon={CheckSquare} title="Tâches du jour" right={<button type="button" onClick={() => navigate('/admin/crm/taches')} className="rounded-lg border border-[#2F6BFF] px-2.5 py-1 text-[12px] text-[#2F6BFF]">Voir tout</button>} />
          <ul className="space-y-1">
            {o.today_tasks.map((t) => { const I = TASK_ICON[t.type] || CheckSquare; return (
              <li key={t.id} className="flex items-center gap-2.5 py-1.5">
                <input type="checkbox" checked={t.status === 'terminee'} onChange={() => done(t)} className="h-4 w-4 accent-[#2F6BFF]" />
                <I size={15} className="shrink-0 text-[#2F6BFF]" />
                <span className="min-w-0 flex-1 truncate text-[12.5px] text-[#0B1C3F]">{t.title}{t.prospect ? ` — ${t.prospect}` : ''}</span>
                <span className="text-[12px] text-[#64748B]">{new Date(t.due_at).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}</span>
              </li>); })}
            {!o.today_tasks.length && <li className="py-4 text-[12.5px] text-[#64748B]">Rien de prévu aujourd'hui.</li>}
          </ul>
          <button type="button" onClick={() => setModal({ type: 'task' })} className="mt-2 w-full rounded-lg border border-dashed border-[#C9D6EA] py-2 text-[12.5px] text-[#2F6BFF]">+ Nouvelle tâche</button>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <Card>
          <Head icon={Megaphone} title="Campagnes de prospection" sub="Les séquences d'emails personnalisées." right={<button type="button" onClick={() => navigate('/admin/crm/sequences')} className="rounded-lg border border-[#2F6BFF] px-2.5 py-1 text-[12px] text-[#2F6BFF]">Voir toutes</button>} />
          <p className="rounded-xl bg-[#F4F7FC] px-3 py-4 text-[12.5px] text-[#475569]">Les séquences d'emails arrivent avec la page « Séquences d'emails » : envoi depuis votre Gmail, ouvertures et réponses suivies.</p>
        </Card>
        <Card>
          <Head icon={Activity} title="Activité récente" />
          <ul className="space-y-2">
            {o.activity.map((a, i) => (
              <li key={i} className="grid grid-cols-[1fr_auto] gap-2 text-[12.5px]">
                <span className="truncate text-[#0B1C3F]">{a.text}{a.prospect ? ` — ${a.prospect}` : ''}</span>
                <span className="text-[11.5px] text-[#94A3B8]">{ago(a.at)} · {a.by}</span>
              </li>
            ))}
            {!o.activity.length && <li className="text-[12.5px] text-[#64748B]">Aucune activité pour le moment.</li>}
          </ul>
        </Card>
        <Card>
          <Head icon={Sparkles} title="FIDCLIC — Assistant de prospection" sub="Retrouvez vos prospects en une question." />
          <form onSubmit={(e) => { e.preventDefault(); if (ask.trim()) navigate(`/admin/crm/prospects?q=${encodeURIComponent(ask.trim())}`); }} className="flex gap-2">
            <input className={inputCls} placeholder="Chercher : « barbier Tours », « Karim »…" value={ask} onChange={(e) => setAsk(e.target.value)} />
            <button type="submit" className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-white" style={{ background: BLUE }} aria-label="Chercher"><Send size={16} /></button>
          </form>
          <div className="mt-3 flex flex-wrap gap-2">
            {[['Prospects les plus chauds', '?stage=proposition'], ['Rendez-vous à tenir', '?stage=rdv'], ['À contacter', '?stage=a_contacter'], ['Sans commercial', '?assigned=none']].map(([l, q]) => (
              <button key={l} type="button" onClick={() => navigate(`/admin/crm/prospects${q}`)} className="rounded-lg border border-[#DCE3EE] px-2.5 py-1.5 text-[12px] text-[#2F6BFF] hover:border-[#2F6BFF]">{l}</button>
            ))}
          </div>
        </Card>
      </div>

      {toast}
      {modal?.type === 'import' && <ImportModal meta={meta} onClose={() => setModal(null)} onDone={(m) => { setModal(null); refresh(m); }} />}
      {modal?.type === 'add' && <ProspectModal meta={meta} onClose={() => setModal(null)} onSaved={(_, m) => { setModal(null); refresh(m); }} />}
      {modal?.type === 'team' && <TeamModal onClose={() => setModal(null)} onChanged={load} />}
      {modal?.type === 'goal' && (
        <Modal title="Objectif du mois" onClose={() => setModal(null)}>
          <label className="block text-[13px]">Nombre de nouveaux clients à signer ce mois-ci
            <input type="number" min={0} className={`${inputCls} mt-1`} value={goal} onChange={(e) => setGoal(e.target.value)} /></label>
          <button type="button" onClick={async () => { await crmAPI.setGoal(Number(goal) || 0); setModal(null); refresh('Objectif enregistré.'); }}
                  className="mt-3 w-full rounded-lg py-2.5 text-[13.5px] font-semibold text-white" style={{ background: BLUE }}>Enregistrer</button>
        </Modal>
      )}
      {modal?.type === 'task' && <TaskModal meta={meta} onClose={() => setModal(null)} onSaved={() => { setModal(null); refresh('Tâche créée.'); }} />}
    </div>
  );
}
