import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  FileBarChart, Download, Loader2, Lock, Mail, CalendarDays, ArrowLeft, TrendingUp, TrendingDown,
  Lightbulb, Bot, Info, Clock, RefreshCw,
} from 'lucide-react';
import api, { ownerAPI } from '../lib/api';
import { openUpgrade } from '../components/PlanAccess';
import InfoTip from '../components/InfoTip';

/**
 * Rapports de vos campagnes — the month's campaigns, measured
 * (features/campaign_report.py, user 2026-10-02). Pro AI.
 *
 * The owner picks the day of the month the report is written (16 by default,
 * so every campaign of the month has had its 15 days) and whether it is also
 * emailed. Each report: the month's figures, against the month before, the
 * best and weakest sends, every send, the Autopilot's month, what works here
 * and what to do next. A PDF of it, any time.
 */
const nf = (n) => (n ?? 0).toLocaleString('fr-FR', { maximumFractionDigits: 1 });
const money = (n) => `${(n ?? 0).toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`;
const signed = (n) => `${n >= 0 ? '+' : ''}${nf(n)}`;
const dmy = (iso) => (iso ? new Date(iso).toLocaleDateString('fr-FR', { day: 'numeric', month: 'long' }) : '');

const Card = ({ children, className = '' }) => (
  <section className={`rounded-2xl border border-[#E6EEFB] bg-white p-5 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)] ${className}`}>{children}</section>
);

function Table({ rows }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] border-collapse text-[12.5px]">
        <thead>
          <tr className="border-b border-[#EEF3FB] text-left text-[11.5px] text-[#64748B]">
            {['Campagne', 'Envoyée le', 'Touchés', 'Revenus', 'Attendus', 'En plus', 'CA'].map((h, i) => (
              <th key={h} className={`px-2 py-2 font-semibold ${i >= 2 ? 'text-right' : ''}`}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className="border-b border-[#F4F7FC] last:border-b-0">
              <td className="px-2 py-2.5">
                <span className="font-semibold text-[#0B1C3F]">{r.name}</span>
                {r.autopilot && <span className="ml-1.5 rounded bg-[#F3EEFF] px-1.5 py-0.5 text-[10px] font-bold text-[#6D28D9]">Autopilot</span>}
              </td>
              <td className="px-2 py-2.5 text-[#64748B]">{dmy(r.sent_at)}</td>
              <td className="px-2 py-2.5 text-right tabular-nums">{nf(r.n)}</td>
              {r.mature ? (
                <>
                  <td className="px-2 py-2.5 text-right tabular-nums">{nf(r.came)}</td>
                  <td className="px-2 py-2.5 text-right tabular-nums text-[#64748B]">{nf(r.expected)}</td>
                  <td className={`px-2 py-2.5 text-right font-bold tabular-nums ${r.extra >= 1 ? 'text-[#0F8B58]' : 'text-[#64748B]'}`}>{signed(r.extra)}</td>
                  <td className="px-2 py-2.5 text-right tabular-nums">{money(r.revenue)}</td>
                </>
              ) : (
                <td colSpan={4} className="px-2 py-2.5 text-right text-[11.5px] text-[#64748B]">
                  <Clock size={11} className="mr-1 inline" /> Résultat le {dmy(r.ready_on)}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Report({ month }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState('');
  const [pdf, setPdf] = useState(false);
  useEffect(() => {
    setD(null); setErr('');
    ownerAPI.campaignReport(month).then(({ data }) => setD(data.data))
      .catch((e) => setErr(e?.response?.data?.detail || 'Rapport indisponible.'));
  }, [month]);
  const download = async () => {
    setPdf(true);
    try {
      const { data: blob } = await api.get(`/owner/campaign-reports/${month}/pdf`, { responseType: 'blob' });
      const url = URL.createObjectURL(new Blob([blob], { type: 'application/pdf' }));
      const a = document.createElement('a');
      a.href = url; a.download = `rapport-campagnes-${month}.pdf`;
      document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
    } catch { setErr("Le PDF n'a pas pu être téléchargé."); }
    finally { setPdf(false); }
  };
  if (err) return <Card><p className="text-[13px] text-[#C0392B]">{err}</p></Card>;
  if (!d) return <Card key="loading"><p className="flex items-center gap-2 text-[13px] text-[#64748B]"><Loader2 size={14} className="animate-spin" /> Chargement…</p></Card>;
  const t = d.totals, p = d.previous;
  const tiles = [
    ['Campagnes envoyées', nf(t.campaigns), '#0B1C3F', 'campaigns_sent'], ['Clients touchés', nf(t.touched), '#0B1C3F', 'reach'],
    ['Clients revenus', nf(t.came), '#0B1C3F', 'report_back'], ['Venus en plus grâce aux messages', signed(t.extra), t.extra >= 1 ? '#0F8B58' : '#64748B', 'effect'],
    ['CA des clients revenus', money(t.revenue), '#0B1C3F', 'report_revenue'], ['CA FidClic du mois', money(d.fidclic_ca), '#0F8B58', 'fidclic'],
  ];
  return (
    <div className="space-y-4">
      <Card>
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-[19px] font-extrabold capitalize text-[#0B1C3F]">{d.label}</h2>
            <p className="text-[12px] text-[#64748B]">Rédigé le {new Date(d.generated_at).toLocaleDateString('fr-FR')} · {d.shop}</p>
          </div>
          <button type="button" onClick={download} disabled={pdf}
                  className="inline-flex items-center gap-2 rounded-xl bg-[#2F6BFF] px-4 py-2.5 text-[13px] font-semibold text-white hover:bg-[#2559DB] disabled:opacity-60">
            {pdf ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />} Télécharger le PDF
          </button>
        </div>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
          {tiles.map(([label, v, color, help]) => (
            <div key={label} className="rounded-xl border border-[#EEF3FB] p-3">
              <p className="text-[21px] font-extrabold leading-none tabular-nums" style={{ color }}>{v}</p>
              <p className="mt-1 flex items-center gap-1 text-[11.5px] text-[#64748B]">{label} <InfoTip k={help} size={12} /></p>
            </div>
          ))}
        </div>
        <p className="mt-3 text-[12px] text-[#64748B]">
          Le mois d'avant ({p.label}) : {nf(p.campaigns)} campagnes, {nf(p.came)} clients revenus,
          {' '}{signed(p.extra)} grâce aux messages.
          {t.measured > 0 && p.measured > 0 && (t.extra >= p.extra
            ? <span className="ml-1 font-semibold text-[#0F8B58]"><TrendingUp size={12} className="inline" /> mieux</span>
            : <span className="ml-1 font-semibold text-[#B45309]"><TrendingDown size={12} className="inline" /> moins bien</span>)}
        </p>
        {d.pending.length > 0 && (
          <p className="mt-2 flex items-start gap-1.5 rounded-xl bg-[#EEF2F8] px-3 py-2 text-[12px] text-[#475569]">
            <Clock size={13} className="mt-px shrink-0" /> {d.pending.length} campagne{d.pending.length > 1 ? 's' : ''} pas encore
            mesurable{d.pending.length > 1 ? 's' : ''} : leur résultat arrive {d.window_days} jours après l'envoi. Elles ne sont pas comptées.
          </p>
        )}
      </Card>

      {(d.best.length > 0 || d.weakest.length > 0) && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <h3 className="mb-2 flex items-center gap-2 text-[14px] font-bold text-[#0B1C3F]"><TrendingUp size={15} className="text-[#0F8B58]" /> Ce qui a le mieux marché</h3>
            {d.best.length ? d.best.map((r) => (
              <p key={r.id} className="flex items-center justify-between gap-2 border-b border-[#F4F7FC] py-1.5 text-[12.5px] last:border-b-0">
                <span className="truncate text-[#0B1C3F]">{r.name}</span><span className="shrink-0 font-bold text-[#0F8B58]">{signed(r.extra)} clients</span>
              </p>
            )) : <p className="text-[12.5px] text-[#94A3B8]">Aucune campagne n'a fait revenir plus de clients que prévu ce mois-ci.</p>}
          </Card>
          <Card>
            <h3 className="mb-2 flex items-center gap-2 text-[14px] font-bold text-[#0B1C3F]"><TrendingDown size={15} className="text-[#B45309]" /> Les plus faibles</h3>
            {d.weakest.length ? d.weakest.map((r) => (
              <p key={r.id} className="flex items-center justify-between gap-2 border-b border-[#F4F7FC] py-1.5 text-[12.5px] last:border-b-0">
                <span className="truncate text-[#0B1C3F]">{r.name}</span><span className="shrink-0 font-bold text-[#64748B]">{signed(r.extra)} clients</span>
              </p>
            )) : <p className="text-[12.5px] text-[#94A3B8]">Toutes vos campagnes mesurées ont fait mieux que prévu.</p>}
          </Card>
        </div>
      )}

      <Card>
        <h3 className="mb-2 text-[14px] font-bold text-[#0B1C3F]">Toutes les campagnes du mois</h3>
        {d.campaigns.length ? <Table rows={d.campaigns} /> : <p className="text-[12.5px] text-[#94A3B8]">Aucune campagne envoyée ce mois-ci.</p>}
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        {(d.learnings.length > 0 || d.autopilot.prepared > 0) && (
          <Card>
            {d.autopilot.prepared > 0 && (
              <>
                <h3 className="mb-1.5 flex items-center gap-2 text-[14px] font-bold text-[#0B1C3F]"><Bot size={15} className="text-[#6D28D9]" /> Autopilot</h3>
                <p className="mb-3 text-[12.5px] text-[#475569]">
                  {d.autopilot.prepared} campagnes préparées : {d.autopilot.sent} validées, {d.autopilot.skipped} ignorées, {d.autopilot.expired} expirées.
                </p>
              </>
            )}
            {d.learnings.length > 0 && (
              <>
                <h3 className="mb-1.5 flex items-center gap-2 text-[14px] font-bold text-[#0B1C3F]"><Lightbulb size={15} className="text-[#6D28D9]" /> Ce qui marche chez vous</h3>
                {d.learnings.map((s) => <p key={s} className="mb-1 text-[12.5px] leading-snug text-[#334155]">• {s}</p>)}
              </>
            )}
          </Card>
        )}
        {d.advice.length > 0 && (
          <Card>
            <h3 className="mb-1.5 text-[14px] font-bold text-[#0B1C3F]">Pour le mois prochain</h3>
            {d.advice.map((s) => <p key={s} className="mb-1 text-[12.5px] leading-snug text-[#334155]">• {s}</p>)}
          </Card>
        )}
      </div>
      <p className="flex items-start gap-1.5 text-[11px] leading-snug text-[#94A3B8]"><Info size={12} className="mt-px shrink-0" /> {d.method}</p>
    </div>
  );
}

export default function CampaignReportsPage() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [d, setD] = useState(null);
  const [busy, setBusy] = useState('');
  const [msg, setMsg] = useState('');
  const [err, setErr] = useState('');
  const load = useCallback(() => ownerAPI.campaignReports().then(({ data }) => setD(data)).catch(() => setErr('Rapports indisponibles.')), []);
  useEffect(() => { load(); }, [load]);
  // `cg`: the Campagnes canvas and top bar (index.css, main:has(.cg)).
  if (!d) return <div className="cg flex min-h-[40vh] items-center justify-center text-[#64748B]"><Loader2 className="animate-spin" /></div>;

  const month = params.get('month') || d.reports[0]?.month;
  const save = async (patch) => {
    setBusy('save'); setErr(''); setMsg('');
    try { const { data } = await ownerAPI.saveCampaignReportSettings({ ...d.settings, ...patch }); setD(data); setMsg('Enregistré.'); }
    catch (e) { setErr(e?.response?.data?.detail?.message || e?.response?.data?.detail || "L'enregistrement n'a pas abouti."); }
    finally { setBusy(''); }
  };
  const generate = async () => {
    setBusy('gen'); setErr(''); setMsg('');
    try {
      const { data } = await ownerAPI.generateCampaignReport({ month: d.last_month });
      await load();
      setParams({ month: data.month });
      setMsg(`Rapport de ${d.last_month_label} rédigé.`);
    } catch (e) { setErr(e?.response?.data?.detail?.message || e?.response?.data?.detail || 'Le rapport n\'a pas pu être rédigé.'); }
    finally { setBusy(''); }
  };

  return (
    <div className="cg space-y-4">
      <button type="button" onClick={() => navigate('/dashboard/campaigns')}
              className="inline-flex items-center gap-1.5 text-[12.5px] font-semibold text-[#64748B] hover:text-[#2F6BFF]">
        <ArrowLeft size={14} /> Campagnes
      </button>
      <header className="flex flex-wrap items-start gap-3">
        <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-[#EAF1FF] text-[#2F6BFF]"><FileBarChart size={20} /></span>
        <div>
          <h1 className="flex items-center gap-2 text-[24px] font-bold text-[#0B1C3F]">
            Rapports de vos campagnes <span className="rounded-md bg-[#F3EEFF] px-1.5 py-0.5 text-[11px] font-bold text-[#6D28D9]">Pro AI</span>
          </h1>
          <p className="text-[13px] text-[#64748B]">Chaque mois, ce que vos campagnes ont vraiment rapporté — et quoi faire ensuite.</p>
        </div>
      </header>

      {!d.plan_ok ? (
        <Card className="flex flex-wrap items-center justify-between gap-3">
          <p className="flex items-center gap-2 text-[13px] text-[#475569]"><Lock size={15} /> Le rapport mensuel des campagnes est inclus dans l'offre Pro AI.</p>
          <button type="button" onClick={() => openUpgrade({ feature: 'ai', label: 'Rapport mensuel', message: "Le rapport mensuel des campagnes est inclus dans l'offre Pro AI.", upgrade: { label: 'Pro AI' } })}
                  className="rounded-xl bg-[#2F6BFF] px-4 py-2.5 text-[13px] font-semibold text-white">Passer à Pro AI</button>
        </Card>
      ) : (
        <>
          <Card>
            {msg && <p className="mb-3 rounded-xl bg-[#E7F7EE] px-3 py-2 text-[12.5px] text-[#0F8B58]">{msg}</p>}
            {err && <p className="mb-3 rounded-xl bg-[#FEECEC] px-3 py-2 text-[12.5px] text-[#C0392B]">{err}</p>}
            <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
              <label className="flex items-center gap-2 text-[12.5px] text-[#334155]">
                <CalendarDays size={15} className="text-[#2F6BFF]" /> Recevoir le rapport le
                <select disabled={!d.can_edit || !!busy} value={d.settings.day} onChange={(e) => save({ day: Number(e.target.value) })}
                        className="rounded-lg border border-[#E6EEFB] bg-white px-2 py-1.5 text-[12.5px] outline-none focus:border-[#2F6BFF]">
                  {Array.from({ length: 28 }, (_, i) => i + 1).map((n) => <option key={n} value={n}>{n}</option>)}
                </select>
                de chaque mois
              </label>
              <label className="flex cursor-pointer items-center gap-2 text-[12.5px] text-[#334155]">
                <input type="checkbox" className="h-4 w-4 accent-[#2F6BFF]" disabled={!d.can_edit || !!busy}
                       checked={d.settings.email} onChange={(e) => save({ email: e.target.checked })} />
                <Mail size={14} className="text-[#2F6BFF]" /> Aussi par email, avec le PDF
              </label>
              <span className="text-[12px] text-[#64748B]">Prochain rapport : {new Date(d.next_on).toLocaleDateString('fr-FR', { day: 'numeric', month: 'long' })}</span>
              {d.can_edit && (
                <button type="button" onClick={generate} disabled={!!busy}
                        className="ml-auto inline-flex items-center gap-1.5 rounded-xl border border-[#E6EEFB] px-3.5 py-2 text-[12.5px] font-semibold text-[#334155] hover:border-[#2F6BFF]">
                  {busy === 'gen' ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />} Rédiger {d.last_month_label} maintenant
                </button>
              )}
            </div>
            {d.settings.day < 16 && (
              <p className="mt-2 text-[11.5px] text-[#B45309]">
                Avant le 16, les campagnes de la fin du mois n'ont pas encore leurs 15 jours : elles seront listées sans être comptées.
              </p>
            )}
          </Card>

          {d.reports.length ? (
            <div className="grid gap-4 lg:grid-cols-[220px_1fr]">
              <Card className="h-fit p-3">
                <p className="mb-2 px-2 text-[11.5px] font-semibold uppercase tracking-wide text-[#94A3B8]">Mois</p>
                {d.reports.map((r) => (
                  <button key={r.month} type="button" onClick={() => setParams({ month: r.month })}
                          className={`mb-1 flex w-full items-center justify-between rounded-xl px-3 py-2 text-left text-[13px] capitalize transition ${
                            r.month === month ? 'bg-[#EAF1FF] font-semibold text-[#2F6BFF]' : 'text-[#334155] hover:bg-[#F5F8FE]'}`}>
                    {r.label}
                    {!r.seen && <span className="h-2 w-2 rounded-full bg-[#F59E0B]" title="Pas encore lu" />}
                  </button>
                ))}
              </Card>
              {month && <Report month={month} />}
            </div>
          ) : (
            <Card>
              <p className="text-[13px] text-[#475569]">
                Aucun rapport pour l'instant. Le premier arrivera le {new Date(d.next_on).toLocaleDateString('fr-FR', { day: 'numeric', month: 'long' })}
                {d.can_edit && <> — ou rédigez dès maintenant celui de {d.last_month_label}.</>}
              </p>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
