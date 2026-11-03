import React, { useEffect, useState } from 'react';
import { Download } from 'lucide-react';
import { adminAPI } from '../../../lib/api';
import { Breadcrumb, Loading, useToast, downloadBlob } from '../../crm/ui';
import { AiTabs } from './shared';

/* FIDCLIC AI › Apprentissage (learning log, user 2026-11-02): every text
   FidClic IA wrote, what the owner did with it, his 👍 / 👎, and what it
   brought in — the examples a smaller FidClic model will learn from
   (api/features/learning_log.py). Names, phones, e-mails are already gone. */

const SURFACES = {
  campaign_ai: 'Rédiger une campagne', automation_ai: 'Rédiger une automatisation', autopilot: 'Autopilot',
  template: 'Modèles pré-remplis (Insights, Produits, Fiche)', copilot: 'Copilote', support: 'Assistant support',
};
const STATUS = { proposed: 'Proposé', accepted: 'Envoyé tel quel', edited: 'Modifié', rejected: 'Refusé', abandoned: 'Jamais envoyé', expired: 'Expiré' };
const pct = (v) => (v == null ? '—' : `${v} %`);

function Card({ label, value, sub, testid }) {
  return (
    <div className="rounded-2xl border border-[#EDF1F7] bg-white p-4" data-testid={testid}>
      <p className="text-[12.5px] font-semibold text-[#64748B]">{label}</p>
      <p className="mt-1 text-[26px] font-bold tabular-nums text-[#0B1C3F]">{value}</p>
      {sub && <p className="text-[12px] text-[#94A3B8]">{sub}</p>}
    </div>
  );
}

const textOf = (o) => (o ? (o.text || [o.title, o.message].filter(Boolean).join(' — ')) : '');

export default function AiLearningPage() {
  const [d, setD] = useState(null);
  const [say, toast] = useToast();
  useEffect(() => { adminAPI.aiLearning().then(({ data }) => setD(data)).catch(() => setD({ error: true })); }, []);
  const exportIt = async (label) => {
    try { await downloadBlob(adminAPI.aiLearningExport(label), `fidclic-ia-exemples-${label}.jsonl`); } catch { say("L'export n'a pas pu être téléchargé."); }
  };

  if (!d) return <Loading />;
  if (d.error) return <p className="text-[14px] text-[#B91C1C]">L&apos;apprentissage n&apos;a pas pu être chargé.</p>;
  const share = Math.min(100, Math.round((100 * d.good) / d.goal));

  return (
    <div className="crm">
      {toast}
      <Breadcrumb items={[['Super Admin', '/admin'], ['FIDCLIC AI', '/admin/ai'], ['Apprentissage']]} />
      <h1 className="text-[28px] font-bold leading-tight text-[#0B1C3F]">Apprentissage de FidClic IA</h1>
      <p className="mb-3 text-[15px] text-[#475569]">Chaque texte écrit par FidClic IA, ce que le commerçant en a fait et ce qu&apos;il a rapporté.
        Noms, téléphones et e-mails sont retirés avant d&apos;être gardés.</p>
      <AiTabs />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Card label="Bons exemples" value={d.good.toLocaleString('fr-FR')} sub={`objectif ${d.goal.toLocaleString('fr-FR')} pour entraîner un modèle FidClic`} testid="learn-good" />
        <Card label="Mauvais exemples" value={d.bad.toLocaleString('fr-FR')} testid="learn-bad" />
        <Card label="👍" value={d.feedback.up.toLocaleString('fr-FR')} testid="learn-up" />
        <Card label="👎" value={d.feedback.down.toLocaleString('fr-FR')} sub={d.feedback.reasons.map((r) => `${r.label} ${r.n}`).join(' · ') || null} testid="learn-down" />
      </div>
      <div className="mt-3 h-2 w-full rounded-full bg-[#E6EEFB]" aria-label={`${share} % de l'objectif`}>
        <div className="h-2 rounded-full bg-[#2F6BFF]" style={{ width: `${share}%` }} />
      </div>

      <section className="mt-4 overflow-x-auto rounded-2xl border border-[#EDF1F7] bg-white p-4" data-testid="learn-surfaces">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-[15px] font-bold text-[#0B1C3F]">Par endroit</h2>
          <div className="flex gap-2">
            <button type="button" onClick={() => exportIt('good')} data-testid="learn-export"
                    className="inline-flex items-center gap-1.5 rounded-lg bg-[#2F6BFF] px-3 py-1.5 text-[12.5px] font-semibold text-white"><Download size={14} /> Bons exemples (JSONL)</button>
            <button type="button" onClick={() => exportIt('bad')}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-[#EEF3FF] px-3 py-1.5 text-[12.5px] font-semibold text-[#2F6BFF]"><Download size={14} /> Mauvais exemples</button>
          </div>
        </div>
        <table className="mt-2 w-full text-[13px]">
          <thead><tr className="text-left text-[#94A3B8]"><th className="py-1.5">Endroit</th><th>Écrits</th><th>Tel quel</th><th>Modifiés</th><th>Refusés</th><th>Jamais envoyés</th><th>Gardés</th><th>Ressemblance si modifié</th><th>Résultat mesuré</th></tr></thead>
          <tbody>
            {d.surfaces.map((s) => (
              <tr key={s.surface} className="border-t border-[#F1F5FB]"><td className="py-1.5 font-semibold">{SURFACES[s.surface] || s.surface}</td>
                <td className="tabular-nums">{s.total}</td><td className="tabular-nums">{s.accepted}</td><td className="tabular-nums">{s.edited}</td>
                <td className="tabular-nums">{s.rejected}</td><td className="tabular-nums">{s.abandoned}</td><td className="tabular-nums">{pct(s.kept_pct)}</td>
                <td className="tabular-nums">{s.edit_similarity == null ? '—' : `${Math.round(s.edit_similarity * 100)} %`}</td><td className="tabular-nums">{s.measured}</td></tr>
            ))}
            {!d.surfaces.length && <tr><td colSpan={9} className="py-2 text-[#94A3B8]">Rien encore : les exemples arrivent dès qu&apos;un commerçant utilise FidClic IA.</td></tr>}
          </tbody>
        </table>
      </section>

      <section className="mt-4 rounded-2xl border border-[#EDF1F7] bg-white p-4" data-testid="learn-recent">
        <h2 className="text-[15px] font-bold text-[#0B1C3F]">Derniers exemples</h2>
        <ul className="mt-2 space-y-2 text-[13px]">
          {d.recent.map((x) => (
            <li key={x.id} className="rounded-xl border border-[#F1F5FB] p-2.5">
              <p className="text-[11.5px] text-[#94A3B8]">{SURFACES[x.surface] || x.surface} · {x.activity || '—'} · {STATUS[x.status] || x.status}
                {x.label ? ` · ${x.label === 'good' ? 'bon' : 'mauvais'}` : ''}{x.feedback?.vote ? ` · ${x.feedback.vote === 'up' ? '👍' : '👎'}` : ''}
                {x.outcome?.rate != null ? ` · ${x.outcome.rate} % revenus vs ${x.outcome.temoin_rate} % témoin` : ''}</p>
              <p className="mt-0.5 text-[#334155]"><span className="font-semibold">IA :</span> {textOf(x.output)}</p>
              {x.final && <p className="mt-0.5 text-[#334155]"><span className="font-semibold">Envoyé :</span> {textOf(x.final)}</p>}
              {x.feedback?.text && <p className="mt-0.5 text-[#B45309]">« {x.feedback.text} »</p>}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
