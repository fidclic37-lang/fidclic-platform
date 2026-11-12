import React, { useCallback, useEffect, useRef, useState } from 'react';
import { QRCodeSVG } from 'qrcode.react';
import { UserRound, KeyRound, ShieldCheck, MonitorSmartphone, BellRing, Save, Camera, Trash2, LogOut, Mail, Bell } from 'lucide-react';
import { meAPI, ownerAPI } from '../../../lib/api';
import { Card, Loading, useToast } from '../../crm/ui';

/* Super admin › Mes paramètres (user, 2026-11-11), PR 3 of 3 — every member of
   FidClic's team, about themselves: profil, mot de passe + 2FA, sessions, mes
   alertes. Server: api/features/team_me.py (+ the shops' own routes for the
   password, 2FA and devices, opened to the team). */

const INPUT = 'h-10 w-full rounded-xl border border-[#DCE3EE] bg-white px-3 text-[13.5px] outline-none focus:border-[#2F6BFF]';
const detail = (e, fb) => {
  const d = e?.response?.data?.detail;
  return typeof d === 'string' ? d : (Array.isArray(d) ? d.map((x) => String(x.msg || '').replace(/^Value error, /, '')).join(' · ') : fb);
};
const when = (s) => (s ? new Date(s).toLocaleString('fr-FR', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Europe/Paris' }) : '');

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

function Btn({ children, onClick, busy, tone = 'blue', testid, disabled }) {
  const cls = tone === 'red' ? 'border border-[#FCA5A5] text-[#E11D48] bg-white' : 'bg-[#2F6BFF] text-white';
  return <button type="button" data-testid={testid} onClick={onClick} disabled={busy || disabled}
                 className={`inline-flex h-9 items-center gap-1.5 rounded-xl px-4 text-[13px] font-semibold disabled:opacity-40 ${cls}`}>{children}</button>;
}

export default function MyAccount() {
  const [d, setD] = useState(null);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState('');
  const [say, node] = useToast();
  const [p, setP] = useState({ first_name: '', last_name: '', phone: '' });
  const [pw, setPw] = useState({ current: '', next: '', again: '' });
  const [totp, setTotp] = useState(null);        // {secret, uri} while setting up
  const [code, setCode] = useState('');
  const [backup, setBackup] = useState(null);
  const [off, setOff] = useState({ password: '', code: '' });
  const file = useRef(null);

  const fill = useCallback((data) => {
    setD(data);
    setP({ first_name: data.profile.first_name, last_name: data.profile.last_name, phone: data.profile.phone });
  }, []);
  const load = useCallback(() => meAPI.get().then(({ data }) => { fill(data); setErr(''); })
    .catch((e) => setErr(detail(e, 'La page n\'a pas pu être chargée.'))), [fill]);
  useEffect(() => { load(); }, [load]);

  const run = async (key, fn, ok) => {
    setBusy(key);
    try { const r = await fn(); if (r?.data?.profile) fill(r.data); if (ok) say(ok); return r; }
    catch (e) { say(detail(e, 'Échec.')); return null; }
    finally { setBusy(''); }
  };

  const pickPhoto = (e) => {
    const f = e.target.files?.[0];
    e.target.value = '';
    if (!f) return;
    if (f.size > 2 * 1024 * 1024) { say('Photo trop lourde (2 Mo maximum).'); return; }
    const r = new FileReader();
    r.onload = () => run('photo', () => meAPI.saveProfile({ photo: r.result }), 'Photo enregistrée.');
    r.readAsDataURL(f);
  };

  if (err) return <p className="rounded-xl bg-[#FEF2F2] px-3 py-2 text-[13px] text-[#B91C1C]">{err}</p>;
  if (!d) return <Loading />;
  const s = d.security;
  const initials = `${(d.profile.first_name || d.profile.email)[0] || ''}${(d.profile.last_name || '')[0] || ''}`.toUpperCase();
  return (
    <div className="grid gap-4 xl:grid-cols-2" data-testid="my-account">
      {node}
      <Block icon={UserRound} title="Profil" sub={`${d.profile.email} · ${d.profile.role}`}>
        <div className="mb-4 flex items-center gap-3">
          {d.profile.photo
            ? <img src={d.profile.photo} alt="" className="h-14 w-14 rounded-full object-cover" data-testid="my-photo" />
            : <span className="grid h-14 w-14 place-items-center rounded-full bg-[#EAF1FF] text-[18px] font-bold text-[#2F6BFF]" translate="no">{initials}</span>}
          <input ref={file} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={pickPhoto} data-testid="photo-input" />
          <Btn onClick={() => file.current?.click()} busy={busy === 'photo'}><Camera size={14} /> Changer la photo</Btn>
          {d.profile.photo && <Btn tone="red" busy={busy === 'photo'} onClick={() => run('photo', () => meAPI.saveProfile({ photo: null }), 'Photo retirée.')}><Trash2 size={14} /></Btn>}
        </div>
        <div className="mb-3 grid gap-3 sm:grid-cols-2">
          <div><label className="mb-1 block text-[12.5px] font-medium" htmlFor="me-fn">Prénom</label>
            <input id="me-fn" className={INPUT} maxLength={80} value={p.first_name} onChange={(e) => setP({ ...p, first_name: e.target.value })} /></div>
          <div><label className="mb-1 block text-[12.5px] font-medium" htmlFor="me-ln">Nom</label>
            <input id="me-ln" className={INPUT} maxLength={80} value={p.last_name} onChange={(e) => setP({ ...p, last_name: e.target.value })} /></div>
          <div><label className="mb-1 block text-[12.5px] font-medium" htmlFor="me-ph">Téléphone</label>
            <input id="me-ph" className={INPUT} maxLength={30} value={p.phone} onChange={(e) => setP({ ...p, phone: e.target.value })} placeholder="06 12 34 56 78" /></div>
        </div>
        <Btn testid="profile-save" busy={busy === 'profile'} onClick={() => run('profile', () => meAPI.saveProfile(p), 'Profil enregistré.')}><Save size={14} /> Enregistrer</Btn>
      </Block>

      <Block icon={KeyRound} title="Mot de passe" sub={s.password_changed_at ? `Changé le ${when(s.password_changed_at)}.` : (s.provider ? `Connexion avec ${s.provider}.` : '')}>
        <div className="mb-3 grid gap-3">
          {s.has_password && <input type="password" aria-label="Mot de passe actuel" autoComplete="current-password" className={INPUT} placeholder="Mot de passe actuel" value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} />}
          <input type="password" aria-label="Nouveau mot de passe" autoComplete="new-password" className={INPUT} placeholder="Nouveau mot de passe (12 caractères, majuscule, chiffre, symbole)" value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} />
          <input type="password" aria-label="Confirmer" autoComplete="new-password" className={INPUT} placeholder="Confirmer" value={pw.again} onChange={(e) => setPw({ ...pw, again: e.target.value })} />
        </div>
        {pw.again && pw.next !== pw.again && <p className="mb-2 text-[12.5px] text-[#E11D48]">Les deux mots de passe ne sont pas identiques.</p>}
        <Btn testid="password-save" busy={busy === 'pw'} disabled={!pw.next || pw.next !== pw.again}
             onClick={async () => { const r = await run('pw', () => ownerAPI.changePassword(pw.current, pw.next), null);
               if (r) { setPw({ current: '', next: '', again: '' }); say(`Mot de passe changé${r.data.other_sessions_closed ? ` · ${r.data.other_sessions_closed} autre(s) appareil(s) déconnecté(s)` : ''}.`); load(); } }}>
          <Save size={14} /> Changer le mot de passe</Btn>
      </Block>

      <Block icon={ShieldCheck} title="Double authentification (2FA)" sub="Un code de votre application d'authentification à chaque connexion.">
        <p className={`mb-3 inline-flex rounded-lg px-2.5 py-1 text-[12.5px] font-semibold ${s.totp ? 'bg-[#E7F7EE] text-[#0F8B58]' : 'bg-[#FFF4DB] text-[#B45309]'}`} data-testid="totp-state">
          {s.totp ? `Activée · ${s.backup_codes_left} codes de secours` : 'Désactivée'}</p>
        {backup && (
          <div className="mb-3 rounded-xl border border-[#FDE68A] bg-[#FFFBEB] p-3 text-[12.5px] text-[#92400E]">
            <p className="mb-1 font-semibold">Codes de secours — notez-les maintenant, ils ne seront plus affichés :</p>
            <p className="grid grid-cols-2 gap-1 font-mono text-[13px] sm:grid-cols-5" translate="no">{backup.map((c) => <span key={c}>{c}</span>)}</p>
          </div>
        )}
        {!s.totp && !totp && <Btn testid="totp-start" busy={busy === 'totp'} onClick={async () => { const r = await run('totp', () => ownerAPI.totpSetup(), null); if (r) setTotp(r.data); }}>Activer</Btn>}
        {!s.totp && totp && (
          <div className="grid gap-3 sm:grid-cols-[auto_1fr] sm:items-start">
            <div className="flex justify-center rounded-xl bg-[#F8FAFF] p-3"><QRCodeSVG value={totp.uri} size={150} /></div>
            <div>
              <p className="mb-2 text-[12.5px] text-[#475569]">Scannez avec votre application (Google Authenticator, 1Password…), ou saisissez la clé :
                <code className="ml-1 break-all rounded bg-[#F1F5F9] px-1 text-[11.5px]" translate="no" data-testid="totp-secret">{totp.secret}</code></p>
              <input aria-label="Code à 6 chiffres" inputMode="numeric" maxLength={8} className={`${INPUT} mb-2`} placeholder="Code à 6 chiffres" value={code} onChange={(e) => setCode(e.target.value.trim())} />
              <Btn testid="totp-confirm" busy={busy === 'totp'} disabled={code.length < 6}
                   onClick={async () => { const r = await run('totp', () => ownerAPI.totpEnable(code), 'Double authentification activée.');
                     if (r) { setBackup(r.data.backup_codes); setTotp(null); setCode(''); load(); } }}>Confirmer</Btn>
            </div>
          </div>
        )}
        {s.totp && (
          <div className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
            <input type="password" aria-label="Mot de passe pour désactiver" className={INPUT} placeholder="Mot de passe" value={off.password} onChange={(e) => setOff({ ...off, password: e.target.value })} />
            <input aria-label="Code pour désactiver" className={INPUT} placeholder="Code ou code de secours" value={off.code} onChange={(e) => setOff({ ...off, code: e.target.value.trim() })} />
            <Btn tone="red" busy={busy === 'totp'} disabled={!off.code}
                 onClick={async () => { const r = await run('totp', () => ownerAPI.totpDisable(off.password, off.code), 'Double authentification désactivée.');
                   if (r) { setOff({ password: '', code: '' }); setBackup(null); load(); } }}>Désactiver</Btn>
          </div>
        )}
      </Block>

      <Block icon={MonitorSmartphone} title="Mes sessions" sub="Les appareils connectés à votre compte ces 30 derniers jours.">
        <ul className="mb-3 divide-y divide-[#F1F5F9]" data-testid="my-sessions">
          {d.sessions.map((x) => (
            <li key={x.sid} className="flex items-center gap-3 py-2.5">
              <span className="min-w-0 flex-1">
                <span className="block text-[13.5px] font-semibold text-[#0B1C3F]">{[x.device, x.browser].filter(Boolean).join(' · ')}
                  {x.current && <span className="ml-2 rounded bg-[#E7F7EE] px-1.5 py-0.5 text-[10.5px] font-semibold text-[#0F8B58]">Cet appareil</span>}</span>
                <span className="block text-[12px] text-[#64748B]"><span translate="no">{x.place || 'Lieu inconnu'}</span> · {when(x.last_seen)}</span>
              </span>
              {!x.current && <button type="button" aria-label={`Déconnecter ${x.device}`} onClick={() => run('s' + x.sid, () => ownerAPI.endSession(x.sid), 'Appareil déconnecté.').then(load)}
                                     className="inline-flex h-8 items-center gap-1 rounded-lg border border-[#DCE3EE] px-2.5 text-[12px] text-[#475569]"><LogOut size={13} /> Déconnecter</button>}
            </li>
          ))}
          {!d.sessions.length && <li className="py-4 text-[13px] text-[#94A3B8]">Aucune session.</li>}
        </ul>
        {d.sessions.filter((x) => !x.current).length > 0 && (
          <Btn tone="red" testid="sessions-others" busy={busy === 'others'}
               onClick={() => run('others', () => ownerAPI.endOtherSessions(), 'Les autres appareils sont déconnectés.').then(load)}><LogOut size={14} /> Déconnecter les autres appareils</Btn>
        )}
      </Block>

      <Block icon={BellRing} title="Mes alertes" sub="Pour chaque type : dans la cloche seulement, ou aussi par email. Seuls les types que votre rôle ouvre sont listés.">
        <ul className="divide-y divide-[#F1F5F9]" data-testid="my-alerts">
          {d.alerts.map((a) => (
            <li key={a.key} className="flex flex-wrap items-center gap-3 py-2.5" data-alert={a.key}>
              <span className="min-w-0 flex-1 text-[13.5px] text-[#0B1C3F]">{a.label}</span>
              <span className="flex gap-1" role="radiogroup" aria-label={a.label}>
                {[['bell', 'Cloche', Bell], ['email', 'Cloche + email', Mail]].map(([v, l, I]) => (
                  <button key={v} type="button" role="radio" aria-checked={a.value === v} disabled={busy === 'al'}
                          onClick={() => a.value !== v && run('al', () => meAPI.saveAlerts({ [a.key]: v }), 'Alertes enregistrées.')}
                          className={`inline-flex h-8 items-center gap-1 rounded-lg border px-2.5 text-[12px] font-medium ${a.value === v ? 'border-[#2F6BFF] bg-[#EAF1FF] text-[#2F6BFF]' : 'border-[#DCE3EE] text-[#475569]'}`}><I size={13} /> {l}</button>
                ))}
              </span>
            </li>
          ))}
        </ul>
      </Block>
    </div>
  );
}
