import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Bookmark, Play, Trash2, FileBarChart, Loader2, Download } from 'lucide-react';
import { adminAPI } from '../../../lib/api';
import { Breadcrumb, Loading, Modal, useToast, downloadBlob, BLUE } from '../../crm/ui';
import { AiTabs, ResultTable, ResultCharts, Robot, day } from './shared';

/* FIDCLIC AI › Analyses sauvegardées — recalculated on today's data when opened. */

export default function AiSavedPage() {
  const navigate = useNavigate();
  const [rows, setRows] = useState(null);
  const [open, setOpen] = useState(null);
  const [busy, setBusy] = useState(null);
  const [say, toast] = useToast();
  const load = useCallback(() => { adminAPI.aiSaved().then(({ data }) => setRows(data.rows)).catch(() => setRows([])); }, []);
  useEffect(() => { load(); }, [load]);

  const run = async (s) => {
    setBusy(s.id);
    try { const { data } = await adminAPI.aiRunSaved(s.id); setOpen({ s, res: data }); load(); }
    catch (e) { say("L'analyse n'a pas pu être relancée."); }
    setBusy(null);
  };
  const remove = async (s) => {
    if (!window.confirm(`Supprimer « ${s.title} » ? Ses rapports automatiques seront supprimés aussi.`)) return;
    try { await adminAPI.aiDeleteSaved(s.id); say('Analyse supprimée.'); load(); } catch (e) { say('Suppression impossible.'); }
  };

  if (!rows) return <Loading />;
  return (
    <div className="crm">
      <Breadcrumb items={[['Super Admin', '/admin'], ['FIDCLIC AI', '/admin/ai'], ['Analyses sauvegardées']]} />
      <h1 className="text-[28px] font-bold leading-tight text-[#0B1C3F]">Analyses sauvegardées</h1>
      <p className="mb-3 text-[15px] text-[#475569]">Vos analyses favorites, recalculées sur les données du jour à chaque ouverture.</p>
      <AiTabs />
      <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
        {rows.map((s) => (
          <section key={s.id} className="flex flex-col rounded-2xl border border-[#EDF1F7] bg-white p-4 shadow-[0_1px_2px_rgba(11,28,63,.03)]">
            <div className="mb-2 flex items-start gap-3">
              <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-[#EAF1FF] text-[#2F6BFF]"><Bookmark size={18} /></span>
              <div className="min-w-0 flex-1"><p className="truncate text-[15px] font-bold text-[#0B1C3F]">{s.title}</p>
                <p className="truncate text-[12px] text-[#64748B]">« {s.question} » · {s.days} derniers jours</p></div>
            </div>
            <p className="flex-1 rounded-lg bg-[#F8FAFF] px-3 py-2 text-[12.5px] text-[#334155]">{s.last_headline}</p>
            <p className="mt-2 text-[11.5px] text-[#94A3B8]">Dernier calcul : {day(s.last_run_at)} · par {s.created_by}</p>
            <div className="mt-3 flex gap-2">
              <button type="button" onClick={() => run(s)} disabled={busy === s.id} className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg py-2 text-[12.5px] font-semibold text-white disabled:opacity-60" style={{ background: BLUE }}>
                {busy === s.id ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />} Ouvrir</button>
              <button type="button" onClick={() => navigate(`/admin/ai/rapports?saved=${s.id}`)} className="inline-flex items-center gap-1.5 rounded-lg border border-[#DCE3EE] px-3 text-[12.5px] text-[#2F6BFF]"><FileBarChart size={14} /> Rapport</button>
              <button type="button" aria-label="Supprimer" onClick={() => remove(s)} className="rounded-lg border border-[#FCA5A5] bg-[#FEF2F2] px-3 text-[#E11D48]"><Trash2 size={14} /></button>
            </div>
          </section>
        ))}
        {!rows.length && (
          <section className="rounded-2xl border border-dashed border-[#C9D6EA] bg-white p-10 text-center md:col-span-2 2xl:col-span-3">
            <div className="mx-auto w-fit"><Robot size={80} /></div>
            <p className="mt-2 text-[14px] text-[#475569]">Aucune analyse sauvegardée. Posez une question dans « AI Intelligence », puis « Sauvegarder ».</p>
            <button type="button" onClick={() => navigate('/admin/ai')} className="mt-3 rounded-lg px-4 py-2 text-[13px] font-semibold text-white" style={{ background: BLUE }}>Poser une question</button>
          </section>
        )}
      </div>
      {toast}
      {open && (
        <Modal title={open.s.title} onClose={() => setOpen(null)} wide>
          <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
            <div><p className="text-[15px] font-semibold text-[#0B1C3F]">{open.res.headline}</p><p className="text-[13px] text-[#64748B]">{open.res.detail}</p></div>
            {open.res.rows?.length > 0 && <button type="button" onClick={() => downloadBlob(adminAPI.aiExport(open.res.key, { question: open.s.question }), `fidclic-ai-${open.res.key}.csv`)}
                                                 className="inline-flex h-10 items-center gap-1.5 rounded-lg border border-[#2F6BFF] px-3 text-[13px] font-medium text-[#2F6BFF]"><Download size={15} /> Exporter (CSV)</button>}
          </div>
          <ResultTable res={open.res} onOpen={() => {}} />
          <div className="mt-4"><ResultCharts charts={open.res.charts} /></div>
        </Modal>
      )}
    </div>
  );
}
