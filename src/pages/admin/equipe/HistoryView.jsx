import React, { useEffect, useState } from 'react';
import { Download, Search, Loader2, Repeat } from 'lucide-react';
import { teamAPI } from '../../../lib/api';
import { Pager, downloadBlob } from '../../crm/ui';
import { Avatar, TypeChip, PriorityPill, StatusBadge, frDateTime, todayParis, STATUS } from './shared';

/* Super admin › Suivi d'équipe › Historique (user, 2026-10-08: « purane tasks
   ka info kaise milega »): every task ever made, filtered, paged, exported. */

const monthAgo = () => {
  const d = new Date(`${todayParis()}T12:00:00`);
  d.setMonth(d.getMonth() - 1);
  return d.toISOString().slice(0, 10);
};
const sel = 'h-10 rounded-xl border border-[#E3E9F3] bg-white px-3 text-[13px] text-[#0B1C3F] outline-none focus:border-[#2F6BFF]';

export default function HistoryView({ onOpenTask, refreshKey }) {
  const [f, setF] = useState({ date_from: monthAgo(), date_to: todayParis(), member: '', type_id: '', status: '', priority: '', q: '' });
  const [typed, setTyped] = useState('');
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(20);
  const [d, setD] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => { const id = setTimeout(() => setF((x) => ({ ...x, q: typed })), 300); return () => clearTimeout(id); }, [typed]);
  useEffect(() => { setPage(1); }, [f]);
  useEffect(() => {
    let alive = true;
    setBusy(true);
    teamAPI.history({ ...f, page, per_page: perPage })
      .then(({ data }) => { if (alive) { setD(data); setError(''); } })
      .catch((e) => alive && setError(e?.response?.data?.detail || "L'historique n'a pas pu être chargé."))
      .finally(() => alive && setBusy(false));
    return () => { alive = false; };
  }, [f, page, perPage, refreshKey]);

  const set = (k) => (e) => setF((x) => ({ ...x, [k]: e.target.value }));
  const s = d?.summary;
  return (
    <section className="rounded-2xl border border-[#E8EEF7] bg-white p-4 shadow-[0_1px_2px_rgba(11,28,63,.03)] sm:p-5">
      <div className="flex flex-wrap items-end gap-2.5">
        <label className="text-[12px] font-semibold text-[#475569]">Du<input type="date" value={f.date_from} onChange={set('date_from')} className={`${sel} mt-1 block`} /></label>
        <label className="text-[12px] font-semibold text-[#475569]">Au<input type="date" value={f.date_to} onChange={set('date_to')} className={`${sel} mt-1 block`} /></label>
        <select value={f.member} onChange={set('member')} className={sel} aria-label="Membre">
          <option value="">Tous les membres</option>
          {(d?.members || []).map((m) => <option key={m.email} value={m.email}>{m.name}</option>)}
        </select>
        <select value={f.type_id} onChange={set('type_id')} className={sel} aria-label="Type">
          <option value="">Tous les types</option><option value="none">Sans type</option>
          {(d?.types || []).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
        <select value={f.status} onChange={set('status')} className={sel} aria-label="Statut">
          <option value="">Tous les statuts</option>
          <option value="a_faire">À faire</option>
          <option value="en_retard">En retard (toutes)</option>
          <option value="terminee">Terminées (toutes)</option>
          <option value="terminee_retard">Terminées en retard</option>
          <option value="supprimee">Supprimées</option>
          <option value="toutes">Toutes, supprimées comprises</option>
        </select>
        <select value={f.priority} onChange={set('priority')} className={sel} aria-label="Priorité">
          <option value="">Toutes priorités</option><option value="haute">Haute</option><option value="moyenne">Moyenne</option><option value="basse">Basse</option>
        </select>
        <label className="relative min-w-[200px] flex-1">
          <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
          <input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="Rechercher une tâche…" className={`${sel} w-full pl-9`} />
        </label>
        <button type="button" onClick={() => downloadBlob(teamAPI.historyExport(f), 'suivi-equipe.csv')}
                className="inline-flex h-10 items-center gap-1.5 rounded-xl border border-[#E3E9F3] bg-white px-3.5 text-[13px] font-semibold text-[#334155] hover:border-[#2F6BFF]">
          <Download size={15} /> Exporter
        </button>
      </div>

      {s && (
        <div className="mt-4 flex flex-wrap gap-2 text-[12.5px]">
          {[['Total', s.total, '#2F6BFF'], ['Terminées à temps', s.terminee, STATUS.terminee.dot], ['Terminées en retard', s.terminee_retard, STATUS.terminee_retard.dot],
            ['En retard', s.en_retard, STATUS.en_retard.dot], ['À faire', s.a_faire, STATUS.a_faire.dot]].map(([l, v, c]) => (
            <span key={l} className="inline-flex items-center gap-1.5 rounded-lg bg-[#F6F8FC] px-2.5 py-1.5 text-[#475569]">
              <span className="h-2 w-2 rounded-full" style={{ background: c }} />{l} <b className="text-[#0B1C3F]">{v}</b>
            </span>
          ))}
        </div>
      )}

      {error && <p className="mt-4 rounded-lg bg-[#FEF2F2] px-3 py-2 text-[12.5px] text-[#B91C1C]">{error}</p>}
      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[860px] border-collapse">
          <thead>
            <tr className="border-b border-[#EEF2F8] text-left text-[11.5px] font-semibold text-[#64748B]">
              {['Tâche', 'Assignée à', 'Échéance', 'Statut', 'Terminée le', 'Priorité'].map((h) => <th key={h} className="px-2 py-2.5">{h}</th>)}
            </tr>
          </thead>
          <tbody>
            {(d?.rows || []).map((t) => (
              <tr key={t.id} onClick={() => onOpenTask(t.id)} className="cursor-pointer border-b border-[#F4F7FC] last:border-b-0 hover:bg-[#F8FAFD]">
                <td className="max-w-[320px] px-2 py-2.5">
                  <span className="flex items-center gap-1.5 truncate text-[13px] font-semibold text-[#0B1C3F]">{t.title}{t.repeat && <Repeat size={12} className="shrink-0 text-[#2F6BFF]" />}</span>
                  <span className="mt-0.5 block"><TypeChip type={t.type} /></span>
                </td>
                <td className="px-2 py-2.5">
                  <span className="flex flex-wrap gap-1.5">{t.assignees.map((a) => <span key={a.email} className="inline-flex items-center gap-1 text-[12.5px] text-[#334155]"><Avatar name={a.name} size={20} />{a.name}</span>)}</span>
                </td>
                <td className="whitespace-nowrap px-2 py-2.5 text-[12.5px] text-[#334155]">{frDateTime(t.due_at)}</td>
                <td className="px-2 py-2.5"><StatusBadge s={t.status} late={t.status === 'en_retard' || t.status === 'terminee_retard' ? t.late_by_minutes : 0} /></td>
                <td className="whitespace-nowrap px-2 py-2.5 text-[12.5px] text-[#334155]">{t.completed_at ? `${frDateTime(t.completed_at)}${t.completed_by ? ` · ${t.completed_by.name}` : ''}` : '—'}</td>
                <td className="px-2 py-2.5"><PriorityPill p={t.priority} /></td>
              </tr>
            ))}
          </tbody>
        </table>
        {busy && !d && <p className="flex items-center justify-center gap-2 py-12 text-[13px] text-[#64748B]"><Loader2 size={15} className="animate-spin" /> Chargement…</p>}
        {d && !d.rows.length && <p className="py-12 text-center text-[13px] text-[#64748B]">Aucune tâche ne correspond à ces filtres.</p>}
      </div>
      {d && d.total > 0 && <Pager page={d.page} pages={d.pages} total={d.total} perPage={perPage} onPage={setPage} onPerPage={(n) => { setPerPage(n); setPage(1); }} what="tâches" />}
    </section>
  );
}
