import React, { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Plus, Send, Pencil, Trash2, Loader2, AlertTriangle } from 'lucide-react';
import { adminAPI } from '../../../lib/api';
import { Breadcrumb, Loading, Modal, useToast, BLUE, inputCls } from '../../crm/ui';
import { AiTabs, day } from './shared';

/* FIDCLIC AI › Rapports automatiques — a saved analysis emailed every week or
   month (daily cron, Brevo mailer). */

const DAYS = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche'];
const when = (r) => (r.frequency === 'weekly' ? `Chaque ${DAYS[r.weekday]}` : `Le ${r.monthday} de chaque mois`);

function Switch({ on, onChange }) {
  return (
    <button type="button" role="switch" aria-checked={on} onClick={() => onChange(!on)} className={`relative h-6 w-11 rounded-full transition ${on ? 'bg-[#10B981]' : 'bg-[#E2E8F0]'}`}>
      <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition ${on ? 'left-[22px]' : 'left-0.5'}`} />
    </button>
  );
}

export default function AiReportsPage() {
  const [params, setParams] = useSearchParams();
  const [d, setD] = useState(null);
  const [modal, setModal] = useState(null);
  const [busy, setBusy] = useState(null);
  const [say, toast] = useToast();
  const load = useCallback(() => { adminAPI.aiReports().then(({ data }) => setD(data)).catch(() => setD({ rows: [], saved: [] })); }, []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    const sid = params.get('saved');
    if (sid && d) { setModal({ report: null, saved_id: sid }); params.delete('saved'); setParams(params, { replace: true }); }
  }, [d]); // eslint-disable-line react-hooks/exhaustive-deps

  const act = async (fn, ok) => { try { await fn(); say(ok); load(); } catch (e) { say(typeof e?.response?.data?.detail === 'string' ? e.response.data.detail : 'Action impossible.'); } };
  const sendNow = async (r) => { setBusy(r.id); await act(() => adminAPI.aiSendReport(r.id), 'Rapport envoyé.'); setBusy(null); };

  if (!d) return <Loading />;
  return (
    <div className="crm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Breadcrumb items={[['Super Admin', '/admin'], ['FIDCLIC AI', '/admin/ai'], ['Rapports automatiques']]} />
          <h1 className="text-[28px] font-bold leading-tight text-[#0B1C3F]">Rapports automatiques</h1>
          <p className="mb-3 text-[15px] text-[#475569]">Recevez une analyse par email, chaque semaine ou chaque mois, calculée le jour même.</p>
        </div>
        <button type="button" disabled={!d.saved.length} onClick={() => setModal({ report: null })} className="inline-flex h-11 items-center gap-2 rounded-xl px-4 text-[13.5px] font-medium text-white disabled:opacity-50" style={{ background: BLUE }}><Plus size={16} /> Nouveau rapport</button>
      </div>
      <AiTabs />
      {!d.saved.length && <p className="mb-3 rounded-xl bg-[#EFF5FF] px-4 py-2.5 text-[13px] text-[#1E4FD8]">Sauvegardez d'abord une analyse dans « AI Intelligence » : un rapport envoie une analyse sauvegardée.</p>}
      <section className="rounded-2xl border border-[#EDF1F7] bg-white p-4 shadow-[0_1px_2px_rgba(11,28,63,.03)]">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[860px] text-[12.5px]">
            <thead><tr className="border-b border-[#EDF1F7] text-left text-[#64748B]">{['Analyse', 'Fréquence', 'Destinataires', 'Prochain envoi', 'Dernier envoi', 'Actif', ''].map((h) => <th key={h} className="px-2 py-2 font-medium">{h}</th>)}</tr></thead>
            <tbody>
              {d.rows.map((r) => (
                <tr key={r.id} className="border-b border-[#F4F7FC]">
                  <td className="px-2 py-2.5 font-semibold text-[#0B1C3F]">{r.title}</td>
                  <td className="px-2 py-2.5 text-[#475569]">{when(r)}</td>
                  <td className="px-2 py-2.5 text-[#475569]">{r.recipients.join(', ')}</td>
                  <td className="px-2 py-2.5 text-[#475569]">{r.active ? day(r.next_at) : '—'}</td>
                  <td className="px-2 py-2.5 text-[#475569]">{r.last_sent_at ? day(r.last_sent_at) : 'Jamais'}{r.last_error && <span className="mt-0.5 flex items-center gap-1 text-[11.5px] text-[#E11D48]"><AlertTriangle size={12} /> {r.last_error}</span>}</td>
                  <td className="px-2 py-2.5"><Switch on={r.active} onChange={(v) => act(() => adminAPI.aiEditReport(r.id, { ...r, active: v }), v ? 'Rapport activé.' : 'Rapport en pause.')} /></td>
                  <td className="px-2 py-2.5 text-right">
                    <span className="inline-flex gap-1.5">
                      <button type="button" onClick={() => sendNow(r)} disabled={busy === r.id} className="inline-flex items-center gap-1 rounded-lg border border-[#DCE3EE] px-2.5 py-1 text-[12px] text-[#2F6BFF] disabled:opacity-60">{busy === r.id ? <Loader2 size={12} className="animate-spin" /> : <Send size={12} />} Envoyer maintenant</button>
                      <button type="button" aria-label="Modifier" onClick={() => setModal({ report: r })} className="rounded-lg border border-[#DCE3EE] p-1.5 text-[#2F6BFF]"><Pencil size={13} /></button>
                      <button type="button" aria-label="Supprimer" onClick={() => window.confirm('Supprimer ce rapport ?') && act(() => adminAPI.aiDeleteReport(r.id), 'Rapport supprimé.')} className="rounded-lg border border-[#FCA5A5] bg-[#FEF2F2] p-1.5 text-[#E11D48]"><Trash2 size={13} /></button>
                    </span>
                  </td>
                </tr>
              ))}
              {!d.rows.length && <tr><td colSpan={7} className="py-10 text-center text-[#64748B]">Aucun rapport automatique pour le moment.</td></tr>}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-[12px] text-[#94A3B8]">Envoi le matin du jour prévu. Les emails partent par Brevo : sans configuration email, l'envoi échoue et l'erreur s'affiche ici.</p>
      </section>
      {toast}
      {modal && <ReportModal report={modal.report} savedId={modal.saved_id} saved={d.saved} onClose={() => setModal(null)} onDone={(m) => { setModal(null); say(m); load(); }} />}
    </div>
  );
}

function ReportModal({ report, savedId, saved, onClose, onDone }) {
  const [f, setF] = useState({ saved_id: report?.saved_id || savedId || saved[0]?.id || '', frequency: report?.frequency || 'weekly',
                               weekday: report?.weekday ?? 0, monthday: report?.monthday ?? 1, recipients: (report?.recipients || []).join(', '),
                               active: report ? report.active : true });
  const [err, setErr] = useState('');
  const save = async () => {
    const body = { ...f, weekday: Number(f.weekday), monthday: Number(f.monthday), recipients: f.recipients.split(/[,;\s]+/).filter(Boolean) };
    try { if (report) await adminAPI.aiEditReport(report.id, body); else await adminAPI.aiCreateReport(body); onDone(report ? 'Rapport modifié.' : 'Rapport programmé.'); }
    catch (e) { setErr(typeof e?.response?.data?.detail === 'string' ? e.response.data.detail : 'Enregistrement impossible.'); }
  };
  const sel = 'h-10 w-full rounded-lg border border-[#DCE3EE] bg-white px-3 text-[13.5px]';
  return (
    <Modal title={report ? 'Modifier le rapport' : 'Nouveau rapport automatique'} onClose={onClose}>
      <div className="space-y-3 text-[13px]">
        <label className="block"><span className="mb-1 block text-[11.5px] text-[#64748B]">Analyse</span>
          <select className={sel} value={f.saved_id} onChange={(e) => setF({ ...f, saved_id: e.target.value })}>{saved.map((s) => <option key={s.id} value={s.id}>{s.title}</option>)}</select></label>
        <div className="grid grid-cols-2 gap-2">
          <label className="block"><span className="mb-1 block text-[11.5px] text-[#64748B]">Fréquence</span>
            <select className={sel} value={f.frequency} onChange={(e) => setF({ ...f, frequency: e.target.value })}><option value="weekly">Chaque semaine</option><option value="monthly">Chaque mois</option></select></label>
          {f.frequency === 'weekly'
            ? <label className="block"><span className="mb-1 block text-[11.5px] text-[#64748B]">Jour</span><select className={sel} value={f.weekday} onChange={(e) => setF({ ...f, weekday: e.target.value })}>{DAYS.map((x, i) => <option key={x} value={i}>{x}</option>)}</select></label>
            : <label className="block"><span className="mb-1 block text-[11.5px] text-[#64748B]">Jour du mois</span><select className={sel} value={f.monthday} onChange={(e) => setF({ ...f, monthday: e.target.value })}>{Array.from({ length: 28 }, (_, i) => <option key={i + 1} value={i + 1}>{i + 1}</option>)}</select></label>}
        </div>
        <label className="block"><span className="mb-1 block text-[11.5px] text-[#64748B]">Destinataires (séparés par des virgules)</span>
          <textarea className={`${inputCls} h-20 py-2`} value={f.recipients} onChange={(e) => setF({ ...f, recipients: e.target.value })} placeholder="meriem@fidclic.com, admin@fidclic.com" /></label>
        <label className="flex items-center gap-2"><input type="checkbox" checked={f.active} onChange={(e) => setF({ ...f, active: e.target.checked })} className="h-4 w-4 accent-[#2F6BFF]" /> Actif</label>
        {err && <p className="text-[13px] text-[#C0392B]">{err}</p>}
        <button type="button" disabled={!f.saved_id || !f.recipients.trim()} onClick={save} className="w-full rounded-lg py-2.5 text-[13.5px] font-semibold text-white disabled:opacity-50" style={{ background: BLUE }}>Enregistrer</button>
      </div>
    </Modal>
  );
}
