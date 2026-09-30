import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Gauge, AlarmClock, CalendarCheck, Compass, UserX, FileClock, Hourglass, Moon, MailOpen, ChevronRight, Users, Activity, Target,
  TrendingUp, Loader2, Check, Pencil, ExternalLink, Plus,
} from 'lucide-react';
import { crmAPI } from '../../lib/api';
import { Modal, StageBadge, Avatar, nf, ago, BLUE, FUNNEL_BG } from './ui';

/* CRM › Vue d'ensemble › « Pilotage commercial » (features/crm_pilotage.py):
   what needs attention now, the sales team, the pipeline's health. Every
   line opens what to act on. */

const ICON = { alarm: AlarmClock, calendar: CalendarCheck, compass: Compass, user: UserX, file: FileClock, hourglass: Hourglass, moon: Moon, mail: MailOpen };
const TONE = { rose: ['#FFE4E6', '#E11D48'], violet: ['#F3E8FF', '#9333EA'], amber: ['#FFF4DB', '#D97706'], blue: ['#EAF1FF', '#2F6BFF'],
  slate: ['#F1F5F9', '#475569'], green: ['#E7F7EE', '#0F8B58'] };
const STAGE_BG = { a_contacter: FUNNEL_BG[1], contacte: FUNNEL_BG[2], rdv: FUNNEL_BG[3], proposition: FUNNEL_BG[4], essai: FUNNEL_BG[5], signe: FUNNEL_BG[6] };

const Panel = ({ icon: I, title, sub, children }) => (
  <section className="flex flex-col rounded-2xl border border-[#EDF1F7] bg-white p-4">
    <h3 className="flex items-center gap-2 text-[15px] font-bold text-[#0B1C3F]"><I size={18} className="text-[#2F6BFF]" /> {title}</h3>
    {sub && <p className="mb-3 text-[12px] text-[#64748B]">{sub}</p>}
    {children}
  </section>
);

export default function Pilotage({ data, meta, onTask, onNewTask, onDone }) {
  const navigate = useNavigate();
  const [open, setOpen] = useState(null);
  if (!data) {
    return <section className="mt-4 rounded-2xl border border-[#EDF1F7] bg-white p-6 text-center text-[13px] text-[#64748B]"><Loader2 size={15} className="mr-1 inline animate-spin" /> Chargement du pilotage…</section>;
  }
  const h = data.health;
  return (
    <section className="mt-4 rounded-2xl border border-[#EDF1F7] bg-[#FBFCFF] p-4 shadow-[0_1px_2px_rgba(11,28,63,.03)]">
      <header className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-[#EAF1FF] text-[#2F6BFF]"><Gauge size={21} /></span>
          <div>
            <h2 className="text-[18px] font-bold text-[#0B1C3F]">Pilotage commercial</h2>
            <p className="text-[13px] text-[#64748B]">Ce qui demande votre attention, la performance de votre équipe et la santé de votre pipeline.</p>
          </div>
        </div>
        <span className={`rounded-lg px-3 py-1.5 text-[13px] font-semibold ${data.total ? 'bg-[#FFF1F2] text-[#E11D48]' : 'bg-[#E7F7EE] text-[#0F8B58]'}`}>
          {data.total ? `${nf(data.total)} point${data.total > 1 ? 's' : ''} à traiter` : 'Tout est à jour'}</span>
      </header>

      <div className="grid gap-4 xl:grid-cols-[1fr_1.15fr_1fr]">
        {/* À traiter maintenant */}
        <Panel icon={AlarmClock} title="À traiter maintenant" sub="Cliquez sur une ligne pour agir.">
          <ul className="space-y-1.5">
            {data.attention.map((a) => { const I = ICON[a.icon] || Target; const [bg, fg] = TONE[a.tone] || TONE.blue; const zero = !a.count; return (
              <li key={a.key}>
                <button type="button" disabled={zero} onClick={() => setOpen(a)}
                        className={`flex w-full items-center gap-2.5 rounded-xl border px-2.5 py-2 text-left text-[12.5px] transition ${zero ? 'border-transparent opacity-55' : 'border-[#EEF2F8] bg-white hover:border-[#2F6BFF]'}`}>
                  <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg" style={{ background: bg, color: fg }}><I size={15} /></span>
                  <span className="flex-1 text-[#334155]">{a.label}</span>
                  <span className={`min-w-[28px] rounded-md px-1.5 py-0.5 text-center text-[12px] font-bold ${zero ? 'bg-[#F1F5F9] text-[#94A3B8]' : ''}`} style={zero ? undefined : { background: bg, color: fg }}>{nf(a.count)}</span>
                  {!zero && <ChevronRight size={14} className="text-[#94A3B8]" />}
                </button>
              </li>); })}
          </ul>
        </Panel>

        {/* Équipe commerciale */}
        <Panel icon={Users} title="Équipe commerciale" sub="Sur la période choisie en haut de page. Cliquez pour voir ses prospects.">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[420px] text-[12.5px]">
              <thead><tr className="text-left text-[11.5px] text-[#64748B]">{['Commercial', 'Actifs', 'En retard', 'Appels', 'Signés', 'Conversion'].map((x) => <th key={x} className="px-1.5 py-1.5 font-medium">{x}</th>)}</tr></thead>
              <tbody>
                {data.team.map((m) => (
                  <tr key={m.email} onClick={() => navigate(`/admin/crm/prospects?assigned=${encodeURIComponent(m.email)}`)} className="cursor-pointer border-t border-[#F1F5F9] hover:bg-[#F8FAFF]">
                    <td className="px-1.5 py-2">{m.email === 'none' ? <span className="font-medium text-[#94A3B8]">Non assigné</span> : <Avatar name={m.name} size={24} />}</td>
                    <td className="px-1.5 py-2 font-semibold text-[#0B1C3F]">{nf(m.active)}</td>
                    <td className="px-1.5 py-2">{m.overdue ? <span className="rounded-md bg-[#FFE4E6] px-1.5 py-0.5 font-semibold text-[#E11D48]">{m.overdue}</span> : <span className="text-[#94A3B8]">0</span>}</td>
                    <td className="px-1.5 py-2 text-[#475569]">{nf(m.calls)}</td>
                    <td className="px-1.5 py-2">{m.signed_period ? <span className="rounded-md bg-[#E7F7EE] px-1.5 py-0.5 font-semibold text-[#0F8B58]">+{m.signed_period}</span> : <span className="text-[#94A3B8]">0</span>}</td>
                    <td className="px-1.5 py-2">
                      {m.conversion === null ? <span className="text-[#94A3B8]">—</span> : (
                        <span className="flex items-center gap-1.5"><span className="h-1.5 w-12 overflow-hidden rounded-full bg-[#EEF2F8]"><span className="block h-full rounded-full bg-[#10B981]" style={{ width: `${Math.min(100, m.conversion)}%` }} /></span>
                          <span className="text-[#475569]">{m.conversion} %</span></span>)}
                    </td>
                  </tr>
                ))}
                {!data.team.length && <tr><td colSpan={6} className="py-6 text-center text-[#94A3B8]">Aucun prospect assigné pour le moment.</td></tr>}
              </tbody>
            </table>
          </div>
        </Panel>

        {/* Santé du pipeline */}
        <Panel icon={Activity} title="Santé du pipeline" sub="Passage à l'étape suivante sur la période, temps moyen par étape.">
          <ul className="space-y-1.5">
            {h.stages.map((s) => (
              <li key={s.key}>
                <button type="button" onClick={() => navigate(`/admin/crm/prospects?stage=${s.key}`)} className="grid w-full grid-cols-[1fr_auto] items-center gap-2 rounded-xl px-2.5 py-1.5 text-left hover:ring-1 hover:ring-[#2F6BFF]" style={{ background: STAGE_BG[s.key] }}>
                  <span className="min-w-0">
                    <span className="block text-[12.5px] font-semibold text-[#0B1C3F]">{s.label} <span className="font-normal text-[#475569]">· {nf(s.count)}</span></span>
                    <span className="block text-[11.5px] text-[#64748B]">
                      {s.next ? (s.conversion === null ? `→ ${s.next} : —` : `→ ${s.next} : ${s.conversion} %`) : 'Clients gagnés'}
                      {s.avg_days !== null && ` · ${s.avg_days} j en moyenne`}
                    </span>
                  </span>
                  {s.stale > 0 ? <span className="rounded-md bg-white/80 px-1.5 py-0.5 text-[11px] font-medium text-[#D97706]" title="Sans activité depuis 14 jours">{s.stale} en sommeil</span> : <ChevronRight size={14} className="text-[#94A3B8]" />}
                </button>
              </li>
            ))}
          </ul>
          <div className="mt-3 grid grid-cols-2 gap-2">
            <p className="rounded-xl bg-white px-3 py-2 ring-1 ring-[#EEF2F8]" title={`Propositions × ${h.forecast_basis.proposition ?? '—'} % et essais × ${h.forecast_basis.essai ?? '—'} % (taux passés)`}>
              <span className="flex items-center gap-1 text-[11.5px] text-[#64748B]"><TrendingUp size={13} className="text-[#10B981]" /> Signatures attendues</span>
              <strong className="text-[20px] text-[#0B1C3F]">{nf(h.forecast)}</strong></p>
            <p className="rounded-xl bg-white px-3 py-2 ring-1 ring-[#EEF2F8]">
              <span className="flex items-center gap-1 text-[11.5px] text-[#64748B]"><Target size={13} className="text-[#2F6BFF]" /> Taux de gain</span>
              <strong className="text-[20px] text-[#0B1C3F]">{h.win_rate === null ? '—' : `${h.win_rate} %`}</strong></p>
          </div>
        </Panel>
      </div>

      {open && <AttentionModal item={open} meta={meta} onClose={() => setOpen(null)} onTask={(t) => { setOpen(null); onTask(t); }}
                               onNewTask={(pid) => { setOpen(null); onNewTask(pid); }} onDone={onDone} />}
    </section>
  );
}

function AttentionModal({ item, meta, onClose, onTask, onNewTask, onDone }) {
  const navigate = useNavigate();
  const [d, setD] = useState(null);
  const [busy, setBusy] = useState(null);
  const load = () => crmAPI.pilotageList(item.key).then(({ data }) => setD(data)).catch(() => setD({ rows: [], kind: 'prospects' }));
  React.useEffect(() => { load(); }, [item.key]); // eslint-disable-line react-hooks/exhaustive-deps
  const act = async (id, fn, msg) => { setBusy(id); try { await fn(); onDone(msg); load(); } catch (e) { onDone(typeof e?.response?.data?.detail === 'string' ? e.response.data.detail : 'Action impossible.'); } setBusy(null); };
  const btn = 'inline-flex items-center gap-1 rounded-md border border-[#DCE3EE] bg-white px-2.5 py-1 text-[12px] text-[#2F6BFF] hover:border-[#2F6BFF] disabled:opacity-50';
  return (
    <Modal title={`${item.label} (${item.count})`} onClose={onClose} wide>
      {!d ? <p className="py-8 text-center text-[13px] text-[#64748B]"><Loader2 size={15} className="mr-1 inline animate-spin" /> Chargement…</p> : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-[12.5px]">
            {d.kind === 'tasks' ? (
              <>
                <thead><tr className="text-left text-[#64748B]">{['Tâche', 'Commerce', 'Échéance', 'Assigné à', ''].map((x) => <th key={x} className="px-2 py-2 font-medium">{x}</th>)}</tr></thead>
                <tbody>
                  {d.rows.map((t) => (
                    <tr key={t.id} className="border-t border-[#F1F5F9]">
                      <td className="px-2 py-2.5 font-medium text-[#0B1C3F]">{t.title}</td>
                      <td className="px-2 py-2.5 text-[#475569]">{t.prospect || '—'}</td>
                      <td className="px-2 py-2.5"><span className={`rounded-md px-2 py-0.5 text-[11.5px] font-medium ${t.status === 'en_retard' ? 'bg-[#FEE2E2] text-[#B91C1C]' : 'bg-[#F3E8FF] text-[#7E22CE]'}`}>{new Date(t.due_at).toLocaleString('fr-FR', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}</span></td>
                      <td className="px-2 py-2.5"><Avatar name={t.assigned_name} /></td>
                      <td className="px-2 py-2.5 text-right">
                        <span className="inline-flex gap-1.5">
                          {item.key === 'rdv_confirm'
                            ? <button type="button" disabled={busy === t.id} onClick={() => act(t.id, () => crmAPI.editTask(t.id, { confirm_status: 'confirme' }), 'Rendez-vous confirmé.')} className={btn}><Check size={12} /> Confirmer</button>
                            : <button type="button" disabled={busy === t.id} onClick={() => act(t.id, () => crmAPI.editTask(t.id, { status: 'terminee' }), 'Tâche terminée.')} className={btn}><Check size={12} /> Terminer</button>}
                          <button type="button" onClick={() => onTask(t)} className={btn}><Pencil size={12} /> Replanifier</button>
                        </span>
                      </td>
                    </tr>))}
                </tbody>
              </>
            ) : (
              <>
                <thead><tr className="text-left text-[#64748B]">{['Commerce', 'Étape', 'Commercial', 'Dernière activité', ''].map((x) => <th key={x} className="px-2 py-2 font-medium">{x}</th>)}</tr></thead>
                <tbody>
                  {d.rows.map((p) => (
                    <tr key={p.id} className="border-t border-[#F1F5F9]">
                      <td className="px-2 py-2.5"><span className="font-medium text-[#0B1C3F]">{p.name}</span><span className="block text-[11.5px] text-[#94A3B8]">{[p.sector, p.city].filter(Boolean).join(' · ')}</span></td>
                      <td className="px-2 py-2.5"><StageBadge stage={p.stage} label={p.stage_label} /></td>
                      <td className="px-2 py-2.5">
                        {item.key === 'unassigned' ? (
                          <select defaultValue="" disabled={busy === p.id} onChange={(e) => e.target.value && act(p.id, () => crmAPI.editProspect(p.id, { assigned_to: e.target.value }), 'Prospect assigné.')}
                                  className="h-8 rounded-lg border border-[#DCE3EE] bg-white px-2 text-[12px]">
                            <option value="">Assigner à…</option>{(meta?.users || []).filter((u) => u.active !== false).map((u) => <option key={u.email} value={u.email}>{u.name}</option>)}
                          </select>) : <Avatar name={p.assigned_name} />}
                      </td>
                      <td className="px-2 py-2.5 text-[#475569]">{p.last_activity_at ? ago(p.last_activity_at) : '—'}</td>
                      <td className="px-2 py-2.5 text-right">
                        <span className="inline-flex gap-1.5">
                          <button type="button" onClick={() => onNewTask(p.id)} className={btn}><Plus size={12} /> Tâche</button>
                          <button type="button" onClick={() => navigate(`/admin/crm/prospects?open=${p.id}`)} className="inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-[12px] font-medium text-white" style={{ background: BLUE }}><ExternalLink size={12} /> Ouvrir</button>
                        </span>
                      </td>
                    </tr>))}
                </tbody>
              </>
            )}
            {!d.rows.length && <tbody><tr><td colSpan={5} className="py-8 text-center text-[#64748B]">Plus rien à traiter ici.</td></tr></tbody>}
          </table>
        </div>
      )}
    </Modal>
  );
}
