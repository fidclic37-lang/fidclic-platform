import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Users, Headphones, CalendarDays, FileText, Handshake, Upload, Plus, Target, Settings2, Zap, Mail, ListChecks,
  Phone, Flame, Search, Download, Filter, Sparkles, Send, UsersRound, CheckSquare, ChevronRight, Activity, Megaphone,
  MoreHorizontal, Loader2, ArrowUp, ArrowDown, Minus,
} from 'lucide-react';
import { crmAPI } from '../../lib/api';
import { useAuth } from '../../contexts/AuthContext';
import { Card, Head, Kpi, Donut, Bars, StageBadge, Avatar, Logo, Select, Loading, Breadcrumb, Pager, useToast, downloadBlob, Modal, nf, dayTime, ago, BLUE, STAGE_TONE, inputCls, StageSteps } from './ui';
import { ImportModal, ProspectModal, TeamModal } from './modals';
import { toneOf, SEQ_TONE } from './emailUi';
import Pilotage from './Pilotage';

/* CRM › Vue d'ensemble — laid out to the approved image (2026-09-30): pipeline first,
   the four breakdowns, « Pilotage commercial » (Pilotage.jsx), today's tasks beside the
   quick actions, then campaigns / activity / assistant. The previous layout is kept
   unrouted in CrmOverviewPageV2.jsx. Every figure is counted
   from the CRM (features/crm.py); businesses on FidClic come in on their own
   with their real stage. */

const PERIODS = [[7, '7 derniers jours'], [30, '30 derniers jours'], [90, '90 derniers jours'], [365, '12 derniers mois']];
const KPI = {
  total: [Users, '#2F6BFF', '#EAF1FF'], contact: [Headphones, '#F59E0B', '#FFF4DB'], rdv: [CalendarDays, '#9333EA', '#F3E8FF'],
  proposition: [FileText, '#2F6BFF', '#EAF1FF'], signe: [Handshake, '#10B981', '#E7F7EE'],
};
const TASK_ICON = { appel: Phone, email: Mail, relance: Send, rdv: CalendarDays, preparation: ListChecks, suivi: CheckSquare };
const PRIORITY = { haute: ['Haute', '#FFE4E6', '#E11D48', ArrowUp], moyenne: ['Moyenne', '#FFF4DB', '#D97706', Minus], basse: ['Basse', '#E7F7EE', '#0F8B58', ArrowDown] };
const ACTIVITY_DOT = { stage: '#2F6BFF', appel: '#10B981', email: '#8B5CF6', relance: '#F59E0B', rdv: '#9333EA', preparation: '#0EA5E9', suivi: '#EC4899' };

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

export default function CrmOverviewPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const admin = user?.role === 'super_admin';
  const [days, setDays] = useState(30);
  const [o, setO] = useState(null);
  const [meta, setMeta] = useState(null);
  const [seqs, setSeqs] = useState(null);
  const [pil, setPil] = useState(null);
  const [modal, setModal] = useState(null);
  const [goal, setGoal] = useState('');
  const [ask, setAsk] = useState('');
  const [err, setErr] = useState('');
  const [say, toast] = useToast();

  const load = useCallback(() => {
    const from = new Date(Date.now() - days * 86400000).toISOString();
    crmAPI.overview({ from }).then(({ data }) => setO(data)).catch((e) => setErr(e?.response?.data?.detail || 'Impossible de charger le CRM.'));
    crmAPI.meta().then(({ data }) => setMeta(data)).catch(() => {});
    crmAPI.sequences({ per_page: 3, quiet: true }).then(({ data }) => setSeqs(data.rows)).catch(() => setSeqs([]));
    crmAPI.pilotage({ from }).then(({ data }) => setPil(data)).catch(() => setPil(null));
  }, [days]);
  useEffect(() => { load(); }, [load]);
  const refresh = (m) => { if (m) say(m); load(); };

  if (!o) return err ? <p className="rounded-xl bg-[#FEF2F2] px-4 py-3 text-[13.5px] text-[#B91C1C]">{err}</p> : <Loading />;
  const total = o.cards.find((c) => c.key === 'total')?.value || 0;
  const done = async (t) => { await crmAPI.editTask(t.id, { status: 'terminee' }); refresh('Tâche terminée.'); };
  const outline = 'rounded-lg border border-[#2F6BFF] px-2.5 py-1 text-[12px] text-[#2F6BFF]';

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

      {/* 1 — pipeline (full width: each step opens the list on that stage) */}
      <Card>
        <Head icon={Target} title="Pipeline de prospection" right={<button type="button" onClick={() => navigate('/admin/crm/pipeline')} className="rounded-lg border border-[#2F6BFF] px-3 py-1.5 text-[12.5px] font-medium text-[#2F6BFF]">Ouvrir le pipeline</button>} />
        <StageSteps showPct steps={o.funnel.map((s, i) => ({ ...s, value: i ? s.key : '' }))}
                    onPick={(s) => navigate(s.value ? `/admin/crm/prospects?stage=${s.value}` : '/admin/crm/prospects')} />
      </Card>

      {/* 2 — sources, sectors, cities, monthly goal */}
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

      {/* 3 — pilotage commercial: what needs attention, the team, the pipeline's health */}
      <Pilotage data={pil} meta={meta} onTask={(t) => setModal({ type: 'task', task: t })} onNewTask={(pid) => setModal({ type: 'task', prospectId: pid })} onDone={refresh} />

      {/* 4 — today's tasks + quick actions */}
      <div className="mt-4 grid gap-4 xl:grid-cols-[1.9fr_1fr]">
        <Card>
          <Head icon={CheckSquare} title="Tâches du jour" right={<button type="button" onClick={() => navigate('/admin/crm/taches')} className={outline}>Voir tout</button>} />
          <div className="overflow-x-auto">
            <table className="w-full min-w-[680px] text-[12.5px]">
              <thead><tr className="border-b border-[#EDF1F7] text-left text-[#64748B]">
                <th className="w-7 px-2 py-2" />
                {['Tâche', 'Commerce', 'Type', 'Priorité', 'Échéance', 'Assigné à'].map((h) => <th key={h} className="px-2 py-2 font-medium">{h}</th>)}
                <th className="w-8 px-2 py-2" />
              </tr></thead>
              <tbody>
                {o.today_tasks.map((t) => {
                  const I = TASK_ICON[t.type] || CheckSquare;
                  const [pl, pb, pf, PI] = PRIORITY[t.priority] || PRIORITY.moyenne;
                  const [db, dfg] = t.status === 'terminee' ? ['#F1F5F9', '#64748B'] : t.status === 'en_retard' ? ['#FEE2E2', '#B91C1C'] : ['#FFF1F2', '#E11D48'];
                  const time = new Date(t.due_at).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
                  return (
                    <tr key={t.id} className={`border-b border-[#F4F7FC] ${t.status === 'terminee' ? 'opacity-60' : ''}`}>
                      <td className="px-2 py-2"><input type="checkbox" aria-label="Terminer la tâche" checked={t.status === 'terminee'} disabled={t.status === 'terminee'} onChange={() => done(t)} className="h-4 w-4 accent-[#2F6BFF]" /></td>
                      <td className="px-2 py-2"><span className="flex items-center gap-2"><I size={15} className="shrink-0 text-[#2F6BFF]" /><span className={`text-[#0B1C3F] ${t.status === 'terminee' ? 'line-through' : ''}`}>{t.title}{t.prospect ? ` — ${t.prospect}` : ''}</span></span></td>
                      <td className="px-2 py-2 text-[#475569]">{t.prospect || '—'}</td>
                      <td className="px-2 py-2 text-[#475569]">{t.type_label}</td>
                      <td className="px-2 py-2"><span className="inline-flex items-center gap-1 whitespace-nowrap rounded-md px-2 py-1 text-[11.5px] font-medium" style={{ background: pb, color: pf }}><PI size={12} /> {pl}</span></td>
                      <td className="px-2 py-2"><span className="whitespace-nowrap rounded-md px-2 py-1 text-[11.5px] font-medium" style={{ background: db, color: dfg }}>{t.status === 'en_retard' ? 'En retard' : "Aujourd'hui"} {time}</span></td>
                      <td className="px-2 py-2"><Avatar name={t.assigned_name} /></td>
                      <td className="px-2 py-2 text-center"><button type="button" aria-label="Modifier la tâche" onClick={() => setModal({ type: 'task', task: t })} className="rounded-md p-1 text-[#2F6BFF] hover:bg-[#EAF1FF]"><MoreHorizontal size={16} /></button></td>
                    </tr>);
                })}
                {!o.today_tasks.length && <tr><td colSpan={8} className="py-6 text-center text-[#64748B]">Rien de prévu aujourd'hui.</td></tr>}
              </tbody>
            </table>
          </div>
          <button type="button" onClick={() => setModal({ type: 'task' })} className="mt-3 w-full rounded-lg border border-dashed border-[#C9D6EA] py-2 text-[12.5px] text-[#2F6BFF]">+ Nouvelle tâche</button>
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

      {/* 5 — campaigns, recent activity, assistant */}
      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <Card>
          <Head icon={Megaphone} title="Campagnes de prospection" sub="Les séquences d'emails personnalisées." right={<button type="button" onClick={() => navigate('/admin/crm/sequences')} className={outline}>Voir toutes</button>} />
          <ul className="space-y-3">
            {!seqs && <li key="loading" className="py-3 text-center text-[12.5px] text-[#64748B]"><Loader2 size={14} className="mr-1 inline animate-spin" /> Chargement…</li>}
            {seqs?.map((s) => { const [bg, fg] = toneOf(s.name); const [sb, sf] = SEQ_TONE[s.status] || SEQ_TONE.brouillon; return (
              <li key={s.id}>
                <button type="button" onClick={() => navigate('/admin/crm/sequences')} className="grid w-full grid-cols-[34px_1fr_auto_48px_40px] items-center gap-2.5 text-left">
                  <span className="grid h-[34px] w-[34px] place-items-center rounded-lg" style={{ background: bg, color: fg }}><Mail size={16} /></span>
                  <span className="min-w-0"><span className="line-clamp-2 text-[12.5px] font-semibold leading-snug text-[#0B1C3F]">{s.name}</span><span className="text-[11.5px] text-[#64748B]">{nf(s.prospects)} prospect{s.prospects > 1 ? 's' : ''}</span></span>
                  <span className="whitespace-nowrap rounded-md px-2 py-0.5 text-[11px] font-medium" style={{ background: sb, color: sf }}>{s.status_label}</span>
                  <span><strong className="block text-[13px] text-[#0B1C3F]">{s.sent ? `${s.open_rate}%` : '—'}</strong><span className="text-[10.5px] text-[#94A3B8]">Ouverture</span></span>
                  <span><strong className="block text-[13px] text-[#0B1C3F]">{s.sent ? `${s.click_rate}%` : '—'}</strong><span className="text-[10.5px] text-[#94A3B8]">Clics</span></span>
                </button>
              </li>); })}
            {seqs && !seqs.length && (
              <li className="rounded-xl bg-[#F4F7FC] px-3 py-4 text-[12.5px] text-[#475569]">Aucune séquence pour le moment. <button type="button" onClick={() => navigate('/admin/crm/sequences')} className="font-medium text-[#2F6BFF]">Créer une séquence</button></li>
            )}
          </ul>
        </Card>
        <Card>
          <Head icon={Activity} title="Activité récente" />
          <ul className="space-y-2">
            {o.activity.map((a, i) => (
              <li key={i} className="grid grid-cols-[10px_1fr_auto] items-center gap-2 text-[12.5px]">
                <span className="h-2 w-2 rounded-full" style={{ background: ACTIVITY_DOT[a.type] || '#94A3B8' }} />
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
      {modal?.type === 'task' && <TaskModal meta={meta} task={modal.task} prospectId={modal.prospectId} onClose={() => setModal(null)} onSaved={() => { setModal(null); refresh(modal.task ? 'Tâche modifiée.' : 'Tâche créée.'); }} />}
    </div>
  );
}

export function TaskModal({ meta, prospectId, task, preset, onClose, onSaved }) {
  const soon = new Date(Date.now() + 3600000); soon.setMinutes(0, 0, 0);
  const local = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  const base = task || preset || {};
  const [f, setF] = useState({ title: base.title || '', type: base.type || 'appel', priority: base.priority || 'moyenne',
                               due: base.due_at ? local(new Date(base.due_at)) : local(soon), prospect_id: base.prospect_id || prospectId || '',
                               prospectName: base.prospect || '', assigned_to: base.assigned_to || '', description: base.description || '',
                               duration_min: base.duration_min || 30, confirm_status: base.confirm_status || 'a_confirmer' });
  const [q, setQ] = useState('');
  const [found, setFound] = useState([]);
  const [err, setErr] = useState('');
  useEffect(() => {
    if (prospectId || q.length < 2) { setFound([]); return; }
    crmAPI.prospects({ q, per_page: 6 }).then(({ data }) => setFound(data.rows)).catch(() => {});
  }, [q, prospectId]);
  const save = async () => {
    setErr('');
    const body = { title: f.title, type: f.type, priority: f.priority, due_at: new Date(f.due).toISOString(),
                   prospect_id: f.prospect_id || null, description: f.description, duration_min: Number(f.duration_min) || 30,
                   confirm_status: f.confirm_status, ...(f.assigned_to ? { assigned_to: f.assigned_to } : {}) };
    try { if (task?.id) await crmAPI.editTask(task.id, body); else await crmAPI.addTask(body); onSaved(); }
    catch (e) { setErr(e?.response?.data?.detail || 'Enregistrement impossible.'); }
  };
  return (
    <Modal title={task?.id ? 'Modifier la tâche' : 'Nouvelle tâche'} onClose={onClose}>
      <div className="grid gap-3 sm:grid-cols-2">
        <input className={`${inputCls} sm:col-span-2`} placeholder="Ex. Appeler le commerce" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} />
        <Select label="Type" value={f.type} onChange={(v) => setF({ ...f, type: v })}>{(meta?.task_types || []).map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}</Select>
        <Select label="Priorité" value={f.priority} onChange={(v) => setF({ ...f, priority: v })}><option value="haute">Haute</option><option value="moyenne">Moyenne</option><option value="basse">Basse</option></Select>
        <label className="block"><span className="mb-1 block text-[11.5px] text-[#64748B]">Échéance</span><input type="datetime-local" className={inputCls} value={f.due} onChange={(e) => setF({ ...f, due: e.target.value })} /></label>
        <Select label="Durée" value={f.duration_min} onChange={(v) => setF({ ...f, duration_min: v })}>
          {[15, 30, 45, 60, 90, 120].map((m) => <option key={m} value={m}>{m < 60 ? `${m} min` : `${m / 60} h${m % 60 ? ' 30' : ''}`}</option>)}
        </Select>
        <Select label="Statut du rendez-vous" value={f.confirm_status} onChange={(v) => setF({ ...f, confirm_status: v })}>
          <option value="a_confirmer">À confirmer</option><option value="confirme">Confirmé</option><option value="annule">Annulé</option>
        </Select>
        <Select label="Assigné à" value={f.assigned_to} onChange={(v) => setF({ ...f, assigned_to: v })}><option value="">Moi</option>{(meta?.users || []).filter((u) => u.active).map((u) => <option key={u.email} value={u.email}>{u.name}</option>)}</Select>
        {!prospectId && (
          <div className="sm:col-span-2">
            <span className="mb-1 block text-[11.5px] text-[#64748B]">Commerce (facultatif)</span>
            {f.prospect_id ? <p className="flex items-center justify-between rounded-lg bg-[#F4F7FC] px-3 py-2 text-[13px]">{f.prospectName || 'Commerce choisi'}<button type="button" className="text-[12px] text-[#2F6BFF]" onClick={() => setF({ ...f, prospect_id: '' })}>Changer</button></p> : (
              <>
                <input className={inputCls} placeholder="Chercher un commerce…" value={q} onChange={(e) => setQ(e.target.value)} />
                {found.map((p) => <button key={p.id} type="button" onClick={() => { setF({ ...f, prospect_id: p.id, prospectName: p.name }); setQ(''); }} className="block w-full px-2 py-1.5 text-left text-[13px] hover:bg-[#F4F7FC]">{p.name} <span className="text-[#94A3B8]">{p.city}</span></button>)}
              </>
            )}
          </div>
        )}
        <textarea className={`${inputCls} h-20 py-2 sm:col-span-2`} placeholder="Description" value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} />
      </div>
      {err && <p className="mt-2 text-[13px] text-[#C0392B]">{err}</p>}
      <button type="button" disabled={!f.title.trim()} onClick={save} className="mt-4 w-full rounded-lg py-2.5 text-[13.5px] font-semibold text-white disabled:opacity-50" style={{ background: BLUE }}>Enregistrer</button>
    </Modal>
  );
}
