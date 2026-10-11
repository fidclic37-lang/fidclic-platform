import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft, Plus, Pencil, MessageSquare, Zap } from 'lucide-react';
import { ownerAPI } from '../lib/api';
import { ICONS, TONES, EXAMPLES } from '../components/automations/meta';

/**
 * « Exemples de messages » — ready-made words for each automation. A first
 * version from the Automatisations mockup; the user sends this page's own
 * mockups next (2026-10-11).
 */
const GROUPS = ['Tous', 'Fidélisation', 'Réactivation', 'Avis', 'Géolocalisation'];

export default function AutomationExamplesPage() {
  const navigate = useNavigate();
  const [d, setD] = useState(null);
  const [group, setGroup] = useState('Tous');
  useEffect(() => { ownerAPI.automations().then(({ data }) => setD(data)).catch(() => setD({ scenarios: [], can_edit: false })); }, []);
  const can = Boolean(d?.can_edit);
  const shown = EXAMPLES.map((ex, i) => ({ ...ex, i })).filter((ex) => group === 'Tous' || ex.group === group);
  const use = (ex, step) => navigate(`/dashboard/automations/nouvelle?scenario=${ex.scenario}&ex=${ex.i}${step ? `&step=${step}` : ''}`);

  return (
    <div className="pb-10">
      <header className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-4">
          <button type="button" onClick={() => navigate('/dashboard/automations')} aria-label="Retour aux automatisations"
                  className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-[#EEF4FF] text-[#1463FF]"><ArrowLeft size={22} /></button>
          <div>
            <h1 className="text-[30px] font-extrabold leading-tight text-[#0B1C3F]">Exemples de messages</h1>
            <p className="text-[15px] text-[#475569]">Des messages prêts à l'emploi pour chaque automatisation. Utilisez-les tels quels ou personnalisez-les.</p>
          </div>
        </div>
        {can && (
          <button type="button" onClick={() => navigate('/dashboard/automations/nouvelle')}
                  className="inline-flex items-center gap-2 rounded-xl bg-[#1463FF] px-6 py-3.5 text-[15px] font-semibold text-white">
            <Plus size={19} /> Créer une automatisation</button>
        )}
      </header>
      <div className="mb-5 flex flex-wrap gap-2">
        {GROUPS.map((g) => (
          <button key={g} type="button" onClick={() => setGroup(g)}
                  className={`rounded-xl border px-5 py-2.5 text-[14.5px] font-semibold ${group === g ? 'border-[#1463FF] bg-[#1463FF] text-white' : 'border-[#E2E8F0] bg-white text-[#334155]'}`}>{g}</button>
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        {shown.map((ex) => {
          const sc = d?.scenarios?.find((x) => x.key === ex.scenario);
          const I = ICONS[sc?.icon] || MessageSquare;
          const [bg, fg] = TONES[sc?.tone] || TONES.blue;
          const vars = [...new Set((`${ex.title} ${ex.body}`.match(/\{[^{}\s]+\}/g) || []))];
          return (
            <section key={ex.i} className="rounded-2xl border border-[#E6EEFB] bg-white p-5 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
              <div className="mb-3 flex flex-wrap items-start gap-3">
                <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl" style={{ background: bg, color: fg }}><I size={28} /></span>
                <span className="min-w-0 flex-1"><span className="block text-[18px] font-bold text-[#0B1C3F]">{sc?.label}</span>
                  <span className="text-[13.5px] text-[#64748B]">{sc?.sub}</span></span>
                <span className="flex items-center gap-2 rounded-xl bg-[#ECFDF3] px-3 py-2 text-[12.5px] text-[#047857]"><Zap size={15} />
                  <span><span className="block">Déclencheur :</span><b>{sc?.trigger_label}</b></span></span>
              </div>
              <div className="grid gap-3 sm:grid-cols-[1fr_170px]">
                <div className="space-y-2">
                  <div className="rounded-xl border border-[#E6EEFB] p-3">
                    <p className="flex justify-between text-[12px] text-[#64748B]"><span>Titre de la notification</span><span>{ex.title.length}/60</span></p>
                    <p className="text-[14px] text-[#0B1C3F]">{ex.title}</p>
                  </div>
                  <div className="rounded-xl border border-[#E6EEFB] p-3">
                    <p className="flex justify-between text-[12px] text-[#64748B]"><span>Message</span><span>{ex.body.length}/180</span></p>
                    <p className="text-[14px] text-[#0B1C3F]">{ex.body}</p>
                  </div>
                </div>
                {can && (
                  <div className="flex flex-col gap-2">
                    <button type="button" onClick={() => use(ex, 5)} className="rounded-xl bg-[#1463FF] py-3 text-[14px] font-semibold text-white">Utiliser ce modèle</button>
                    <button type="button" onClick={() => use(ex, 3)} className="inline-flex items-center justify-center gap-2 rounded-xl border border-[#BFD3FF] py-3 text-[14px] font-semibold text-[#1463FF]"><Pencil size={15} /> Personnaliser</button>
                  </div>
                )}
              </div>
              <p className="mt-3 flex flex-wrap items-center gap-2 text-[13px] text-[#475569]">Variables :
                {vars.map((v) => <span key={v} className="rounded-lg bg-[#EEF4FF] px-2 py-0.5 text-[12.5px] font-semibold text-[#1D4ED8]">{v}</span>)}</p>
            </section>
          );
        })}
      </div>
    </div>
  );
}
