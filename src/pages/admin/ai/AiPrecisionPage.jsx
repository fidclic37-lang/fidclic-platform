import React, { useCallback, useEffect, useState } from 'react';
import { Download, Loader2, RotateCcw, Target } from 'lucide-react';
import { adminAPI } from '../../../lib/api';
import { Breadcrumb, Loading, useToast, downloadBlob } from '../../crm/ui';
import { AiTabs } from './shared';

/* FIDCLIC AI › Précision (user, 2026-10-25): what the client brain predicted
   for each client's next visit, and what really happened — against the two
   rules a shop would otherwise use. Super admin only; the rows are anonymous
   once their outcome is known (features/brain_journal.py). */

const SECTORS = { cafe: 'Café', bakery: 'Boulangerie', bar: 'Bar', pizzeria: 'Pizzeria', restaurant: 'Restaurant',
  retail: 'Commerce', salon: 'Salon / barbier', spa: 'Spa / institut', gym: 'Salle de sport', other: 'Autre' };
const pct = (v) => (v == null ? '—' : `${v} %`);
const days = (v) => (v == null ? '—' : `${String(v).replace('.', ',')} j`);
const month = (m) => new Date(`${m}-01T12:00:00Z`).toLocaleDateString('fr-FR', { month: 'short', year: 'numeric' });

function Card({ label, value, sub, tone = '#0B1C3F', testid }) {
  return (
    <div className="rounded-2xl border border-[#EDF1F7] bg-white p-4" data-testid={testid}>
      <p className="text-[12.5px] font-semibold text-[#64748B]">{label}</p>
      <p className="mt-1 text-[26px] font-bold tabular-nums" style={{ color: tone }}>{value}</p>
      {sub && <p className="text-[12px] text-[#94A3B8]">{sub}</p>}
    </div>
  );
}

export default function AiPrecisionPage() {
  const [d, setD] = useState(null);
  const [source, setSource] = useState('all');
  const [sector, setSector] = useState('');
  const [busy, setBusy] = useState(false);
  const [say, toast] = useToast();
  const load = useCallback(() => {
    adminAPI.aiPrecision({ source, sector }).then(({ data }) => setD(data)).catch(() => setD({ error: true }));
  }, [source, sector]);
  useEffect(() => { load(); }, [load]);

  const rerun = async () => {
    if (!window.confirm('Relancer le backtest sur toutes les boutiques ? Seul le journal de FidClic IA est réécrit ; aucune donnée client ni message.')) return;
    setBusy(true);
    try { await adminAPI.aiPrecisionBacktest({}); say('Backtest terminé.'); load(); } catch (e) { say("Le backtest n'a pas pu être lancé."); }
    setBusy(false);
  };

  if (!d) return <Loading />;
  if (d.error) return <p className="text-[14px] text-[#B91C1C]">La précision n&apos;a pas pu être chargée.</p>;
  const s = d.summary;
  const better = s.brain.median_error != null && s.mean.median_error != null && s.brain.median_error <= s.mean.median_error;

  return (
    <div className="crm">
      {toast}
      <Breadcrumb items={[['Super Admin', '/admin'], ['FIDCLIC AI', '/admin/ai'], ['Précision']]} />
      <h1 className="text-[28px] font-bold leading-tight text-[#0B1C3F]">Précision de FidClic IA</h1>
      <p className="mb-3 text-[15px] text-[#475569]">
        Ce que le cerveau client a prédit pour la prochaine visite de chaque client, et ce qui s&apos;est vraiment passé —
        comparé à la moyenne simple de ses écarts et à la règle fixe des {d.rules.fixed_days} jours.
      </p>
      <AiTabs />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        {[['all', 'Tout'], ['live', 'En direct'], ['backtest', 'Backtest']].map(([k, l]) => (
          <button key={k} type="button" onClick={() => setSource(k)} aria-pressed={source === k}
                  className={`h-9 rounded-lg px-3 text-[13px] font-semibold ${source === k ? 'bg-[#2F6BFF] text-white' : 'border border-[#DCE3EE] text-[#334155]'}`}>{l}</button>
        ))}
        <select aria-label="Secteur" value={sector} onChange={(e) => setSector(e.target.value)}
                className="h-9 rounded-lg border border-[#DCE3EE] px-2 text-[13px]">
          <option value="">Tous les secteurs</option>
          {Object.entries(SECTORS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
        <span className="ml-auto flex gap-2">
          <button type="button" onClick={rerun} disabled={busy}
                  className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-[#DCE3EE] px-3 text-[13px] font-semibold text-[#334155] disabled:opacity-50">
            {busy ? <Loader2 size={14} className="animate-spin" /> : <RotateCcw size={14} />} Relancer le backtest
          </button>
          <button type="button" onClick={() => downloadBlob(adminAPI.aiPrecisionExport(), 'fidclic-ia-journal.csv').catch(() => say("L'export n'a pas pu être généré."))}
                  className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-[#0B1C3F] px-3 text-[13px] font-semibold text-white">
            <Download size={14} /> Exporter le journal (CSV)
          </button>
        </span>
      </div>

      {s.checked === 0 && s.not_returned === 0 ? (
        <p className="rounded-2xl border border-dashed border-[#DCE3EE] px-4 py-10 text-center text-[14px] text-[#64748B]" data-testid="precision-empty">
          Aucune prédiction vérifiée pour l&apos;instant. {s.open ? `${s.open} en attente de la prochaine visite.` : 'Le backtest tourne une boutique à la fois (toutes les 15 minutes).'}
        </p>
      ) : (
        <>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <Card testid="precision-checked" label="Prédictions vérifiées" value={s.checked.toLocaleString('fr-FR')}
                  sub={`${s.open} en attente · ${s.not_returned} non revenus`} />
            <Card testid="precision-window" label="Dans la fourchette annoncée" value={pct(s.in_window)} tone="#2F6BFF"
                  sub="le client est revenu entre les deux dates" />
            <Card testid="precision-error" label="Erreur médiane" value={days(s.brain.median_error)} tone={better ? '#0F7A45' : '#B42318'}
                  sub={`moyenne simple ${days(s.mean.median_error)} · règle ${d.rules.fixed_days} j ${days(s.fixed30.median_error)}`} />
            <Card testid="precision-near" label={`À ±${d.rules.near_days} jours`} value={pct(s.brain.near)}
                  sub={`moyenne simple ${pct(s.mean.near)} · règle ${d.rules.fixed_days} j ${pct(s.fixed30.near)}`} />
          </div>

          <div className="mt-4 grid gap-4 xl:grid-cols-2">
            <section className="rounded-2xl border border-[#EDF1F7] bg-white p-4" data-testid="precision-calibration">
              <h2 className="text-[15px] font-bold text-[#0B1C3F]">La confiance annoncée est-elle honnête ?</h2>
              <p className="mb-2 text-[12.5px] text-[#64748B]">Pour chaque niveau de confiance, la part des clients vraiment revenus dans la fourchette.</p>
              <table className="w-full text-[13px]">
                <thead><tr className="text-left text-[#94A3B8]"><th className="py-1.5">Confiance</th><th>Annoncée</th><th>Réelle</th><th className="text-right">Prédictions</th></tr></thead>
                <tbody>
                  {s.calibration.map((c) => (
                    <tr key={c.label} className="border-t border-[#F1F5FB]"><td className="py-1.5 font-semibold">{c.label}</td>
                      <td>{pct(c.said)}</td><td className="font-semibold text-[#2F6BFF]">{pct(c.real)}</td><td className="text-right tabular-nums">{c.n}</td></tr>
                  ))}
                </tbody>
              </table>
            </section>
            <section className="rounded-2xl border border-[#EDF1F7] bg-white p-4" data-testid="precision-sectors">
              <h2 className="text-[15px] font-bold text-[#0B1C3F]">Par secteur</h2>
              <table className="mt-2 w-full text-[13px]">
                <thead><tr className="text-left text-[#94A3B8]"><th className="py-1.5">Secteur</th><th>Vérifiées</th><th>Fourchette</th><th>Erreur</th><th>Moy. simple</th></tr></thead>
                <tbody>
                  {d.sectors.map((x) => (
                    <tr key={x.sector} className="border-t border-[#F1F5FB]"><td className="py-1.5 font-semibold">{SECTORS[x.sector] || (x.sector.charAt(0).toUpperCase() + x.sector.slice(1))}</td>
                      <td className="tabular-nums">{x.checked}</td><td>{pct(x.in_window)}</td><td>{days(x.brain.median_error)}</td><td>{days(x.mean.median_error)}</td></tr>
                  ))}
                </tbody>
              </table>
            </section>
          </div>

          {d.months.length > 0 && (
            <section className="mt-4 rounded-2xl border border-[#EDF1F7] bg-white p-4">
              <h2 className="text-[15px] font-bold text-[#0B1C3F]">Mois par mois</h2>
              <table className="mt-2 w-full text-[13px]">
                <thead><tr className="text-left text-[#94A3B8]"><th className="py-1.5">Prédiction faite en</th><th>Vérifiées</th><th>Fourchette</th><th>Erreur</th><th>Non revenus</th></tr></thead>
                <tbody>
                  {d.months.map((x) => (
                    <tr key={x.month} className="border-t border-[#F1F5FB]"><td className="py-1.5 font-semibold">{month(x.month)}</td>
                      <td className="tabular-nums">{x.checked}</td><td>{pct(x.in_window)}</td><td>{days(x.brain.median_error)}</td><td className="tabular-nums">{x.not_returned}</td></tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}
        </>
      )}

      <section className="mt-4 rounded-2xl bg-[#F8FAFF] p-4 text-[12.5px] leading-relaxed text-[#475569]">
        <p className="mb-1 inline-flex items-center gap-1.5 font-semibold text-[#0B1C3F]"><Target size={14} /> Comment c&apos;est mesuré — modèle {d.model}</p>
        <p>Chaque passage en caisse d&apos;un client au rythme connu (3 jours de visite) enregistre une fourchette pour sa prochaine visite.
          Sa visite suivante, un autre jour, la vérifie ; sans visite après {d.rules.expire}, il compte comme « non revenu ».
          Le backtest rejoue l&apos;historique de chaque boutique avec le rythme du secteur (jamais la médiane d&apos;aujourd&apos;hui, pour ne pas voir l&apos;avenir).
          Une ligne vérifiée ne garde plus l&apos;identité du client : seulement le secteur, les indicateurs et le résultat.</p>
        {d.runs.length > 0 && <p className="mt-1.5">Backtests : {d.runs.filter((r) => r.clients).map((r) => `${r.tenant} (${r.resolved} vérifiées)`).join(' · ') || 'aucune boutique avec assez de visites'}.</p>}
      </section>
    </div>
  );
}
