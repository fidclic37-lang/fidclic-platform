import React, { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Users, Grid3x3, Layers, Rocket, TrendingUp, TrendingDown, Map as MapIcon, Info, Loader2, ArrowUpRight, ArrowDownRight,
} from 'lucide-react';
import { adminAPI } from '../../../lib/api';
import { nf } from '../../crm/ui';

/* Super admin › Analytics › « Analyses avancées » (user, 2026-10-01) —
   features/analytics_deep.py. Each section loads on its own. */

const fr = (v, d = 1) => (v == null ? '—' : Number(v).toLocaleString('fr-FR', { maximumFractionDigits: d }));
const eur = (v) => (v == null ? '—' : `€${Number(v).toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`);
const MONTH = (key) => new Date(`${key}-15T12:00:00`).toLocaleDateString('fr-FR', { month: 'short', year: 'numeric' });

function useLoad(fn, deps) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState('');
  useEffect(() => {
    let alive = true;
    setD(null); setErr('');
    fn().then(({ data }) => { if (alive) setD(data); }).catch((e) => { if (alive) setErr(e?.response?.data?.detail || 'Indisponible pour le moment.'); });
    return () => { alive = false; };
  }, deps); // eslint-disable-line react-hooks/exhaustive-deps
  return [d, err];
}
const Wait = ({ err }) => <div className="flex items-center justify-center gap-2 py-12 text-[13px] text-[#64748B]">{err || <><Loader2 size={15} className="animate-spin" /> Chargement…</>}</div>;
const Tip = ({ text }) => (
  <span className="group relative inline-flex align-middle"><Info size={14} className="text-[#94A3B8]" />
    <span className="pointer-events-none absolute right-0 top-6 z-20 hidden w-72 rounded-lg bg-[#0B1C3F] px-3 py-2 text-left text-[12px] font-normal leading-snug text-white shadow-lg group-hover:block">{text}</span>
  </span>
);

/* ---------------------------------------------------------------- cohorts */
export function CohortsSection({ Card, Head }) {
  const [d, err] = useLoad(() => adminAPI.deepCohorts({ months: 12 }), []);
  const shade = (p) => (p == null ? '#F8FAFC' : `rgba(16,185,129,${0.08 + (p / 100) * 0.62})`);
  return (
    <Card>
      <Head icon={Users} title="Cohortes de rétention" sub="Par mois d'inscription : part des commerces toujours clients (en essai ou abonnés) les mois suivants."
            right={<Tip text="Mois 0 = fin du mois d'inscription. Les mois passés sont reconstitués à partir des dates connues (inscription, résiliation, fin d'essai, suspension) ; le mois en cours utilise la situation d'aujourd'hui." />} />
      {!d ? <Wait err={err} /> : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[820px] border-separate border-spacing-[3px] text-center text-[12px]">
            <thead><tr className="text-[#64748B]"><th className="px-2 py-1 text-left font-medium">Inscrits en</th><th className="px-2 py-1 font-medium">Commerces</th>
              {Array.from({ length: d.months }, (_, k) => <th key={k} className="px-1 py-1 font-medium">M{k}</th>)}</tr></thead>
            <tbody>
              {d.rows.map((r) => (
                <tr key={r.cohort}>
                  <td className="whitespace-nowrap px-2 py-1.5 text-left font-medium text-[#0B1C3F]">{MONTH(r.cohort)}</td>
                  <td className="px-2 py-1.5 text-[#475569]">{nf(r.size)}</td>
                  {Array.from({ length: d.months }, (_, k) => { const c = r.cells[k]; return (
                    <td key={k} className="rounded-md px-1 py-1.5 font-semibold" title={c && c.pct != null ? `${c.kept} / ${r.size} toujours clients` : ''}
                        style={{ background: c ? shade(c.pct) : 'transparent', color: c && c.pct != null && c.pct > 60 ? '#fff' : '#0B1C3F' }}>
                      {c ? (c.pct == null ? '' : `${c.pct}%`) : ''}
                    </td>); })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

/* ---------------------------------------------------------------- benchmarks */
export function BenchmarksSection({ Card, Head }) {
  const [d, err] = useLoad(() => adminAPI.deepBenchmarks(), []);
  return (
    <Card>
      <Head icon={Grid3x3} title="Benchmarks par secteur" sub="Le commerce médian de chaque secteur, sur les 90 derniers jours."
            right={<Tip text="Médiane (et non moyenne) : un très gros commerce ne fausse pas le résultat. Seuls les commerces de plus de 30 jours avec de l'activité comptent. Le panier moyen ne prend que les passages où un montant a été saisi. Moins de 3 commerces : échantillon faible, à lire avec prudence." />} />
      {!d ? <Wait err={err} /> : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-left text-[13px]">
            <thead className="border-b border-[#EDF1F7] text-[12px] text-[#64748B]">
              <tr><th className="px-2 py-2 font-medium">Secteur</th><th className="px-2 py-2 font-medium">Commerces</th><th className="px-2 py-2 text-right font-medium">Panier moyen</th>
                <th className="px-2 py-2 text-right font-medium">Visites / client</th><th className="px-2 py-2 text-right font-medium">Taux de retour</th>
                <th className="px-2 py-2 text-right font-medium">Cartes / sem.</th><th className="px-2 py-2 text-right font-medium">Scans / sem.</th></tr>
            </thead>
            <tbody>
              {d.rows.map((r) => { const all = r.sector === 'Toute la plateforme'; return (
                <tr key={r.sector} className={`border-b border-[#F4F7FC] ${all ? 'bg-[#F5F8FF] font-semibold' : ''}`}>
                  <td className="px-2 py-2 text-[#0B1C3F]">{r.sector}</td>
                  <td className="px-2 py-2 text-[#475569]">{nf(r.n)} {r.low_sample && !all && <span className="ml-1 rounded-md bg-[#FFF4DB] px-1.5 py-0.5 text-[11px] font-medium text-[#B45309]">échantillon faible</span>}</td>
                  <td className="px-2 py-2 text-right" title={r.panier_n ? `${r.panier_n} commerce(s) saisissent un montant` : 'Aucun montant saisi'}>{eur(r.panier)}</td>
                  <td className="px-2 py-2 text-right">{fr(r.visites_client)}</td>
                  <td className="px-2 py-2 text-right">{r.retour == null ? '—' : `${fr(r.retour, 0)}%`}</td>
                  <td className="px-2 py-2 text-right">{fr(r.cartes_semaine)}</td>
                  <td className="px-2 py-2 text-right">{fr(r.scans_semaine)}</td>
                </tr>); })}
              {!d.rows.length && <tr><td colSpan={7} className="py-10 text-center text-[#94A3B8]">Pas encore assez d'activité.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

/* ---------------------------------------------------------------- adoption */
export function AdoptionSection({ Card, Head }) {
  const [d, err] = useLoad(() => adminAPI.deepAdoption(), []);
  return (
    <Card>
      <Head icon={Layers} title="Adoption des fonctionnalités par plan" sub="Part des commerces de chaque plan qui utilisent vraiment chaque fonctionnalité."
            right={d && <Tip text={Object.entries(d.definitions).map(([k, v]) => `${d.features.find((f) => f.key === k)?.label} : ${v}`).join(' · ')} />} />
      {!d ? <Wait err={err} /> : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[860px] text-left text-[12.5px]">
            <thead className="border-b border-[#EDF1F7] text-[12px] text-[#64748B]">
              <tr><th className="px-2 py-2 font-medium">Plan</th>{d.features.map((f) => <th key={f.key} className="px-2 py-2 text-center font-medium">{f.label}</th>)}</tr>
            </thead>
            <tbody>
              {d.rows.map((r) => (
                <tr key={r.plan} className="border-b border-[#F4F7FC]">
                  <td className="whitespace-nowrap px-2 py-2.5"><strong className="text-[#0B1C3F]">{r.label}</strong><span className="block text-[11.5px] text-[#64748B]">{nf(r.count)} commerce{r.count > 1 ? 's' : ''}</span></td>
                  {r.cells.map((c) => (
                    <td key={c.key} className="px-2 py-2.5 text-center">
                      {c.included ? (
                        <span className="inline-block w-[74px]">
                          <strong className="block text-[13px] text-[#0B1C3F]">{c.pct}%</strong>
                          <span className="mt-1 block h-1.5 overflow-hidden rounded-full bg-[#EEF2F8]"><span className="block h-full rounded-full bg-[#2F6BFF]" style={{ width: `${c.pct}%` }} /></span>
                          <span className="text-[11px] text-[#94A3B8]">{nf(c.count)}/{nf(r.count)}</span>
                        </span>
                      ) : <span className="text-[11.5px] text-[#CBD5E1]" title="Pas dans ce plan">Non inclus</span>}
                    </td>
                  ))}
                </tr>
              ))}
              {!d.rows.length && <tr><td colSpan={9} className="py-10 text-center text-[#94A3B8]">Aucun commerce client.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

/* ---------------------------------------------------------------- plan moves */
const KIND = { upgrade: ['Montée', '#E7F7EE', '#0F8B58'], downgrade: ['Descente', '#FDECEF', '#E11D48'], activation: ['Activation', '#EAF1FF', '#2F6BFF'], change: ['Changement', '#F1F5F9', '#475569'] };
export function PlanMovesSection({ range, Card, Head }) {
  const [d, err] = useLoad(() => adminAPI.deepPlanMoves(range), [range.from, range.to]);
  return (
    <Card>
      <Head icon={Rocket} title="Upgrades / downgrades" sub="Changements de plan sur la période — par l'équipe ou payés en ligne." />
      {!d ? <Wait err={err} /> : (
        <>
          <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
            {[['Montées', d.upgrades, '#0F8B58'], ['Descentes', d.downgrades, '#E11D48'], ['Activations', d.activations, '#2F6BFF'],
              ['MRR', `${d.mrr_change >= 0 ? '+' : ''}€${fr(d.mrr_change, 0)}`, d.mrr_change >= 0 ? '#0F8B58' : '#E11D48']].map(([l, v, c]) => (
              <span key={l} className="rounded-xl bg-[#F8FAFF] px-3 py-2"><span className="block text-[11.5px] text-[#64748B]">{l}</span><strong className="text-[18px]" style={{ color: c }}>{v}</strong></span>
            ))}
          </div>
          <ul className="max-h-[260px] divide-y divide-[#F1F5F9] overflow-y-auto">
            {d.rows.map((r, i) => { const [l, bg, fg] = KIND[r.kind] || KIND.change; return (
              <li key={i} className="flex items-center gap-3 py-2 text-[12.5px]">
                <span className="rounded-md px-2 py-0.5 text-[11px] font-semibold" style={{ background: bg, color: fg }}>{l}</span>
                <span className="min-w-0 flex-1"><Link to={`/admin/commerces/${r.tenant_id}`} className="font-medium text-[#0B1C3F] hover:text-[#2F6BFF]">{r.name}</Link>
                  <span className="block text-[11.5px] text-[#64748B]">{r.from ? `${r.from} → ` : ''}{r.to} · {r.by}</span></span>
                <span className={`whitespace-nowrap font-semibold ${r.mrr_change >= 0 ? 'text-[#0F8B58]' : 'text-[#E11D48]'}`}>{r.mrr_change >= 0 ? '+' : ''}€{fr(r.mrr_change, 0)}</span>
                <span className="whitespace-nowrap text-[11.5px] text-[#94A3B8]">{new Date(r.at).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' })}</span>
              </li>); })}
            {!d.rows.length && <li className="py-8 text-center text-[12.5px] text-[#94A3B8]">Aucun changement de plan sur la période.</li>}
          </ul>
        </>
      )}
    </Card>
  );
}

/* ---------------------------------------------------------------- growth */
function GrowthList({ rows, up }) {
  if (!rows.length) return <p className="py-6 text-center text-[12.5px] text-[#94A3B8]">Personne ici pour le moment.</p>;
  return (
    <ul className="divide-y divide-[#F1F5F9]">
      {rows.map((r, i) => (
        <li key={r.id} className="flex items-center gap-3 py-2">
          <span className="w-4 text-[12px] text-[#94A3B8]">{i + 1}</span>
          <span className="min-w-0 flex-1"><Link to={`/admin/commerces/${r.id}`} className="block truncate text-[13px] font-medium text-[#0B1C3F] hover:text-[#2F6BFF]">{r.name}</Link>
            <span className="block text-[11.5px] text-[#64748B]" title={`Scans ${r.values.scans[0]} → ${r.values.scans[1]} · Cartes ${r.values.cartes[0]} → ${r.values.cartes[1]} · CA €${fr(r.values.ca[0], 0)} → €${fr(r.values.ca[1], 0)}`}>
              Scans {r.parts.scans == null ? '—' : `${r.parts.scans > 0 ? '+' : ''}${r.parts.scans}%`} · Cartes {r.parts.cartes == null ? '—' : `${r.parts.cartes > 0 ? '+' : ''}${r.parts.cartes}%`} · CA {r.parts.ca == null ? '—' : `${r.parts.ca > 0 ? '+' : ''}${r.parts.ca}%`}
            </span></span>
          <span className={`inline-flex items-center gap-0.5 rounded-lg px-2 py-1 text-[12.5px] font-bold ${up ? 'bg-[#E7F7EE] text-[#0F8B58]' : 'bg-[#FDECEF] text-[#E11D48]'}`}>
            {r.score >= 0 ? <ArrowUpRight size={13} /> : <ArrowDownRight size={13} />}{r.score > 0 ? '+' : ''}{r.score}%</span>
        </li>
      ))}
    </ul>
  );
}
export function GrowthSection({ range, Card, Head }) {
  const [d, err] = useLoad(() => adminAPI.deepGrowth(range), [range.from, range.to]);
  return (
    <Card>
      <Head icon={TrendingUp} title="Top / bottom croissance" sub="Score combiné : évolution des scans, des nouvelles cartes et du CA, période vs la précédente."
            right={d && <Tip text={`Chaque évolution est plafonnée entre ${d.rules.cap[0]} % et +${d.rules.cap[1]} %, puis on fait la moyenne. Ne comptent que les commerces présents sur les deux périodes, avec au moins ${d.rules.min_activity} scans ou cartes. Écartés : ${d.too_young} trop récent(s), ${d.too_quiet} trop peu actif(s).`} />} />
      {!d ? <Wait err={err} /> : (
        <>
          <div className="grid gap-4 md:grid-cols-2">
            <div><p className="mb-1 flex items-center gap-1.5 text-[13px] font-semibold text-[#0F8B58]"><TrendingUp size={15} /> Les plus en hausse</p><GrowthList rows={d.top} up /></div>
            <div><p className="mb-1 flex items-center gap-1.5 text-[13px] font-semibold text-[#E11D48]"><TrendingDown size={15} /> Les plus en baisse</p><GrowthList rows={d.bottom} /></div>
          </div>
          <p className="mt-2 text-[11.5px] text-[#94A3B8]">{nf(d.eligible)} commerce(s) comparé(s) · {nf(d.too_young)} trop récent(s) · {nf(d.too_quiet)} trop peu actif(s).</p>
        </>
      )}
    </Card>
  );
}

/* ---------------------------------------------------------------- map */
const STAND = { essai: ['#8B5CF6', 'En essai'], abonne: ['#10B981', 'Abonné'], impaye: ['#E11D48', 'Impayé'], resilie: ['#0B1C3F', 'Résilié'], non_converti: ['#F59E0B', 'Essai non converti'] };
export function MapSection({ Card, Head }) {
  const [d, err] = useLoad(() => adminAPI.deepMap(), []);
  const box = useRef(null);
  const map = useRef(null);
  const [noLib, setNoLib] = useState(false);
  useEffect(() => {
    if (!d || !box.current) return undefined;
    let tries = 0;
    const draw = () => {
      const L = window.L;
      if (!L) { tries += 1; if (tries > 40) setNoLib(true); else setTimeout(draw, 250); return; }
      if (!map.current) {
        map.current = L.map(box.current, { center: [46.6, 2.4], zoom: 5.5, scrollWheelZoom: false });
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: '© OpenStreetMap', maxZoom: 18 }).addTo(map.current);
      }
      map.current._fcLayer?.remove?.();
      const layer = L.layerGroup().addTo(map.current);
      const bounds = [];
      d.points.forEach((p) => {
        const [color, label] = STAND[p.standing] || STAND.abonne;
        const m = L.circleMarker([p.lat, p.lng], { radius: 7 + Math.min(10, Math.sqrt(p.clients || 0) / 3), color: '#fff', weight: 2, fillColor: color, fillOpacity: 0.85 });
        const esc = (x) => String(x || '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
        m.bindPopup(`<strong>${esc(p.name)}</strong><br/>${esc(p.city)} ${esc(p.postal_code)}<br/>${esc(p.plan?.label)} · ${label}${p.status_label ? ` · ${esc(p.status_label)}` : ''}<br/>${p.clients} clients<br/><a href="/admin/commerces/${encodeURIComponent(p.id)}">Voir le commerce</a><br/><span style="color:#94A3B8;font-size:11px">Position : ${esc(p.source)}</span>`);
        m.addTo(layer);
        bounds.push([p.lat, p.lng]);
      });
      if (bounds.length > 1) map.current.fitBounds(bounds, { padding: [30, 30], maxZoom: 12 });
      else if (bounds.length === 1) map.current.setView(bounds[0], 11);
      map.current._fcLayer = layer;
    };
    draw();
    return undefined;
  }, [d]);
  useEffect(() => () => { if (map.current) { map.current.remove(); map.current = null; } }, []);
  return (
    <Card>
      <Head icon={MapIcon} title="Carte des commerces" sub="Chaque commerce à sa position — sinon au centre de son code postal ou de sa ville. Couleur = situation, taille = nombre de clients." />
      {!d ? <Wait err={err} /> : (
        <>
          <div className="mb-2 flex flex-wrap gap-3 text-[12px] text-[#475569]">
            {Object.entries(STAND).map(([k, [c, l]]) => <span key={k} className="inline-flex items-center gap-1.5"><i className="h-2.5 w-2.5 rounded-full" style={{ background: c }} />{l} ({nf(d.points.filter((p) => p.standing === k).length)})</span>)}
          </div>
          {noLib ? <p className="rounded-xl bg-[#F8FAFF] p-6 text-center text-[13px] text-[#64748B]">La carte n'a pas pu se charger (bloqueur ou hors ligne).</p>
            : <div ref={box} className="h-[420px] w-full overflow-hidden rounded-xl border border-[#EDF1F7]" />}
          {d.missing.length > 0 && <p className="mt-2 text-[12px] text-[#64748B]">{nf(d.missing.length)} commerce(s) sans adresse exploitable : {d.missing.slice(0, 6).map((m) => m.name).join(', ')}{d.missing.length > 6 ? '…' : ''}</p>}
        </>
      )}
    </Card>
  );
}
