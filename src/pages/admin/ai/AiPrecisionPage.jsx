import React, { useCallback, useEffect, useState } from 'react';
import { Download, Loader2, RotateCcw, Target, Brain, ArrowRightLeft } from 'lucide-react';
import { adminAPI } from '../../../lib/api';
import { Breadcrumb, Loading, useToast, downloadBlob } from '../../crm/ui';
import { AiTabs } from './shared';

/* FIDCLIC AI › Précision (user, 2026-10-25): what the client brain predicted
   for each client's next visit, and what really happened — against the plain
   mean of the client's gaps and the shop's own « Client actif » rule. Super
   admin only; the rows are anonymous once their outcome is known
   (features/brain_journal.py). */

const SECTORS = { cafe: 'Café', bakery: 'Boulangerie', bar: 'Bar', pizzeria: 'Pizzeria', restaurant: 'Restaurant',
  retail: 'Commerce', salon: 'Salon / barbier', spa: 'Spa / institut', gym: 'Salle de sport', other: 'Autre' };
const pct = (v) => (v == null ? '—' : `${v} %`);
const days = (v) => (v == null ? '—' : `${String(v).replace('.', ',')} j`);
const month = (m) => new Date(`${m}-01T12:00:00Z`).toLocaleDateString('fr-FR', { month: 'short', year: 'numeric' });

const PHASES = { clients: 'clients rejoués', rythmes: 'boutiques lues', rejeu: 'clients rejoués', tables: 'calcul des fenêtres', lignes: 'lignes écrites' };

/* What runs in the background (features/ai_jobs, user 2026-10-26): the
   buttons answer at once, the tick does the work in slices; the figures
   above stay those of the last complete run until the new one ends. */
function Jobs({ jobs }) {
  if (!jobs?.length) return null;
  return (
    <section className="mb-4 rounded-2xl border border-[#DCE7FF] bg-[#F5F8FF] p-4" data-testid="ai-jobs">
      <p className="mb-2 text-[13px] text-[#475569]">
        En arrière-plan, toutes les 15 minutes. Les chiffres affichés restent ceux du dernier calcul complet jusqu&apos;à la fin.
      </p>
      <ul className="space-y-2">
        {jobs.map((j) => {
          const share = j.total ? Math.min(100, Math.round((100 * j.done) / j.total)) : 0;
          const state = j.status === 'failed' ? 'Échec' : j.status === 'done' ? 'Terminé' : j.status === 'queued' ? 'En attente du prochain passage' : 'En cours';
          return (
            <li key={j.id} data-testid={`ai-job-${j.kind}`} className="text-[13px]">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold text-[#0B1C3F]">{j.label}</span>
                <span className={j.status === 'failed' ? 'text-[#B91C1C]' : 'text-[#475569]'}>{state}</span>
                {j.total ? <span className="text-[#475569]">· {j.done.toLocaleString('fr-FR')} / {j.total.toLocaleString('fr-FR')} {PHASES[j.phase] || ''}</span> : null}
              </div>
              {j.status !== 'failed' && j.status !== 'done' && (
                <div className="mt-1 h-1.5 w-full max-w-[420px] rounded-full bg-[#DCE7FF]">
                  <div className="h-1.5 rounded-full bg-[#2F6BFF]" style={{ width: `${share}%` }} />
                </div>
              )}
              {j.status === 'failed' && j.error && <p className="mt-0.5 text-[12px] text-[#B91C1C]">{j.error} — relancez pour réessayer.</p>}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function Card({ label, value, sub, tone = '#0B1C3F', testid }) {
  return (
    <div className="rounded-2xl border border-[#EDF1F7] bg-white p-4" data-testid={testid}>
      <p className="text-[12.5px] font-semibold text-[#64748B]">{label}</p>
      <p className="mt-1 text-[26px] font-bold tabular-nums" style={{ color: tone }}>{value}</p>
      {sub && <p className="text-[12px] text-[#94A3B8]">{sub}</p>}
    </div>
  );
}


/* Groupe témoin (user, 2026-10-25): what the messages really bring in, every
   shop, by sector — the R&D proof (Bpifrance), no shop or client named. */
function UpliftJournal() {
  const [u, setU] = useState(null);
  useEffect(() => { adminAPI.aiUplift().then(({ data }) => setU(data)).catch(() => setU(null)); }, []);
  if (!u) return null;
  const eur = (n) => (n == null ? '—' : `${n > 0 ? '+' : ''}${Math.round(n).toLocaleString('fr-FR')} €`);
  const rate = (x) => (x == null ? '—' : `${String(x).replace('.', ',')} %`);
  const t = u.total;
  return (
    <section className="mt-4 rounded-2xl border border-[#EDF1F7] bg-white p-4" data-testid="precision-uplift">
      <h2 className="text-[15px] font-bold text-[#0B1C3F]">Groupe témoin : ce que les messages rapportent vraiment</h2>
      <p className="mt-0.5 text-[12.5px] text-[#64748B]">{u.share} % de chaque envoi groupé et de chaque relance, tirés au hasard, sans message ; comparés {u.window_days} jours après.
        Toutes boutiques{t.sent.n ? ` : ${rate(t.sent.rate)} revenus avec le message contre ${rate(t.temoin.rate)} sans (${t.temoin.n} témoins), ${eur(t.extra_revenue)}` : ' : pas encore de mesure'}.</p>
      {u.sectors.length > 0 && (
        <table className="mt-2 w-full text-[13px]">
          <thead><tr className="text-left text-[#94A3B8]"><th className="py-1.5">Secteur</th><th>Boutiques</th><th>Envois</th><th>Messagés / témoins</th><th>Revenus avec / sans</th><th>Gain</th><th>Pour 100 clients</th></tr></thead>
          <tbody>
            {u.sectors.map((x) => (
              <tr key={x.sector} className="border-t border-[#F1F5FB]"><td className="py-1.5 font-semibold">{SECTORS[x.sector] || (x.sector.charAt(0).toUpperCase() + x.sector.slice(1))}</td>
                <td className="tabular-nums">{x.shops}</td><td className="tabular-nums">{x.sends}</td>
                <td className="tabular-nums">{x.sent.n} / {x.temoin.n}</td><td>{rate(x.sent.rate)} / {rate(x.temoin.rate)}</td>
                <td className="tabular-nums">{eur(x.extra_revenue)}{!x.enough && x.temoin.n > 0 ? ' (indicatif)' : ''}</td><td className="tabular-nums">{eur(x.per_100)}</td></tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

export default function AiPrecisionPage() {
  const [d, setD] = useState(null);
  const [source, setSource] = useState('all');
  const [model, setModel] = useState('');
  const [sector, setSector] = useState('');
  const [busy, setBusy] = useState(false);
  const [say, toast] = useToast();
  const load = useCallback(() => {
    adminAPI.aiPrecision({ source, sector, model }).then(({ data }) => setD(data)).catch(() => setD({ error: true }));
  }, [source, sector, model]);
  useEffect(() => { load(); }, [load]);
  // while something runs in the background, the page follows it
  const running = (d?.jobs || []).some((j) => j.status === 'queued' || j.status === 'running');
  useEffect(() => {
    if (!running) return undefined;
    const t = setInterval(load, 30_000);
    return () => clearInterval(t);
  }, [running, load]);

  const rerun = async () => {
    if (!window.confirm('Relancer le backtest sur toutes les boutiques ? Seul le journal de FidClic IA est réécrit ; aucune donnée client ni message.')) return;
    setBusy(true);
    try {
      const { data } = await adminAPI.aiPrecisionBacktest({});
      say(data.started?.length ? 'Backtest lancé : il tourne en arrière-plan, les chiffres actuels restent affichés jusqu\'à la fin.'
        : 'Le backtest est déjà en cours.');
      load();
    } catch (e) { say("Le backtest n'a pas pu être lancé."); }
    setBusy(false);
  };

  const relearn = async () => {
    setBusy(true);
    try {
      const { data } = await adminAPI.aiPrecisionLearn();
      say(data.started ? 'Réapprentissage lancé : brain-v2 garde ses tables actuelles jusqu\'à la fin.' : 'Le réapprentissage est déjà en cours.');
      load();
    } catch (e) { say("L'apprentissage n'a pas pu être lancé."); }
    setBusy(false);
  };
  const switchTo = async (to) => {
    const msg = to === 'brain-v2'
      ? 'Passer à brain-v2 ? Tous les profils clients seront recalculés par brain-v2 (quelques milliers toutes les 15 minutes). brain-v1 restera en observation.'
      : 'Revenir à brain-v1 ? Tous les profils clients seront recalculés par brain-v1.';
    if (!window.confirm(msg)) return;
    setBusy(true);
    try { await adminAPI.aiPrecisionChampion({ model: to }); say(`${to} est en service.`); setModel(''); load(); }
    catch (e) { say(e?.response?.data?.detail || 'Le changement a été refusé.'); }
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
        comparé à la moyenne simple de ses écarts et à la règle « Client actif » de chaque boutique (Règles clients ; 30 jours si elle n&apos;a rien réglé).
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

      <Jobs jobs={d.jobs} />

      <section className="mb-4 rounded-2xl border border-[#EDF1F7] bg-white p-4" data-testid="precision-compare">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <h2 className="inline-flex items-center gap-1.5 text-[15px] font-bold text-[#0B1C3F]"><Brain size={16} /> Quel cerveau prédit le mieux ?</h2>
          <span className="text-[12.5px] text-[#64748B]">Sur les mêmes prédictions vérifiées. Les clients voient le cerveau « en service » ; l&apos;autre est en observation.</span>
        </div>
        <table className="w-full text-[13px]">
          <thead><tr className="text-left text-[#94A3B8]"><th className="py-1.5">Méthode</th><th>Vérifiées</th><th>Dans la fourchette</th><th>Erreur médiane</th><th>À ±{d.rules.near_days} j</th></tr></thead>
          <tbody>
            {[['brain-v1', d.compare.v1, d.compare.v1.brain], ['brain-v2', d.compare.v2, d.compare.v2.brain]].map(([k, x, m]) => (
              <tr key={k} className="border-t border-[#F1F5FB]" data-testid={`compare-${k}`}>
                <td className="py-2 font-semibold">{k}{' '}
                  <span className={`ml-1 rounded-md px-1.5 py-0.5 text-[11px] font-semibold ${d.champion === k ? 'bg-[#E7F7EE] text-[#0F7A45]' : 'bg-[#F1F5F9] text-[#475569]'}`}>
                    {d.champion === k ? 'En service' : 'En observation'}</span></td>
                <td className="tabular-nums">{x.checked.toLocaleString('fr-FR')}</td><td>{pct(x.in_window)}</td>
                <td className="font-semibold">{days(m.median_error)}</td><td>{pct(m.near)}</td>
              </tr>
            ))}
            <tr className="border-t border-[#F1F5FB] text-[#64748B]"><td className="py-2">Moyenne simple de ses écarts</td><td /><td>—</td><td>{days(d.compare.v1.mean.median_error)}</td><td>{pct(d.compare.v1.mean.near)}</td></tr>
            <tr className="border-t border-[#F1F5FB] text-[#64748B]"><td className="py-2">Règle « Client actif » de la boutique</td><td /><td>—</td><td>{days(d.compare.v1.rule.median_error)}</td><td>{pct(d.compare.v1.rule.near)}</td></tr>
          </tbody>
        </table>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {d.champion === 'brain-v1' ? (
            <button type="button" onClick={() => switchTo('brain-v2')} disabled={busy || !d.compare.can_switch} data-testid="switch-v2"
                    className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-[#0F7A45] px-3 text-[13px] font-semibold text-white disabled:cursor-not-allowed disabled:opacity-40">
              <ArrowRightLeft size={14} /> Passer à brain-v2
            </button>
          ) : (
            <button type="button" onClick={() => switchTo('brain-v1')} disabled={busy} data-testid="switch-v1"
                    className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-[#DCE3EE] px-3 text-[13px] font-semibold text-[#334155]">
              <ArrowRightLeft size={14} /> Revenir à brain-v1
            </button>
          )}
          <button type="button" onClick={relearn} disabled={busy}
                  className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-[#DCE3EE] px-3 text-[13px] font-semibold text-[#334155] disabled:opacity-50">
            {busy ? <Loader2 size={14} className="animate-spin" /> : <RotateCcw size={14} />} Réapprendre brain-v2
          </button>
          <span className="text-[12px] text-[#94A3B8]">
            {d.learned ? `Appris le ${new Date(d.learned.at).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })} sur ${d.learned.shops} boutiques, ${d.learned.returns.toLocaleString('fr-FR')} retours réels.` : "brain-v2 n'a pas encore appris (une fois par jour)."}
          </span>
        </div>
        {d.champion === 'brain-v1' && !d.compare.can_switch && (
          <ul className="mt-2 list-disc pl-5 text-[12.5px] text-[#92400E]" data-testid="switch-why-not">
            {d.compare.why_not.map((w) => <li key={w}>{w}</li>)}
          </ul>
        )}
      </section>

      <div className="mb-3 flex items-center gap-2 text-[13px]">
        <span className="text-[#64748B]">Détail de :</span>
        {['brain-v1', 'brain-v2'].map((k) => (
          <button key={k} type="button" onClick={() => setModel(k)} aria-pressed={d.model === k}
                  className={`h-8 rounded-lg px-3 font-semibold ${d.model === k ? 'bg-[#0B1C3F] text-white' : 'border border-[#DCE3EE] text-[#334155]'}`}>{k}</button>
        ))}
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
                  sub={`moyenne simple ${days(s.mean.median_error)} · règle boutique ${days(s.rule.median_error)}`} />
            <Card testid="precision-near" label={`À ±${d.rules.near_days} jours`} value={pct(s.brain.near)}
                  sub={`moyenne simple ${pct(s.mean.near)} · règle boutique ${pct(s.rule.near)}`} />
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

      <UpliftJournal />

      <section className="mt-4 rounded-2xl bg-[#F8FAFF] p-4 text-[12.5px] leading-relaxed text-[#475569]">
        <p className="mb-1 inline-flex items-center gap-1.5 font-semibold text-[#0B1C3F]"><Target size={14} /> Comment c&apos;est mesuré</p>
        <p>Chaque passage en caisse d&apos;un client au rythme connu (3 jours de visite) enregistre une fourchette pour sa prochaine visite.
          Sa visite suivante, un autre jour, la vérifie ; sans visite après {d.rules.expire}, il compte comme « non revenu ».
          Le backtest rejoue l&apos;historique de chaque boutique avec le rythme du secteur (jamais la médiane d&apos;aujourd&apos;hui, pour ne pas voir l&apos;avenir).
          Une ligne vérifiée ne garde plus l&apos;identité du client : seulement le secteur, les indicateurs et le résultat.</p>
        <p className="mt-1.5">brain-v2 apprend du réseau : le rythme habituel de chaque secteur et, pour les clients qui se ressemblent, l&apos;écart réel entre son rythme et le vrai retour — sa fourchette en garde 7 sur 10.
          Son backtest ne laisse jamais une boutique se voir : fourchettes, rythme du secteur et confiance sont appris sur les autres boutiques.</p>
        {d.runs.length > 0 && <p className="mt-1.5">Backtests : {d.runs.filter((r) => r.clients).map((r) => `${r.tenant} (${r.resolved} vérifiées)`).join(' · ') || 'aucune boutique avec assez de visites'}.</p>}
      </section>
    </div>
  );
}
