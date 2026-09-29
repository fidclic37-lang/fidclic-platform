import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  CalendarDays, CalendarCheck, Users, Send, ChevronLeft, ChevronRight, Plus, Search, Phone, Mail, MapPin, Building2, User,
  Clock, Check, Pencil, CalendarClock, ExternalLink, FileText, ListChecks, CheckSquare, BarChart3, ArrowRight,
} from 'lucide-react';
import { crmAPI } from '../../lib/api';
import { useAuth } from '../../contexts/AuthContext';
import { Card, Head, Kpi, Avatar, Logo, Select, Loading, Breadcrumb, Modal, useToast, nf, BLUE, inputCls } from './ui';
import { TaskModal } from './CrmOverviewPage';

/* CRM › Calendrier — every task with a date, drawn as an agenda
   (jour / semaine / mois). Built to the approved mockup. */

const TYPE = {
  rdv: ['#EAF1FF', '#2F6BFF', CalendarDays], appel: ['#E7F7EE', '#0F8B58', Phone], email: ['#F3EEFF', '#7C3AED', Mail],
  relance: ['#FFF4DB', '#D97706', Send], proposition: ['#FDECEF', '#E11D48', FileText], preparation: ['#E0F2FE', '#0284C7', ListChecks],
  suivi: ['#F1F5F9', '#475569', CheckSquare],
};
const CONFIRM = { confirme: ['#E7F7EE', '#0F8B58', 'Confirmé'], a_confirmer: ['#FFF4DB', '#D97706', 'À confirmer'], annule: ['#FDECEF', '#E11D48', 'Annulé'] };
const STATUS = { a_faire: ['#FDECEF', '#E11D48', 'À faire'], en_cours: ['#EAF1FF', '#2F6BFF', 'En cours'], terminee: ['#E7F7EE', '#0F8B58', 'Terminé'], en_retard: ['#FDECEF', '#B91C1C', 'En retard'] };
const PRIO = { haute: ['#FDECEF', '#E11D48', 'Haute'], moyenne: ['#FFF4DB', '#D97706', 'Moyenne'], basse: ['#E7F7EE', '#0F8B58', 'Basse'] };
const Pill = ({ tone }) => <span className="inline-flex whitespace-nowrap rounded-md px-2 py-0.5 text-[11.5px] font-medium" style={{ background: tone[0], color: tone[1] }}>{tone[2]}</span>;

const H0 = 8; const H1 = 19; const ROW = 56;              // grid 08:00 → 19:00, 56px per hour
const DAYS = ['Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam', 'Dim'];
const day0 = (d) => { const x = new Date(d); x.setHours(0, 0, 0, 0); return x; };
const addDays = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
const monday = (d) => addDays(day0(d), -((day0(d).getDay() + 6) % 7));
const sameDay = (a, b) => day0(a).getTime() === day0(b).getTime();
const hm = (d) => new Date(d).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);

function rangeOf(view, anchor) {
  if (view === 'jour') return [day0(anchor), addDays(day0(anchor), 1)];
  if (view === 'semaine') return [monday(anchor), addDays(monday(anchor), 7)];
  const first = new Date(anchor.getFullYear(), anchor.getMonth(), 1);
  const start = monday(first);
  return [start, addDays(start, 42)];
}
function label(view, anchor) {
  const [a, b] = rangeOf(view, anchor);
  if (view === 'jour') return cap(a.toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }));
  if (view === 'mois') return cap(anchor.toLocaleDateString('fr-FR', { month: 'long', year: 'numeric' }));
  const end = addDays(b, -1);
  return `${a.getDate()}${a.getMonth() !== end.getMonth() ? ` ${a.toLocaleDateString('fr-FR', { month: 'long' })}` : ''} – ${end.toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' })}`;
}

export default function CrmCalendarPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const admin = user?.role === 'super_admin';
  const [view, setView] = useState('semaine');
  const [anchor, setAnchor] = useState(new Date());
  const [f, setF] = useState({ type: '', assigned: '', sector: '', status: '', q: '' });
  const [d, setD] = useState(null);
  const [meta, setMeta] = useState(null);
  const [sel, setSel] = useState(null);
  const [modal, setModal] = useState(null);
  const [err, setErr] = useState('');
  const [say, toast] = useToast();

  const [from, to] = useMemo(() => rangeOf(view, anchor), [view, anchor]);
  const load = useCallback(() => {
    crmAPI.calendar({ ...f, from: from.toISOString(), to: to.toISOString() }).then(({ data }) => {
      setErr(''); setD(data); setSel((s) => (s && data.events.find((e) => e.id === s.id)) || data.events.find((e) => new Date(e.due_at) >= new Date()) || data.events[0] || null);
    }).catch((e) => setErr(e?.response?.data?.detail || 'Impossible de charger le calendrier.'));
  }, [f, from, to]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { crmAPI.meta().then(({ data }) => setMeta(data)).catch(() => {}); }, []);
  const act = async (fn, m) => { try { await fn(); say(m); load(); } catch (e) { say(e?.response?.data?.detail || 'Action impossible.'); } };
  const step = (n) => setAnchor(view === 'jour' ? addDays(anchor, n) : view === 'semaine' ? addDays(anchor, 7 * n) : new Date(anchor.getFullYear(), anchor.getMonth() + n, 1));

  if (!d) return err ? <p className="rounded-xl bg-[#FEF2F2] px-4 py-3 text-[13.5px] text-[#B91C1C]">{err}</p> : <Loading />;
  const C = d.cards;
  const e = sel;
  const days = view === 'jour' ? [from] : Array.from({ length: 7 }, (_, i) => addDays(from, i));
  const byDay = (day) => d.events.filter((x) => sameDay(x.due_at, day));
  const maxAct = Math.max(1, ...d.activity.map((a) => d.activity_kinds.reduce((s, k) => s + a[k.key], 0)));

  return (
    <div className="crm">
      <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <Breadcrumb items={[['Super Admin', admin ? '/admin' : null], ['CRM de prospection', '/admin/crm'], ['Calendrier']]} />
          <h1 className="text-[28px] font-bold leading-tight text-[#0B1C3F]">Calendrier</h1>
          <p className="text-[15px] text-[#475569]">Planifiez et suivez vos rendez-vous, appels et relances de prospection.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={() => setAnchor(new Date())} className="h-10 rounded-xl border border-[#DCE3EE] bg-white px-4 text-[13.5px] text-[#0B1C3F]">Aujourd'hui</button>
          <span className="flex h-10 items-center rounded-xl border border-[#DCE3EE] bg-white">
            <button type="button" aria-label="Précédent" onClick={() => step(-1)} className="px-2.5"><ChevronLeft size={16} /></button>
            <span className="border-x border-[#EDF1F7] px-2.5 text-[#94A3B8]"><CalendarDays size={15} /></span>
            <button type="button" aria-label="Suivant" onClick={() => step(1)} className="px-2.5"><ChevronRight size={16} /></button>
          </span>
          <span className="min-w-[190px] text-[14px] font-semibold text-[#0B1C3F]">{label(view, anchor)}</span>
          <span className="flex h-10 overflow-hidden rounded-xl border border-[#DCE3EE] bg-white">
            {[['jour', 'Jour'], ['semaine', 'Semaine'], ['mois', 'Mois']].map(([k, l]) => (
              <button key={k} type="button" onClick={() => setView(k)} className={`px-4 text-[13px] ${view === k ? 'bg-[#EAF1FF] font-semibold text-[#2F6BFF]' : 'text-[#475569]'}`}>{l}</button>
            ))}
          </span>
          <button type="button" onClick={() => setModal({ type: 'task', preset: { type: 'rdv', title: 'Rendez-vous' } })} className="inline-flex h-10 items-center gap-2 rounded-xl px-4 text-[13.5px] font-medium text-white" style={{ background: BLUE }}><Plus size={16} /> Nouvel événement</button>
        </div>
      </header>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi icon={CalendarDays} tone="#2F6BFF" bg="#EAF1FF" value={C.today.value} label="Événements aujourd'hui" delta={C.today.delta} series={C.today.series} />
        <Kpi icon={CalendarCheck} tone="#10B981" bg="#E7F7EE" value={C.week.value} label="Événements cette semaine" delta={C.week.delta} series={C.week.series} />
        <Kpi icon={Users} tone="#8B5CF6" bg="#F3EEFF" value={C.rdv.value} label="Rendez-vous planifiés" delta={C.rdv.delta} series={C.rdv.series} />
        <Kpi icon={Send} tone="#F59E0B" bg="#FFF4DB" value={C.relances.value} label="Relances à faire" delta={C.relances.delta} series={C.relances.series} />
      </div>

      <div className="mt-4 grid items-start gap-4 xl:grid-cols-[1fr_330px]">
        <Card className="min-w-0 p-0">
          <div className="grid gap-2 border-b border-[#EDF1F7] p-4 md:grid-cols-[repeat(4,1fr)_1.4fr] md:items-end">
            <Select label="Type d'événement" value={f.type} onChange={(v) => setF({ ...f, type: v })}><option value="">Tous les types</option>{(meta?.task_types || []).map((x) => <option key={x.key} value={x.key}>{x.label}</option>)}</Select>
            <Select label="Assigné à" value={f.assigned} onChange={(v) => setF({ ...f, assigned: v })}><option value="">Tous</option>{(meta?.users || []).map((u) => <option key={u.email} value={u.email}>{u.name}</option>)}</Select>
            <Select label="Secteur" value={f.sector} onChange={(v) => setF({ ...f, sector: v })}><option value="">Tous les secteurs</option>{(meta?.sectors || []).map((s) => <option key={s}>{s}</option>)}</Select>
            <Select label="Statut" value={f.status} onChange={(v) => setF({ ...f, status: v })}><option value="">Tous</option><option value="confirme">Confirmé</option><option value="a_confirmer">À confirmer</option><option value="annule">Annulé</option><option value="terminee">Terminé</option><option value="en_retard">En retard</option></Select>
            <label className="relative"><Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
              <input className={`${inputCls} pl-9`} placeholder="Rechercher un commerce, un contact…" value={f.q} onChange={(ev) => setF({ ...f, q: ev.target.value })} /></label>
          </div>
          {view === 'mois'
            ? <MonthGrid from={from} anchor={anchor} byDay={byDay} sel={e} onPick={setSel} onDay={(day) => { setAnchor(day); setView('jour'); }} />
            : <WeekGrid days={days} byDay={byDay} sel={e} onPick={setSel} />}
        </Card>

        <Card className="xl:sticky xl:top-4">
          <Head title="Détails de l'événement" />
          {!e ? <p className="py-10 text-center text-[13px] text-[#64748B]">Aucun événement sur cette période.</p> : (
            <div className="space-y-3 text-[13px]">
              <div className="flex items-start gap-3">
                <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl" style={{ background: TYPE[e.type]?.[0], color: TYPE[e.type]?.[1] }}>{React.createElement(TYPE[e.type]?.[2] || CalendarDays, { size: 20 })}</span>
                <div className="min-w-0 flex-1"><p className="text-[15px] font-bold text-[#0B1C3F]">{e.title}</p><Pill tone={CONFIRM[e.confirm_status]} /></div>
              </div>
              <p className="flex items-center gap-2 text-[#0B1C3F]"><Clock size={14} className="text-[#2F6BFF]" />{cap(new Date(e.due_at).toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }))}</p>
              <p className="pl-6 text-[#475569]">{hm(e.due_at)} – {hm(e.end_at)} ({e.duration_min} min)</p>
              {e.prospect && (
                <div className="flex items-center gap-3 rounded-xl border border-[#EDF1F7] p-2.5"><Logo name={e.prospect} size={40} />
                  <div className="min-w-0 flex-1"><p className="truncate font-semibold text-[#0B1C3F]">{e.prospect}</p><p className="text-[12px] text-[#64748B]">{[e.sector, e.city].filter(Boolean).join(' · ')}</p></div>
                  <button type="button" onClick={() => navigate(`/admin/crm/prospects?open=${e.prospect_id}`)} className="text-[12px] text-[#2F6BFF]">Voir</button>
                </div>
              )}
              <div className="space-y-1.5">
                {[[User, 'Contact', [e.contact, e.contact_role && `(${e.contact_role})`].filter(Boolean).join(' ')],
                  [Phone, 'Téléphone', e.phone && <a href={`tel:${e.phone}`} className="text-[#2F6BFF]">{e.phone}</a>],
                  [Mail, 'Email', e.email && <a href={`mailto:${e.email}`} className="text-[#2F6BFF]">{e.email}</a>],
                  [MapPin, 'Adresse', e.address]].map(([I, k, v]) => (
                  <p key={k} className="grid grid-cols-[92px_1fr] gap-2"><span className="flex items-center gap-2 text-[#64748B]"><I size={13} className="text-[#2F6BFF]" />{k}</span><span className="min-w-0 break-words text-[#0B1C3F]">{v || '—'}</span></p>
                ))}
                {e.address && <a href={`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(e.address)}`} target="_blank" rel="noreferrer" className="ml-[100px] inline-flex items-center gap-1 text-[12px] text-[#2F6BFF]">Ouvrir dans Google Maps <ExternalLink size={11} /></a>}
              </div>
              <div className="grid grid-cols-2 gap-2">
                <Select label="Assigné à" value={e.assigned_to || ''} onChange={(v) => act(() => crmAPI.editTask(e.id, { assigned_to: v }), 'Événement réassigné.')}>{(meta?.users || []).map((u) => <option key={u.email} value={u.email}>{u.name}</option>)}</Select>
                <Select label="Rendez-vous" value={e.confirm_status} onChange={(v) => act(() => crmAPI.editTask(e.id, { confirm_status: v }), 'Statut changé.')}><option value="confirme">Confirmé</option><option value="a_confirmer">À confirmer</option><option value="annule">Annulé</option></Select>
                <p><span className="mb-1 block text-[11.5px] text-[#64748B]">Statut</span><Pill tone={STATUS[e.status]} /></p>
                <p><span className="mb-1 block text-[11.5px] text-[#64748B]">Priorité</span><Pill tone={PRIO[e.priority]} /></p>
              </div>
              {e.description && <div><p className="mb-1 font-semibold text-[#0B1C3F]">Notes</p><p className="rounded-lg border border-[#EDF1F7] p-2.5 text-[#334155]">{e.description}</p></div>}
              <div className="grid grid-cols-2 gap-2">
                <button type="button" onClick={() => setModal({ type: 'task', task: e })} className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-[#DCE3EE] py-2 text-[12.5px] text-[#2F6BFF]"><Pencil size={13} /> Modifier</button>
                <button type="button" onClick={() => setModal({ type: 'move', event: e })} className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-[#DCE3EE] py-2 text-[12.5px] text-[#2F6BFF]"><CalendarClock size={13} /> Reprogrammer</button>
              </div>
              {e.status !== 'terminee' && <button type="button" onClick={() => act(() => crmAPI.editTask(e.id, { status: 'terminee' }), 'Événement terminé.')} className="flex w-full items-center justify-center gap-2 rounded-lg py-2.5 text-[13.5px] font-semibold text-white" style={{ background: BLUE }}><Check size={16} /> Marquer comme terminé</button>}
            </div>
          )}
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Card>
          <Head icon={CheckSquare} title="Tâches du jour" right={<button type="button" onClick={() => navigate('/admin/crm/taches')} className="text-[12.5px] text-[#2F6BFF]">Voir tout</button>} />
          <ul className="space-y-2">{d.today.map((t) => (
            <li key={t.id} className="flex items-center gap-2 text-[13px]">
              <button type="button" aria-label="Terminer" onClick={() => t.status !== 'terminee' && act(() => crmAPI.editTask(t.id, { status: 'terminee' }), 'Tâche terminée.')}
                      className={`grid h-4 w-4 shrink-0 place-items-center rounded border ${t.status === 'terminee' ? 'border-[#10B981] bg-[#10B981] text-white' : 'border-[#CBD5E1]'}`}>{t.status === 'terminee' && <Check size={11} />}</button>
              <span className={`min-w-0 flex-1 truncate ${t.status === 'terminee' ? 'text-[#94A3B8] line-through' : 'text-[#0B1C3F]'}`}>{t.title}{t.prospect ? ` — ${t.prospect}` : ''}</span>
              <span className="text-[12px] text-[#64748B]">{hm(t.due_at)}</span><Pill tone={PRIO[t.priority]} />
            </li>))}
            {!d.today.length && <li className="py-6 text-center text-[13px] text-[#94A3B8]">Rien de prévu aujourd'hui.</li>}
          </ul>
        </Card>
        <Card>
          <Head icon={CalendarDays} title="Prochains rendez-vous" />
          <ul className="space-y-2.5">{d.upcoming.map((r) => (
            <li key={r.id}><button type="button" onClick={() => { setAnchor(new Date(r.due_at)); setSel(r); }} className="flex w-full items-center gap-3 text-left text-[13px]">
              <span className="w-12 shrink-0 rounded-lg bg-[#EAF1FF] py-1 text-center leading-tight text-[#2F6BFF]"><span className="block text-[10.5px] uppercase">{new Date(r.due_at).toLocaleDateString('fr-FR', { weekday: 'short' })}</span><strong className="text-[15px]">{new Date(r.due_at).getDate()}</strong></span>
              <span className="min-w-0 flex-1"><span className="block truncate font-medium text-[#0B1C3F]">{r.prospect || r.title}</span><span className="text-[12px] text-[#64748B]">{hm(r.due_at)} – {hm(r.end_at)}</span></span>
              <Pill tone={CONFIRM[r.confirm_status]} />
            </button></li>))}
            {!d.upcoming.length && <li className="py-6 text-center text-[13px] text-[#94A3B8]">Aucun rendez-vous à venir.</li>}
          </ul>
        </Card>
        <Card>
          <Head icon={BarChart3} title="Activité de prospection" sub="7 derniers jours" />
          <div className="flex h-[130px] items-end gap-2">
            {d.activity.map((a) => (
              <div key={a.day} className="flex flex-1 flex-col items-center gap-1">
                <div className="flex w-full max-w-[26px] flex-col-reverse overflow-hidden rounded-md" style={{ height: `${(d.activity_kinds.reduce((s, k) => s + a[k.key], 0) / maxAct) * 100}px` }}>
                  {d.activity_kinds.map((k) => a[k.key] > 0 && <span key={k.key} title={`${k.label} : ${a[k.key]}`} style={{ flex: a[k.key], background: TYPE[k.key][1] }} />)}
                </div>
                <span className="text-[11px] text-[#64748B]">{DAYS[(new Date(a.day).getDay() + 6) % 7]}</span>
              </div>
            ))}
          </div>
          <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-[12px] text-[#475569]">
            {d.activity_kinds.map((k) => <span key={k.key} className="flex items-center gap-1.5"><i className="h-2 w-2 rounded-full" style={{ background: TYPE[k.key][1] }} />{k.label} <strong className="text-[#0B1C3F]">{nf(k.total)}</strong></span>)}
          </div>
          <button type="button" onClick={() => navigate('/admin/crm')} className="mt-3 inline-flex items-center gap-1 text-[12.5px] text-[#2F6BFF]">Vue d'ensemble <ArrowRight size={13} /></button>
        </Card>
      </div>

      {toast}
      {modal?.type === 'task' && <TaskModal meta={meta} task={modal.task} preset={modal.preset} onClose={() => setModal(null)} onSaved={() => { setModal(null); say('Événement enregistré.'); load(); }} />}
      {modal?.type === 'move' && <MoveModal event={modal.event} onClose={() => setModal(null)} onDone={(due) => { setModal(null); act(() => crmAPI.editTask(modal.event.id, { due_at: due }), 'Événement reprogrammé.'); }} />}
    </div>
  );
}

function WeekGrid({ days, byDay, sel, onPick }) {
  const now = new Date();
  const hours = Array.from({ length: H1 - H0 }, (_, i) => H0 + i);
  return (
    <div className="overflow-x-auto">
      <div className="min-w-[760px]">
        <div className="grid border-b border-[#EDF1F7]" style={{ gridTemplateColumns: `60px repeat(${days.length}, 1fr)` }}>
          <span />
          {days.map((day) => (
            <p key={day.toISOString()} className={`py-2.5 text-center text-[12.5px] ${sameDay(day, now) ? 'font-semibold text-[#2F6BFF]' : 'text-[#475569]'}`}>
              {DAYS[(day.getDay() + 6) % 7]} {day.getDate()}{sameDay(day, now) && <span className="mx-auto mt-0.5 block h-1 w-1 rounded-full bg-[#2F6BFF]" />}
            </p>
          ))}
        </div>
        <div className="relative grid" style={{ gridTemplateColumns: `60px repeat(${days.length}, 1fr)` }}>
          <div>{hours.map((h) => <p key={h} className="pr-2 text-right text-[11px] text-[#94A3B8]" style={{ height: ROW }}>{String(h).padStart(2, '0')}:00</p>)}</div>
          {days.map((day) => (
            <div key={day.toISOString()} className={`relative border-l border-[#F1F5F9] ${sameDay(day, now) ? 'bg-[#FAFCFF]' : ''}`} style={{ height: ROW * hours.length }}>
              {hours.map((h) => <span key={h} className="absolute inset-x-0 border-t border-[#F1F5F9]" style={{ top: (h - H0) * ROW }} />)}
              {sameDay(day, now) && now.getHours() >= H0 && now.getHours() < H1 && (
                <span className="absolute inset-x-0 z-10 h-0.5 bg-[#E11D48]" style={{ top: (now.getHours() - H0 + now.getMinutes() / 60) * ROW }} />
              )}
              {lay(byDay(day)).map(({ ev, col, cols }) => {
                const s = new Date(ev.due_at);
                const top = Math.max(0, (s.getHours() - H0 + s.getMinutes() / 60) * ROW);
                const h = Math.max(24, (ev.duration_min / 60) * ROW - 2);
                const [bg, fg] = TYPE[ev.type] || TYPE.suivi;
                return (
                  <button key={ev.id} type="button" onClick={() => onPick(ev)} title={`${ev.title}${ev.prospect ? ` — ${ev.prospect}` : ''}`}
                          className={`absolute overflow-hidden rounded-lg border-l-[3px] px-1.5 py-1 text-left text-[11.5px] leading-tight ${sel?.id === ev.id ? 'ring-2 ring-[#2F6BFF]' : ''} ${ev.confirm_status === 'annule' ? 'opacity-50 line-through' : ''}`}
                          style={{ top: Math.min(top, ROW * (H1 - H0) - h), height: h, left: `calc(${(col / cols) * 100}% + 2px)`, width: `calc(${100 / cols}% - 4px)`, background: bg, borderColor: fg, color: '#0B1C3F' }}>
                    <span className="block truncate font-semibold" style={{ color: fg }}>{ev.title}</span>
                    {h > 34 && <span className="block truncate">{ev.prospect || ''}</span>}
                    {h > 48 && <span className="block text-[#64748B]">{hm(ev.due_at)} – {hm(ev.end_at)}</span>}
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* Side-by-side columns for overlapping events of one day. */
function lay(evs) {
  const out = []; let group = []; let groupEnd = 0;
  const flush = () => { const cols = Math.max(...group.map((g) => g.col)) + 1; group.forEach((g) => out.push({ ...g, cols })); group = []; };
  [...evs].sort((a, b) => new Date(a.due_at) - new Date(b.due_at)).forEach((ev) => {
    const s = new Date(ev.due_at).getTime(); const e = new Date(ev.end_at).getTime();
    if (group.length && s >= groupEnd) flush();
    const used = new Set(group.filter((g) => new Date(g.ev.end_at).getTime() > s).map((g) => g.col));
    let col = 0; while (used.has(col)) col += 1;
    group.push({ ev, col }); groupEnd = Math.max(group.length > 1 ? groupEnd : 0, e);
  });
  if (group.length) flush();
  return out;
}

function MonthGrid({ from, anchor, byDay, sel, onPick, onDay }) {
  const now = new Date();
  return (
    <div className="overflow-x-auto">
      <div className="grid min-w-[700px] grid-cols-7">
        {DAYS.map((x) => <p key={x} className="border-b border-[#EDF1F7] py-2 text-center text-[12px] text-[#64748B]">{x}</p>)}
        {Array.from({ length: 42 }, (_, i) => addDays(from, i)).map((day) => {
          const evs = byDay(day);
          const out = day.getMonth() !== anchor.getMonth();
          return (
            <div key={day.toISOString()} className={`min-h-[104px] border-b border-l border-[#F1F5F9] p-1.5 ${out ? 'bg-[#FAFBFD]' : ''}`}>
              <button type="button" onClick={() => onDay(day)} className={`mb-1 grid h-6 w-6 place-items-center rounded-full text-[12px] ${sameDay(day, now) ? 'bg-[#2F6BFF] font-semibold text-white' : out ? 'text-[#CBD5E1]' : 'text-[#0B1C3F]'}`}>{day.getDate()}</button>
              {evs.slice(0, 3).map((ev) => { const [bg, fg] = TYPE[ev.type] || TYPE.suivi; return (
                <button key={ev.id} type="button" onClick={() => onPick(ev)} className={`mb-0.5 block w-full truncate rounded px-1.5 py-0.5 text-left text-[11px] ${sel?.id === ev.id ? 'ring-1 ring-[#2F6BFF]' : ''}`} style={{ background: bg, color: fg }}>{hm(ev.due_at)} {ev.prospect || ev.title}</button>); })}
              {evs.length > 3 && <button type="button" onClick={() => onDay(day)} className="text-[11px] text-[#2F6BFF]">+{evs.length - 3} autres</button>}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function MoveModal({ event, onClose, onDone }) {
  const local = (x) => new Date(new Date(x).getTime() - new Date(x).getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  const [v, setV] = useState(local(event.due_at));
  return (
    <Modal title={`Reprogrammer — ${event.title}`} onClose={onClose}>
      <label className="mb-1 block text-[12.5px] text-[#475569]">Nouvelle date et heure</label>
      <input type="datetime-local" className={inputCls} value={v} onChange={(x) => setV(x.target.value)} />
      <div className="mt-3 flex flex-wrap gap-2">
        {[['+1 h', 1 / 24], ['Demain', 1], ['+1 semaine', 7]].map(([l, n]) => (
          <button key={l} type="button" onClick={() => setV(local(new Date(new Date(v).getTime() + n * 86400000)))} className="rounded-lg border border-[#DCE3EE] px-3 py-1.5 text-[12.5px] text-[#2F6BFF]">{l}</button>
        ))}
      </div>
      <button type="button" disabled={!v} onClick={() => onDone(new Date(v).toISOString())} className="mt-4 w-full rounded-lg py-2.5 text-[13.5px] font-semibold text-white disabled:opacity-50" style={{ background: BLUE }}>Reprogrammer</button>
    </Modal>
  );
}
