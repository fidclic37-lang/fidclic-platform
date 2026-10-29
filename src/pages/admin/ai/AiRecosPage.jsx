import React, { useEffect, useState } from 'react';
import { adminAPI } from '../../../lib/api';
import { Breadcrumb, Loading, nf } from '../../crm/ui';
import { AiTabs } from './shared';

/* Super admin › FIDCLIC AI › Recommandations (user, 2026-10-29): every idea
   FidClic IA showed — shown, opened, sent — and what the sent ones brought,
   measured with the groupe témoin (api/features/reco_journal.py `kpis`). */

const PERIODS = [[7, '7 jours'], [30, '30 jours'], [90, '90 jours'], [365, '12 mois']];
const SURFACES = { copilote: 'Copilote', insights: 'Insights', dashboard: 'Tableau de bord', repere: '« A repéré »',
  clients: 'Clients', segmentation: 'Segmentation', alerte: 'Alertes', autopilot: 'Autopilot', autre: 'Autre' };
const pl = (n, one, many) => `${nf(n)} ${Number(n) > 1 ? many : one}`;
const pct = (v) => (v == null ? '—' : `${v} %`);
const eur = (v) => (v == null ? '—' : `${v > 0 ? '+' : ''}${Number(v).toLocaleString('fr-FR', { maximumFractionDigits: 0 })} €`);

const Tile = ({ label, value, note }) => (
  <div className="rounded-2xl border border-[#E6EEFB] bg-white p-4">
    <p className="text-[12.5px] text-[#64748B]">{label}</p>
    <p className="mt-1 text-[24px] font-bold leading-tight text-[#0B1C3F]">{value}</p>
    {note && <p className="mt-1 text-[12px] text-[#64748B]">{note}</p>}
  </div>
);

const Table = ({ testid, head, rows }) => (
  <div className="overflow-x-auto rounded-2xl border border-[#E6EEFB] bg-white">
    <table data-testid={testid} className="w-full text-[13px]">
      <thead><tr className="text-left text-[#94A3B8]">{head.map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr></thead>
      <tbody>
        {rows.length ? rows.map((r, i) => (
          <tr key={i} className="border-t border-[#F1F5F9]">{r.map((c, j) => <td key={j} className="px-3 py-2 text-[#0B1C3F]">{c}</td>)}</tr>
        )) : <tr><td colSpan={head.length} className="px-3 py-4 text-center text-[#94A3B8]">Rien sur cette période.</td></tr>}
      </tbody>
    </table>
  </div>
);

export default function AiRecosPage() {
  const [days, setDays] = useState(30);
  const [d, setD] = useState(null);
  useEffect(() => {
    setD(null);
    adminAPI.aiRecos(days).then(({ data }) => setD(data)).catch(() => setD({ error: true }));
  }, [days]);

  return (
    <div className="crm">
      <Breadcrumb items={[['Super Admin', '/admin'], ['FIDCLIC AI', '/admin/ai'], ['Recommandations']]} />
      <h1 className="text-[28px] font-bold leading-tight text-[#0B1C3F]">Recommandations de FidClic IA</h1>
      <p className="mb-3 text-[15px] text-[#475569]">
        Chaque idée montrée aux commerçants — Copilote, Insights, Tableau de bord, « FidClic IA a repéré » — ce qu&apos;ils en ont fait,
        et ce que les campagnes envoyées ont rapporté, mesuré avec le groupe témoin (15 jours après l&apos;envoi).
      </p>
      <AiTabs />
      <div className="mb-4 flex flex-wrap gap-2">
        {PERIODS.map(([v, l]) => (
          <button key={v} type="button" onClick={() => setDays(v)}
                  className={`rounded-lg border px-3 py-1.5 text-[13px] ${days === v ? 'border-[#2F6BFF] bg-[#EEF4FF] font-semibold text-[#2F6BFF]' : 'border-[#DCE3EE] text-[#334155]'}`}>{l}</button>
        ))}
      </div>
      {!d && <Loading />}
      {d?.error && <p className="text-[14px] text-[#B91C1C]">Les recommandations n&apos;ont pas pu être chargées.</p>}
      {d && !d.error && (
        <>
          <div data-testid="reco-kpis" className="mb-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Tile label="Adoption" value={pct(d.totals.adoption_pct)}
                  note={`${pl(d.totals.shops_opened, 'commerce', 'commerces')} sur ${nf(d.totals.shops_shown)} ${d.totals.shops_opened > 1 ? 'ont' : 'a'} ouvert une idée`} />
            <Tile label="Acceptation" value={pct(d.totals.acceptance_pct)}
                  note={`${pl(d.totals.opened, 'idée ouverte', 'idées ouvertes')} sur ${nf(d.totals.shown)} montrées (commerce × idée)`} />
            <Tile label="Exécution" value={pct(d.totals.execution_pct)} note={pl(d.totals.sent, 'campagne envoyée', 'campagnes envoyées')} />
            <Tile label="Gain mesuré" value={eur(d.totals.euros)}
                  note={d.totals.measured ? `${pl(d.totals.measured, 'campagne mesurée', 'campagnes mesurées')} · ${eur(d.totals.euros_per_send)} par envoi` : 'aucune campagne mesurée'} />
          </div>
          <h2 className="mb-2 text-[16px] font-bold text-[#0B1C3F]">Par idée</h2>
          <Table testid="reco-by-key" head={['Idée', 'Commerces (montrée)', 'Commerces (ouverte)', 'Envoyées', 'Mesurées', 'Gain']}
                 rows={(d.by_key || []).map((r) => [<span translate="no" className="notranslate font-mono text-[12.5px]">{r.key}</span>,
                   nf(r.shops_shown), nf(r.shops_opened), nf(r.sent), nf(r.measured), eur(r.measured ? r.euros : null)])} />
          <div className="mt-5 grid gap-5 lg:grid-cols-2">
            <div>
              <h2 className="mb-2 text-[16px] font-bold text-[#0B1C3F]">Par endroit</h2>
              <Table testid="reco-by-surface" head={['Endroit', 'Montrées', 'Ouvertes', 'Acceptation', 'Envoyées']}
                     rows={(d.by_surface || []).map((r) => [SURFACES[r.surface] || r.surface, nf(r.shown), nf(r.opened), pct(r.acceptance_pct), nf(r.sent)])} />
            </div>
            <div>
              <h2 className="mb-2 text-[16px] font-bold text-[#0B1C3F]">Par secteur</h2>
              <Table testid="reco-by-sector" head={['Secteur', 'Commerces', 'Adoption', 'Envoyées', 'Gain']}
                     rows={(d.by_sector || []).map((r) => [r.sector, nf(r.shops_shown), pct(r.adoption_pct), nf(r.sent), eur(r.euros || null)])} />
            </div>
          </div>
        </>
      )}
    </div>
  );
}
