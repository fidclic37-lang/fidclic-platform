import React, { useCallback, useEffect, useState } from 'react';
import {
  X, Check, Loader2, Pencil, Trash2, Repeat, CalendarClock, MessageSquare, History, Send, AlertTriangle, Plus, User,
} from 'lucide-react';
import { teamAPI } from '../../../lib/api';
import {
  Avatar, TypeChip, PriorityPill, StatusBadge, PeoplePicker, field, frDateTime, lateText, todayParis, nowTimeParis,
  DAYS_SHORT, STATUS, Shell,
} from './shared';
import { ListPicker } from './Lists';

export { Shell };

/* Super admin › Suivi d'équipe — the windows: a task (details, Terminée,
   Modifier, Supprimer, comments, its history), a new task with every option
   (description, repeats), one person's breakdown, the types, the team. */

const err = (e, fallback) => e?.response?.data?.detail || fallback;

const Label = ({ children }) => <span className="mb-1 block text-[12px] font-semibold text-[#475569]">{children}</span>;

/* ── the form: a new task, or a change to one ─────────────────────────── */
export function TaskForm({ initial, board, onDone, onClose, editing, onRefresh, onManage, onAddMember }) {
  const t = initial || {};
  const [title, setTitle] = useState(t.title || '');
  const [description, setDescription] = useState(t.description || '');
  const [typeId, setTypeId] = useState(t.type?.id || t.type_id || '');
  const [priority, setPriority] = useState(t.priority || (board.priorities.find((p) => p.default) || board.priorities[0] || {}).id || '');
  const [assignees, setAssignees] = useState((t.assignees || []).map((a) => (typeof a === 'string' ? a : a.email)));
  const [day, setDay] = useState(t.due_date || todayParis());
  const [hour, setHour] = useState(t.due_time || nowTimeParis());
  const [repeat, setRepeat] = useState('');
  const [every, setEvery] = useState(1);
  const [weekdays, setWeekdays] = useState([]);
  const [endKind, setEndKind] = useState('never');
  const [until, setUntil] = useState('');
  const [count, setCount] = useState(10);
  const [applyTo, setApplyTo] = useState('this');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');

  const dayIdx = (() => { const d = new Date(`${day}T12:00:00`); return (d.getDay() + 6) % 7; })();
  const save = async () => {
    setMsg('');
    if (!title.trim()) { setMsg('Donnez un titre à la tâche.'); return; }
    if (!assignees.length) { setMsg('Assignez la tâche à au moins une personne.'); return; }
    if (!day || !hour) { setMsg("La date et l'heure sont obligatoires."); return; }
    const body = { title: title.trim(), description, type_id: typeId || '', priority: priority || null, assignees, due_date: day, due_time: hour };
    setBusy(true);
    try {
      if (editing) {
        await teamAPI.edit(t.id, { ...body, apply_to: applyTo });
      } else {
        if (repeat) {
          body.recurrence = {
            freq: repeat, interval: Number(every) || 1,
            ...(repeat === 'weekly' ? { weekdays: weekdays.length ? weekdays : [dayIdx] } : {}),
            ...(endKind === 'until' && until ? { until } : {}),
            ...(endKind === 'count' ? { count: Number(count) || 1 } : {}),
          };
        }
        await teamAPI.create({ ...body, type_id: typeId || null });
      }
      onDone(editing ? 'Tâche modifiée.' : 'Tâche ajoutée.', day);
    } catch (e) {
      setMsg(err(e, "La tâche n'a pas pu être enregistrée."));
    } finally { setBusy(false); }
  };

  return (
    <Shell title={editing ? 'Modifier la tâche' : 'Nouvelle tâche'} onClose={onClose} wide>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="sm:col-span-2"><Label>Titre</Label>
          <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} className={field} placeholder="Nouvelle tâche…" autoFocus />
        </label>
        <label className="sm:col-span-2"><Label>Description</Label>
          <textarea value={description} onChange={(e) => setDescription(e.target.value)} maxLength={5000} rows={4}
                    className={`${field} h-auto py-2.5`} placeholder="Détails, liens, étapes…" />
        </label>
        <div><Label>Assigner à</Label><PeoplePicker members={board.members} value={assignees} onChange={setAssignees} onAddMember={onAddMember} /></div>
        <div><Label>Type</Label>
          <ListPicker kind="types" items={board.types} value={typeId} onChange={setTypeId} placeholder="Sans type" canEdit
                      onAdded={onRefresh} onManage={onManage && (() => onManage('types'))} />
        </div>
        <label><Label>Échéance — date</Label><input type="date" required value={day} onChange={(e) => setDay(e.target.value)} className={field} /></label>
        <label><Label>Échéance — heure</Label><input type="time" required value={hour} onChange={(e) => setHour(e.target.value)} className={field} /></label>
        <div className="sm:col-span-2"><Label>Priorité</Label>
          <ListPicker kind="priorities" items={board.priorities} value={priority} onChange={(v) => setPriority(v || priority)} canEdit
                      onAdded={onRefresh} onManage={onManage && (() => onManage('priorities'))} className="sm:max-w-[50%]" />
        </div>

        {!editing && (
          <div className="rounded-xl border border-[#E3E9F3] p-3 sm:col-span-2">
            <p className="mb-2 flex items-center gap-1.5 text-[12.5px] font-bold text-[#0B1C3F]"><Repeat size={14} className="text-[#2F6BFF]" /> Répétition</p>
            <div className="flex flex-wrap gap-2">
              {[['', 'Ne se répète pas'], ['daily', 'Chaque jour'], ['weekdays', 'Jours ouvrés'], ['weekly', 'Chaque semaine'], ['monthly', 'Chaque mois']].map(([k, l]) => (
                <button key={k || 'none'} type="button" onClick={() => setRepeat(k)} aria-pressed={repeat === k}
                        className={`h-8 rounded-lg border px-3 text-[12.5px] ${repeat === k ? 'border-[#2F6BFF] bg-[#EAF1FF] font-semibold text-[#0B1C3F]' : 'border-[#E3E9F3] text-[#475569]'}`}>{l}</button>
              ))}
            </div>
            {['daily', 'weekly', 'monthly'].includes(repeat) && (
              <label className="mt-3 flex items-center gap-2 text-[12.5px] text-[#475569]">
                Tous les
                <input type="number" min={1} max={52} value={every} onChange={(e) => setEvery(e.target.value)} className="h-8 w-16 rounded-lg border border-[#E3E9F3] px-2" />
                {{ daily: 'jour(s)', weekly: 'semaine(s)', monthly: 'mois' }[repeat]}
              </label>
            )}
            {repeat === 'weekly' && (
              <div className="mt-3 flex flex-wrap gap-1.5">
                {DAYS_SHORT.map((d, i) => {
                  const on = (weekdays.length ? weekdays : [dayIdx]).includes(i);
                  return (
                    <button key={d} type="button" aria-pressed={on}
                            onClick={() => { const cur = weekdays.length ? weekdays : [dayIdx]; setWeekdays(on ? cur.filter((x) => x !== i) : [...cur, i].sort()); }}
                            className={`h-8 w-11 rounded-lg text-[12px] font-semibold capitalize ${on ? 'bg-[#2F6BFF] text-white' : 'bg-[#F1F5F9] text-[#475569]'}`}>{d}</button>
                  );
                })}
              </div>
            )}
            {repeat && (
              <div className="mt-3 flex flex-wrap items-center gap-3 text-[12.5px] text-[#475569]">
                <span className="font-semibold">Fin :</span>
                {[['never', 'Jamais'], ['until', 'Le'], ['count', 'Après']].map(([k, l]) => (
                  <label key={k} className="flex items-center gap-1.5">
                    <input type="radio" checked={endKind === k} onChange={() => setEndKind(k)} className="accent-[#2F6BFF]" />{l}
                    {k === 'until' && endKind === 'until' && <input type="date" value={until} onChange={(e) => setUntil(e.target.value)} className="h-8 rounded-lg border border-[#E3E9F3] px-2" />}
                    {k === 'count' && endKind === 'count' && (<><input type="number" min={1} max={500} value={count} onChange={(e) => setCount(e.target.value)} className="h-8 w-16 rounded-lg border border-[#E3E9F3] px-2" /> fois</>)}
                  </label>
                ))}
              </div>
            )}
          </div>
        )}

        {editing && t.series_id && (
          <div className="rounded-xl border border-[#E3E9F3] p-3 text-[12.5px] text-[#475569] sm:col-span-2">
            <p className="mb-2 font-semibold text-[#0B1C3F]">Cette tâche se répète ({t.repeat}). Appliquer à :</p>
            <label className="mr-4 inline-flex items-center gap-1.5"><input type="radio" checked={applyTo === 'this'} onChange={() => setApplyTo('this')} className="accent-[#2F6BFF]" /> Cette tâche</label>
            <label className="inline-flex items-center gap-1.5"><input type="radio" checked={applyTo === 'following'} onChange={() => setApplyTo('following')} className="accent-[#2F6BFF]" /> Cette tâche et les suivantes</label>
            {applyTo === 'following' && <p className="mt-1.5 text-[11.5px] text-[#64748B]">Les suivantes prennent le texte, les personnes et l'heure ; chacune garde son jour.</p>}
          </div>
        )}
      </div>
      {msg && <p className="mt-3 rounded-lg bg-[#FEF2F2] px-3 py-2 text-[12.5px] text-[#B91C1C]">{msg}</p>}
      <div className="mt-4 flex justify-end gap-2">
        <button type="button" onClick={onClose} className="h-10 rounded-xl border border-[#E3E9F3] px-4 text-[13px] font-semibold text-[#475569]">Annuler</button>
        <button type="button" onClick={save} disabled={busy}
                className="inline-flex h-10 items-center gap-2 rounded-xl bg-[#2F6BFF] px-5 text-[13px] font-semibold text-white hover:bg-[#2559DB] disabled:opacity-60">
          {busy && <Loader2 size={14} className="animate-spin" />}{editing ? 'Enregistrer' : 'Ajouter la tâche'}
        </button>
      </div>
    </Shell>
  );
}

/* ── one task ─────────────────────────────────────────────────────────── */
export function TaskDrawer({ taskId, board, canEdit, onClose, onChanged, say, onManage, onAddMember }) {
  const [d, setD] = useState(null);
  const [tab, setTab] = useState('comments');
  const [text, setText] = useState('');
  const [editing, setEditing] = useState(false);
  const [confirmDel, setConfirmDel] = useState(false);
  const [busy, setBusy] = useState('');
  const [msg, setMsg] = useState('');

  const load = useCallback(() => {
    teamAPI.task(taskId).then(({ data }) => setD(data)).catch((e) => setMsg(err(e, 'Tâche introuvable.')));
  }, [taskId]);
  useEffect(() => { load(); }, [load]);

  const act = async (key, fn, ok) => {
    setBusy(key); setMsg('');
    try { await fn(); if (ok) say(ok); load(); onChanged(); return true; } catch (e) { setMsg(err(e, 'Action impossible.')); return false; } finally { setBusy(''); }
  };
  const t = d?.task;
  const done = t && (t.status === 'terminee' || t.status === 'terminee_retard');
  const deleted = t?.status === 'supprimee';

  if (editing && t) {
    return <TaskForm initial={t} board={board} editing onClose={() => setEditing(false)} onRefresh={onChanged} onManage={onManage} onAddMember={onAddMember}
                     onDone={(m) => { say(m); setEditing(false); load(); onChanged(); }} />;
  }
  return (
    <Shell side onClose={onClose} title={t?.title || 'Tâche'}>
      <header className="flex items-start gap-3 border-b border-[#EEF2F8] px-5 py-4">
        {t && canEdit && !deleted ? (
          <button type="button" onClick={() => act('done', () => teamAPI.complete(t.id, !done), done ? 'Tâche remise à faire.' : 'Tâche terminée.')}
                  aria-label={done ? 'Décocher Terminée' : 'Marquer terminée'} disabled={!!busy}
                  className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md border-2 ${done ? 'border-[#22C55E] bg-[#22C55E] text-white' : 'border-[#CBD5E1] hover:border-[#2F6BFF]'}`}>
            {done && <Check size={15} strokeWidth={3} />}
          </button>
        ) : <span className="mt-0.5 h-6 w-6" />}
        <div className="min-w-0 flex-1">
          <h3 className={`text-[17px] font-bold leading-snug text-[#0B1C3F] ${done ? 'line-through decoration-[#94A3B8]' : ''}`}>{t?.title || 'Chargement…'}</h3>
          {t && <div className="mt-1.5 flex flex-wrap items-center gap-1.5"><StatusBadge s={t.status} late={t.late_by_minutes} /><TypeChip type={t.type} /><PriorityPill label={t.priority_label} color={t.priority_color} /></div>}
        </div>
        <button type="button" onClick={onClose} aria-label="Fermer" className="text-[#94A3B8] hover:text-[#0B1C3F]"><X size={20} /></button>
      </header>
      <div className="flex-1 overflow-y-auto px-5 py-4">
        {msg && <p className="mb-3 rounded-lg bg-[#FEF2F2] px-3 py-2 text-[12.5px] text-[#B91C1C]">{msg}</p>}
        {!t ? <p className="flex items-center gap-2 text-[13px] text-[#64748B]"><Loader2 size={15} className="animate-spin" /> Chargement…</p> : (
          <>
            <dl className="grid grid-cols-[120px_1fr] gap-x-3 gap-y-2.5 text-[13px]">
              <dt className="text-[#64748B]">Échéance</dt>
              <dd className="flex items-center gap-1.5 font-medium text-[#0B1C3F]"><CalendarClock size={14} className="text-[#64748B]" />{frDateTime(t.due_at)}</dd>
              <dt className="text-[#64748B]">Assignée à</dt>
              <dd className="flex flex-wrap gap-2">{t.assignees.map((a) => <span key={a.email} className="inline-flex items-center gap-1.5"><Avatar name={a.name} size={22} /><span className="text-[#0B1C3F]">{a.name}</span></span>)}</dd>
              {done && (<><dt className="text-[#64748B]">Terminée</dt><dd className="text-[#0B1C3F]">{frDateTime(t.completed_at)}{t.completed_by ? ` par ${t.completed_by.name}` : ''}{t.status === 'terminee_retard' ? ` (${lateText(t.late_by_minutes)} après l'échéance)` : ''}</dd></>)}
              {t.repeat && (<><dt className="text-[#64748B]">Répétition</dt><dd className="flex items-center gap-1.5 text-[#0B1C3F]"><Repeat size={13} className="text-[#2F6BFF]" />{t.repeat}</dd></>)}
              <dt className="text-[#64748B]">Créée</dt>
              <dd className="text-[#475569]">{frDateTime(t.created_at)}{t.created_by ? ` par ${t.created_by.name}` : ''}</dd>
            </dl>
            {t.description
              ? <p className="mt-4 whitespace-pre-wrap rounded-xl bg-[#F8FAFD] px-3.5 py-3 text-[13px] leading-relaxed text-[#334155]">{t.description}</p>
              : <p className="mt-4 text-[12.5px] italic text-[#94A3B8]">Pas de description.</p>}

            {canEdit && !deleted && (
              <div className="mt-4 flex flex-wrap gap-2">
                <button type="button" onClick={() => setEditing(true)} className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-[#E3E9F3] px-3 text-[12.5px] font-semibold text-[#334155] hover:border-[#2F6BFF]"><Pencil size={14} /> Modifier</button>
                <button type="button" onClick={() => setConfirmDel(true)} className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-[#FBD5D5] px-3 text-[12.5px] font-semibold text-[#DC2626] hover:bg-[#FEF2F2]"><Trash2 size={14} /> Supprimer</button>
                {t.series_id && (
                  <button type="button" disabled={!!busy}
                          onClick={() => window.confirm('Arrêter la répétition après cette tâche ? Les suivantes non terminées seront supprimées.') && act('stop', () => teamAPI.stopSeries(t.id), 'Répétition arrêtée.')}
                          className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-[#E3E9F3] px-3 text-[12.5px] font-semibold text-[#334155]"><Repeat size={14} /> Arrêter la répétition</button>
                )}
              </div>
            )}
            {confirmDel && (
              <div className="mt-3 rounded-xl border border-[#FBD5D5] bg-[#FEF8F8] p-3 text-[12.5px] text-[#7F1D1D]">
                <p className="mb-2 flex items-center gap-1.5 font-semibold"><AlertTriangle size={14} /> Supprimer « {t.title} » ? Elle restera visible dans l'Historique.</p>
                <div className="flex flex-wrap gap-2">
                  <button type="button" onClick={async () => { if (await act('del', () => teamAPI.remove(t.id, 'this'), 'Tâche supprimée.')) onClose(); }}
                          className="h-8 rounded-lg bg-[#DC2626] px-3 font-semibold text-white">{t.series_id ? 'Cette tâche' : 'Supprimer'}</button>
                  {t.series_id && (
                    <button type="button" onClick={async () => { if (await act('del', () => teamAPI.remove(t.id, 'following'), 'Tâches supprimées.')) onClose(); }}
                            className="h-8 rounded-lg border border-[#DC2626] px-3 font-semibold text-[#DC2626]">Cette tâche et les suivantes</button>
                  )}
                  <button type="button" onClick={() => setConfirmDel(false)} className="h-8 rounded-lg px-3 text-[#475569]">Annuler</button>
                </div>
              </div>
            )}

            <div className="mt-6 flex gap-1 border-b border-[#EEF2F8]">
              {[['comments', `Commentaires (${d.comments.length})`, MessageSquare], ['events', 'Historique', History]].map(([k, l, I]) => (
                <button key={k} type="button" onClick={() => setTab(k)}
                        className={`-mb-px inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-[12.5px] font-semibold ${tab === k ? 'border-[#2F6BFF] text-[#2F6BFF]' : 'border-transparent text-[#64748B]'}`}>
                  <I size={14} />{l}
                </button>
              ))}
            </div>
            {tab === 'comments' ? (
              <div className="pt-3">
                {!d.comments.length && <p className="text-[12.5px] text-[#94A3B8]">Aucun commentaire pour l'instant.</p>}
                <ul className="space-y-3">
                  {d.comments.map((c) => (
                    <li key={c.id} className="flex gap-2.5">
                      <Avatar name={c.author.name} size={28} />
                      <div className="min-w-0 flex-1 rounded-xl bg-[#F8FAFD] px-3 py-2">
                        <p className="flex items-center gap-2 text-[11.5px] text-[#64748B]"><span className="font-semibold text-[#0B1C3F]">{c.author.name}</span>{frDateTime(c.at)}
                          {(c.mine || canEdit) && c.mine && <button type="button" onClick={() => act('c', () => teamAPI.deleteComment(c.id))} className="ml-auto text-[#94A3B8] hover:text-[#DC2626]" aria-label="Supprimer le commentaire"><Trash2 size={12} /></button>}
                        </p>
                        <p className="mt-0.5 whitespace-pre-wrap text-[13px] text-[#334155]">{c.text}</p>
                      </div>
                    </li>
                  ))}
                </ul>
                {canEdit && (
                  <form className="mt-3 flex gap-2" onSubmit={async (e) => { e.preventDefault(); if (text.trim() && await act('c', () => teamAPI.comment(t.id, text.trim()))) setText(''); }}>
                    <input value={text} onChange={(e) => setText(e.target.value)} maxLength={3000} placeholder="Écrire un commentaire…" className={field} />
                    <button type="submit" disabled={!text.trim() || busy === 'c'} aria-label="Envoyer"
                            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-[#2F6BFF] text-white disabled:opacity-50"><Send size={16} /></button>
                  </form>
                )}
              </div>
            ) : (
              <ol className="relative mt-3 space-y-3 border-l-2 border-[#EEF2F8] pl-4">
                {d.events.map((e, i) => (
                  <li key={i} className="relative">
                    <span className="absolute -left-[21px] top-1.5 h-2.5 w-2.5 rounded-full border-2 border-white bg-[#2F6BFF]" />
                    <p className="text-[12.5px] text-[#0B1C3F]">{e.text}</p>
                    <p className="text-[11.5px] text-[#94A3B8]">{frDateTime(e.at)}{e.actor ? ` · ${e.actor.name}` : ''}</p>
                  </li>
                ))}
              </ol>
            )}
          </>
        )}
      </div>
    </Shell>
  );
}

/* ── one person: everything, by status ────────────────────────────────── */
export function MemberBreakdown({ member, week, onClose, onOpenTask }) {
  const [scope, setScope] = useState('week');
  const [d, setD] = useState(null);
  useEffect(() => {
    setD(null);
    teamAPI.breakdown(member.email, { week, scope }).then(({ data }) => setD(data)).catch(() => setD({ error: true }));
  }, [member.email, week, scope]);
  const c = d?.counts;
  const tiles = c ? [
    ['Tâches assignées', c.total, '#2F6BFF'], ['Terminées à temps', c.terminee, '#22C55E'], ['Terminées en retard', c.terminee_retard, '#F97316'],
    ['En retard (non terminées)', c.en_retard, '#EF4444'], ['À faire', c.a_faire, '#F5B70B'], ['Complétion', `${c.pct}%`, '#0B1C3F'],
  ] : [];
  return (
    <Shell title={(<span className="flex items-center gap-2.5"><Avatar name={member.name} size={32} />{member.name}</span>)} onClose={onClose} wide>
      <div className="mb-4 inline-flex rounded-xl bg-[#F1F5F9] p-1">
        {[['week', 'Cette semaine'], ['all', 'Depuis le début']].map(([k, l]) => (
          <button key={k} type="button" onClick={() => setScope(k)} className={`h-8 rounded-lg px-3 text-[12.5px] font-semibold ${scope === k ? 'bg-white text-[#0B1C3F] shadow-sm' : 'text-[#64748B]'}`}>{l}</button>
        ))}
      </div>
      {!d ? <p className="flex items-center gap-2 text-[13px] text-[#64748B]"><Loader2 size={15} className="animate-spin" /> Chargement…</p>
        : d.error ? <p className="text-[13px] text-[#B91C1C]">Détail indisponible.</p> : (
          <>
            <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
              {tiles.map(([l, v, col]) => (
                <div key={l} className="rounded-xl border border-[#EEF2F8] p-3">
                  <p className="text-[22px] font-bold leading-none" style={{ color: col }}>{v}</p>
                  <p className="mt-1 text-[12px] text-[#64748B]">{l}</p>
                </div>
              ))}
            </div>
            {c.done > 0 && (
              <p className="mt-3 text-[12.5px] text-[#475569]">
                Ponctualité : <b className="text-[#0B1C3F]">{c.on_time_pct}%</b> des tâches terminées l'ont été à temps
                {d.avg_late_minutes ? <> · retard moyen <b className="text-[#0B1C3F]">{lateText(d.avg_late_minutes)}</b></> : null}.
              </p>
            )}
            <div className="mt-4 space-y-4">
              {d.groups.filter((g) => g.tasks.length).map((g) => (
                <section key={g.key}>
                  <h4 className="mb-1.5 flex items-center gap-2 text-[13px] font-bold text-[#0B1C3F]">
                    <span className="h-2 w-2 rounded-full" style={{ background: STATUS[g.key].dot }} />{g.label} <span className="font-medium text-[#94A3B8]">({g.tasks.length})</span>
                  </h4>
                  <ul className="divide-y divide-[#F1F5F9] rounded-xl border border-[#EEF2F8]">
                    {g.tasks.map((t) => (
                      <li key={t.id}>
                        <button type="button" onClick={() => onOpenTask(t.id)} className="flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-[#F8FAFD]">
                          <span className="min-w-0 flex-1 truncate text-[13px] text-[#0B1C3F]">{t.title}</span>
                          <TypeChip type={t.type} />
                          <span className="whitespace-nowrap text-[11.5px] text-[#64748B]">{frDateTime(t.due_at)}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </section>
              ))}
              {!c.total && <p className="text-[13px] text-[#94A3B8]">Aucune tâche sur cette période.</p>}
            </div>
          </>
        )}
    </Shell>
  );
}

