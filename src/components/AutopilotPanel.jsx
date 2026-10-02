import React, { useCallback, useEffect, useState } from 'react';
import {
  Bot, Loader2, Check, X, Clock, CalendarDays, Sun, Pencil, Info, Lightbulb, Lock, Sparkles,
} from 'lucide-react';
import { ownerAPI } from '../lib/api';
import { useResendCheck } from './ResendCheck';
import { openUpgrade } from './PlanAccess';
import InfoTip from './InfoTip';

/**
 * Autopilot — FidClic IA prepares a campaign every day and one every week;
 * the owner validates (features/autopilot.py, user 2026-10-02). Pro AI.
 *
 * Two rhythms switched on their own, at the owner's times. A proposal waits
 * « À valider » — in the bell and here — and can be edited, validated or
 * skipped until 24 h after its time. Nothing leaves without the owner.
 */
const pad = (n) => String(n).padStart(2, '0');
const HOURS = Array.from({ length: 24 }, (_, h) => h);
const MINUTES = [0, 15, 30, 45];
const when = (iso) => {
  const d = new Date(iso);
  return d.toLocaleString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit' });
};
const STATUS = {
  sent: ['Envoyée', '#E7F7EE', '#0F8B58'], scheduled: ['Programmée', '#EFF5FF', '#1D4ED8'],
  skipped: ['Ignorée', '#EEF2F8', '#64748B'], expired: ['Expirée', '#FFF7E6', '#B45309'],
  empty: ['Pas de campagne', '#EEF2F8', '#64748B'],
};

const Switch = ({ on, onChange, disabled }) => (
  <button type="button" role="switch" aria-checked={on} disabled={disabled} onClick={() => onChange(!on)}
          className={`relative h-6 w-11 shrink-0 rounded-full transition disabled:opacity-50 ${on ? 'bg-[#2F6BFF]' : 'bg-[#DFE6F1]'}`}>
    <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all ${on ? 'left-[22px]' : 'left-0.5'}`} />
  </button>
);
const sel = 'rounded-lg border border-[#E6EEFB] bg-white px-2 py-1.5 text-[12.5px] text-[#0B1C3F] outline-none focus:border-[#2F6BFF] disabled:bg-[#F8FAFF]';

function Proposal({ p, canEdit, onDone, guard }) {
  const [edit, setEdit] = useState(false);
  const [title, setTitle] = useState(p.title);
  const [message, setMessage] = useState(p.message);
  const [busy, setBusy] = useState('');
  const [err, setErr] = useState('');
  const daily = p.kind === 'daily';

  const approve = async () => {
    setBusy('ok'); setErr('');
    try {
      const exclude = await guard({ customer_ids: p.customer_ids || [] });
      if (exclude === null) { setBusy(''); return; }
      const { data } = await ownerAPI.autopilotApprove(p.id, {
        ...(title !== p.title ? { title } : {}), ...(message !== p.message ? { message } : {}),
        ...(exclude.length ? { exclude_ids: exclude } : {}),
      });
      onDone(data.status === 'scheduled' ? `Campagne programmée pour ${when(p.send_at)}.` : `Campagne envoyée à ${data.audience} clients.`);
    } catch (e) { setErr(e?.response?.data?.detail || "L'envoi n'a pas abouti."); setBusy(''); }
  };
  const skip = async () => {
    setBusy('skip'); setErr('');
    try { await ownerAPI.autopilotSkip(p.id); onDone('Proposition ignorée.'); }
    catch (e) { setErr(e?.response?.data?.detail || 'Impossible.'); setBusy(''); }
  };

  return (
    <article className="rounded-2xl border border-[#BFD3FF] bg-white p-4 shadow-[0_18px_40px_-30px_rgba(47,107,255,.6)]">
      <header className="mb-2 flex flex-wrap items-center gap-2">
        <span className="rounded-md bg-[#EAF1FF] px-2 py-0.5 text-[11px] font-bold text-[#1D4ED8]">
          {daily ? 'Campagne du jour' : 'Campagne de la semaine'}
        </span>
        <span className="rounded-md bg-[#FFF7E6] px-2 py-0.5 text-[11px] font-bold text-[#B45309]">À valider</span>
        <span className="ml-auto flex items-center gap-1 text-[11.5px] text-[#64748B]">
          <Clock size={12} /> {when(p.send_at)} · valable jusqu'au {when(p.expires_at)}
        </span>
      </header>

      {edit ? (
        <div className="mb-3 space-y-2">
          <input value={title} maxLength={50} onChange={(e) => setTitle(e.target.value)}
                 className="w-full rounded-xl border border-[#E6EEFB] px-3 py-2 text-[13px] font-semibold outline-none focus:border-[#2F6BFF]" />
          <textarea value={message} maxLength={160} rows={3} onChange={(e) => setMessage(e.target.value)}
                    className="w-full resize-none rounded-xl border border-[#E6EEFB] px-3 py-2 text-[13px] outline-none focus:border-[#2F6BFF]" />
        </div>
      ) : (
        <div className="mb-3 rounded-xl bg-[#F5F8FE] px-3 py-2.5">
          <p className="text-[13.5px] font-bold text-[#0B1C3F]">{title}</p>
          <p className="mt-0.5 text-[12.5px] leading-snug text-[#475569]">{message}</p>
          <p className="mt-1 text-[10.5px] text-[#94A3B8]">
            {p.written_by === 'ia' ? 'Rédigé par FidClic IA' : 'Modèle FidClic'} · {'{first_name}'} et {'{business_name}'} seront remplacés
          </p>
        </div>
      )}

      <p className="mb-1 text-[12.5px] text-[#334155]">
        <b className="text-[#0B1C3F]">{p.audience_count} clients</b> — {p.audience_label}
      </p>
      <ul className="mb-2 space-y-0.5">
        {(p.reasons || []).map((r) => <li key={r} className="text-[12px] text-[#64748B]">· {r}</li>)}
        {p.left_out && (p.left_out.recent > 0 || p.left_out.limit > 0) && (
          <li className="text-[12px] text-[#64748B]">
            · Retirés : {p.left_out.recent > 0 && `${p.left_out.recent} déjà contacté${p.left_out.recent > 1 ? 's' : ''} ces 3 derniers jours`}
            {p.left_out.recent > 0 && p.left_out.limit > 0 && ', '}
            {p.left_out.limit > 0 && `${p.left_out.limit} à leur limite de messages`}.
          </li>
        )}
      </ul>
      {(p.advice || []).map((a) => (
        <p key={a} className="mb-1.5 flex items-start gap-1.5 rounded-lg bg-[#F3EEFF] px-2.5 py-1.5 text-[11.5px] text-[#6D28D9]">
          <Lightbulb size={12} className="mt-px shrink-0" /> {a}
        </p>
      ))}
      {err && <p className="mb-2 rounded-lg bg-[#FEECEC] px-3 py-2 text-[12px] text-[#C0392B]">{err}</p>}
      {canEdit ? (
        <div className="mt-3 flex flex-wrap gap-2">
          <button type="button" onClick={approve} disabled={!!busy || !title.trim() || !message.trim()}
                  className="inline-flex items-center gap-1.5 rounded-xl bg-[#2F6BFF] px-3.5 py-2 text-[12.5px] font-semibold text-white hover:bg-[#2559DB] disabled:opacity-50">
            {busy === 'ok' ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} />} Valider
          </button>
          <button type="button" onClick={() => setEdit((v) => !v)} disabled={!!busy}
                  className="inline-flex items-center gap-1.5 rounded-xl border border-[#E6EEFB] px-3.5 py-2 text-[12.5px] font-semibold text-[#334155] hover:border-[#2F6BFF]">
            <Pencil size={13} /> {edit ? 'Terminer' : 'Modifier'}
          </button>
          <button type="button" onClick={skip} disabled={!!busy}
                  className="inline-flex items-center gap-1.5 rounded-xl border border-[#E6EEFB] px-3.5 py-2 text-[12.5px] font-semibold text-[#64748B] hover:border-[#E11D48] hover:text-[#E11D48]">
            <X size={13} /> Ignorer
          </button>
        </div>
      ) : <p className="mt-2 text-[11.5px] text-[#94A3B8]">Le propriétaire valide les campagnes de l'Autopilot.</p>}
    </article>
  );
}

export default function AutopilotPanel() {
  const [d, setD] = useState(null);
  const [busy, setBusy] = useState('');
  const [msg, setMsg] = useState('');
  const [err, setErr] = useState('');
  const [guard, resendModal] = useResendCheck();

  const load = useCallback(() => ownerAPI.autopilot().then(({ data }) => setD(data)).catch(() => {}), []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (d && window.location.hash === '#autopilot') document.getElementById('autopilot')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, [Boolean(d)]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!d) return null;
  const s = d.settings;
  const can = d.can_edit && d.plan_ok;

  const save = async (patch) => {
    setBusy('save'); setErr(''); setMsg('');
    try {
      const { data } = await ownerAPI.saveAutopilot(patch);
      setD(data);
      setMsg('Autopilot enregistré.');
    } catch (e) { setErr(e?.response?.data?.detail?.message || e?.response?.data?.detail || "L'enregistrement n'a pas abouti."); }
    finally { setBusy(''); }
  };
  const prepare = async () => {
    setBusy('prep'); setErr(''); setMsg('');
    try {
      const { data } = await ownerAPI.autopilotPrepare();
      setD(data);
      setMsg(data.prepared ? `${data.prepared} campagne${data.prepared > 1 ? 's' : ''} préparée${data.prepared > 1 ? 's' : ''} — à valider ci-dessous.`
        : data.empty ? "Aucun client dont c'est le moment aujourd'hui : pas de campagne, pour ne pas déranger."
          : 'Les campagnes du jour et de la semaine sont déjà prêtes.');
    } catch (e) { setErr(e?.response?.data?.detail?.message || e?.response?.data?.detail || 'Impossible de préparer.'); }
    finally { setBusy(''); }
  };
  const done = (m) => { setMsg(m); load(); };

  return (
    <section id="autopilot" className="mb-5 scroll-mt-24 rounded-2xl border border-[#E6EEFB] bg-white p-5 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
      {resendModal}
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#F3EEFF] text-[#6D28D9]"><Bot size={19} /></span>
          <div>
            <h2 className="flex items-center gap-2 text-[15px] font-bold text-[#0B1C3F]">
              Autopilot <InfoTip k="autopilot" /> <span className="rounded-md bg-[#F3EEFF] px-1.5 py-0.5 text-[10.5px] font-bold text-[#6D28D9]">Pro AI</span>
            </h2>
            <p className="text-[12.5px] leading-snug text-[#64748B]">
              FidClic IA prépare vos campagnes à partir de ce qui marche chez vous. Rien ne part sans votre validation.
            </p>
          </div>
        </div>
        {can && (s.daily.enabled || s.weekly.enabled) && (
          <button type="button" onClick={prepare} disabled={!!busy}
                  className="inline-flex items-center gap-1.5 rounded-xl border border-[#E6EEFB] px-3.5 py-2 text-[12.5px] font-semibold text-[#334155] hover:border-[#2F6BFF]">
            {busy === 'prep' ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />} Préparer maintenant
          </button>
        )}
      </div>

      {!d.plan_ok ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-[#F5F8FE] px-4 py-3">
          <p className="flex items-center gap-2 text-[12.5px] text-[#475569]"><Lock size={14} /> L'Autopilot est inclus dans l'offre Pro AI.</p>
          <button type="button" onClick={() => openUpgrade({ feature: 'ai', label: 'Autopilot', message: "L'Autopilot est inclus dans l'offre Pro AI.", upgrade: { label: 'Pro AI' } })}
                  className="rounded-xl bg-[#2F6BFF] px-3.5 py-2 text-[12.5px] font-semibold text-white">Passer à Pro AI</button>
        </div>
      ) : (
        <>
          {msg && <p className="mb-3 rounded-xl bg-[#E7F7EE] px-3 py-2 text-[12.5px] text-[#0F8B58]">{msg}</p>}
          {err && <p className="mb-3 rounded-xl bg-[#FEECEC] px-3 py-2 text-[12.5px] text-[#C0392B]">{err}</p>}
          <div className="mb-4 grid gap-3 md:grid-cols-2">
            <div className="rounded-xl border border-[#E6EEFB] p-3.5">
              <div className="mb-2 flex items-center justify-between gap-2">
                <span className="flex items-center gap-2 text-[13px] font-bold text-[#0B1C3F]"><Sun size={15} className="text-[#F59E0B]" /> Chaque jour</span>
                <Switch on={s.daily.enabled} disabled={!can || !!busy} onChange={(v) => save({ daily: { ...s.daily, enabled: v } })} />
              </div>
              <p className="mb-2 text-[11.5px] leading-snug text-[#64748B]">
                Une petite campagne aux clients dont c'est le moment : habitués en retard, leur jour habituel, nouveaux après une semaine.
              </p>
              <label className="flex items-center gap-2 text-[12px] text-[#334155]">
                Heure
                <select className={sel} disabled={!can} value={s.daily.hour} onChange={(e) => save({ daily: { ...s.daily, hour: Number(e.target.value) } })}>
                  {HOURS.map((h) => <option key={h} value={h}>{pad(h)} h</option>)}
                </select>
                <select className={sel} disabled={!can} value={s.daily.minute} onChange={(e) => save({ daily: { ...s.daily, minute: Number(e.target.value) } })}>
                  {MINUTES.map((m) => <option key={m} value={m}>{pad(m)}</option>)}
                </select>
              </label>
            </div>
            <div className="rounded-xl border border-[#E6EEFB] p-3.5">
              <div className="mb-2 flex items-center justify-between gap-2">
                <span className="flex items-center gap-2 text-[13px] font-bold text-[#0B1C3F]"><CalendarDays size={15} className="text-[#2F6BFF]" /> Chaque semaine</span>
                <Switch on={s.weekly.enabled} disabled={!can || !!busy} onChange={(v) => save({ weekly: { ...s.weekly, enabled: v } })} />
              </div>
              <p className="mb-2 text-[11.5px] leading-snug text-[#64748B]">
                Une campagne à un grand groupe : vos inactifs quand ils sont nombreux, sinon vos fidèles, sinon tout le monde.
              </p>
              <label className="flex flex-wrap items-center gap-2 text-[12px] text-[#334155]">
                Le
                <select className={sel} disabled={!can} value={s.weekly.weekday} onChange={(e) => save({ weekly: { ...s.weekly, weekday: Number(e.target.value) } })}>
                  {d.days.map((day, i) => <option key={day} value={i}>{day}</option>)}
                </select>
                à
                <select className={sel} disabled={!can} value={s.weekly.hour} onChange={(e) => save({ weekly: { ...s.weekly, hour: Number(e.target.value) } })}>
                  {HOURS.map((h) => <option key={h} value={h}>{pad(h)} h</option>)}
                </select>
                <select className={sel} disabled={!can} value={s.weekly.minute} onChange={(e) => save({ weekly: { ...s.weekly, minute: Number(e.target.value) } })}>
                  {MINUTES.map((m) => <option key={m} value={m}>{pad(m)}</option>)}
                </select>
              </label>
            </div>
          </div>
          <p className="mb-4 flex items-start gap-1.5 text-[11px] leading-snug text-[#94A3B8]">
            <Info size={12} className="mt-px shrink-0" />
            Validez jusqu'à {d.valid_hours} h après l'heure prévue ; ensuite la campagne expire. Vos limites de messages par client
            (Paramètres › Notifications) et les clients déjà contactés ces 3 derniers jours sont toujours respectés.
            {!d.precise && ' Pour l\'instant, une campagne validée part le jour prévu : tout de suite si vous validez ce jour-là, sinon le matin de ce jour.'}
          </p>

          <h3 className="mb-2 text-[13px] font-bold text-[#0B1C3F]">À valider</h3>
          {d.pending.length ? (
            <div className="mb-4 grid gap-3 lg:grid-cols-2">
              {d.pending.map((p) => <Proposal key={p.id} p={p} canEdit={d.can_edit} onDone={done} guard={guard} />)}
            </div>
          ) : (
            <p className="mb-4 rounded-xl bg-[#F5F8FE] px-3 py-2.5 text-[12.5px] text-[#64748B]">
              {s.daily.enabled || s.weekly.enabled
                ? 'Rien à valider pour le moment. Les prochaines campagnes arrivent ici et dans la cloche 🔔.'
                : "Activez « Chaque jour » ou « Chaque semaine » : les campagnes préparées arriveront ici et dans la cloche 🔔."}
            </p>
          )}

          {d.history.length > 0 && (
            <>
              <h3 className="mb-2 text-[13px] font-bold text-[#0B1C3F]">Historique</h3>
              <ul className="divide-y divide-[#EEF3FB] rounded-xl border border-[#E6EEFB]">
                {d.history.map((h) => {
                  const [label, bg, fg] = STATUS[h.status] || STATUS.skipped;
                  return (
                    <li key={h.id} className="flex flex-wrap items-center gap-2 px-3 py-2 text-[12px]">
                      <span className="w-24 shrink-0 text-[#94A3B8]">{new Date(h.for_date).toLocaleDateString('fr-FR')}</span>
                      <span className="shrink-0 text-[#64748B]">{h.kind === 'daily' ? 'Jour' : 'Semaine'}</span>
                      <span className="min-w-0 flex-1 truncate text-[#0B1C3F]">{h.title || (h.reasons || [])[0] || '—'}</span>
                      <span className="rounded-md px-1.5 py-0.5 text-[10.5px] font-bold" style={{ background: bg, color: fg }}>{label}</span>
                    </li>
                  );
                })}
              </ul>
            </>
          )}
        </>
      )}
    </section>
  );
}
