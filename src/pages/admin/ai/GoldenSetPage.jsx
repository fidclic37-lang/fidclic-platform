import React, { useEffect, useState } from 'react';
import { Play, ExternalLink, ChevronRight } from 'lucide-react';
import { adminAPI } from '../../../lib/api';
import { Breadcrumb, Loading, useToast } from '../../crm/ui';
import { AiTabs } from './shared';

/* FIDCLIC AI › Golden set (user 2026-11-03): ~250 known questions asked to the
   real model on demo shops, graded at 100 % — one failed question = a failed
   run. Runs come from the GitHub workflow (a PR labelled « ai », or « Lancer »);
   their cost is on the AI meter as « golden_set » (api/features/golden_set.py). */

const ACCOUNTS = { owner: 'Patron', gare: 'Manager Gare', sans_ca: 'Manager sans Analyses', staff: 'Caisse', vide: 'Commerce vide', starter: 'Offre Starter' };
const when = (iso) => (iso ? new Date(iso).toLocaleString('fr-FR', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—');

function state(r) {
  if (r.status !== 'completed') return ['En cours', 'bg-[#EEF3FF] text-[#2F6BFF]'];
  if (r.total == null) return [r.conclusion === 'success' ? 'Réussi' : 'Échoué', r.conclusion === 'success' ? 'bg-[#ECFDF5] text-[#047857]' : 'bg-[#FEF2F2] text-[#B91C1C]'];
  return r.ok ? ['100 %', 'bg-[#ECFDF5] text-[#047857]'] : [`${r.passed}/${r.total}`, 'bg-[#FEF2F2] text-[#B91C1C]'];
}

/* The shops' own data in the golden set (user 2026-11-09: every shop by default):
   an anonymized copy each night, read by the GitHub run. One switch per shop. */
function RealShops() {
  const [rows, setRows] = useState(null);
  const [busy, setBusy] = useState('');
  const load = () => adminAPI.aiGoldenReal().then(({ data }) => setRows(data.shops)).catch(() => setRows([]));
  useEffect(() => { load(); }, []);
  const flip = async (r) => {
    setBusy(r.id);
    try { await adminAPI.aiGoldenRealSet(r.id, !r.on); await load(); } finally { setBusy(''); }
  };
  if (!rows) return null;
  return (
    <section className="mt-4 rounded-2xl border border-[#EDF1F7] bg-white p-4" data-testid="golden-real-shops">
      <h2 className="text-[15px] font-bold text-[#0B1C3F]">Données réelles des commerces</h2>
      <p className="mt-1 text-[12.5px] text-[#64748B]">Chaque nuit, une copie anonymisée de chaque commerce (sans nom, téléphone ni e-mail de client) sert aussi au test. Le rapport public n&apos;affiche aucun chiffre.</p>
      <ul className="mt-2 divide-y divide-[#F1F5FB] text-[13px]">
        {rows.map((r) => (
          <li key={r.id} className="flex items-center justify-between gap-3 py-2">
            <span className="min-w-0">
              <span className="font-semibold text-[#0B1C3F]" translate="no">{r.name || r.id}</span>
              <span className="ml-2 text-[#94A3B8]">{r.built_at ? `copie du ${when(r.built_at)}` : 'pas encore copié'}</span>
            </span>
            <button type="button" role="switch" aria-checked={r.on} aria-label={`Données réelles de ${r.name || r.id}`} disabled={busy === r.id}
                    onClick={() => flip(r)} className={`relative h-6 w-11 shrink-0 rounded-full transition ${r.on ? 'bg-[#1463FF]' : 'bg-[#D6DEEA]'}`}>
              <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition ${r.on ? 'left-[22px]' : 'left-0.5'}`} />
            </button>
          </li>))}
      </ul>
    </section>
  );
}

export default function GoldenSetPage() {
  const [d, setD] = useState(null);
  const [open, setOpen] = useState(null);
  const [busy, setBusy] = useState(false);
  const [say, toast] = useToast();
  const load = () => adminAPI.aiGolden().then(({ data }) => { setD(data); setOpen((o) => o ?? data.runs.find((r) => r.total != null)?.id ?? null); })
    .catch(() => setD({ error: true }));
  useEffect(() => { load(); }, []);
  const launch = async () => {
    setBusy(true);
    try { await adminAPI.aiGoldenRun(); say('Test lancé : le résultat arrive ici dans 20 à 40 minutes.'); load(); }
    catch (e) { say(e?.response?.data?.detail || "Le test n'a pas pu être lancé."); }
    finally { setBusy(false); }
  };

  if (!d) return <Loading />;
  if (d.error) return <p className="text-[14px] text-[#B91C1C]">Le golden set n&apos;a pas pu être chargé.</p>;
  const total = Object.values(d.bank).reduce((n, v) => n + v.length, 0);
  const run = d.runs.find((r) => r.id === open);

  return (
    <div className="crm">
      {toast}
      <Breadcrumb items={[['Super Admin', '/admin'], ['FIDCLIC AI', '/admin/ai'], ['Golden set']]} />
      <h1 className="text-[28px] font-bold leading-tight text-[#0B1C3F]">Golden set de FidClic IA</h1>
      <p className="mb-3 text-[15px] text-[#475569]">{total} questions connues, posées au vrai modèle sur des commerces de démonstration.
        Une seule question ratée et le test échoue.</p>
      <AiTabs />

      <section className="rounded-2xl border border-[#EDF1F7] bg-white p-4" data-testid="golden-runs">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-[15px] font-bold text-[#0B1C3F]">Derniers tests</h2>
          {d.can_run && (
            <button type="button" onClick={launch} disabled={busy || !d.configured || d.running} data-testid="golden-run"
                    className="inline-flex items-center gap-1.5 rounded-lg bg-[#2F6BFF] px-3 py-1.5 text-[12.5px] font-semibold text-white disabled:opacity-50">
              <Play size={14} /> {d.running ? 'Test en cours…' : 'Lancer un test complet'}</button>
          )}
        </div>
        {!d.configured && (
          <p className="mt-2 rounded-xl bg-[#FFF7ED] p-2.5 text-[13px] text-[#9A3412]" data-testid="golden-setup">
            GitHub n&apos;est pas relié : ajoutez <code>GOLDEN_GITHUB_TOKEN</code> (accès « Actions » au dépôt {d.repo}) dans Vercel pour voir les tests et les lancer d&apos;ici.
            Sans lui, un test se lance avec l&apos;étiquette « ai » sur une PR.</p>
        )}
        <table className="mt-2 w-full text-[13px]">
          <thead><tr className="text-left text-[#94A3B8]"><th className="py-1.5">Quand</th><th>Déclenché par</th><th>Résultat</th><th>Modèle</th><th>Coût</th><th /></tr></thead>
          <tbody>
            {d.runs.map((r) => { const [label, cls] = state(r); return (
              <tr key={r.id} className={`cursor-pointer border-t border-[#F1F5FB] ${open === r.id ? 'bg-[#F8FAFF]' : ''}`} onClick={() => setOpen(r.id)}>
                <td className="py-1.5">{when(r.created_at)}</td><td>{r.trigger}</td>
                <td><span className={`rounded-full px-2 py-0.5 text-[12px] font-semibold ${cls}`}>{label}</span></td>
                <td className="text-[#64748B]">{r.model || '—'}</td>
                <td className="tabular-nums">{r.cost_eur == null ? '—' : `${Number(r.cost_eur).toLocaleString('fr-FR', { maximumFractionDigits: 2 })} €`}</td>
                <td>{r.url && <a href={r.url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()} className="inline-flex items-center gap-1 text-[#2F6BFF]">GitHub <ExternalLink size={12} /></a>}</td>
              </tr>); })}
            {!d.runs.length && <tr><td colSpan={6} className="py-2 text-[#94A3B8]">Aucun test pour l&apos;instant.</td></tr>}
          </tbody>
        </table>
      </section>

      {run && run.by_type && (
        <section className="mt-4 rounded-2xl border border-[#EDF1F7] bg-white p-4" data-testid="golden-detail">
          <h2 className="text-[15px] font-bold text-[#0B1C3F]">Test du {when(run.created_at)} — {run.passed}/{run.total}</h2>
          <div className="mt-2 grid grid-cols-2 gap-2 md:grid-cols-4">
            {Object.entries(run.by_type).map(([k, v]) => (
              <div key={k} className="rounded-xl border border-[#F1F5FB] p-2.5">
                <p className="text-[12px] text-[#64748B]">{d.types[k] || k}</p>
                <p className={`text-[18px] font-bold tabular-nums ${v.passed === v.total ? 'text-[#047857]' : 'text-[#B91C1C]'}`}>{v.passed}/{v.total}</p>
              </div>))}
          </div>
          {run.failures?.length > 0 && (
            <ul className="mt-3 space-y-2 text-[13px]" data-testid="golden-failures">
              {run.failures.map((f) => (
                <li key={f.id} className="rounded-xl border border-[#FDE2E2] p-2.5">
                  <p className="text-[11.5px] text-[#94A3B8]">{f.id} · {d.types[f.type] || f.type} · {ACCOUNTS[f.account] || f.account}</p>
                  <p className="font-semibold text-[#0B1C3F]">{f.text}</p>
                  <p className="text-[#B91C1C]">{(f.why || []).join(' · ')}</p>
                  {f.answer && <p className="mt-0.5 text-[#475569]">« {f.answer} »</p>}
                </li>))}
            </ul>
          )}
        </section>
      )}

      {run && run.real && (
        <section className="mt-4 rounded-2xl border border-[#EDF1F7] bg-white p-4" data-testid="golden-real-result">
          <h2 className="text-[15px] font-bold text-[#0B1C3F]">Données réelles anonymisées — {run.real.passed}/{run.real.total} ({run.real.shops} commerce{run.real.shops > 1 ? 's' : ''})</h2>
          {run.real.failures?.length > 0 && (
            <ul className="mt-2 space-y-1 text-[13px] text-[#B91C1C]">
              {run.real.failures.map((f) => <li key={f.id}><span translate="no">{f.id}</span> — {f.why.join(' ; ')}</li>)}
            </ul>
          )}
        </section>
      )}

      <RealShops />

      <section className="mt-4 rounded-2xl border border-[#EDF1F7] bg-white p-4" data-testid="golden-bank">
        <h2 className="text-[15px] font-bold text-[#0B1C3F]">Les questions</h2>
        <ul className="mt-2 divide-y divide-[#F1F5FB] text-[13px]">
          {Object.entries(d.bank).map(([k, qs]) => (
            <li key={k}>
              <details className="py-1.5">
                <summary className="flex cursor-pointer list-none items-center justify-between font-semibold text-[#334155]">
                  <span className="inline-flex items-center gap-1"><ChevronRight size={14} /> {d.types[k] || k}</span>
                  <span className="tabular-nums text-[#94A3B8]">{qs.length}</span></summary>
                <ul className="mt-1 space-y-0.5 pl-5 text-[#475569]">
                  {qs.map((q) => <li key={q.id}><span className="text-[#94A3B8]">{ACCOUNTS[q.account] || q.account}{q.surface === 'draft' ? ' · Rédiger' : ''} —</span> {q.text}</li>)}
                </ul>
              </details>
            </li>))}
        </ul>
      </section>
    </div>
  );
}
