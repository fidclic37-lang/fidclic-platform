import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { X, Download, Info } from 'lucide-react';
import { ownerAPI } from '../lib/api';
import { eur } from '../lib/money';

/**
 * « Impact FidClic » opened (user, 2026-11-10): the visits FidClic counted,
 * on the page the card was clicked on (the Tableau de bord or Analyses), for
 * that page's period — when, who, how much, and what brought them.
 * No « Par action » / « Par jour », no « Établissement » (the one chosen in
 * the menu) nor « Délai » (user, 2026-11-10: « hata do completely »).
 * « Attendus de toute façon » are listed in grey and never in the total.
 */
const DOT = {
  campagnes: '#2F6BFF', geolocalisation: '#8B5CF6', offres: '#F59E0B',
  automatisations: '#10B981', parrainage: '#F43F5E', attendus: '#CBD5E1',
};

const nf = (n) => new Intl.NumberFormat('fr-FR').format(n || 0);
const plural = (n, one, many) => `${nf(n)} ${n > 1 ? many : one}`;
const dayLabel = (iso) => new Date(iso).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', timeZone: 'Europe/Paris' });
const timeLabel = (iso) => new Date(iso).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Europe/Paris' });

function SourceTag({ k, label }) {
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-[12px] text-[#334155]">
      <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: DOT[k] }} />{label}
    </span>
  );
}

export default function ImpactDetail({ from = 'home', params, initial = {}, onClose }) {
  const [d, setD] = useState(null);
  const [error, setError] = useState('');
  const [source, setSource] = useState(initial.source || '');      // '' = all, 'attendus'
  const [exporting, setExporting] = useState(false);

  const box = useRef(null);
  useEffect(() => {
    setSource(initial.source || '');
    try { box.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }); } catch (_e) { /* old browsers */ }
  }, [initial.source, initial.at]);

  useEffect(() => {
    let alive = true;
    setD(null); setError('');
    ownerAPI.impactDetail(from, params)
      .then(({ data }) => { if (alive) setD(data); })
      .catch((e) => { if (alive) setError(e?.response?.data?.detail || "Impossible de charger le détail de l'impact."); });
    return () => { alive = false; };
  }, [from, params]);

  const labels = useMemo(() => Object.fromEntries((d?.sources || []).map((s) => [s.key, s.label])), [d]);
  const visits = useMemo(() => (d?.visits || []).filter((v) => !source
    || (source === 'attendus' ? v.attendu : v.source === source && !v.attendu)), [d, source]);

  const exportCsv = async () => {
    setExporting(true);
    try {
      const { data: blob } = await ownerAPI.impactDetailExport(from, params);
      const url = URL.createObjectURL(new Blob([blob], { type: 'text/csv;charset=utf-8' }));
      const a = document.createElement('a');
      a.href = url; a.download = `fidclic-impact-${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
    } catch { setError("L'export n'a pas abouti."); }
    finally { setExporting(false); }
  };

  const t = d?.totals;

  return (
    <section ref={box} id="impact-detail" aria-label="Détail de l'impact FidClic" data-testid="impact-detail"
             className="mb-4 scroll-mt-24 rounded-2xl border border-[#C9D5FB] bg-white p-5 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <h3 className="text-[17px] font-bold text-[#0B1C3F]">D'où vient votre CA FidClic</h3>
          {t && (
            <p className="mt-1 text-[12.5px] text-[#475569]">
              <b className="text-[#0F8B58] tabular-nums">{eur(t.revenue)}</b> · {plural(t.visits, 'visite ramenée', 'visites ramenées')}
              {t.attendus.visits > 0 && (
                <> · <span className="text-[#64748B]">{plural(t.attendus.visits, 'visite attendue', 'visites attendues')} de toute façon ({eur(t.attendus.revenue)}), non comptée{t.attendus.visits > 1 ? 's' : ''}</span></>
              )}
            </p>
          )}
        </div>
        <button type="button" onClick={exportCsv} disabled={!d || exporting}
                className="inline-flex items-center gap-1.5 rounded-lg border border-[#DCE5F5] px-3 py-1.5 text-[12.5px] font-semibold text-[#1D4ED8] disabled:opacity-50">
          <Download size={14} /> {exporting ? 'Export…' : 'Exporter (CSV)'}
        </button>
        <button type="button" onClick={onClose} aria-label="Fermer le détail"
                className="rounded-lg p-1.5 text-[#64748B] hover:bg-[#F1F5F9]"><X size={18} /></button>
      </div>

      {/* filters by source */}
      <div className="mt-4 flex flex-wrap gap-1.5" aria-label="Filtrer par source">
        {[{ key: '', label: 'Toutes' }, ...(d?.sources || []), { key: 'attendus', label: 'Attendus' }].map((s) => {
          const n = !t ? null : s.key === '' ? t.visits : s.key === 'attendus' ? t.attendus.visits : t.sources[s.key]?.visits;
          return (
            <button key={s.key || 'all'} type="button" aria-pressed={source === s.key} onClick={() => setSource(s.key)}
                    className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[12px] ${source === s.key ? 'border-[#2F6BFF] bg-[#EAF1FF] font-semibold text-[#1D4ED8]' : 'border-[#E2E8F0] text-[#475569]'}`}>
              {s.key && <span className="h-2 w-2 rounded-full" style={{ background: DOT[s.key] }} />}
              {s.label}{n !== null && n !== undefined && <span className="tabular-nums text-[#94A3B8]">{nf(n)}</span>}
            </button>
          );
        })}
      </div>

      <div className="mt-3">
        {error && <p className="rounded-xl bg-[#FEECEC] px-3 py-2 text-[12.5px] text-[#C0392B]">{error}</p>}
        {!d && !error && <p className="py-8 text-center text-[12.5px] text-[#94A3B8]">Chargement du détail…</p>}

        {d && (visits.length === 0 ? (
          <p className="py-8 text-center text-[12.5px] text-[#94A3B8]">Aucune visite ramenée par FidClic sur cette période.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-[12.5px]">
              <thead className="text-[11.5px] uppercase tracking-wide text-[#94A3B8]">
                <tr><th className="py-2 pr-3 font-semibold">Quand</th><th className="py-2 pr-3 font-semibold">Client</th>
                  {!d.clients_hidden && <th className="py-2 pr-3 text-right font-semibold">Montant</th>}
                  <th className="py-2 font-semibold">Grâce à</th></tr>
              </thead>
              <tbody>
                {visits.map((v) => (
                  <tr key={v.id || `${v.at}-${v.client}`} data-attendu={v.attendu ? '1' : undefined}
                      className={`border-t border-[#EEF2F8] ${v.attendu ? 'text-[#94A3B8]' : ''}`}>
                    <td className="whitespace-nowrap py-2.5 pr-3" translate="no">{dayLabel(v.at)} · {timeLabel(v.at)}</td>
                    <td className="py-2.5 pr-3">
                      {v.client_id
                        ? <Link to={`/dashboard/customers?q=${encodeURIComponent(v.client)}`} className={`font-medium hover:underline ${v.attendu ? '' : 'text-[#0B1C3F]'}`}>{v.client}</Link>
                        : <span className={d.clients_hidden ? '' : 'italic'}>{v.client}</span>}
                    </td>
                    {!d.clients_hidden && <td className={`py-2.5 pr-3 text-right tabular-nums ${v.attendu ? '' : 'font-semibold text-[#0B1C3F]'}`}>{eur(v.amount)}</td>}
                    <td className="py-2.5">
                      <div className={v.attendu ? '' : 'text-[#0B1C3F]'}>{v.action_name}</div>
                      <SourceTag k={v.attendu ? 'attendus' : v.source} label={labels[v.source]} />
                      {v.attendu && <div className="mt-0.5 text-[11px]">Attendu de toute façon · non compté</div>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {d.clients_hidden && (
              <p data-testid="clients-hidden" className="mt-2 flex items-center gap-1.5 text-[12px] text-[#64748B]">
                <Info size={13} /> Noms et montants des clients masqués : votre accès ne comprend pas la page Clients.
              </p>
            )}
            {d.truncated && (
              <p className="mt-2 flex items-center gap-1.5 text-[12px] text-[#64748B]">
                <Info size={13} /> Les {nf(d.visits.length)} visites les plus récentes sont affichées. L'export CSV les contient toutes.
              </p>
            )}
          </div>
        ))}
      </div>
      <p className="mt-3 text-[11.5px] text-[#94A3B8]">
        Une visite compte si le client est venu dans les {d?.window_days || 15} jours après un message FidClic (le plus récent l'emporte), ou s'il est venu par parrainage.
      </p>
    </section>
  );
}
