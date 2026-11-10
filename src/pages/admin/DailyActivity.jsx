import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Activity, ChevronLeft, ChevronRight, ChevronDown, Gift, Send, UserPlus, Store } from 'lucide-react';
import { adminAPI } from '../../lib/api';
import { protectNames } from '../../lib/translator';
import { Card, Loading, nf } from '../crm/ui';

/* Super admin › Tableau de bord › « Activité du jour » (user, 2026-11-10).
   Three sections — Parrainage, Campagnes + automatisations, Nouveaux
   clients — with every business's activity of one Paris day: today live
   (it moves to the new day by itself at midnight), any past day with ‹ ›.
   One line per business, per store for a franchise; a line opens its
   details. */

const SECTION = {
  parrainage: { icon: Gift, color: '#E11D48', bg: '#FDECEF', empty: 'Aucun parrainage ce jour-là.' },
  campagnes: { icon: Send, color: '#2F6BFF', bg: '#EAF1FF', empty: 'Aucune campagne ni automatisation envoyée ce jour-là.' },
  nouveaux_clients: { icon: UserPlus, color: '#10B981', bg: '#E7F7EE', empty: 'Aucun nouveau client ce jour-là.' },
};
const LIVE_MS = 60 * 1000;
const hm = (s) => (s ? new Date(s).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Paris' }) : '');
const dayLabel = (s) => new Date(`${s}T12:00:00`).toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
const plural = (n, one, many) => `${nf(n)} ${n > 1 ? many : one}`;

function lineText(key, r) {
  if (key === 'parrainage') return plural(r.count, 'parrainage', 'parrainages');
  if (key === 'nouveaux_clients') return plural(r.count, 'nouveau client', 'nouveaux clients');
  return [r.campaigns ? plural(r.campaigns, 'campagne', 'campagnes') : null,
    r.automations ? plural(r.automations, 'message automatique', 'messages automatiques') : null,
    plural(r.messages, 'message', 'messages') + ' au total'].filter(Boolean).join(' · ');
}

function Item({ k, i }) {
  if (k === 'parrainage') {
    return <><span translate="no" className="font-medium text-[#0B1C3F]">{i.parrain}</span> → <span translate="no" className="font-medium text-[#0B1C3F]">{i.filleul}</span>
      <span className={`ml-2 rounded px-1.5 py-0.5 text-[11px] ${i.status === 'Validé' ? 'bg-[#E7F7EE] text-[#0F8B58]' : 'bg-[#FFF4DB] text-[#B45309]'}`}>{i.status}</span></>;
  }
  if (k === 'nouveaux_clients') return <><span translate="no" className="font-medium text-[#0B1C3F]">{i.name}</span><span className="ml-2 text-[#64748B]">{i.source}</span></>;
  return <><span className={`mr-2 rounded px-1.5 py-0.5 text-[11px] ${i.kind === 'campagne' ? 'bg-[#EAF1FF] text-[#2F6BFF]' : 'bg-[#F3EEFF] text-[#7C3AED]'}`}>{i.kind === 'campagne' ? 'Campagne' : 'Automatisation'}</span>
    <span translate="no" className="font-medium text-[#0B1C3F]">{i.name}</span><span className="ml-2 text-[#64748B]">{plural(i.messages, 'message', 'messages')}</span></>;
}

function Section({ s }) {
  const navigate = useNavigate();
  const [open, setOpen] = useState(null);
  const meta = SECTION[s.key] || SECTION.campagnes;
  const I = meta.icon;
  return (
    <Card className="flex min-w-0 flex-col">
      <header className="mb-3 flex items-center gap-2.5">
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full" style={{ background: meta.bg, color: meta.color }}><I size={16} /></span>
        <h3 className="flex-1 text-[14.5px] font-bold text-[#0B1C3F]">{s.title}</h3>
        <span data-testid={`total-${s.key}`} className="rounded-full px-2.5 py-0.5 text-[12.5px] font-semibold tabular-nums" style={{ background: meta.bg, color: meta.color }}>{nf(s.total)}</span>
      </header>
      {!s.rows.length && <p className="py-6 text-center text-[13px] text-[#94A3B8]">{meta.empty}</p>}
      <ul className="max-h-[420px] space-y-1.5 overflow-y-auto" data-testid={`section-${s.key}`}>
        {s.rows.map((r) => {
          const id = `${r.tenant_id}:${r.store_id || ''}`;
          const shown = open === id;
          return (
            <li key={id} className="rounded-xl border border-[#F1F5F9]">
              <button type="button" onClick={() => setOpen(shown ? null : id)} aria-expanded={shown}
                      className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-[#FAFCFF]">
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] font-semibold text-[#0B1C3F]" translate="no">{r.tenant_name}</span>
                  {r.store_name && <span className="flex items-center gap-1 truncate text-[11.5px] text-[#64748B]" translate="no"><Store size={11} /> {r.store_name}</span>}
                  <span className="block truncate text-[12px] text-[#475569]">{lineText(s.key, r)}</span>
                </span>
                <span className="shrink-0 text-right text-[11.5px] text-[#94A3B8]" translate="no">dernier<br />{hm(r.last_at)}</span>
                <ChevronDown size={15} className={`shrink-0 text-[#94A3B8] transition ${shown ? 'rotate-180' : ''}`} />
              </button>
              {shown && (
                <div className="border-t border-[#F1F5F9] px-3 py-2">
                  <ul className="space-y-1 text-[12.5px]">
                    {r.items.map((i, n) => (
                      <li key={n} className="flex items-start gap-2">
                        <span className="w-11 shrink-0 tabular-nums text-[#94A3B8]" translate="no">{hm(i.at)}</span>
                        <span className="min-w-0 flex-1"><Item k={s.key} i={i} /></span>
                      </li>
                    ))}
                  </ul>
                  {r.more > 0 && <p className="mt-1 text-[11.5px] text-[#94A3B8]">… et {nf(r.more)} de plus.</p>}
                  <button type="button" onClick={() => navigate(`/admin/commerces/${r.tenant_id}${r.store_id ? `?store=${encodeURIComponent(r.store_id)}` : ''}`)}
                          className="mt-2 inline-flex items-center gap-1 text-[12px] font-medium text-[#2F6BFF]">Ouvrir {r.store_name ? 'la boutique' : 'le commerce'} <ChevronRight size={13} /></button>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

export default function DailyActivity() {
  const [day, setDay] = useState(null);           // null = today, live
  const [d, setD] = useState(null);
  const [err, setErr] = useState('');
  const load = useCallback(() => {
    adminAPI.dashboardActivity(day ? { day } : undefined)
      .then(({ data }) => {
        protectNames((data?.sections || []).flatMap((s) => s.rows.flatMap((r) => [r.tenant_name, r.store_name])).filter(Boolean));
        setD(data); setErr('');
      })
      .catch((e) => setErr(e?.response?.data?.detail || "L'activité n'a pas pu être chargée."));
  }, [day]);
  useEffect(() => { load(); }, [load]);
  // today stays live, and turns into the new day by itself at Paris midnight
  // — only while the page is in sight: a tab left open in the background
  // would read the whole day again every minute for nobody
  useEffect(() => {
    if (day) return undefined;
    const tick = () => { if (!document.hidden) load(); };
    const t = setInterval(tick, LIVE_MS);
    document.addEventListener('visibilitychange', tick);
    return () => { clearInterval(t); document.removeEventListener('visibilitychange', tick); };
  }, [day, load]);

  // today's date is « live » (no day asked): it then follows midnight by itself
  const go = (to) => setDay(!to || to === d?.today_day ? null : to);
  return (
    <Card className="mt-4">
      <header className="mb-3 flex flex-wrap items-center gap-3">
        <Activity size={19} className="text-[#2F6BFF]" />
        <div className="min-w-0 flex-1">
          <h2 className="text-[15px] font-bold text-[#0B1C3F]">Activité du jour</h2>
          <p className="text-[12px] text-[#64748B]">Tous les commerces, de minuit à minuit (heure de Paris).{d?.today ? ' Mis à jour en direct.' : ''}</p>
        </div>
        <div className="flex items-center gap-1.5">
          <button type="button" aria-label="Jour précédent" disabled={!d} onClick={() => go(d.prev)} className="grid h-9 w-9 place-items-center rounded-xl border border-[#DCE3EE] bg-white text-[#0B1C3F] disabled:opacity-40"><ChevronLeft size={16} /></button>
          <span data-testid="activity-day" className="min-w-[210px] text-center text-[13.5px] font-semibold capitalize text-[#0B1C3F]">{d ? (d.today ? "Aujourd'hui" : dayLabel(d.day)) : '…'}</span>
          <button type="button" aria-label="Jour suivant" disabled={!d || !d.next} onClick={() => go(d.next)} className="grid h-9 w-9 place-items-center rounded-xl border border-[#DCE3EE] bg-white text-[#0B1C3F] disabled:opacity-40"><ChevronRight size={16} /></button>
          <input type="date" aria-label="Choisir un jour" value={d?.day || ''} max={d?.today_day}
                 onChange={(e) => e.target.value && go(e.target.value)} className="h-9 rounded-xl border border-[#DCE3EE] bg-white px-2 text-[12.5px] text-[#0B1C3F]" />
          {day && <button type="button" onClick={() => setDay(null)} className="h-9 rounded-xl bg-[#EAF1FF] px-3 text-[12.5px] font-medium text-[#2F6BFF]">Aujourd'hui</button>}
        </div>
      </header>
      {err && <p className="rounded-xl bg-[#FEF2F2] px-3 py-2 text-[13px] text-[#B91C1C]">{err}</p>}
      {!d && !err && <Loading />}
      {d && <div className="grid gap-4 lg:grid-cols-3">{d.sections.map((s) => <Section key={`${d.day}-${s.key}`} s={s} />)}</div>}
    </Card>
  );
}
