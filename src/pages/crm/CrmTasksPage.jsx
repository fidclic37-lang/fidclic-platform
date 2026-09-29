import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  CheckSquare, Clock, Check, XCircle, FileText, Plus, ChevronDown, Search, SlidersHorizontal, Phone, Mail, Send, CalendarDays,
  ListChecks, Target, MoreHorizontal, User, Pencil, Copy, Trash2, Loader2, Building2, ExternalLink,
} from 'lucide-react';
import { crmAPI } from '../../lib/api';
import { useAuth } from '../../contexts/AuthContext';
import { Card, Head, Kpi, Donut, Bars, Avatar, Logo, Select, Loading, Breadcrumb, Pager, useToast, Modal, nf, dayTime, BLUE, inputCls } from './ui';
import { TaskModal } from './CrmOverviewPage';

/* CRM › Tâches — built to the approved mockup. */

const TYPE_ICON = { appel: Phone, email: Mail, relance: Send, rdv: CalendarDays, proposition: FileText, preparation: ListChecks, suivi: CheckSquare };
const PRIO = { haute: ['#FDECEF', '#E11D48', 'Haute'], moyenne: ['#FFF4DB', '#D97706', 'Moyenne'], basse: ['#E7F7EE', '#0F8B58', 'Basse'] };
const STATUS = { a_faire: ['#FDECEF', '#E11D48', 'À faire'], en_cours: ['#EAF1FF', '#2F6BFF', 'En cours'], terminee: ['#E7F7EE', '#0F8B58', 'Terminée'], en_retard: ['#FDECEF', '#B91C1C', 'En retard'] };
const Pill = ({ tone }) => <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-md px-2 py-1 text-[12px] font-medium" style={{ background: tone[0], color: tone[1] }}>{tone[2]}</span>;
const TABS = [['', 'Toutes les tâches', 'all'], ['a_faire', 'À faire', 'a_faire'], ['en_cours', 'En cours', 'en_cours'], ['terminee', 'Terminées', 'terminee'], ['en_retard', 'En retard', 'en_retard']];

export default function CrmTasksPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const admin = user?.role === 'super_admin';
  const [meta, setMeta] = useState(null);
  const [sum, setSum] = useState(null);
  const [list, setList] = useState(null);
  const [status, setStatus] = useState('');
  const [f, setF] = useState({ q: '', assigned: '', priority: '', type: '', when: '' });
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(10);
  const [sel, setSel] = useState(null);
  const [modal, setModal] = useState(null);
  const [menu, setMenu] = useState(false);
  const [rowMenu, setRowMenu] = useState(null);
  const [say, toast] = useToast();

  const range = () => {
    const d0 = new Date(); d0.setHours(0, 0, 0, 0);
    if (f.when === 'today') return { from: d0.toISOString(), to: new Date(d0.getTime() + 86400000).toISOString() };
    if (f.when === 'week') return { from: d0.toISOString(), to: new Date(d0.getTime() + 7 * 86400000).toISOString() };
    if (f.when === 'past') return { to: d0.toISOString() };
    return {};
  };
  const loadAll = useCallback(() => {
    crmAPI.tasksSummary().then(({ data }) => setSum(data)).catch(() => {});
    crmAPI.tasks({ ...f, ...range(), status, page, per_page: perPage }).then(({ data }) => {
      setList(data); setSel((s) => (s && data.rows.find((r) => r.id === s.id)) || data.rows[0] || null);
    }).catch(() => setList({ rows: [], total: 0, counts: {}, pages: 1 }));
  }, [f, status, page, perPage]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { loadAll(); }, [loadAll]);
  useEffect(() => { crmAPI.meta().then(({ data }) => setMeta(data)).catch(() => {}); }, []);
  const act = async (fn, m) => { try { await fn(); say(m); loadAll(); } catch (e) { say(e?.response?.data?.detail || 'Action impossible.'); } };
  const setFilter = (k) => (v) => { setPage(1); setF({ ...f, [k]: v }); };

  if (!sum || !list) return <Loading />;
  const K = Object.fromEntries(sum.cards.map((c) => [c.key, c]));
  const t = sel;
  return (
    <div className="crm" onClick={() => { setMenu(false); setRowMenu(null); }}>
      <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <Breadcrumb items={[['Super Admin', admin ? '/admin' : null], ['CRM de prospection', '/admin/crm'], ['Tâches']]} />
          <h1 className="text-[28px] font-bold leading-tight text-[#0B1C3F]">Tâches</h1>
          <p className="text-[15px] text-[#475569]">Organisez et suivez toutes vos actions de prospection pour transformer plus de commerces en clients.</p>
        </div>
        <div className="flex gap-2">
          <button type="button" onClick={() => setModal({ type: 'templates' })} className="inline-flex h-10 items-center gap-2 rounded-xl border border-[#2F6BFF] bg-white px-4 text-[13.5px] font-medium text-[#2F6BFF]"><FileText size={16} /> Modèles de tâches</button>
          <span className="relative" onClick={(e) => e.stopPropagation()}>
            <button type="button" onClick={() => setMenu((v) => !v)} className="inline-flex h-10 items-center gap-2 rounded-xl px-4 text-[13.5px] font-medium text-white" style={{ background: BLUE }}><Plus size={16} /> Nouvelle tâche <ChevronDown size={15} /></button>
            {menu && (
              <span className="absolute right-0 top-full z-30 mt-1 flex w-64 flex-col overflow-hidden rounded-xl border border-[#E6EEFB] bg-white py-1 shadow-[0_24px_60px_-28px_rgba(11,28,63,.5)]">
                <button type="button" onClick={() => { setMenu(false); setModal({ type: 'task' }); }} className="px-3.5 py-2 text-left text-[13px] font-semibold text-[#2F6BFF] hover:bg-[#F4F7FC]">Tâche vierge</button>
                {sum.presets.map((p) => (
                  <button key={p.id || p.title} type="button" onClick={() => { setMenu(false); setModal({ type: 'task', preset: p }); }} className="px-3.5 py-2 text-left text-[13px] text-[#334155] hover:bg-[#F4F7FC]">{p.title}</button>
                ))}
              </span>
            )}
          </span>
        </div>
      </header>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi icon={CheckSquare} tone="#2F6BFF" bg="#EAF1FF" value={K.today.value} label="Tâches aujourd'hui" delta={K.today.delta} series={K.today.series} />
        <Kpi icon={Clock} tone="#F59E0B" bg="#FFF4DB" value={K.en_cours.value} label="Tâches en cours" delta={K.en_cours.delta} series={K.en_cours.series} />
        <Kpi icon={Check} tone="#10B981" bg="#E7F7EE" value={K.terminee.value} label="Tâches terminées" delta={K.terminee.delta} series={K.terminee.series} />
        <Kpi icon={XCircle} tone="#E11D48" bg="#FDECEF" value={K.en_retard.value} label="Tâches en retard" delta={K.en_retard.delta} series={K.en_retard.series} />
      </div>

      <div className="mt-4 grid items-start gap-4 xl:grid-cols-[1fr_320px]">
        <div className="min-w-0">
          <Card className="p-0">
            <nav className="flex flex-wrap gap-1 border-b border-[#EDF1F7] px-3">
              {TABS.map(([k, l, c]) => (
                <button key={l} type="button" onClick={() => { setPage(1); setStatus(k); }} className={`border-b-2 px-3 py-3 text-[13.5px] ${status === k ? 'border-[#2F6BFF] font-medium text-[#2F6BFF]' : 'border-transparent text-[#0B1C3F]'}`}>{l} ({nf(list.counts[c] || 0)})</button>
              ))}
            </nav>
            <div className="p-4">
              <div className="mb-3 grid gap-2 md:grid-cols-[1.6fr_repeat(4,1fr)] md:items-end">
                <label className="relative"><Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
                  <input className={`${inputCls} pl-9`} placeholder="Rechercher une tâche, un commerce, un contact…" value={f.q} onChange={(e) => setFilter('q')(e.target.value)} /></label>
                <Select label="Assigné à" value={f.assigned} onChange={setFilter('assigned')}><option value="">Tous</option>{(meta?.users || []).map((u) => <option key={u.email} value={u.email}>{u.name}</option>)}</Select>
                <Select label="Priorité" value={f.priority} onChange={setFilter('priority')}><option value="">Toutes</option><option value="haute">Haute</option><option value="moyenne">Moyenne</option><option value="basse">Basse</option></Select>
                <Select label="Type" value={f.type} onChange={setFilter('type')}><option value="">Tous</option>{(meta?.task_types || []).map((x) => <option key={x.key} value={x.key}>{x.label}</option>)}</Select>
                <Select label="Date d'échéance" value={f.when} onChange={setFilter('when')}><option value="">Toutes</option><option value="today">Aujourd'hui</option><option value="week">7 prochains jours</option><option value="past">Passées</option></Select>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[860px] text-[12.5px]">
                  <thead><tr className="border-b border-[#EDF1F7] text-left text-[#64748B]">{['Tâche', 'Commerce', 'Contact', 'Type', 'Priorité', 'Statut', "Date d'échéance", 'Assigné à', ''].map((h) => <th key={h} className="px-2 py-2 font-medium">{h}</th>)}</tr></thead>
                  <tbody>
                    {list.rows.map((r) => { const I = TYPE_ICON[r.type] || CheckSquare; return (
                      <tr key={r.id} onClick={() => setSel(r)} className={`cursor-pointer border-b border-[#F4F7FC] ${t?.id === r.id ? 'bg-[#F4F8FF]' : 'hover:bg-[#FAFCFF]'}`}>
                        <td className="px-2 py-2.5"><span className="flex items-center gap-2"><I size={16} className="shrink-0 text-[#2F6BFF]" /><span className="max-w-[170px] truncate text-[#2F6BFF]">{r.title}</span></span></td>
                        <td className="px-2 py-2.5">{r.prospect ? <span className="flex items-center gap-2"><Logo name={r.prospect} size={26} /><span className="max-w-[130px] truncate font-medium text-[#0B1C3F]">{r.prospect}</span></span> : '—'}</td>
                        <td className="max-w-[120px] truncate px-2 py-2.5 text-[#475569]">{r.contact || '—'}</td>
                        <td className="px-2 py-2.5 text-[#475569]">{r.type_label}</td>
                        <td className="px-2 py-2.5"><Pill tone={PRIO[r.priority]} /></td>
                        <td className="px-2 py-2.5"><Pill tone={STATUS[r.status]} /></td>
                        <td className={`px-2 py-2.5 ${r.status === 'en_retard' ? 'text-[#E11D48]' : 'text-[#475569]'}`}>{dayTime(r.due_at)}</td>
                        <td className="max-w-[120px] px-2 py-2.5"><Avatar name={r.assigned_name} size={22} /></td>
                        <td className="relative px-2 py-2.5" onClick={(e) => e.stopPropagation()}>
                          <button type="button" aria-label="Actions" onClick={() => setRowMenu(rowMenu === r.id ? null : r.id)} className="rounded p-1 hover:bg-[#F4F7FC]"><MoreHorizontal size={16} /></button>
                          {rowMenu === r.id && (
                            <span className="absolute right-2 top-full z-20 flex w-44 flex-col overflow-hidden rounded-xl border border-[#E6EEFB] bg-white py-1 shadow-lg">
                              {r.status !== 'terminee' && <button type="button" onClick={() => act(() => crmAPI.editTask(r.id, { status: 'terminee' }), 'Tâche terminée.')} className="px-3 py-2 text-left hover:bg-[#F4F7FC]">Marquer terminée</button>}
                              {r.status === 'a_faire' && <button type="button" onClick={() => act(() => crmAPI.editTask(r.id, { status: 'en_cours' }), 'Tâche en cours.')} className="px-3 py-2 text-left hover:bg-[#F4F7FC]">Passer en cours</button>}
                              <button type="button" onClick={() => setModal({ type: 'task', task: r })} className="px-3 py-2 text-left hover:bg-[#F4F7FC]">Modifier</button>
                              <button type="button" onClick={() => act(() => crmAPI.deleteTask(r.id), 'Tâche supprimée.')} className="px-3 py-2 text-left text-[#E11D48] hover:bg-[#FEF2F2]">Supprimer</button>
                            </span>
                          )}
                        </td>
                      </tr>); })}
                    {!list.rows.length && <tr><td colSpan={9} className="py-12 text-center text-[#64748B]">Aucune tâche ici.</td></tr>}
                  </tbody>
                </table>
              </div>
              <Pager page={page} pages={list.pages} total={list.total} perPage={perPage} onPage={setPage} onPerPage={(n) => { setPerPage(n); setPage(1); }} what="tâches" />
            </div>
          </Card>
          <div className="mt-4 grid gap-4 lg:grid-cols-3">
            <Card><Head icon={Target} title="Répartition des tâches par statut" /><Donut rows={sum.by_status} center={nf(list.counts.all)} sub="tâches" /></Card>
            <Card><Head icon={Target} title="Répartition par type" /><Donut rows={sum.by_type} center={nf(list.counts.all)} sub="tâches" /></Card>
            <Card><Head icon={Target} title="Charge de travail par utilisateur" /><Bars rows={sum.workload} /></Card>
          </div>
        </div>

        <Card className="sticky top-4">
          <Head title="Détails de la tâche" />
          {!t ? <p className="py-10 text-center text-[13px] text-[#64748B]">Choisissez une tâche.</p> : (
            <div className="space-y-3 text-[13px]">
              <p className="flex items-start gap-2 text-[16px] font-bold text-[#0B1C3F]">{React.createElement(TYPE_ICON[t.type] || CheckSquare, { size: 20, className: 'mt-0.5 shrink-0 text-[#2F6BFF]' })}<span className="flex-1">{t.title}</span><Pill tone={STATUS[t.status]} /></p>
              {t.prospect && (
                <>
                  <div className="flex items-center gap-3"><Logo name={t.prospect} size={46} /><div><p className="font-semibold text-[#0B1C3F]">{t.prospect}</p><p className="text-[12px] text-[#64748B]">{[t.sector, t.city].filter(Boolean).join(' · ')}</p></div></div>
                  <button type="button" onClick={() => navigate(`/admin/crm/prospects?open=${t.prospect_id}`)} className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg border border-[#2F6BFF] py-2 text-[12.5px] text-[#2F6BFF]"><ExternalLink size={13} /> Ouvrir le prospect</button>
                  <div>
                    <p className="mb-1 font-semibold text-[#0B1C3F]">Informations</p>
                    {[[User, 'Contact', [t.contact, t.contact_role && `(${t.contact_role})`].filter(Boolean).join(' ')], [Phone, 'Téléphone', t.phone], [Mail, 'Email', t.email]].map(([I, k, v]) => (
                      <p key={k} className="grid grid-cols-[100px_1fr] gap-2 py-0.5"><span className="flex items-center gap-2 text-[#64748B]"><I size={13} className="text-[#2F6BFF]" />{k}</span><span className="truncate text-[#0B1C3F]">{v || '—'}</span></p>
                    ))}
                  </div>
                </>
              )}
              {t.description && <div><p className="mb-1 font-semibold text-[#0B1C3F]">Description</p><p className="rounded-lg border border-[#EDF1F7] p-2.5 text-[#334155]">{t.description}</p></div>}
              <div className="grid grid-cols-2 gap-2">
                <div><span className="mb-1 block text-[11.5px] text-[#64748B]">Date d'échéance</span><p className={`rounded-lg border border-[#DCE3EE] px-2.5 py-2 ${t.status === 'en_retard' ? 'text-[#E11D48]' : 'text-[#0B1C3F]'}`}>{dayTime(t.due_at)}</p></div>
                <Select label="Assigné à" value={t.assigned_to || ''} onChange={(v) => act(() => crmAPI.editTask(t.id, { assigned_to: v }), 'Tâche réassignée.')}>{(meta?.users || []).map((u) => <option key={u.email} value={u.email}>{u.name}</option>)}</Select>
                <Select label="Priorité" value={t.priority} onChange={(v) => act(() => crmAPI.editTask(t.id, { priority: v }), 'Priorité changée.')}><option value="haute">Haute</option><option value="moyenne">Moyenne</option><option value="basse">Basse</option></Select>
                <Select label="Type" value={t.type} onChange={(v) => act(() => crmAPI.editTask(t.id, { type: v }), 'Type changé.')}>{(meta?.task_types || []).map((x) => <option key={x.key} value={x.key}>{x.label}</option>)}</Select>
              </div>
              {t.status !== 'terminee' && <button type="button" onClick={() => act(() => crmAPI.editTask(t.id, { status: 'terminee' }), 'Tâche terminée.')} className="flex w-full items-center justify-center gap-2 rounded-lg py-2.5 text-[13.5px] font-semibold text-white" style={{ background: BLUE }}><Check size={16} /> Marquer comme terminée</button>}
              <div className="grid grid-cols-3 gap-2">
                <button type="button" onClick={() => setModal({ type: 'task', task: t })} className="inline-flex items-center justify-center gap-1 rounded-lg border border-[#DCE3EE] py-2 text-[12px] text-[#2F6BFF]"><Pencil size={13} /> Modifier</button>
                <button type="button" onClick={() => setModal({ type: 'task', preset: { ...t, id: undefined } })} className="inline-flex items-center justify-center gap-1 rounded-lg border border-[#DCE3EE] py-2 text-[12px] text-[#2F6BFF]"><Copy size={13} /> Dupliquer</button>
                <button type="button" onClick={() => act(() => crmAPI.deleteTask(t.id), 'Tâche supprimée.')} className="inline-flex items-center justify-center gap-1 rounded-lg border border-[#FCA5A5] bg-[#FEF2F2] py-2 text-[12px] text-[#E11D48]"><Trash2 size={13} /> Supprimer</button>
              </div>
            </div>
          )}
        </Card>
      </div>

      {toast}
      {modal?.type === 'task' && <TaskModal meta={meta} task={modal.task} preset={modal.preset} onClose={() => setModal(null)} onSaved={() => { setModal(null); say('Tâche enregistrée.'); loadAll(); }} />}
      {modal?.type === 'templates' && <TemplatesModal presets={sum.presets} meta={meta} onClose={() => setModal(null)} onChanged={loadAll} />}
    </div>
  );
}

function TemplatesModal({ presets, meta, onClose, onChanged }) {
  const [f, setF] = useState({ title: '', type: 'appel', priority: 'moyenne', description: '' });
  const [err, setErr] = useState('');
  return (
    <Modal title="Modèles de tâches" onClose={onClose}>
      <ul className="mb-4 divide-y divide-[#F1F5F9]">
        {presets.map((p) => (
          <li key={p.id || p.title} className="flex items-center gap-2 py-2 text-[13px]">
            <span className="flex-1 text-[#0B1C3F]">{p.title}</span><span className="text-[12px] text-[#94A3B8]">{meta?.task_types.find((x) => x.key === p.type)?.label} · {p.priority}</span>
            {p.id && <button type="button" onClick={() => crmAPI.deleteTaskTemplate(p.id).then(onChanged)} aria-label="Supprimer" className="text-[#E11D48]"><Trash2 size={14} /></button>}
          </li>
        ))}
      </ul>
      <div className="grid gap-2 sm:grid-cols-2">
        <input className={`${inputCls} sm:col-span-2`} placeholder="Titre du modèle" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} />
        <Select value={f.type} onChange={(v) => setF({ ...f, type: v })}>{(meta?.task_types || []).map((x) => <option key={x.key} value={x.key}>{x.label}</option>)}</Select>
        <Select value={f.priority} onChange={(v) => setF({ ...f, priority: v })}><option value="haute">Haute</option><option value="moyenne">Moyenne</option><option value="basse">Basse</option></Select>
        {err && <p className="text-[12.5px] text-[#C0392B] sm:col-span-2">{err}</p>}
        <button type="button" disabled={!f.title.trim()} onClick={() => crmAPI.addTaskTemplate(f).then(() => { setF({ ...f, title: '' }); onChanged(); }).catch((e) => setErr(e?.response?.data?.detail || 'Impossible.'))}
                className="rounded-lg py-2.5 text-[13.5px] font-semibold text-white disabled:opacity-50 sm:col-span-2" style={{ background: BLUE }}>Ajouter le modèle</button>
      </div>
    </Modal>
  );
}
