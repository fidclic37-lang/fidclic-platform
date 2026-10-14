import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { QRCodeSVG } from 'qrcode.react';
import {
  Shield, ShieldCheck, Clock, ArrowRight, Lock, Monitor, Smartphone, Tablet, Users, User, MoreVertical,
  Database, CloudUpload, KeyRound, Trash2, CheckCircle2, X, Loader2, Check, LogOut, AlertTriangle,
  ShieldAlert, Pencil, Download, UserPlus, Bell, Mail,
} from 'lucide-react';
import { ownerAPI } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';

/* Paramètres › Sécurité — built to the approved mockup, for the owner,
   administrateurs and managers (features/security_page.py). Everyone manages
   its own password, 2FA and devices; on others, each acts as the team
   hierarchy allows — a manager on its staff only. Team and activity follow
   the establishment menu. */

const BLUE = '#2F6BFF';
const longDate = (iso) => (iso ? new Date(iso).toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' }) : '—');
const stamp = (iso) => (iso ? `${new Date(iso).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric' })} à ${new Date(iso).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}` : '');
const DEVICE_ICON = { mobile: Smartphone, tablet: Tablet, desktop: Monitor };
const ACT_ICON = { 'auth.login': [CheckCircle2, '#10B981'], 'auth.oauth_login': [CheckCircle2, '#10B981'], 'auth.login_failed': [ShieldAlert, '#E11D48'],
  'privacy.export': [Download, '#F59E0B'], 'team.user_created': [UserPlus, '#8B5CF6'], 'security.password_changed': [KeyRound, BLUE] };

const Card = ({ children, className = '' }) => (
  <section className={`rounded-2xl border border-[#EDF1F7] bg-white p-4 shadow-[0_1px_2px_rgba(11,28,63,.03)] ${className}`}>{children}</section>
);
const Head = ({ icon: Icon, title, sub, right, tone = BLUE, bg = '#EEF4FF' }) => (
  <header className="mb-3 flex items-start gap-3">
    <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl" style={{ background: bg, color: tone }}><Icon size={23} /></span>
    <div className="min-w-0 flex-1">
      <h2 className="text-[16px] font-bold text-[#0B1C3F]">{title}</h2>
      {sub && <div className="text-[13px] leading-snug text-[#64748B]">{sub}</div>}
    </div>
    {right}
  </header>
);
const OnPill = ({ on = true, label }) => (
  <span className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-[12.5px] ${on ? 'bg-[#E7F7EE] text-[#0F8B58]' : 'bg-[#FEF3C7] text-[#92400E]'}`}>
    {on ? <CheckCircle2 size={14} className="text-white" fill="#10B981" /> : <AlertTriangle size={13} />} {label || (on ? 'Activée' : 'Désactivée')}
  </span>
);
const inputCls = 'h-11 w-full rounded-lg border border-[#DCE3EE] bg-white px-3 text-[14px] text-[#0B1C3F] outline-none focus:border-[#2F6BFF]';
function Modal({ title, onClose, children }) {
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-[#0B1C3F]/30 sm:items-center sm:p-6" onClick={onClose}>
      <div className="max-h-[92vh] w-full max-w-md overflow-y-auto rounded-t-2xl bg-white p-5 shadow-2xl sm:rounded-2xl" onClick={(e) => e.stopPropagation()}>
        <header className="mb-4 flex items-center justify-between">
          <h3 className="text-[16px] font-bold text-[#0B1C3F]">{title}</h3>
          <button type="button" onClick={onClose} aria-label="Fermer" className="text-[#94A3B8] hover:text-[#0B1C3F]"><X size={18} /></button>
        </header>
        {children}
      </div>
    </div>
  );
}

export default function SecuritePage() {
  const navigate = useNavigate();
  const { logout } = useAuth();
  const [d, setD] = useState(null);
  const [err, setErr] = useState('');
  const [toast, setToast] = useState('');
  const [modal, setModal] = useState(null);
  const [menu, setMenu] = useState(null);
  const [busy, setBusy] = useState('');
  const [form, setForm] = useState({});
  const [mErr, setMErr] = useState('');

  // The pending e-mail change lives on its own endpoint: an account without
  // the « Changer l'adresse e-mail » permission is refused it, and the card
  // simply shows the address with no way to change it.
  const [mailPending, setMailPending] = useState(null);
  const [mayChangeEmail, setMayChangeEmail] = useState(false);
  const load = useCallback(() => {
    ownerAPI.security().then(({ data }) => setD(data)).catch((e) => setErr(e?.response?.data?.detail || 'Impossible de charger la sécurité.'));
    ownerAPI.emailState()
      .then(({ data }) => { setMailPending(data.pending); setMayChangeEmail(true); })
      .catch(() => { setMailPending(null); setMayChangeEmail(false); });
  }, []);
  useEffect(() => { load(); }, [load]);
  const say = (m) => { setToast(m); setTimeout(() => setToast(''), 3500); };
  const open = (type, extra = {}) => { setForm({}); setMErr(''); setModal({ type, ...extra }); };
  // « Code de la caisse » — the form's own state; d.caisse_pin is the truth
  const [pin, setPin] = useState({ on: false, mode: 'shop', code: '' });
  useEffect(() => {
    if (d?.caisse_pin) setPin((p) => ({ ...p, on: d.caisse_pin.on, mode: d.caisse_pin.mode }));
  }, [d?.caisse_pin?.on, d?.caisse_pin?.mode]);

  const run = async (key, fn, ok, after) => {
    setBusy(key); setMErr('');
    try { const r = await fn(); if (ok) say(ok); if (after) after(r?.data); else setModal(null); load(); }
    catch (e) { setMErr(e?.response?.data?.detail || "L'action n'a pas abouti."); }
    finally { setBusy(''); }
  };

  if (!d) {
    return err ? <p className="rounded-xl bg-[#FEF2F2] px-4 py-3 text-[13.5px] text-[#B91C1C]">{err}</p>
      : <div key="loading" className="flex items-center justify-center gap-2 rounded-2xl border border-[#E6EEFB] bg-white py-24 text-[13px] text-[#64748B]"><Loader2 size={16} className="animate-spin" /> Chargement…</div>;
  }
  const la = d.last_activity;
  const place = [la.country, la.city && `(${la.city})`].filter(Boolean).join(' ');

  return (
    <div className="sec" onClick={() => setMenu(null)}>
      <header className="mb-4 flex items-start gap-3">
        <span className="mt-0.5 flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-[#EAF1FF] text-[#2F6BFF]"><Shield size={24} /></span>
        <div>
          <h1 className="text-[28px] font-bold leading-tight tracking-[-0.01em] text-[#0B1C3F]">Sécurité</h1>
          <p className="text-[15px] text-[#475569]">Protégez votre compte, vos données et l'accès à votre établissement.</p>
        </div>
      </header>
      {err && <p className="mb-4 rounded-xl bg-[#FEF2F2] px-4 py-2.5 text-[13px] text-[#B91C1C]">{err}</p>}

      <div className="grid gap-4 xl:grid-cols-2">
        {/* row 1 */}
        <section className={`flex flex-wrap items-center gap-4 rounded-2xl border p-4 ${d.secure ? 'border-[#D5F0E0] bg-gradient-to-r from-[#F1FBF5] to-white' : 'border-[#FDE68A] bg-[#FFFBEB]'}`}>
          <span className={`flex h-14 w-14 items-center justify-center rounded-xl ${d.secure ? 'bg-[#DDF4E7] text-[#10B981]' : 'bg-[#FEF3C7] text-[#D97706]'}`}><ShieldCheck size={28} /></span>
          <div className="min-w-0 flex-1">
            <p className="text-[17px] font-bold text-[#0B1C3F]">{d.secure ? 'Compte sécurisé' : 'Compte à renforcer'}</p>
            <p className="text-[13.5px] text-[#475569]">{d.secure ? 'Toutes les mesures de sécurité essentielles sont activées.'
              : 'Activez la double authentification pour protéger votre compte.'}</p>
          </div>
          {d.secure ? <span className="inline-flex items-center gap-2 rounded-lg bg-[#10B981] px-4 py-2.5 text-[14px] font-medium text-white"><CheckCircle2 size={16} /> Sécurisé</span>
            : <button type="button" onClick={() => open('2fa')} className="rounded-lg bg-[#F59E0B] px-4 py-2.5 text-[14px] font-medium text-white">Activer la 2FA</button>}
        </section>
        <Card>
          <Head icon={Clock} title="Dernière activité"
                sub={<>{stamp(la.at)}{place && <><br />Connexion depuis : {place}</>}</>}
                right={<button type="button" onClick={() => open('history')} className="inline-flex shrink-0 items-center gap-1.5 self-center rounded-xl border border-[#2F6BFF] px-4 py-2.5 text-[13px] font-medium text-[#2F6BFF]">Voir l'historique <ArrowRight size={14} /></button>} />
        </Card>

        {/* row 2 */}
        <Card>
          <Head icon={Mail} title="Adresse e-mail" sub="L'adresse avec laquelle vous vous connectez." />
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div className="min-w-0">
              <p className="text-[13.5px] text-[#0B1C3F]">Adresse actuelle</p>
              <p translate="no" className="notranslate truncate text-[14px] text-[#475569]">{d.me.email}</p>
              {mailPending && (
                <p className="mt-1 text-[12.5px] text-[#92400E]">
                  En attente de confirmation sur <strong translate="no" className="notranslate">{mailPending.new_email}</strong>
                  {' '}— {mailPending.method === 'code' ? 'par code' : 'par lien'}.
                </p>
              )}
            </div>
            {mayChangeEmail && (
              <button type="button" onClick={() => open('email')}
                      className="inline-flex items-center gap-2 rounded-xl border border-[#2F6BFF] px-5 py-2.5 text-[13.5px] font-medium text-[#2F6BFF]">
                {mailPending ? 'Reprendre' : "Modifier l'adresse"} <ArrowRight size={14} />
              </button>
            )}
          </div>
        </Card>
        <Card>
          <Head icon={Lock} title="Mot de passe" sub="Protégez votre compte avec un mot de passe fort." />
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <p className="text-[13.5px] text-[#0B1C3F]">Dernière modification</p>
              <p className="text-[14px] text-[#475569]">{d.me.has_password ? longDate(d.me.password_changed_at) : `Connexion via ${d.me.provider || 'Google/Apple'}`}</p>
            </div>
            <button type="button" onClick={() => open('password')}
                    className="inline-flex items-center gap-2 rounded-xl border border-[#2F6BFF] px-5 py-2.5 text-[13.5px] font-medium text-[#2F6BFF]">
              {d.me.has_password ? 'Modifier le mot de passe' : 'Créer un mot de passe'} <ArrowRight size={14} />
            </button>
          </div>
        </Card>
        <Card>
          <Head icon={Shield} title="Authentification à deux facteurs (2FA)" sub="Ajoutez une couche de sécurité supplémentaire à votre compte."
                right={<OnPill on={d.me.totp} />} />
          <div className="flex flex-wrap items-center gap-3">
            <div className={`flex min-w-0 flex-1 items-center gap-3 rounded-xl p-3 ${d.me.totp ? 'bg-[#EEFAF3]' : 'bg-[#FFFBEB]'}`}>
              {d.me.totp ? <CheckCircle2 size={22} className="shrink-0 text-white" fill="#10B981" /> : <AlertTriangle size={20} className="shrink-0 text-[#D97706]" />}
              <p className="text-[12.5px] leading-snug">
                <span className={d.me.totp ? 'text-[#0F8B58]' : 'text-[#92400E]'}>{d.me.totp ? 'La double authentification est activée sur votre compte.' : "La double authentification n'est pas activée."}</span><br />
                <span className="text-[#64748B]">{d.me.totp ? `Un code de votre application est demandé à chaque connexion. ${d.me.backup_codes_left} code(s) de secours restant(s).`
                  : 'Un code de votre téléphone sera demandé à chaque connexion.'}</span>
              </p>
            </div>
            <button type="button" onClick={() => open('2fa')}
                    className="inline-flex items-center gap-2 rounded-xl border border-[#2F6BFF] px-4 py-2.5 text-[13px] font-medium text-[#2F6BFF]">
              {d.me.totp ? 'Gérer la double authentification' : 'Activer'} <ArrowRight size={14} />
            </button>
          </div>
        </Card>

        {/* « Code de la caisse » — off by default (user, 2026-10-14): a till
            should open on the scanner. A shop that wants a lock turns it on
            and says who shares it. It is a lock, not a login: nobody is
            signed out, the device simply does not scan until it is typed. */}
        {d.caisse_pin && (
        <Card>
          <Head icon={KeyRound} title="Code de la caisse"
                sub="Facultatif. Sans code, une caisse enregistrée scanne dès qu'on l'ouvre." />
          <div className="space-y-3 pt-1">
            <label className="flex items-start gap-2.5">
              <input type="checkbox" className="mt-0.5 h-4 w-4 accent-[#2F6BFF]" checked={pin.on}
                     onChange={(e) => setPin((p) => ({ ...p, on: e.target.checked }))} />
              <span>
                <span className="block text-[13.5px] font-semibold text-[#0B1C3F]">Demander un code sur les caisses</span>
                <span className="block text-[12.5px] text-[#64748B]">
                  Une fois saisi, l'appareil scanne pour la journée.
                </span>
              </span>
            </label>
            {pin.on && (
              <>
                <div className="flex flex-wrap gap-2">
                  {[['shop', 'Le même code pour la boutique'], ['device', 'Un code par appareil']].map(([k, l]) => (
                    <button key={k} type="button" onClick={() => setPin((p) => ({ ...p, mode: k }))}
                            className={`rounded-lg border px-3 py-1.5 text-[12.5px] font-semibold ${
                              pin.mode === k ? 'border-[#2F6BFF] text-[#2F6BFF]' : 'border-[#E1E8F5] text-[#475569]'}`}>
                      {l}
                    </button>
                  ))}
                </div>
                <input value={pin.code} onChange={(e) => setPin((p) => ({ ...p, code: e.target.value.replace(/\D/g, '').slice(0, 8) }))}
                       inputMode="numeric" placeholder={d.caisse_pin.set ? 'Nouveau code (4 à 8 chiffres)' : 'Code (4 à 8 chiffres)'}
                       className="w-full max-w-[240px] rounded-xl border border-[#E1E8F5] px-3 py-2 text-[14px] tracking-[0.3em]" />
                {pin.mode === 'device' && (
                  <p className="text-[12.5px] text-[#64748B]">
                    Le code est enregistré sur l'appareil où vous êtes. Répétez l'opération sur chaque caisse.
                  </p>
                )}
              </>
            )}
            <button type="button" disabled={busy === 'pin'}
                    onClick={() => run('pin', () => ownerAPI.setCaisseCode({ on: pin.on, mode: pin.mode, code: pin.code || undefined }),
                                       'Code de la caisse enregistré.', () => setPin((p) => ({ ...p, code: '' })))}
                    className="rounded-xl bg-[#2F6BFF] px-4 py-2 text-[13px] font-semibold text-white disabled:opacity-50">
              Enregistrer
            </button>
          </div>
        </Card>
        )}

        {/* row 3 */}
        <Card>
          <Head icon={Monitor} title="Sessions actives" sub="Gérez les appareils connectés à votre compte." />
          <ul className="divide-y divide-[#F1F5F9]">
            {d.sessions.map((s) => {
              const Icon = DEVICE_ICON[s.kind] || Monitor;
              return (
                <li key={s.sid} className="flex flex-wrap items-center gap-3 py-2.5">
                  <Icon size={20} className="shrink-0 text-[#0B1C3F]" />
                  <div className="min-w-0 flex-1">
                    <p className="flex items-center gap-2 text-[14px] font-medium text-[#0B1C3F]">{s.device}
                      {/* a device left scanning on a counter, never mistaken for someone's phone */}
                      {s.caisse && (
                        <span translate="no" className="rounded-md bg-[#EEF4FF] px-2 py-0.5 text-[11.5px] font-normal text-[#2F6BFF]">
                          Caisse{s.caisse.store ? ` — ${s.caisse.store}` : ''}
                        </span>
                      )}
                      {s.current && <span className="rounded-md bg-[#E7F7EE] px-2 py-0.5 text-[11.5px] font-normal text-[#0F8B58]">Actuelle</span>}</p>
                    <p className="text-[12.5px] text-[#64748B]">{[s.browser, s.os, s.place].filter(Boolean).join(' • ')}</p>
                  </div>
                  <span className="w-28 text-[12.5px] text-[#64748B]">{s.current ? 'Maintenant' : s.seen}</span>
                  {!s.current && (
                    <button type="button" disabled={busy === s.sid} onClick={() => run(s.sid, () => ownerAPI.endSession(s.sid), 'Appareil déconnecté.')}
                            className="rounded-lg border border-[#E11D48] px-3 py-1.5 text-[12.5px] text-[#E11D48] disabled:opacity-50">Déconnecter</button>
                  )}
                </li>
              );
            })}
          </ul>
          {d.sessions.length > 1 && (
            <button type="button" disabled={busy === 'others'} onClick={() => run('others', ownerAPI.endOtherSessions, 'Autres appareils déconnectés.')}
                    className="mt-2 flex w-full items-center justify-center gap-2 rounded-xl border border-[#DCE3EE] py-2.5 text-[13px] font-medium text-[#E11D48]">
              <LogOut size={15} /> Tout déconnecter des autres appareils
            </button>
          )}
        </Card>
        <Card>
          <Head icon={Users} title="Gestion des accès" sub="Contrôlez les accès de votre équipe à votre établissement." />
          <ul className="divide-y divide-[#F1F5F9]">
            {d.team.slice(0, 6).map((m) => (
              <li key={m.id} className="flex items-center gap-3 py-2.5">
                <User size={20} className="shrink-0 text-[#2F6BFF]" />
                <div className="min-w-0 flex-1">
                  <p className="flex flex-wrap items-center gap-2 text-[14px] font-medium text-[#0B1C3F]">{m.name}
                    <span className={`rounded-md px-2 py-0.5 text-[11.5px] font-normal ${m.role === 'business_owner' ? 'bg-[#EAF1FF] text-[#2F6BFF]' : 'bg-[#F1F5F9] text-[#475569]'}`}>{m.role_label}</span>
                    {m.totp && <ShieldCheck size={14} className="text-[#10B981]" title="2FA activée" />}</p>
                  <p className="truncate text-[12.5px] text-[#64748B]">{m.email}</p>
                </div>
                <span className={`text-[13px] ${m.access === 'Accès complet' ? 'text-[#10B981]' : 'text-[#64748B]'}`}>{m.active ? m.access : 'Désactivé'}</span>
                <span className="relative w-6" onClick={(e) => e.stopPropagation()}>
                  {m.can_reset_password && (
                    <>
                      <button type="button" aria-label={`Actions — ${m.name}`} onClick={() => setMenu(menu === m.id ? null : m.id)} className="rounded p-1 text-[#0B1C3F] hover:bg-[#F4F7FC]"><MoreVertical size={17} /></button>
                      {menu === m.id && (
                        <span className="absolute right-0 top-full z-20 mt-1 flex w-56 flex-col overflow-hidden rounded-xl border border-[#E6EEFB] bg-white py-1 shadow-[0_24px_60px_-28px_rgba(11,28,63,.5)]">
                          <button type="button" onClick={() => { setMenu(null); open('reset', { member: m }); }}
                                  className="flex items-center gap-2 px-3.5 py-2 text-left text-[13px] text-[#334155] hover:bg-[#F4F7FC]"><KeyRound size={14} /> Nouveau mot de passe</button>
                        </span>
                      )}
                    </>
                  )}
                </span>
              </li>
            ))}
          </ul>
          <button type="button" onClick={() => navigate('/dashboard/parametres/equipe')}
                  className="mt-2 flex w-full items-center justify-center gap-2 rounded-xl border border-[#2F6BFF] py-2.5 text-[13px] font-medium text-[#2F6BFF]">
            Gérer les membres de l'équipe <ArrowRight size={14} />
          </button>
        </Card>

        {/* row 4 */}
        <Card>
          <Head icon={Clock} title="Activités récentes" sub="Consultez les dernières actions effectuées sur votre compte."
                right={<button type="button" onClick={() => open('history')} className="inline-flex shrink-0 items-center gap-1.5 self-center rounded-xl border border-[#2F6BFF] px-4 py-2 text-[13px] font-medium text-[#2F6BFF]">Voir tout <ArrowRight size={14} /></button>} />
          <ul className="divide-y divide-[#F1F5F9]">
            {d.activity.slice(0, 5).map((a, i) => {
              const [Icon, tone] = ACT_ICON[a.action] || [Bell, BLUE];
              return (
                <li key={i} className="flex items-start gap-3 py-2">
                  <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg" style={{ background: `${tone}1A`, color: tone }}><Icon size={16} /></span>
                  <div className="min-w-0 flex-1">
                    <p className="text-[13.5px] text-[#0B1C3F]">{a.label}</p>
                    <p className="truncate text-[12px] text-[#64748B]">{a.where || `Par ${a.by}`}</p>
                  </div>
                  <span className="shrink-0 text-[12px] text-[#64748B]">{stamp(a.at)}</span>
                </li>
              );
            })}
            {!d.activity.length && <li className="py-4 text-[13px] text-[#64748B]">Aucune activité pour le moment.</li>}
          </ul>
        </Card>
        <div className="grid content-start gap-4">
          <Card>
            <Head icon={Database} title="Protection des données" sub="Sécurisez vos données et gérez leur conservation." />
            <ul className="divide-y divide-[#F1F5F9]">
              <li className="flex items-center gap-3 py-2.5">
                <CloudUpload size={20} className="shrink-0 text-[#10B981]" />
                <div className="min-w-0 flex-1"><p className="text-[14px] text-[#0B1C3F]">Sauvegarde automatique</p><p className="text-[12.5px] text-[#64748B]">Vos données sont sauvegardées automatiquement chaque jour.</p></div>
                <OnPill on={d.protection.backup} />
              </li>
              <li className="flex items-center gap-3 py-2.5">
                <Lock size={20} className="shrink-0 text-[#10B981]" />
                <div className="min-w-0 flex-1"><p className="text-[14px] text-[#0B1C3F]">Chiffrement des données</p><p className="text-[12.5px] text-[#64748B]">Toutes vos données sont chiffrées et sécurisées.</p></div>
                <OnPill on={d.protection.encryption} />
              </li>
              <li className="flex items-center gap-3 py-2.5">
                <Clock size={20} className="shrink-0 text-[#2F6BFF]" />
                <div className="min-w-0 flex-1"><p className="text-[14px] text-[#0B1C3F]">Durée de conservation</p><p className="text-[12.5px] text-[#64748B]">Choisissez la durée de conservation de vos données clients.</p></div>
                <button type="button" onClick={() => navigate('/dashboard/parametres/donnees')}
                        className="flex h-10 w-32 items-center justify-between rounded-lg border border-[#DCE3EE] px-3 text-[14px] text-[#0B1C3F]">
                  {d.protection.retention_years} ans <Pencil size={13} className="text-[#94A3B8]" />
                </button>
              </li>
            </ul>
          </Card>
          <section className="flex flex-wrap items-center gap-4 rounded-2xl border border-[#FCD9D9] bg-[#FEF4F4] p-4">
            <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-[#FDE2E2] text-[#E11D48]"><Trash2 size={23} /></span>
            <div className="min-w-0 flex-1">
              <p className="text-[16px] font-bold text-[#B42318]">Suppression du compte</p>
              <p className="text-[13px] text-[#64748B]">{d.deletion.scope === 'business' ? 'Supprimez définitivement votre compte et toutes vos données.' : 'Supprimez votre accès personnel (les données du commerce restent).'}</p>
            </div>
            <button type="button" disabled={!!d.deletion.scheduled_at} onClick={() => open('delete')}
                    className="rounded-xl border border-[#E11D48] bg-white px-5 py-2.5 text-[13.5px] font-medium text-[#E11D48] disabled:opacity-50">
              {d.deletion.scheduled_at ? `Suppression le ${longDate(d.deletion.purge_on)}` : 'Supprimer mon compte'}
            </button>
          </section>
        </div>
      </div>

      <div aria-live="polite" className="pointer-events-none fixed bottom-5 left-1/2 z-40 -translate-x-1/2 transition-opacity" style={{ opacity: toast ? 1 : 0 }}>
        <span className="inline-flex items-center gap-2 rounded-full bg-[#0B1C3F] px-4 py-2 text-[13px] font-medium text-white shadow-lg"><Check size={14} /> {toast}</span>
      </div>

      {modal?.type === 'email' && (
        <Modal title="Modifier l'adresse e-mail" onClose={() => setModal(null)}>
          {!(form.sent || mailPending) ? (
            <div className="space-y-3">
              <label className="block text-[13px]">Nouvelle adresse
                <input type="email" autoComplete="email" translate="no" className={`${inputCls} notranslate`} value={form.mail || ''}
                       onChange={(e) => setForm({ ...form, mail: e.target.value })} /></label>
              <label className="block text-[13px]">Votre mot de passe
                <input type="password" autoComplete="current-password" className={inputCls} value={form.pw || ''}
                       onChange={(e) => setForm({ ...form, pw: e.target.value })} /></label>
              <div>
                <p className="mb-1.5 text-[13px] text-[#334155]">Comment confirmer ?</p>
                <div className="inline-flex rounded-lg bg-[#F1F5F9] p-0.5" role="group" aria-label="Comment confirmer ?">
                  {[['link', 'Par lien'], ['code', 'Par code']].map(([k, l]) => (
                    <button key={k} type="button" aria-pressed={(form.method || 'link') === k}
                            onClick={() => setForm({ ...form, method: k })}
                            className={`rounded-md px-3 py-1.5 text-[12.5px] font-semibold ${(form.method || 'link') === k ? 'bg-white text-[#2F6BFF] shadow-sm' : 'text-[#64748B]'}`}>{l}</button>
                  ))}
                </div>
              </div>
              <p className="text-[12px] text-[#64748B]">
                FidClic envoie la confirmation à la <strong>nouvelle</strong> adresse. Tant qu'elle
                n'est pas confirmée, vous vous connectez avec l'adresse actuelle — une faute de frappe
                ne bloque donc rien.
              </p>
              {mErr && <p className="text-[13px] text-[#C0392B]">{mErr}</p>}
              <button type="button" disabled={busy === 'mail' || !form.mail || !form.pw}
                      onClick={() => run('mail', () => ownerAPI.emailStart(form.mail.trim(), form.pw, form.method || 'link'),
                                         null, (r) => { setForm({ ...form, sent: r }); load(); })}
                      className="w-full rounded-xl py-2.5 text-[14px] font-medium text-white disabled:opacity-50" style={{ background: BLUE }}>
                Envoyer la confirmation
              </button>
            </div>
          ) : (
            <div className="space-y-3">
              {(() => { const p = form.sent || mailPending; return (
                <>
                  <p className="text-[13.5px] text-[#475569]">
                    {p.method === 'code' ? 'Un code a été envoyé à ' : 'Un lien a été envoyé à '}
                    <strong translate="no" className="notranslate">{p.sent_to || p.new_email}</strong>.
                  </p>
                  {p.method === 'code' ? (
                    <>
                      <label className="block text-[13px]">Code reçu
                        <input inputMode="numeric" maxLength={6} className={`${inputCls} text-center text-[22px] tracking-[8px]`}
                               value={form.code || ''} onChange={(e) => setForm({ ...form, code: e.target.value.replace(/\D/g, '') })} /></label>
                      {mErr && <p className="text-[13px] text-[#C0392B]">{mErr}</p>}
                      <button type="button" disabled={busy === 'mailc' || (form.code || '').length < 6}
                              onClick={() => run('mailc', () => ownerAPI.emailConfirm({ code: form.code }), 'Adresse e-mail modifiée.')}
                              className="w-full rounded-xl py-2.5 text-[14px] font-medium text-white disabled:opacity-50" style={{ background: BLUE }}>
                        Confirmer
                      </button>
                    </>
                  ) : (
                    <p className="text-[12.5px] text-[#64748B]">Ouvrez ce lien depuis votre boîte mail pour terminer. Il est valable 30 minutes.</p>
                  )}
                  {mErr && p.method !== 'code' && <p className="text-[13px] text-[#C0392B]">{mErr}</p>}
                  <button type="button" onClick={() => run('mailx', () => ownerAPI.emailCancel(), 'Demande annulée.')}
                          className="w-full rounded-xl border border-[#DCE3EE] py-2.5 text-[13.5px] text-[#334155]">Annuler la demande</button>
                </>
              ); })()}
            </div>
          )}
        </Modal>
      )}

      {modal?.type === 'password' && (
        <Modal title={d.me.has_password ? 'Modifier le mot de passe' : 'Créer un mot de passe'} onClose={() => setModal(null)}>
          <div className="space-y-3">
            {d.me.has_password && <label className="block text-[13px]">Mot de passe actuel<input type="password" autoComplete="current-password" className={inputCls} value={form.cur || ''} onChange={(e) => setForm({ ...form, cur: e.target.value })} /></label>}
            <label className="block text-[13px]">Nouveau mot de passe<input type="password" autoComplete="new-password" className={inputCls} value={form.n1 || ''} onChange={(e) => setForm({ ...form, n1: e.target.value })} /></label>
            <label className="block text-[13px]">Confirmer<input type="password" autoComplete="new-password" className={inputCls} value={form.n2 || ''} onChange={(e) => setForm({ ...form, n2: e.target.value })} /></label>
            <p className="text-[12px] text-[#64748B]">10 caractères minimum, avec majuscule, minuscule, chiffre et caractère spécial. Vos autres appareils seront déconnectés.</p>
            {mErr && <p className="text-[13px] text-[#C0392B]">{mErr}</p>}
            <button type="button" disabled={busy === 'pw' || !form.n1 || form.n1 !== form.n2}
                    onClick={() => run('pw', () => ownerAPI.changePassword(form.cur || '', form.n1), 'Mot de passe modifié.')}
                    className="w-full rounded-xl py-2.5 text-[14px] font-medium text-white disabled:opacity-50" style={{ background: BLUE }}>Enregistrer</button>
            {form.n1 && form.n2 && form.n1 !== form.n2 && <p className="text-[12.5px] text-[#C0392B]">Les deux mots de passe ne correspondent pas.</p>}
          </div>
        </Modal>
      )}

      {/* The setup stays on screen until its backup codes have been seen,
          even though the page behind already knows 2FA is on. */}
      {modal?.type === '2fa' && (!d.me.totp || form.setup) && (
        <Modal title="Activer la double authentification" onClose={() => setModal(null)}>
          {!form.setup ? (
            <div className="space-y-3 text-[13.5px] text-[#475569]">
              <p>1. Installez une application d'authentification sur votre téléphone : <strong>Google Authenticator</strong>, <strong>Microsoft Authenticator</strong> ou 1Password.</p>
              <p>2. Scannez le QR code qui va s'afficher.</p>
              <p>3. Saisissez le code à 6 chiffres affiché par l'application.</p>
              {mErr && <p className="text-[13px] text-[#C0392B]">{mErr}</p>}
              <button type="button" disabled={busy === 'setup'} onClick={() => run('setup', ownerAPI.totpSetup, null, (data) => setForm({ setup: data }))}
                      className="w-full rounded-xl py-2.5 text-[14px] font-medium text-white" style={{ background: BLUE }}>Commencer</button>
            </div>
          ) : !form.codes ? (
            <div className="space-y-3">
              <div className="flex justify-center rounded-xl bg-[#F8FAFF] p-4"><QRCodeSVG value={form.setup.uri} size={180} /></div>
              <p className="text-center text-[12px] text-[#64748B]">Ou saisissez cette clé : <code className="select-all break-all font-mono text-[#0B1C3F]">{form.setup.secret}</code></p>
              <input inputMode="numeric" maxLength={6} placeholder="Code à 6 chiffres" className={`${inputCls} text-center tracking-[0.3em]`}
                     value={form.code || ''} onChange={(e) => setForm({ ...form, code: e.target.value })} />
              {mErr && <p className="text-[13px] text-[#C0392B]">{mErr}</p>}
              <button type="button" disabled={busy === 'enable' || (form.code || '').length < 6}
                      onClick={() => run('enable', () => ownerAPI.totpEnable(form.code), 'Double authentification activée.', (data) => setForm({ ...form, codes: data.backup_codes }))}
                      className="w-full rounded-xl py-2.5 text-[14px] font-medium text-white disabled:opacity-50" style={{ background: BLUE }}>Activer</button>
            </div>
          ) : (
            <div className="space-y-3">
              <p className="text-[13.5px] text-[#475569]">Gardez ces <strong>codes de secours</strong> en lieu sûr : chacun permet une connexion si vous perdez votre téléphone. Ils ne seront plus affichés.</p>
              <div className="grid grid-cols-2 gap-2 rounded-xl bg-[#F8FAFF] p-3 font-mono text-[14px] text-[#0B1C3F]">{form.codes.map((c) => <span key={c}>{c}</span>)}</div>
              <button type="button" onClick={() => navigator.clipboard?.writeText(form.codes.join('\n'))} className="w-full rounded-xl border border-[#DCE3EE] py-2.5 text-[13.5px]">Copier les codes</button>
              <button type="button" onClick={() => setModal(null)} className="w-full rounded-xl py-2.5 text-[14px] font-medium text-white" style={{ background: BLUE }}>J'ai noté mes codes</button>
            </div>
          )}
        </Modal>
      )}
      {modal?.type === '2fa' && d.me.totp && !form.setup && (
        <Modal title="Gérer la double authentification" onClose={() => setModal(null)}>
          <p className="mb-3 text-[13.5px] text-[#475569]">Pour la désactiver, confirmez avec votre mot de passe et un code de votre application (ou un code de secours).</p>
          <div className="space-y-3">
            {d.me.has_password && <label className="block text-[13px]">Mot de passe<input type="password" className={inputCls} value={form.pw || ''} onChange={(e) => setForm({ ...form, pw: e.target.value })} /></label>}
            <label className="block text-[13px]">Code<input inputMode="numeric" data-keep-zeros="" className={inputCls} value={form.code || ''} onChange={(e) => setForm({ ...form, code: e.target.value })} /></label>
            {mErr && <p className="text-[13px] text-[#C0392B]">{mErr}</p>}
            <button type="button" disabled={busy === 'disable'} onClick={() => run('disable', () => ownerAPI.totpDisable(form.pw || '', form.code || ''), 'Double authentification désactivée.')}
                    className="w-full rounded-xl border border-[#E11D48] py-2.5 text-[14px] font-medium text-[#E11D48]">Désactiver la double authentification</button>
          </div>
        </Modal>
      )}

      {modal?.type === 'reset' && (
        <Modal title={`Nouveau mot de passe — ${modal.member.name}`} onClose={() => setModal(null)}>
          {!form.cred ? (
            <div className="space-y-3">
              <p className="text-[13.5px] text-[#475569]">Un nouveau mot de passe sera créé pour <strong>{modal.member.email}</strong>. L'ancien ne fonctionnera plus.</p>
              {mErr && <p className="text-[13px] text-[#C0392B]">{mErr}</p>}
              <button type="button" disabled={busy === 'reset'} onClick={() => run('reset', () => ownerAPI.resetTeamPassword(modal.member.id), null, (data) => setForm({ cred: data.credentials }))}
                      className="w-full rounded-xl py-2.5 text-[14px] font-medium text-white" style={{ background: BLUE }}>Créer le nouveau mot de passe</button>
            </div>
          ) : (
            <div className="space-y-3">
              <p className="text-[13.5px] text-[#475569]">Transmettez-le à la personne. Il ne sera plus affiché.</p>
              <div className="rounded-xl bg-[#F8FAFF] p-3 font-mono text-[14px] text-[#0B1C3F]">{form.cred.email}<br />{form.cred.password}</div>
              <button type="button" onClick={() => navigator.clipboard?.writeText(`${form.cred.email}\n${form.cred.password}`)} className="w-full rounded-xl border border-[#DCE3EE] py-2.5 text-[13.5px]">Copier</button>
            </div>
          )}
        </Modal>
      )}

      {modal?.type === 'history' && <HistoryModal onClose={() => setModal(null)} />}

      {modal?.type === 'delete' && (
        <Modal title="Supprimer mon compte" onClose={() => setModal(null)}>
          <p className="text-[13.5px] leading-snug text-[#475569]">
            {d.deletion.scope === 'business'
              ? <>Votre commerce sera <strong>fermé tout de suite</strong> : votre équipe ne pourra plus se connecter et votre abonnement s'arrêtera à la fin de la période payée. Toutes vos données seront <strong>supprimées dans 30 jours</strong>. D'ici là, vous pouvez annuler.</>
              : <>Votre accès personnel sera supprimé tout de suite. Les données du commerce ne sont pas touchées.</>}
          </p>
          <div className="mt-3 space-y-3">
            {d.me.has_password && <label className="block text-[13px]">Mot de passe<input type="password" className={inputCls} value={form.pw || ''} onChange={(e) => setForm({ ...form, pw: e.target.value })} /></label>}
            <label className="block text-[13px]">Tapez <strong>SUPPRIMER</strong> pour confirmer<input className={inputCls} value={form.confirm || ''} onChange={(e) => setForm({ ...form, confirm: e.target.value })} /></label>
            {mErr && <p className="text-[13px] text-[#C0392B]">{mErr}</p>}
            <button type="button" disabled={busy === 'delete' || (form.confirm || '').trim().toUpperCase() !== 'SUPPRIMER'}
                    onClick={() => run('delete', () => ownerAPI.deleteAccount(form.pw || '', form.confirm), null, (data) => {
                      setModal(null);
                      if (data?.deleted === 'self') logout().then(() => navigate('/login'));
                      else { say('Suppression programmée.'); window.location.reload(); }
                    })}
                    className="w-full rounded-xl bg-[#E11D48] py-2.5 text-[14px] font-medium text-white disabled:opacity-50">Supprimer mon compte</button>
          </div>
        </Modal>
      )}
    </div>
  );
}

function HistoryModal({ onClose }) {
  const [rows, setRows] = useState(null);
  useEffect(() => { ownerAPI.securityActivity().then(({ data }) => setRows(data.activity || [])).catch(() => setRows([])); }, []);
  return (
    <Modal title="Historique de sécurité" onClose={onClose}>
      {rows === null ? <p key="loading" className="text-[13px] text-[#64748B]"><Loader2 size={14} className="mr-1 inline animate-spin" /> Chargement…</p> : (
        <ul className="divide-y divide-[#F1F5F9]">
          {rows.map((a, i) => (
            <li key={i} className="py-2">
              <p className={`text-[13.5px] ${a.ok ? 'text-[#0B1C3F]' : 'text-[#E11D48]'}`}>{a.label}</p>
              <p className="text-[12px] text-[#64748B]">{[a.by, a.where, stamp(a.at)].filter(Boolean).join(' · ')}</p>
            </li>
          ))}
          {!rows.length && <li className="py-3 text-[13px] text-[#64748B]">Aucune activité.</li>}
        </ul>
      )}
    </Modal>
  );
}
