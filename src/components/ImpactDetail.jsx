import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { X, Download, Info } from 'lucide-react';
import { ownerAPI } from '../lib/api';
import { eur } from '../lib/money';

/**
 * « Impact FidClic » opened (user, 2026-11-10): where the CA FidClic came
 * from — by action, by visit, by day — on the page the card was clicked on
 * (the Tableau de bord or Analyses), for that page's period.
 * « Attendus de toute façon » are listed in grey and never in the total.
 */
const DOT = {
  campagnes: '#2F6BFF', geolocalisation: '#8B5CF6', offres: '#F59E0B',
  automatisations: '#10B981', parrainage: '#F43F5E', attendus: '#CBD5E1',
};
const VIEWS = [
  { key: 'action', label: 'Par action' },
  { key: 'visite', label: 'Par visite' },
  { key: 'jour', label: 'Par jour' },
];

const nf = (n) => new Intl.NumberFormat('fr-FR').format(n || 0);
const plural = (n, one, many) => `${nf(n)} ${n > 1 ? many : one}`;
const dayLabel = (iso) => new Date(iso).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', timeZone: 'Europe/Paris' });
const timeLabel = (iso) => new Date(iso).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Europe/Paris' });
const dateOnly = (ymd) => new Date(`${ymd}T12:00:00`).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' });
const parisDay = (iso) => new Date(iso).toLocaleDateString('en-CA', { timeZone: 'Europe/Paris' });

function after(v) {
  if (v.source === 'parrainage') return 'Filleul';
  if (v.days_after === null || v.days_after === undefined) return '—';
  if (v.days_after === 0) return 'Le jour même';
  return `${v.days_after} jour${v.days_after > 1 ? 's' : ''} après`;
}

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
  const [view, setView] = useState(initial.view || 'action');
  const [source, setSource] = useState(initial.source || '');      // '' = all, 'attendus'
  const [action, setAction] = useState(null);                       // {key, name}
  const [day, setDay] = useState('');
  const [exporting, setExporting] = useState(false);

  const box = useRef(null);
  useEffect(() => {
    setView(initial.view || 'action'); setSource(initial.source || ''); setAction(null); setDay('');
    try { box.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }); } catch (_e) { /* old browsers */ }
  }, [initial.view, initial.source, initial.at]);

  useEffect(() => {
    let alive = true;
    setD(null); setError('');
    ownerAPI.impactDetail(from, params)
      .then(({ data }) => { if (alive) setD(data); })
      .catch((e) => { if (alive) setError(e?.response?.data?.detail || "Impossible de charger le détail de l'impact."); });
    return () => { alive = false; };
  }, [from, params]);

  const labels = useMemo(() => Object.fromEntries((d?.sources || []).map((s) => [s.key, s.label])), [d]);

  const keepSource = (src, attendu) => {
    if (!source) return true;
    if (source === 'attendus') return attendu;
    return src === source && !attendu;
  };
  const visits = useMemo(() => (d?.visits || []).filter((v) => keepSource(v.source, v.attendu)
    && (!action || v.action === action.key) && (!day || parisDay(v.at) === day)), [d, source, action, day]); // eslint-disable-line react-hooks/exhaustive-deps
  const actions = useMemo(() => (d?.actions || []).filter((a) => !source
    || (source === 'attendus' ? a.attendus.visits > 0 : a.source === source && a.visits > 0)), [d, source]);

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

  const openAction = (a) => { setAction({ key: a.key, name: a.name }); setDay(''); setView('visite'); };
  const openDay = (date) => { setDay(date); setAction(null); setView('visite'); };

  const t = d?.totals;
  const maxDay = Math.max(1, ...(d?.days || []).map((x) => x.total + x.attendus));

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

      {/* views + filters */}
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <div role="tablist" className="flex rounded-xl bg-[#F1F5FB] p-1">
          {VIEWS.map((x) => (
            <button key={x.key} type="button" role="tab" aria-selected={view === x.key} onClick={() => setView(x.key)}
                    className={`rounded-lg px-3 py-1.5 text-[12.5px] font-semibold ${view === x.key ? 'bg-white text-[#0B1C3F] shadow-sm' : 'text-[#64748B]'}`}>
              {x.label}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap gap-1.5" aria-label="Filtrer par source">
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
      </div>
      {(action || day) && view === 'visite' && (
        <div className="mt-2 flex flex-wrap gap-1.5 text-[12px]">
          {action && (
            <button type="button" onClick={() => setAction(null)} className="inline-flex items-center gap-1 rounded-full bg-[#0B1C3F] px-2.5 py-1 text-white">
              {action.name} <X size={12} aria-label="Retirer ce filtre" />
            </button>
          )}
          {day && (
            <button type="button" onClick={() => setDay('')} className="inline-flex items-center gap-1 rounded-full bg-[#0B1C3F] px-2.5 py-1 text-white">
              {dateOnly(day)} <X size={12} aria-label="Retirer ce filtre" />
            </button>
          )}
        </div>
      )}

      <div className="mt-3">
        {error && <p className="rounded-xl bg-[#FEECEC] px-3 py-2 text-[12.5px] text-[#C0392B]">{error}</p>}
        {!d && !error && <p className="py-8 text-center text-[12.5px] text-[#94A3B8]">Chargement du détail…</p>}

        {d && view === 'action' && (
          actions.length === 0 ? <Empty /> : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-[12.5px]">
                <thead className="text-[11.5px] uppercase tracking-wide text-[#94A3B8]">
                  <tr><th className="py-2 pr-3 font-semibold">Action</th><th className="py-2 pr-3 font-semibold">Envoyée le</th>
                    <th className="py-2 pr-3 text-right font-semibold">Clients revenus</th><th className="py-2 pr-3 text-right font-semibold">Visites</th>
                    <th className="py-2 text-right font-semibold">CA FidClic</th></tr>
                </thead>
                <tbody>
                  {actions.map((a) => (
                    <tr key={a.key} className="cursor-pointer border-t border-[#EEF2F8] hover:bg-[#F8FAFF]" onClick={() => openAction(a)}>
                      <td className="py-2.5 pr-3">
                        <button type="button" className="text-left font-semibold text-[#0B1C3F] hover:underline" onClick={(e) => { e.stopPropagation(); openAction(a); }}>
                          {a.name}
                        </button>
                        <div className="mt-0.5"><SourceTag k={a.source} label={labels[a.source] || a.kind} /></div>
                      </td>
                      <td className="py-2.5 pr-3 text-[#475569]">
                        {a.source === 'parrainage' ? 'Filleuls' : a.first_sent ? (a.first_sent.slice(0, 10) === (a.last_sent || '').slice(0, 10)
                          ? dayLabel(a.first_sent) : `du ${dayLabel(a.first_sent)} au ${dayLabel(a.last_sent)}`) : '—'}
                      </td>
                      <td className="py-2.5 pr-3 text-right tabular-nums">{nf(a.clients)}</td>
                      <td className="py-2.5 pr-3 text-right tabular-nums">
                        {nf(a.visits)}
                        {a.attendus.visits > 0 && <div className="text-[11px] text-[#94A3B8]">+ {nf(a.attendus.visits)} attendue{a.attendus.visits > 1 ? 's' : ''}</div>}
                      </td>
                      <td className="py-2.5 text-right font-bold tabular-nums text-[#0B1C3F]">{eur(a.revenue)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        )}

        {d && view === 'visite' && (
          visits.length === 0 ? <Empty /> : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-[12.5px]">
                <thead className="text-[11.5px] uppercase tracking-wide text-[#94A3B8]">
                  <tr><th className="py-2 pr-3 font-semibold">Quand</th><th className="py-2 pr-3 font-semibold">Client</th>
                    {!d.clients_hidden && <th className="py-2 pr-3 text-right font-semibold">Montant</th>}<th className="py-2 pr-3 font-semibold">Établissement</th>
                    <th className="py-2 pr-3 font-semibold">Grâce à</th><th className="py-2 font-semibold">Délai</th></tr>
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
                      <td className="py-2.5 pr-3">{v.store}</td>
                      <td className="py-2.5 pr-3">
                        <div className={v.attendu ? '' : 'text-[#0B1C3F]'}>{v.action_name}</div>
                        <SourceTag k={v.attendu ? 'attendus' : v.source} label={labels[v.source]} />
                        {v.attendu && <div className="mt-0.5 text-[11px]">Attendu de toute façon · non compté</div>}
                      </td>
                      <td className="whitespace-nowrap py-2.5">{after(v)}</td>
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
          )
        )}

        {d && view === 'jour' && (
          d.days.length === 0 ? <Empty /> : (
            <div>
              <div className="flex h-44 items-end gap-1 overflow-x-auto pb-1" aria-label="CA FidClic par jour">
                {d.days.map((x) => {
                  const parts = [...(d.sources || []).map((s) => [s.key, x[s.key]]), ['attendus', x.attendus]]
                    .filter(([k, val]) => val > 0 && (!source || k === source));
                  const shown = parts.reduce((s, [, val]) => s + val, 0);
                  return (
                    <button key={x.date} type="button" onClick={() => openDay(x.date)}
                            title={`${dateOnly(x.date)} : ${eur(x.total)}${x.attendus ? ` (+ ${eur(x.attendus)} attendus)` : ''}`}
                            aria-label={`${dateOnly(x.date)} : ${eur(x.total)}`}
                            className="group flex h-full min-w-[18px] flex-1 flex-col-reverse items-stretch">
                      <span className="flex flex-col-reverse overflow-hidden rounded-t-md group-hover:opacity-80" style={{ height: `${(shown / maxDay) * 100}%` }}>
                        {parts.map(([k, val]) => <span key={k} style={{ height: `${(val / (shown || 1)) * 100}%`, background: DOT[k] }} />)}
                      </span>
                    </button>
                  );
                })}
              </div>
              <div className="flex justify-between text-[11px] text-[#94A3B8]">
                <span>{dateOnly(d.days[0].date)}</span><span>{dateOnly(d.days[d.days.length - 1].date)}</span>
              </div>
              <p className="mt-2 text-[12px] text-[#64748B]">Cliquez sur un jour pour voir ses visites.</p>
            </div>
          )
        )}
      </div>
      <p className="mt-3 text-[11.5px] text-[#94A3B8]">
        Une visite compte si le client est venu dans les {d?.window_days || 15} jours après un message FidClic (le plus récent l'emporte), ou s'il est venu par parrainage.
      </p>
    </section>
  );
}

function Empty() {
  return <p className="py-8 text-center text-[12.5px] text-[#94A3B8]">Aucune visite ramenée par FidClic sur cette période.</p>;
}
