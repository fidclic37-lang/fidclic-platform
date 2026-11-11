import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { UserPlus, Megaphone, Mail, Link2, Save, Trash2, Info, AlertTriangle, ChevronRight } from 'lucide-react';
import { settingsAPI } from '../../../lib/api';
import TimeInput24 from '../../../components/TimeInput24';
import { Card, Loading, useToast } from '../../crm/ui';

/* Super admin › Paramètres › Plateforme (user, 2026-11-11), PR 2 of 3 —
   sign-ups ON/OFF, the maintenance banner, trial days + support inbox +
   sender, and shortcuts to the settings that live on other pages.
   Server: api/features/platform_config.py. Each block saves on its own. */

const INPUT = 'h-10 w-full rounded-xl border border-[#DCE3EE] bg-white px-3 text-[13.5px] outline-none focus:border-[#2F6BFF] disabled:bg-[#F8FAFC]';
const detail = (e) => {
  const d = e?.response?.data?.detail;
  return typeof d === 'string' ? d : (Array.isArray(d) ? d.map((x) => String(x.msg || '').replace(/^Value error, /, '')).join(' · ') : "L'enregistrement a échoué.");
};
// « 2026-11-12T21:00:00+00:00 » ⇄ the date and the 24 h time in Paris (the browser's own zone here)
const split = (iso) => {
  if (!iso) return { d: '', t: '' };
  const x = new Date(iso);
  const p = (n) => String(n).padStart(2, '0');
  return { d: `${x.getFullYear()}-${p(x.getMonth() + 1)}-${p(x.getDate())}`, t: `${p(x.getHours())}:${p(x.getMinutes())}` };
};
const join = ({ d, t }) => (d ? new Date(`${d}T${t || '00:00'}:00`).toISOString() : null);

function Block({ icon: I, title, sub, children }) {
  return (
    <Card>
      <header className="mb-3 flex items-start gap-2.5">
        <I size={18} className="mt-0.5 shrink-0 text-[#2F6BFF]" />
        <div><h2 className="text-[14.5px] font-bold text-[#0B1C3F]">{title}</h2>{sub && <p className="text-[12.5px] text-[#64748B]">{sub}</p>}</div>
      </header>
      {children}
    </Card>
  );
}

function SaveBtn({ busy, onClick, disabled, label = 'Enregistrer', testid }) {
  return (
    <button type="button" data-testid={testid} onClick={onClick} disabled={busy || disabled}
            className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-[#2F6BFF] px-4 text-[13px] font-semibold text-white disabled:opacity-40"><Save size={14} /> {label}</button>
  );
}

export default function PlatformTab({ editable }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState('');
  const [say, node] = useToast();
  // the forms
  const [signMsg, setSignMsg] = useState('');
  const [ban, setBan] = useState({ message: '', level: 'info', from: { d: '', t: '' }, to: { d: '', t: '' } });
  const [mail, setMail] = useState({ trial_days: 30, support_email: '', sender_name: '', sender_email: '' });

  const fill = useCallback((data) => {
    const s = data.settings;
    setD(data);
    setSignMsg(s.signups_message || '');
    const b = s.banner || {};
    setBan({ message: b.message || '', level: b.level || 'info', from: split(b.starts_at), to: split(b.ends_at) });
    setMail({ trial_days: s.trial_days, support_email: s.support_email, sender_name: s.sender_name, sender_email: s.sender_email });
  }, []);
  useEffect(() => {
    settingsAPI.platform().then(({ data }) => { fill(data); setErr(''); }).catch((e) => setErr(detail(e)));
  }, [fill]);

  const save = async (key, body, msg) => {
    setBusy(key);
    try { const { data } = await settingsAPI.savePlatform(body); fill(data); say(msg); } catch (e) { say(detail(e)); } finally { setBusy(''); }
  };

  if (err) return <p className="rounded-xl bg-[#FEF2F2] px-3 py-2 text-[13px] text-[#B91C1C]">{err}</p>;
  if (!d) return <Loading />;
  const s = d.settings;
  const ro = !editable;
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      {node}
      <Block icon={UserPlus} title="Inscriptions des commerces" sub="Fermées : aucun NOUVEAU commerce ne peut créer de compte (email, Google, Apple). Les commerces existants se connectent normalement.">
        <div className="mb-3 flex items-center gap-3">
          <button type="button" role="switch" aria-checked={s.signups_open} aria-label="Inscriptions ouvertes" disabled={ro || busy === 'sign'}
                  data-testid="signups-switch" onClick={() => save('sign', { signups_open: !s.signups_open }, s.signups_open ? 'Inscriptions fermées.' : 'Inscriptions ouvertes.')}
                  className={`relative h-6 w-11 shrink-0 rounded-full transition ${s.signups_open ? 'bg-[#10B981]' : 'bg-[#CBD5E1]'} disabled:opacity-50`}>
            <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition ${s.signups_open ? 'left-[22px]' : 'left-0.5'}`} />
          </button>
          <p className="text-[13.5px] font-semibold text-[#0B1C3F]" data-testid="signups-state">{s.signups_open ? 'Ouvertes' : 'Fermées'}</p>
        </div>
        <label className="mb-1 block text-[12.5px] font-medium text-[#0B1C3F]" htmlFor="pf-sign">Message affiché quand elles sont fermées</label>
        <textarea id="pf-sign" rows={2} maxLength={300} value={signMsg} disabled={ro} onChange={(e) => setSignMsg(e.target.value)}
                  placeholder="Les inscriptions sont fermées pour le moment. Revenez bientôt !"
                  className="mb-3 w-full rounded-xl border border-[#DCE3EE] px-3 py-2 text-[13.5px] outline-none focus:border-[#2F6BFF]" />
        {editable && <SaveBtn busy={busy === 'signmsg'} onClick={() => save('signmsg', { signups_message: signMsg }, 'Message enregistré.')} />}
      </Block>

      <Block icon={Megaphone} title="Bandeau de maintenance" sub="En haut du tableau de bord de tous les commerces, entre son début et sa fin (heure de Paris). Sans dates : jusqu'à ce que vous le retiriez.">
        {s.banner && <p className={`mb-3 rounded-lg px-2.5 py-1.5 text-[12.5px] ${s.banner_live ? 'bg-[#E7F7EE] text-[#0F8B58]' : 'bg-[#F1F5F9] text-[#475569]'}`} data-testid="banner-state">
          {s.banner_live ? 'Affiché en ce moment.' : 'Programmé ou terminé — pas affiché en ce moment.'}</p>}
        <label className="mb-1 block text-[12.5px] font-medium text-[#0B1C3F]" htmlFor="pf-ban">Message</label>
        <input id="pf-ban" className={`${INPUT} mb-3`} maxLength={300} value={ban.message} disabled={ro}
               onChange={(e) => setBan({ ...ban, message: e.target.value })} placeholder="Maintenance ce soir de 22:00 à 22:30" />
        <div className="mb-3 flex gap-1.5" role="radiogroup" aria-label="Niveau du bandeau">
          {[['info', 'Information', Info], ['warning', 'Important', AlertTriangle]].map(([k, l, I]) => (
            <button key={k} type="button" role="radio" aria-checked={ban.level === k} disabled={ro} onClick={() => setBan({ ...ban, level: k })}
                    className={`inline-flex h-9 flex-1 items-center justify-center gap-1.5 rounded-xl border text-[12.5px] font-medium ${ban.level === k ? 'border-[#2F6BFF] bg-[#EAF1FF] text-[#2F6BFF]' : 'border-[#DCE3EE] text-[#475569]'}`}><I size={14} /> {l}</button>
          ))}
        </div>
        <div className="mb-3 grid gap-3 sm:grid-cols-2">
          {[['from', 'Début'], ['to', 'Fin']].map(([k, l]) => (
            <div key={k}>
              <p className="mb-1 text-[12.5px] font-medium text-[#0B1C3F]">{l} <span className="font-normal text-[#94A3B8]">(facultatif)</span></p>
              <div className="flex gap-1.5">
                <input type="date" aria-label={`${l} — date`} className={INPUT} value={ban[k].d} disabled={ro} onChange={(e) => setBan({ ...ban, [k]: { ...ban[k], d: e.target.value } })} />
                <TimeInput24 aria-label={`${l} — heure`} value={ban[k].t} disabled={ro || !ban[k].d} onChange={(e) => setBan({ ...ban, [k]: { ...ban[k], t: e.target.value } })}
                             className="h-10 rounded-xl border border-[#DCE3EE] px-2 text-[13.5px]" />
              </div>
            </div>
          ))}
        </div>
        {ban.message.trim() && (
          <div className={`mb-3 flex items-start gap-2 rounded-xl border px-3 py-2 text-[13px] ${ban.level === 'warning' ? 'border-[#FDE68A] bg-[#FFFBEB] text-[#92400E]' : 'border-[#BFD3FF] bg-[#EFF5FF] text-[#1E40AF]'}`}>
            {ban.level === 'warning' ? <AlertTriangle size={15} className="mt-0.5 shrink-0" /> : <Info size={15} className="mt-0.5 shrink-0" />}
            <span className="whitespace-pre-line break-words">{ban.message}</span>
          </div>
        )}
        {editable && (
          <div className="flex flex-wrap gap-2">
            <SaveBtn testid="banner-save" busy={busy === 'ban'} disabled={!ban.message.trim()} label="Publier le bandeau"
                     onClick={() => save('ban', { banner: { message: ban.message, level: ban.level, starts_at: join(ban.from), ends_at: join(ban.to) } }, 'Bandeau enregistré.')} />
            {s.banner && (
              <button type="button" onClick={() => save('ban', { banner: null }, 'Bandeau retiré.')} disabled={busy === 'ban'}
                      className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-[#FCA5A5] px-3 text-[13px] text-[#E11D48]"><Trash2 size={14} /> Retirer</button>
            )}
          </div>
        )}
      </Block>

      <Block icon={Mail} title="Essai et emails" sub="Vides = les valeurs d'origine (Vercel, puis le code).">
        <div className="mb-3 grid gap-3 sm:grid-cols-2">
          <div>
            <label className="mb-1 block text-[12.5px] font-medium text-[#0B1C3F]" htmlFor="pf-trial">Durée de l'essai (jours)</label>
            <input id="pf-trial" type="number" min={1} max={365} className={INPUT} disabled={ro} value={mail.trial_days}
                   onChange={(e) => setMail({ ...mail, trial_days: e.target.value })} />
            <p className="mt-1 text-[11.5px] text-[#94A3B8]">Pour les nouveaux essais (plan {s.trial_plan}). Même réglage que Plan Limits.</p>
          </div>
          <div>
            <label className="mb-1 block text-[12.5px] font-medium text-[#0B1C3F]" htmlFor="pf-support">Boîte du support</label>
            <input id="pf-support" type="email" className={INPUT} disabled={ro} value={mail.support_email}
                   onChange={(e) => setMail({ ...mail, support_email: e.target.value })} />
            <p className="mt-1 text-[11.5px] text-[#94A3B8]">Reçoit chaque nouvelle demande de support.</p>
          </div>
          <div>
            <label className="mb-1 block text-[12.5px] font-medium text-[#0B1C3F]" htmlFor="pf-sname">Nom de l'expéditeur</label>
            <input id="pf-sname" className={INPUT} maxLength={70} disabled={ro} value={mail.sender_name}
                   onChange={(e) => setMail({ ...mail, sender_name: e.target.value })} />
          </div>
          <div>
            <label className="mb-1 block text-[12.5px] font-medium text-[#0B1C3F]" htmlFor="pf-semail">Email de l'expéditeur</label>
            <input id="pf-semail" type="email" className={INPUT} disabled={ro} value={mail.sender_email}
                   onChange={(e) => setMail({ ...mail, sender_email: e.target.value })} />
          </div>
        </div>
        <p className="mb-3 flex items-start gap-1.5 rounded-lg bg-[#FFFBEB] px-2.5 py-1.5 text-[12px] text-[#92400E]"><AlertTriangle size={13} className="mt-0.5 shrink-0" />
          L'email de l'expéditeur doit être validé dans Brevo, sinon aucun email ne part. Après un changement : Services › Emails FidClic › Tester.</p>
        {editable && <SaveBtn testid="mail-save" busy={busy === 'mail'} onClick={() => save('mail', {
          trial_days: Number(mail.trial_days), support_email: mail.support_email || null, sender_name: mail.sender_name || null, sender_email: mail.sender_email || null,
        }, 'Enregistré.')} />}
      </Block>

      <Block icon={Link2} title="Autres réglages" sub="Ils restent sur leur page ; voici leur valeur actuelle.">
        <ul className="divide-y divide-[#F1F5F9]" data-testid="shortcuts">
          {d.shortcuts.map((x) => (
            <li key={x.key}>
              <Link to={x.href} className="flex items-center gap-3 py-2.5 hover:bg-[#FAFCFF]">
                <span className="min-w-0 flex-1"><span className="block text-[13.5px] font-semibold text-[#0B1C3F]">{x.label}</span>
                  <span className="block text-[12.5px] text-[#475569]" translate="no">{x.value}</span></span>
                <ChevronRight size={15} className="text-[#94A3B8]" />
              </Link>
            </li>
          ))}
        </ul>
      </Block>
    </div>
  );
}
