import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  ClipboardCheck, CheckSquare, Clock3, AlertCircle, ArrowUp, ArrowDown, ChevronLeft, ChevronRight, CalendarDays, ChevronDown,
  Plus, MoreVertical, Check, CircleDashed, Loader2, Repeat, MessageSquare, Settings2, LayoutGrid, History,
} from 'lucide-react';
import { teamAPI } from '../../../lib/api';
import { useAuth } from '../../../contexts/AuthContext';
import { can } from '../../../lib/perms';
import { useToast } from '../../crm/ui';
import {
  Avatar, TypeChip, PriorityPill, Ring, PeoplePicker, field, todayParis, nowTimeParis, PRIORITY, STATUS, lateText,
} from './shared';
import { TaskForm, TaskDrawer, MemberBreakdown, AddMember, TypesManager } from './TaskModals';
import HistoryView from './HistoryView';
import NotificationBell from '../../../components/NotificationBell';

/* Super admin › Suivi d'équipe — built to the approved mockup (user,
   2026-10-08). The week Monday → Sunday, the figures, the team, the filters;
   every status read from the clock (features/team_tasks.py). */

// the quick-add row's boxes keep their own width (field is w-full)
const fixed = field.replace('w-full', '');
const card = 'rounded-2xl border border-[#E8EEF7] bg-white shadow-[0_1px_2px_rgba(11,28,63,.03),0_10px_30px_-24px_rgba(11,28,63,.25)]';

function Kpi({ icon: Icon, iconBg, iconFg, solid, value, label, children, ring }) {
  return (
    <div className={`${card} flex min-h-[96px] items-center gap-2.5 p-3 2xl:gap-3 2xl:p-4`}>
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl 2xl:h-11 2xl:w-11" style={{ background: iconBg }}>
        {solid
          ? <span className="flex h-6 w-6 items-center justify-center rounded-md text-white" style={{ background: iconFg }}><Icon size={15} strokeWidth={3} /></span>
          : <Icon size={23} style={{ color: iconFg }} />}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-[24px] font-bold leading-none text-[#0B1C3F] 2xl:text-[26px]">{value}</p>
        <p className="mt-1 text-[11.5px] leading-tight text-[#475569] 2xl:whitespace-nowrap 2xl:text-[12.5px]">{label}</p>
        {children}
      </div>
      {ring}
    </div>
  );
}

function WeekPicker({ week, onChange }) {
  const input = useRef(null);
  const shift = (n) => {
    const d = new Date(`${week.start}T12:00:00`); d.setDate(d.getDate() + n * 7);
    onChange(d.toISOString().slice(0, 10));
  };
  return (
    <div className="flex items-center gap-2">
      <button type="button" onClick={() => shift(-1)} aria-label="Semaine précédente"
              className={`${card} flex h-11 w-11 items-center justify-center text-[#0B1C3F] hover:border-[#2F6BFF]`}><ChevronLeft size={18} /></button>
      <button type="button" onClick={() => input.current?.showPicker?.() ?? input.current?.click()}
              className={`${card} relative flex h-11 items-center gap-2.5 px-4 text-[13.5px] font-medium text-[#0B1C3F] hover:border-[#2F6BFF]`}>
        <CalendarDays size={17} className="text-[#475569]" />{week.label}<ChevronDown size={14} className="text-[#64748B]" />
        <input ref={input} type="date" tabIndex={-1} aria-hidden="true" value={week.start}
               onChange={(e) => e.target.value && onChange(e.target.value)} className="pointer-events-none absolute inset-0 opacity-0" />
      </button>
      <button type="button" onClick={() => shift(1)} aria-label="Semaine suivante"
              className={`${card} flex h-11 w-11 items-center justify-center text-[#0B1C3F] hover:border-[#2F6BFF]`}><ChevronRight size={18} /></button>
    </div>
  );
}

function TaskItem({ t, today, canEdit, onToggle, onOpen }) {
  const done = t.status === 'terminee' || t.status === 'terminee_retard';
  const tick = today ? '#2F6BFF' : '#22C55E';
  return (
    <li className={`group relative flex gap-2.5 rounded-xl px-1.5 py-2 transition hover:bg-[#F6F9FE] ${t.status === 'en_retard' ? 'bg-[#FFF7F7]' : ''}`}>
      {t.status === 'en_retard' && <span className="absolute inset-y-2 left-0 w-[3px] rounded-full bg-[#EF4444]" />}
      <button type="button" disabled={!canEdit} onClick={() => onToggle(t)} aria-label={done ? `Décocher « ${t.title} »` : `Marquer « ${t.title} » terminée`}
              className={`mt-0.5 flex h-[20px] w-[20px] shrink-0 items-center justify-center rounded-[5px] border-[1.5px] transition ${done ? 'text-white' : 'border-[#CBD5E1] bg-white hover:border-[#2F6BFF]'} disabled:cursor-default`}
              style={done ? { background: t.status === 'terminee_retard' ? '#F97316' : tick, borderColor: t.status === 'terminee_retard' ? '#F97316' : tick } : undefined}>
        {done && <Check size={13} strokeWidth={3.2} />}
      </button>
      <button type="button" onClick={() => onOpen(t.id)} className="min-w-0 flex-1 text-left">
        <span className={`block text-[12.5px] font-medium leading-snug text-[#0B1C3F] ${done ? 'text-[#64748B]' : ''}`}>{t.title}</span>
        <span className="mt-1 flex flex-wrap items-center gap-1"><TypeChip type={t.type} />
          {t.repeat && <Repeat size={11} className="text-[#2F6BFF]" aria-label="Se répète" />}
          {t.comments > 0 && <span className="inline-flex items-center gap-0.5 text-[10.5px] text-[#64748B]"><MessageSquare size={11} />{t.comments}</span>}
        </span>
        <span className="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-1">
          <span className="max-w-full truncate text-[11.5px] text-[#475569]">{t.assignees.map((a) => a.name.split(' ')[0]).join(', ')}</span>
          <PriorityPill p={t.priority} />
        </span>
        <span className="mt-1 flex flex-wrap items-center gap-1 text-[10.5px] text-[#94A3B8]">
          <Clock3 size={11} />{t.due_time}
          {t.status === 'en_retard' && <span className="rounded bg-[#FEECEC] px-1 font-semibold text-[#DC2626]">En retard · {lateText(t.late_by_minutes)}</span>}
          {t.status === 'terminee_retard' && <span className="rounded bg-[#FFF1E6] px-1 font-semibold text-[#C2410C]">Terminée en retard</span>}
        </span>
      </button>
    </li>
  );
}

function DayColumn({ day, canEdit, onToggle, onOpen, onAdd }) {
  const today = day.today;
  return (
    <section className={`flex min-w-[168px] flex-1 basis-0 flex-col rounded-2xl border bg-white p-3 ${today ? 'border-[#2F6BFF] shadow-[0_0_0_1px_#2F6BFF,0_12px_30px_-20px_rgba(47,107,255,.6)]' : 'border-[#E8EEF7] shadow-[0_1px_2px_rgba(11,28,63,.03)]'}`}>
      <header className="flex items-start justify-between">
        <div>
          <h3 className={`text-[15px] font-bold ${today ? 'text-[#2F6BFF]' : 'text-[#0B1C3F]'}`}>{day.name}</h3>
          <p className={`text-[12px] ${today ? 'text-[#2F6BFF]' : 'text-[#64748B]'}`}>{day.short}</p>
        </div>
        <span className="flex h-7 min-w-7 items-center justify-center rounded-full bg-[#F1F5F9] px-2 text-[12px] font-semibold text-[#0B1C3F]">{day.total}</span>
      </header>
      <div className="mt-2.5 flex items-center gap-2">
        <span className="h-[6px] flex-1 overflow-hidden rounded-full bg-[#EEF2F8]">
          <span className="block h-full rounded-full transition-all" style={{ width: `${day.pct}%`, background: today ? '#2F6BFF' : 'linear-gradient(90deg,#38BDF8,#2F6BFF)' }} />
        </span>
        <span className={`w-8 text-right text-[11px] font-medium ${today ? 'text-[#2F6BFF]' : 'text-[#64748B]'}`}>{day.pct}%</span>
      </div>
      <ul className="mt-2 flex-1 space-y-0.5">
        {day.tasks.map((t) => <TaskItem key={t.id} t={t} today={today} canEdit={canEdit} onToggle={onToggle} onOpen={onOpen} />)}
        {!day.tasks.length && <li className="flex flex-col items-center gap-1 py-6 text-[11.5px] text-[#94A3B8]"><CircleDashed size={18} />Aucune tâche</li>}
      </ul>
      {canEdit && (
        <button type="button" onClick={() => onAdd(day.date)}
                className={`mt-3 flex h-10 items-center justify-center gap-1.5 rounded-xl text-[13px] font-medium transition ${today ? 'bg-[#2F6BFF] text-white hover:bg-[#2559DB]' : 'border border-[#E3E9F3] text-[#334155] hover:border-[#2F6BFF]'}`}>
          <Plus size={15} /> Ajouter une tâche
        </button>
      )}
    </section>
  );
}

function CheckRow({ on, onChange, dot, label, count }) {
  return (
    <label className="flex cursor-pointer items-center gap-3 py-1.5">
      <input type="checkbox" checked={on} onChange={(e) => onChange(e.target.checked)} className="peer sr-only" />
      <span className={`flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-md border-[1.5px] transition peer-focus-visible:ring-2 peer-focus-visible:ring-[#2F6BFF]/40 ${on ? 'border-[#2F6BFF] bg-[#2F6BFF] text-white' : 'border-[#CBD5E1] bg-white'}`}>
        {on && <Check size={14} strokeWidth={3} />}
      </span>
      <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: dot }} />
      <span className="flex-1 text-[13.5px] text-[#0B1C3F]">{label}</span>
      <span className="flex h-7 min-w-7 items-center justify-center rounded-full bg-[#F1F5F9] px-2 text-[12px] font-semibold text-[#0B1C3F]">{count}</span>
    </label>
  );
}

function MemberMenu({ m, onDetail, onRename, onRemove }) {
  const [open, setOpen] = useState(false);
  const box = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const close = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [open]);
  return (
    <div ref={box} className="relative">
      <button type="button" onClick={() => setOpen((o) => !o)} aria-label={`Actions pour ${m.name}`} className="flex h-8 w-6 items-center justify-center text-[#475569] hover:text-[#0B1C3F]"><MoreVertical size={17} /></button>
      {open && (
        <div className="absolute right-0 top-full z-30 mt-1 w-48 rounded-xl border border-[#E3E9F3] bg-white py-1 shadow-[0_18px_40px_-20px_rgba(11,28,63,.35)]">
          {[['Voir le détail', onDetail], ['Modifier la fonction', onRename], ["Retirer de l'équipe", onRemove]].filter(([, fn]) => fn).map(([l, fn]) => (
            <button key={l} type="button" onClick={() => { setOpen(false); fn(); }}
                    className={`block w-full px-3 py-2 text-left text-[12.5px] hover:bg-[#F4F7FC] ${l.startsWith('Retirer') ? 'text-[#DC2626]' : 'text-[#334155]'}`}>{l}</button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function SuiviEquipePage() {
  const { user } = useAuth();
  const canEdit = can(user, 'equipe', 'edit');
  const location = useLocation();
  const navigate = useNavigate();
  const [view, setView] = useState('semaine');
  const [week, setWeek] = useState('');
  const [d, setD] = useState(null);
  const [error, setError] = useState('');
  const [say, toast] = useToast();
  const [typeFilter, setTypeFilter] = useState('');
  const [statusF, setStatusF] = useState([]);
  const [prioF, setPrioF] = useState([]);
  const [openTask, setOpenTask] = useState(null);
  const [form, setForm] = useState(null);          // { due_date } for a new task with every option
  const [member, setMember] = useState(null);
  const [modal, setModal] = useState('');
  const [historyKey, setHistoryKey] = useState(0);
  // quick add (the mockup's « Ajouter une nouvelle tâche » row)
  const [qTitle, setQTitle] = useState('');
  const [qPeople, setQPeople] = useState([]);
  const [qDay, setQDay] = useState(todayParis());
  const [qHour, setQHour] = useState(nowTimeParis());
  const [qPrio, setQPrio] = useState('');
  const [qType, setQType] = useState('');
  const [qBusy, setQBusy] = useState(false);

  const load = useCallback((w = week) => {
    teamAPI.board(w || undefined)
      .then(({ data }) => { setD(data); setError(''); })
      .catch((e) => setError(e?.response?.data?.detail || "Le suivi d'équipe n'a pas pu être chargé."));
  }, [week]);
  useEffect(() => { load(); }, [load]);
  // the bell: ?tache=<id> opens that task
  useEffect(() => {
    const id = new URLSearchParams(location.search).get('tache');
    if (!id) return;
    setOpenTask(id);
    navigate({ pathname: location.pathname, search: '' }, { replace: true });
  }, [location.search]); // eslint-disable-line react-hooks/exhaustive-deps
  // the clock moves statuses on its own: read again every minute
  useEffect(() => { const id = setInterval(() => load(), 60 * 1000); return () => clearInterval(id); }, [load]);

  const refresh = () => { load(); setHistoryKey((k) => k + 1); };
  const toggle = async (t) => {
    const done = t.status === 'terminee' || t.status === 'terminee_retard';
    try { await teamAPI.complete(t.id, !done); say(done ? 'Tâche remise à faire.' : 'Tâche terminée.'); refresh(); } catch (e) { say(e?.response?.data?.detail || 'Action impossible.'); }
  };
  const quickAdd = async () => {
    if (!qTitle.trim()) { say('Écrivez la tâche.'); return; }
    if (!qPeople.length) { say('Choisissez à qui assigner la tâche.'); return; }
    if (!qDay || !qHour) { say("La date et l'heure sont obligatoires."); return; }
    setQBusy(true);
    try {
      await teamAPI.create({ title: qTitle.trim(), assignees: qPeople, due_date: qDay, due_time: qHour, priority: qPrio || 'moyenne', type_id: qType || null });
      say('Tâche ajoutée.'); setQTitle('');
      if (d && (qDay < d.week.start || qDay > d.week.end)) setWeek(qDay); else refresh();
    } catch (e) { say(e?.response?.data?.detail || "La tâche n'a pas pu être ajoutée."); } finally { setQBusy(false); }
  };

  const days = useMemo(() => {
    if (!d) return [];
    const keep = (t) => (!typeFilter || (typeFilter === 'none' ? !t.type : t.type?.id === typeFilter))
      && (!prioF.length || prioF.includes(t.priority))
      && (!statusF.length || statusF.some((s) => (s === 'terminee' ? ['terminee', 'terminee_retard'].includes(t.status)
        : s === 'en_retard' ? ['en_retard', 'terminee_retard'].includes(t.status) : t.status === s)));
    return d.days.map((x) => ({ ...x, tasks: x.tasks.filter(keep) }));
  }, [d, typeFilter, statusF, prioF]);

  if (!d) {
    return error
      ? <p className="rounded-xl bg-[#FEF2F2] px-4 py-3 text-[13.5px] text-[#B91C1C]">{error}</p>
      : <div className="flex items-center justify-center gap-2 py-24 text-[13px] text-[#64748B]"><Loader2 size={16} className="animate-spin" /> Chargement…</div>;
  }
  const k = d.kpis;
  const flip = (list, set, v, on) => set(on ? [...list, v] : list.filter((x) => x !== v));

  return (
    <div className="mx-auto max-w-[1680px] pb-10">
      {/* title + week */}
      <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-[30px] font-extrabold tracking-[-0.02em] text-[#0B1C3F] sm:text-[34px]">Suivi d'équipe</h1>
          <p className="mt-1 text-[14.5px] text-[#475569]">Organisez, suivez et optimisez les tâches de votre équipe en temps réel.</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <div className="inline-flex rounded-xl border border-[#E8EEF7] bg-white p-1 shadow-[0_1px_2px_rgba(11,28,63,.03)]">
            {[['semaine', 'Semaine', LayoutGrid], ['historique', 'Historique', History]].map(([key, l, I]) => (
              <button key={key} type="button" onClick={() => setView(key)} aria-pressed={view === key}
                      className={`inline-flex h-9 items-center gap-1.5 rounded-lg px-3 text-[13px] font-semibold ${view === key ? 'bg-[#2F6BFF] text-white' : 'text-[#475569] hover:text-[#0B1C3F]'}`}>
                <I size={15} />{l}
              </button>
            ))}
          </div>
          {view === 'semaine' && <WeekPicker week={d.week} onChange={setWeek} />}
          {/* the mockup's bell: tasks given, due within the hour, late (the super admin
              area has no top bar, so it lives here) */}
          <NotificationBell platformAdmin />
        </div>
      </div>

      {view === 'historique' ? <HistoryView onOpenTask={setOpenTask} refreshKey={historyKey} /> : (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_300px] 2xl:gap-5">
          <div className="min-w-0 space-y-4">
            {/* figures */}
            <div className="grid gap-4 sm:grid-cols-2 min-[1440px]:grid-cols-4">
              <Kpi icon={ClipboardCheck} iconBg="#EAF1FF" iconFg="#2F6BFF" value={k.total} label="Tâches totales">
                {k.total_delta == null ? <p className="mt-1.5 text-[11.5px] text-[#94A3B8]">— vs semaine précédente</p> : (
                  <>
                    <p className={`mt-1.5 flex items-center gap-0.5 text-[12.5px] font-semibold ${k.total_delta >= 0 ? 'text-[#16A34A]' : 'text-[#DC2626]'}`}>
                      {k.total_delta >= 0 ? <ArrowUp size={13} strokeWidth={2.6} /> : <ArrowDown size={13} strokeWidth={2.6} />}{k.total_delta >= 0 ? '+' : ''}{k.total_delta}%
                    </p>
                    <p className="text-[11px] text-[#94A3B8]">vs semaine précédente</p>
                  </>
                )}
              </Kpi>
              <Kpi icon={Check} solid iconBg="#E7F8EE" iconFg="#22C55E" value={k.done} label="Tâches terminées" ring={<Ring pct={k.done_pct} color="#22C55E" size={36} />}>
                <p className="mt-1.5 text-[12.5px]"><b className="text-[#16A34A]">{k.done_pct}%</b> <span className="text-[#475569]">de complétion</span></p>
              </Kpi>
              <Kpi icon={Clock3} iconBg="#FFF6DE" iconFg="#F5B70B" value={k.todo} label="À faire" ring={<Ring pct={k.todo_pct} color="#F5B70B" size={36} />}>
                <p className="mt-1.5 text-[12.5px] font-semibold text-[#D99A06]">{k.todo_pct}%</p>
              </Kpi>
              <Kpi icon={AlertCircle} iconBg="#FEECEC" iconFg="#EF4444" value={k.late} label="En retard" ring={<Ring pct={k.late_pct} color="#EF4444" size={36} />}>
                {/* the user's addition: still open past the deadline, and finished after it — apart */}
                <button type="button" onClick={() => setStatusF(['en_retard'])} title="Afficher les tâches en retard" className="mt-1 block text-left text-[10.5px] leading-snug 2xl:whitespace-nowrap 2xl:text-[11px] text-[#475569] hover:text-[#0B1C3F]">
                  <span className="flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-[#EF4444]" /><b className="text-[#DC2626]">{k.late_open}</b> non terminée{k.late_open > 1 ? 's' : ''}</span>
                  <span className="flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-[#F97316]" /><b className="text-[#C2410C]">{k.late_done}</b> terminée{k.late_done > 1 ? 's' : ''} en retard</span>
                </button>
              </Kpi>
            </div>

            {/* progress */}
            <div className={`${card} p-4`}>
              <p className="text-[13.5px] font-bold text-[#0B1C3F]">Progression de la semaine</p>
              <div className="mt-2.5 flex items-center gap-4">
                <span className="h-3 flex-1 overflow-hidden rounded-full bg-[#EEF2F8]">
                  <span className="block h-full rounded-full transition-all" style={{ width: `${d.progress.pct}%`, background: 'linear-gradient(90deg,#1D5BF0,#2F6BFF)' }} />
                </span>
                <span className="whitespace-nowrap text-[14px] font-bold text-[#0B1C3F]">{d.progress.pct}% <span className="font-medium text-[#64748B]">({d.progress.done} / {d.progress.total})</span></span>
              </div>
            </div>

            {/* quick add */}
            {canEdit && (
              <div className={`${card} p-4`}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-[15px] font-bold text-[#0B1C3F]">Ajouter une nouvelle tâche</p>
                  <button type="button" onClick={() => setForm({ due_date: qDay })} className="text-[12.5px] font-semibold text-[#2F6BFF] hover:underline">
                    Plus d'options (description, répétition…)
                  </button>
                </div>
                <form className="mt-3 flex flex-wrap gap-2.5"
                      onSubmit={(e) => { e.preventDefault(); quickAdd(); }}>
                  <label className="relative min-w-[200px] flex-[2_1_220px]">
                    <CircleDashed size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#64748B]" />
                    <input value={qTitle} onChange={(e) => setQTitle(e.target.value)} maxLength={200} placeholder="Nouvelle tâche…" className={`${field} pl-9`} aria-label="Nouvelle tâche" />
                  </label>
                  <PeoplePicker members={d.members} value={qPeople} onChange={setQPeople} className="min-w-[150px] flex-[1_1_160px]" />
                  <input type="date" required value={qDay} onChange={(e) => setQDay(e.target.value)} className={`${fixed} w-[150px] flex-none`} aria-label="Date d'échéance" />
                  <input type="time" required value={qHour} onChange={(e) => setQHour(e.target.value)} className={`${fixed} w-[112px] flex-none`} aria-label="Heure d'échéance" />
                  <select value={qPrio} onChange={(e) => setQPrio(e.target.value)} className={`${fixed} w-[128px] flex-none ${qPrio ? '' : 'text-[#64748B]'}`} aria-label="Priorité">
                    <option value="">Priorité</option>{Object.entries(PRIORITY).map(([key, p]) => <option key={key} value={key}>{p.label}</option>)}
                  </select>
                  <select value={qType} onChange={(e) => setQType(e.target.value)} className={`${fixed} w-[140px] flex-none ${qType ? '' : 'text-[#64748B]'}`} aria-label="Type">
                    <option value="">Type</option>{d.types.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
                  </select>
                  <button type="submit" disabled={qBusy}
                          className="inline-flex h-11 flex-none items-center justify-center gap-2 whitespace-nowrap rounded-xl bg-[#2F6BFF] px-5 text-[13.5px] font-semibold text-white shadow-[0_8px_18px_-10px_rgba(47,107,255,.8)] hover:bg-[#2559DB] disabled:opacity-60">
                    {qBusy && <Loader2 size={15} className="animate-spin" />}Ajouter la tâche
                  </button>
                </form>
              </div>
            )}

            {/* the week */}
            <div className="-mx-1 overflow-x-auto px-1 pb-2">
              <div className="flex gap-3">
                {days.map((day) => (
                  <DayColumn key={day.date} day={day} canEdit={canEdit} onToggle={toggle} onOpen={setOpenTask} onAdd={(date) => setForm({ due_date: date })} />
                ))}
              </div>
            </div>
          </div>

          {/* right rail */}
          <aside className="space-y-4">
            <div className={`${card} p-4`}>
              <div className="mb-3 flex items-center justify-between">
                <p className="flex items-center gap-2 text-[16px] font-bold text-[#0B1C3F]">Équipe
                  <span className="flex h-7 min-w-7 items-center justify-center rounded-full bg-[#F1F5F9] px-2 text-[12px] font-semibold">{d.members.length}</span>
                </p>
                {canEdit && (
                  <button type="button" onClick={() => setModal('member')}
                          className="inline-flex h-9 items-center gap-1 rounded-lg bg-[#EAF1FF] px-3 text-[13px] font-semibold text-[#2F6BFF] hover:bg-[#DCE8FF]"><Plus size={15} /> Ajouter</button>
                )}
              </div>
              {!d.members.length && <p className="py-4 text-center text-[12.5px] text-[#64748B]">Ajoutez les membres de l'équipe FidClic pour leur assigner des tâches.</p>}
              <ul className="space-y-1">
                {d.members.map((m) => {
                  const bar = m.late ? '#EF4444' : m.pct >= 60 ? '#22C55E' : '#2F6BFF';
                  return (
                    <li key={m.email} className="flex items-center gap-2.5 rounded-xl py-2">
                      <button type="button" onClick={() => setMember(m)} className="flex min-w-0 flex-1 items-center gap-2.5 text-left">
                        <Avatar name={m.name} size={38} />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[13.5px] font-bold text-[#0B1C3F]">{m.name}</span>
                          <span className="block truncate text-[12px] text-[#64748B]">{m.fonction || '—'}{!m.access && <span className="ml-1 text-[#D97706]" title="Pas d'accès à Suivi d'équipe (Admin › Rôles)">· sans accès</span>}</span>
                        </span>
                        <span className="w-[104px] shrink-0">
                          <span className="block text-right text-[12px] text-[#475569]"><b className="text-[#0B1C3F]">{m.done}</b> / {m.assigned} tâches</span>
                          <span className="mt-1 flex items-center gap-1.5">
                            <span className="h-[6px] flex-1 overflow-hidden rounded-full bg-[#EEF2F8]"><span className="block h-full rounded-full" style={{ width: `${m.pct}%`, background: bar }} /></span>
                            <span className="w-8 text-right text-[11px] font-semibold" style={{ color: bar }}>{m.pct}%</span>
                          </span>
                        </span>
                      </button>
                      <MemberMenu m={m} onDetail={() => setMember(m)}
                                  onRename={canEdit ? async () => {
                                    const f = window.prompt(`Fonction de ${m.name}`, m.fonction || '');
                                    if (f == null) return;
                                    try { await teamAPI.editMember(m.email, { email: m.email, fonction: f }); refresh(); } catch (e) { say(e?.response?.data?.detail || 'Action impossible.'); }
                                  } : null}
                                  onRemove={canEdit ? async () => {
                                    if (!window.confirm(`Retirer ${m.name} de l'équipe ? Ses tâches et leur historique restent.`)) return;
                                    try { await teamAPI.removeMember(m.email); say(`${m.name} retiré de l'équipe.`); refresh(); } catch (e) { say(e?.response?.data?.detail || 'Action impossible.'); }
                                  } : null} />
                    </li>
                  );
                })}
              </ul>
            </div>

            <div className={`${card} p-4`}>
              <div className="mb-2.5 flex items-center justify-between">
                <p className="text-[15px] font-bold text-[#0B1C3F]">Type de tâches</p>
                {canEdit && <button type="button" onClick={() => setModal('types')} aria-label="Gérer les types" title="Gérer les types" className="text-[#64748B] hover:text-[#2F6BFF]"><Settings2 size={16} /></button>}
              </div>
              <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)} className={field} aria-label="Type de tâches">
                <option value="">Tous les types</option>
                {d.types.map((x) => <option key={x.id} value={x.id}>{x.name} ({d.counts.type[x.id] || 0})</option>)}
                {d.counts.type[''] ? <option value="none">Sans type ({d.counts.type['']})</option> : null}
              </select>
            </div>

            <div className={`${card} p-4`}>
              <p className="mb-1.5 text-[15px] font-bold text-[#0B1C3F]">Statut</p>
              {[['a_faire', 'À faire'], ['terminee', 'Terminée'], ['en_retard', 'En retard']].map(([key, l]) => (
                <CheckRow key={key} on={statusF.includes(key)} onChange={(on) => flip(statusF, setStatusF, key, on)} dot={STATUS[key].dot} label={l} count={d.counts.status[key]} />
              ))}
              <p className="mb-1.5 mt-4 text-[15px] font-bold text-[#0B1C3F]">Priorité</p>
              {Object.entries(PRIORITY).map(([key, p]) => (
                <CheckRow key={key} on={prioF.includes(key)} onChange={(on) => flip(prioF, setPrioF, key, on)} dot={p.dot} label={p.label} count={d.counts.priority[key]} />
              ))}
              {(statusF.length || prioF.length || typeFilter) ? (
                <button type="button" onClick={() => { setStatusF([]); setPrioF([]); setTypeFilter(''); }}
                        className="mt-3 text-[12.5px] font-semibold text-[#2F6BFF] hover:underline">Effacer les filtres</button>
              ) : null}
            </div>
          </aside>
        </div>
      )}

      {openTask && <TaskDrawer taskId={openTask} board={d} canEdit={canEdit} say={say} onClose={() => setOpenTask(null)} onChanged={refresh} />}
      {form && <TaskForm initial={{ due_date: form.due_date }} board={d} onClose={() => setForm(null)}
                         onDone={(m, day) => { say(m); setForm(null); if (day < d.week.start || day > d.week.end) setWeek(day); else refresh(); }} />}
      {member && <MemberBreakdown member={member} week={d.week.start} onClose={() => setMember(null)} onOpenTask={(id) => { setMember(null); setOpenTask(id); }} />}
      {modal === 'member' && <AddMember onClose={() => setModal('')} onDone={(m) => { say(m); setModal(''); refresh(); }} />}
      {modal === 'types' && <TypesManager types={d.types} onClose={() => setModal('')} onChanged={refresh} />}
      {toast}
    </div>
  );
}
