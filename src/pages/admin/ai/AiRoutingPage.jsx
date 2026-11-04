import React, { useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, Play, Undo2 } from 'lucide-react';
import { Link } from 'react-router-dom';
import { adminAPI } from '../../../lib/api';
import { Breadcrumb, Loading, useToast } from '../../crm/ui';
import { AiTabs } from './shared';

/* FIDCLIC AI › Routage (user 2026-11-04): which model does which job. An answer
   that fails the checks climbs once to the next model up, then the template
   answers. A change applies at once; the page asks for a Golden set run until
   one has tested this table (api/features/ai_routing.py). */

const WHY = { anglais: 'en anglais', contact: 'téléphone ou e-mail', trop_long: 'trop longue', montant: 'montant jamais lu' };
const eur = (v) => `${Number(v || 0).toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`;
const price = (m) => `${String(m.in).replace('.', ',')} / ${String(m.out).replace('.', ',')} $`;

export default function AiRoutingPage() {
  const [d, setD] = useState(null);
  const [busy, setBusy] = useState(null);
  const [say, toast] = useToast();
  const load = () => adminAPI.aiRouting().then(({ data }) => setD(data)).catch(() => setD({ error: true }));
  useEffect(() => { load(); }, []);

  const act = async (job, call) => {
    setBusy(job);
    try { await call(); await load(); }
    catch (e) { say(e?.response?.data?.detail || "Le modèle n'a pas pu être changé."); }
    finally { setBusy(null); }
  };
  const launch = async () => {
    setBusy('golden');
    try { await adminAPI.aiGoldenRun(); say('Golden set lancé : le résultat arrive dans 30 à 60 minutes.'); }
    catch (e) { say(e?.response?.data?.detail || "Le Golden set n'a pas pu être lancé."); }
    finally { setBusy(null); }
  };

  if (!d) return <Loading />;
  if (d.error) return <p className="text-[14px] text-[#B91C1C]">Le routage n&apos;a pas pu être chargé.</p>;
  const label = (id) => d.models.find((m) => m.id === id)?.label || id;

  return (
    <div className="crm">
      {toast}
      <Breadcrumb items={[['Super Admin', '/admin'], ['FIDCLIC AI', '/admin/ai'], ['Routage']]} />
      <h1 className="text-[28px] font-bold leading-tight text-[#0B1C3F]">Routage de FidClic IA</h1>
      <p className="mb-3 text-[15px] text-[#475569]">Chaque travail a son modèle. Une réponse qui échoue aux contrôles monte une fois
        au modèle supérieur ; si elle échoue encore, la réponse simple prend le relais.</p>
      <AiTabs />

      {!d.active && (
        <p className="mb-3 flex items-center gap-2 rounded-xl border border-[#FDE68A] bg-[#FFFBEB] px-4 py-3 text-[13.5px] text-[#92400E]" data-testid="routing-asleep">
          <AlertTriangle size={16} className="shrink-0" />
          Le fournisseur en tête est {d.provider} : cette table ne s&apos;applique qu&apos;à Claude.
        </p>
      )}

      <section data-testid="routing-golden"
        className={`mb-3 flex flex-wrap items-center gap-3 rounded-xl border px-4 py-3 text-[13.5px] ${d.golden.stale ? 'border-[#FDE68A] bg-[#FFFBEB] text-[#92400E]' : 'border-[#BBF7D0] bg-[#F0FDF4] text-[#166534]'}`}>
        {d.golden.stale ? <AlertTriangle size={16} className="shrink-0" /> : <CheckCircle2 size={16} className="shrink-0" />}
        <span className="min-w-0 flex-1">
          {d.golden.stale
            ? 'Aucun Golden set n’a encore testé exactement ces modèles.'
            : `Golden set sur ces modèles : ${d.golden.passed}/${d.golden.total}${d.golden.ok ? '' : ', à corriger'}.`}
          {' '}<Link to="/admin/ai/golden-set" className="font-semibold underline">Voir les résultats</Link>
        </span>
        {d.golden.stale && (
          <button type="button" onClick={launch} disabled={busy === 'golden'}
            className="inline-flex items-center gap-1.5 rounded-lg bg-[#2F6BFF] px-3 py-1.5 text-[12.5px] font-semibold text-white disabled:opacity-50">
            <Play size={13} /> Lancer le Golden set
          </button>
        )}
      </section>

      <section className="overflow-x-auto rounded-2xl border border-[#EDF1F7] bg-white p-4">
        <table className="w-full text-left text-[13.5px]">
          <thead className="text-[12px] text-[#64748B]">
            <tr><th className="py-2 pr-3 font-semibold">Travail</th><th className="pr-3 font-semibold">Modèle</th><th className="pr-3 font-semibold">Monte vers</th>
              <th className="pr-3 text-right font-semibold">Appels (30 j)</th><th className="pr-3 text-right font-semibold">Coût (30 j)</th>
              <th className="pr-3 text-right font-semibold">Montées</th><th className="pr-3 text-right font-semibold">Refusées</th><th /></tr>
          </thead>
          <tbody data-testid="routing-rows">
            {d.routes.map((r) => (
              <tr key={r.feature} className="border-t border-[#EDF1F7]" data-testid={`route-${r.feature}`}>
                <td className="py-2 pr-3 font-medium text-[#0B1C3F]">{r.label}</td>
                <td className="pr-3">
                  <select value={r.model} disabled={busy === r.feature} aria-label={`Modèle de ${r.label}`}
                    onChange={(e) => act(r.feature, () => adminAPI.aiRoutingSet(r.feature, e.target.value))}
                    className="rounded-lg border border-[#DDE3EC] bg-white px-2 py-1 text-[13px]">
                    {d.models.map((m) => <option key={m.id} value={m.id}>{m.label}{m.id === r.default ? ' (par défaut)' : ''}</option>)}
                  </select>
                </td>
                <td className="pr-3 text-[#475569]">{r.above ? label(r.above) : 'Réponse simple'}</td>
                <td className="pr-3 text-right tabular-nums">{r.calls}</td>
                <td className="pr-3 text-right tabular-nums">{eur(r.eur)}</td>
                <td className="pr-3 text-right tabular-nums" title={Object.entries(r.why).map(([k, n]) => `${WHY[k] || k} : ${n}`).join(', ')}>{r.escalated}</td>
                <td className="pr-3 text-right tabular-nums">{r.rejected}</td>
                <td className="text-right">
                  {r.previous && r.previous !== r.model && (
                    <button type="button" disabled={busy === r.feature} onClick={() => act(r.feature, () => adminAPI.aiRoutingRevert(r.feature))}
                      className="inline-flex items-center gap-1 whitespace-nowrap rounded-lg border border-[#DDE3EC] px-2 py-1 text-[12.5px] font-semibold text-[#0B1C3F] hover:bg-[#F8FAFC] disabled:opacity-50">
                      <Undo2 size={13} /> Revenir à {label(r.previous)}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-3 text-[12.5px] text-[#64748B]">
          Prix par million de tokens (entrée / sortie) : {d.models.map((m) => `${m.label} ${price(m)}`).join(' · ')}.
        </p>
      </section>
    </div>
  );
}
