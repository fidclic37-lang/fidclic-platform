import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ClipboardCheck, Clock, CircleAlert, TrendingDown, Gauge, Headset, ListChecks, CalendarDays, ChevronRight, Wallet, LifeBuoy,
  Briefcase, ArrowUp, ArrowDown, Star, Loader2,
} from 'lucide-react';
import { adminAPI } from '../../lib/api';
import { Card, Head, nf } from '../crm/ui';

/* Dashboard › « À suivre aujourd'hui » (user, 2026-10-01): a section of its
   own under the fixed figures — À faire aujourd'hui, Encaissements, Support,
   CRM. A block only shows for a member who may open its module. */

const ICON = { clock: Clock, alert: CircleAlert, 'trending-down': TrendingDown, gauge: Gauge, headset: Headset, list: ListChecks, calendar: CalendarDays };
const TONE = { violet: ['#F3EEFF', '#7C3AED'], rose: ['#FDECEF', '#E11D48'], amber: ['#FFF4DB', '#D97706'], blue: ['#EAF1FF', '#2F6BFF'] };
const eur = (v) => `€${Number(v || 0).toLocaleString('fr-FR', { maximumFractionDigits: 0 })}`;

function Stat({ value, label, tone = '#0B1C3F' }) {
  return <span className="block"><strong className="block text-[19px] font-bold leading-tight" style={{ color: tone }}>{value}</strong><span className="text-[12px] text-[#64748B]">{label}</span></span>;
}

export default function DashboardToday({ openList }) {
  const navigate = useNavigate();
  const [d, setD] = useState(null);
  const [err, setErr] = useState('');
  useEffect(() => { adminAPI.dashboardToday().then(({ data }) => setD(data)).catch(() => setErr('Indisponible pour le moment.')); }, []);
  const go = (a) => (a.list ? openList(a.list) : navigate(a.href));
  const todo = d?.todo || [];
  const pending = todo.reduce((s, i) => s + (i.count ? 1 : 0), 0);
  return (
    <section className="mt-6">
      <h2 className="mb-3 flex items-center gap-2 text-[18px] font-bold text-[#0B1C3F]"><ClipboardCheck size={20} className="text-[#2F6BFF]" /> À suivre aujourd'hui</h2>
      {!d ? (
        <div className="flex items-center justify-center gap-2 rounded-2xl border border-[#EDF1F7] bg-white py-10 text-[13px] text-[#64748B]">{err || <><Loader2 size={15} className="animate-spin" /> Chargement…</>}</div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2 2xl:grid-cols-[1.35fr_1fr_1fr_1fr]">
          <Card>
            <Head icon={ClipboardCheck} title="À faire aujourd'hui" sub={pending ? `${pending} point${pending > 1 ? 's' : ''} à traiter` : 'Rien d’urgent — tout est à jour.'}
                  right={pending ? <span className="rounded-full bg-[#FDECEF] px-2.5 py-0.5 text-[12px] font-semibold text-[#E11D48]">{pending}</span> : null} />
            <ul className="divide-y divide-[#F1F5F9]">
              {todo.map((i) => { const I = ICON[i.icon] || ListChecks; const [bg, fg] = TONE[i.tone] || TONE.blue; return (
                <li key={i.key}>
                  <button type="button" onClick={() => go(i.action)} disabled={!i.count}
                          className="flex w-full items-center gap-3 py-2 text-left text-[13px] text-[#334155] disabled:opacity-45">
                    <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg" style={{ background: bg, color: fg }}><I size={14} /></span>
                    <span className="min-w-0 flex-1">{i.label}{i.detail && i.count ? <span className="block text-[11.5px] text-[#94A3B8]">{i.detail}</span> : null}</span>
                    <strong className="text-[15px]" style={{ color: i.count ? fg : '#94A3B8' }}>{nf(i.count)}</strong>
                    {i.count > 0 && <ChevronRight size={15} className="text-[#94A3B8]" />}
                  </button>
                </li>); })}
            </ul>
          </Card>

          {d.encaissements && (
            <div role="button" tabIndex={0} onClick={() => navigate('/admin/facturation')} onKeyDown={(e) => { if (e.key === 'Enter') navigate('/admin/facturation'); }} className="cursor-pointer text-left">
              <Card className="h-full hover:border-[#BFD3FF]">
                <Head icon={Wallet} tone="#10B981" title="Encaissements" sub="Abonnements FidClic payés ce mois-ci" />
                <div className="flex items-end gap-2">
                  <strong className="text-[26px] font-bold leading-none text-[#0B1C3F]">{eur(d.encaissements.month)}</strong>
                  {d.encaissements.delta != null && <span className={`mb-0.5 inline-flex items-center gap-0.5 text-[12px] font-semibold ${d.encaissements.delta >= 0 ? 'text-[#0F8B58]' : 'text-[#E11D48]'}`}>{d.encaissements.delta >= 0 ? <ArrowUp size={12} /> : <ArrowDown size={12} />}{d.encaissements.delta >= 0 ? '+' : ''}{d.encaissements.delta}%</span>}
                </div>
                <p className="mt-1 text-[12px] text-[#64748B]">{nf(d.encaissements.month_invoices)} paiement{d.encaissements.month_invoices > 1 ? 's' : ''} · vs les mêmes jours du mois dernier</p>
                <div className="mt-4 grid grid-cols-2 gap-3 border-t border-[#F1F5F9] pt-3">
                  <Stat value={eur(d.encaissements.upcoming_30)} label={`à encaisser sous 30 j (${nf(d.encaissements.upcoming_count)})`} />
                  <Stat value={eur(d.encaissements.late)} label={`/ mois en retard (${nf(d.encaissements.late_count)})`} tone={d.encaissements.late_count ? '#E11D48' : '#0B1C3F'} />
                </div>
              </Card>
            </div>
          )}

          {d.support && (
            <div role="button" tabIndex={0} onClick={() => navigate('/admin/support')} onKeyDown={(e) => { if (e.key === 'Enter') navigate('/admin/support'); }} className="cursor-pointer text-left">
              <Card className="h-full hover:border-[#BFD3FF]">
                <Head icon={LifeBuoy} title="Support" sub="Santé du support" />
                <div className="grid grid-cols-3 gap-3">
                  <Stat value={nf(d.support.open)} label="ouverts" />
                  <Stat value={nf(d.support.unread)} label="non lus" tone={d.support.unread ? '#2F6BFF' : '#0B1C3F'} />
                  <Stat value={nf(d.support.urgent)} label="urgents" tone={d.support.urgent ? '#E11D48' : '#0B1C3F'} />
                </div>
                <div className="mt-4 grid grid-cols-2 gap-3 border-t border-[#F1F5F9] pt-3">
                  <Stat value={d.support.first_response_hours != null ? `${String(d.support.first_response_hours).replace('.', ',')} h` : '—'} label="1re réponse (moy. 30 j)" />
                  <Stat value={d.support.satisfaction != null ? <span className="inline-flex items-center gap-1">{String(d.support.satisfaction).replace('.', ',')}<Star size={14} className="fill-[#F59E0B] text-[#F59E0B]" /></span> : '—'}
                        label={`satisfaction (${nf(d.support.ratings)} avis)`} />
                </div>
              </Card>
            </div>
          )}

          {d.crm && (
            <div role="button" tabIndex={0} onClick={() => navigate('/admin/crm')} onKeyDown={(e) => { if (e.key === 'Enter') navigate('/admin/crm'); }} className="cursor-pointer text-left">
              <Card className="h-full hover:border-[#BFD3FF]">
                <Head icon={Briefcase} tone="#7C3AED" title="CRM de prospection" sub="Où en est la vente" />
                <div className="grid grid-cols-3 gap-3">
                  <Stat value={nf(d.crm.active)} label="prospects actifs" />
                  <Stat value={nf(d.crm.proposals)} label="propositions" tone="#7C3AED" />
                  <Stat value={d.crm.forecast != null ? nf(d.crm.forecast) : '—'} label="signatures attendues" tone="#0F8B58" />
                </div>
                <div className="mt-4 grid grid-cols-3 gap-3 border-t border-[#F1F5F9] pt-3">
                  <Stat value={nf(d.crm.signed_month)} label="signés ce mois" />
                  <Stat value={nf(d.crm.rdv_7j)} label="RDV sous 7 j" />
                  <Stat value={nf(d.crm.overdue)} label="tâches en retard" tone={d.crm.overdue ? '#E11D48' : '#0B1C3F'} />
                </div>
              </Card>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
