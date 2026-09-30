import React, { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import {
  Crown, Settings, BarChart3, Headphones, Users, Briefcase, Shield, CalendarDays, ChevronDown, Copy, Loader2, Check,
} from 'lucide-react';
import { securityAPI } from '../../../lib/api';
import { Modal, Select, BLUE, inputCls } from '../../crm/ui';

/* Shared by the Sécurité pages. */

export const TONES = {
  violet: ['#F3EEFF', '#7C3AED'], blue: ['#EAF1FF', '#2F6BFF'], green: ['#E7F7EE', '#0F8B58'], orange: ['#FFF4DB', '#D97706'],
  rose: ['#FDECEF', '#E11D48'], cyan: ['#E0F7FB', '#0891B2'], slate: ['#F1F5F9', '#475569'],
};
export const ROLE_ICONS = { crown: Crown, settings: Settings, chart: BarChart3, headset: Headphones, users: Users, briefcase: Briefcase, shield: Shield };
export const RoleIcon = ({ icon, size = 16 }) => React.createElement(ROLE_ICONS[icon] || Shield, { size });

export function RoleBadge({ name, tone, icon }) {
  const [bg, fg] = TONES[tone] || TONES.blue;
  return <span className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-md px-2 py-1 text-[12px] font-medium" style={{ background: bg, color: fg }}><RoleIcon icon={icon} size={13} /> {name}</span>;
}

export const flag = (cc) => (cc && /^[A-Z]{2}$/.test(cc) ? String.fromCodePoint(...[...cc].map((c) => 127397 + c.charCodeAt(0))) : '🌐');

export const LOGIN_TONE = { Réussie: ['#E7F7EE', '#0F8B58'], Échouée: ['#FFF4DB', '#B45309'], Bloquée: ['#FDECEF', '#E11D48'] };
export const JOURNAL_TONE = { Succès: ['#E7F7EE', '#0F8B58'], Refusé: ['#FFF4DB', '#B45309'], Bloqué: ['#FDECEF', '#E11D48'] };
export const Pill = ({ tone, children }) => <span className="whitespace-nowrap rounded-md px-2 py-0.5 text-[11.5px] font-semibold" style={{ background: tone[0], color: tone[1] }}>{children}</span>;

export const when = (iso) => (iso ? new Date(iso).toLocaleString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—');
const iso = (d) => d.toISOString().slice(0, 10);

/* « 28 sept. 2026 - 28 oct. 2026 » and its menu. */
export function useRange(days = 30) {
  const [r, setR] = useState({ from: iso(new Date(Date.now() - days * 86400000)), to: iso(new Date()) });
  return [r, setR];
}
export function RangePicker({ value, onChange }) {
  const [open, setOpen] = useState(false);
  const fr = (s) => new Date(`${s}T12:00:00`).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric' });
  const pick = (d) => { onChange({ from: iso(new Date(Date.now() - d * 86400000)), to: iso(new Date()) }); setOpen(false); };
  return (
    <span className="relative" onClick={(e) => e.stopPropagation()}>
      <button type="button" onClick={() => setOpen((v) => !v)} className="inline-flex h-11 items-center gap-2 rounded-xl border border-[#DCE3EE] bg-white px-4 text-[13.5px] text-[#0B1C3F]">
        <CalendarDays size={16} /> {fr(value.from)} - {fr(value.to)} <ChevronDown size={15} />
      </button>
      {open && (
        <span className="absolute right-0 top-full z-30 mt-1 flex w-64 flex-col overflow-hidden rounded-xl border border-[#E6EEFB] bg-white py-1 text-[13px] shadow-lg">
          {[[7, '7 derniers jours'], [30, '30 derniers jours'], [90, '90 derniers jours'], [365, '12 derniers mois']].map(([d, l]) => (
            <button key={d} type="button" onClick={() => pick(d)} className="px-3.5 py-2 text-left hover:bg-[#F4F7FC]">{l}</button>
          ))}
          <span className="flex items-center gap-1.5 border-t border-[#EDF1F7] px-3 py-2">
            <input type="date" value={value.from} max={value.to} onChange={(e) => onChange({ ...value, from: e.target.value })} className="h-8 min-w-0 flex-1 rounded-lg border border-[#DCE3EE] px-1.5 text-[12px]" />
            <input type="date" value={value.to} min={value.from} onChange={(e) => onChange({ ...value, to: e.target.value })} className="h-8 min-w-0 flex-1 rounded-lg border border-[#DCE3EE] px-1.5 text-[12px]" />
          </span>
        </span>
      )}
    </span>
  );
}

/* The tabs under the figures, as in the mockup — each opens its page. */
export function SecuTabs({ right }) {
  const { pathname } = useLocation();
  const tabs = [['/admin/securite', 'Utilisateurs'], ['/admin/securite/roles', 'Rôles & Permissions'], ['/admin/securite/connexions', 'Connexions'],
    ['/admin/securite/journal', "Journal d'activité"], ['/admin/securite/parametres', 'Paramètres sécurité']];
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#EDF1F7] px-3">
      <nav className="flex flex-wrap gap-1">
        {tabs.map(([to, l]) => (
          <Link key={to} to={to} className={`border-b-2 px-3 py-3 text-[14px] ${pathname === to ? 'border-[#2F6BFF] font-medium text-[#2F6BFF]' : 'border-transparent text-[#0B1C3F] hover:text-[#2F6BFF]'}`}>{l}</Link>
        ))}
      </nav>
      {right}
    </div>
  );
}

/* A new password is shown once — the person gives it to its owner. */
export function PasswordOnce({ email, password, onClose, title = 'Utilisateur créé' }) {
  const [copied, setCopied] = useState(false);
  const text = `Email : ${email}\nMot de passe provisoire : ${password}\nConnexion : ${window.location.origin}/login`;
  return (
    <Modal title={title} onClose={onClose}>
      <p className="mb-3 text-[13.5px] text-[#334155]">Transmettez ces identifiants à la personne. <strong>Le mot de passe ne sera plus affiché.</strong> Elle pourra activer la double authentification une fois connectée.</p>
      <div className="space-y-1.5 rounded-xl bg-[#F8FAFF] p-3 font-mono text-[13px]"><p>Email : {email}</p><p>Mot de passe : {password}</p></div>
      <button type="button" onClick={() => { navigator.clipboard?.writeText(text); setCopied(true); }} className="mt-3 inline-flex items-center gap-2 text-[13px] text-[#2F6BFF]">{copied ? <Check size={14} /> : <Copy size={14} />} {copied ? 'Copié' : 'Copier'}</button>
      <button type="button" onClick={onClose} className="mt-3 w-full rounded-lg py-2.5 text-[13.5px] font-semibold text-white" style={{ background: BLUE }}>J'ai transmis les identifiants</button>
    </Modal>
  );
}

export function UserModal({ user, roles, onClose, onDone }) {
  const [f, setF] = useState({ email: user?.email || '', first_name: user?.first_name || '', last_name: user?.last_name || '', role_id: user?.role_id || '' });
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true); setErr('');
    try {
      if (user) { await securityAPI.editUser(user.email, { first_name: f.first_name, last_name: f.last_name, role_id: f.role_id }); onDone(null); }
      else { const { data } = await securityAPI.addUser(f); onDone(data); }
    } catch (e) { setErr(e?.response?.data?.detail || 'Enregistrement impossible.'); setBusy(false); }
  };
  const role = roles.find((r) => r.id === f.role_id);
  return (
    <Modal title={user ? `Modifier — ${user.name}` : 'Ajouter un utilisateur'} onClose={onClose}>
      <div className="grid gap-2 sm:grid-cols-2">
        <label><span className="mb-1 block text-[11.5px] text-[#64748B]">Prénom</span><input className={inputCls} value={f.first_name} onChange={(e) => setF({ ...f, first_name: e.target.value })} /></label>
        <label><span className="mb-1 block text-[11.5px] text-[#64748B]">Nom</span><input className={inputCls} value={f.last_name} onChange={(e) => setF({ ...f, last_name: e.target.value })} /></label>
        <label className="sm:col-span-2"><span className="mb-1 block text-[11.5px] text-[#64748B]">Email (identifiant de connexion)</span>
          <input className={inputCls} value={f.email} disabled={!!user} onChange={(e) => setF({ ...f, email: e.target.value })} placeholder="prenom@fidclic.com" /></label>
        <div className="sm:col-span-2">
          <Select label="Rôle" value={f.role_id} onChange={(v) => setF({ ...f, role_id: v })}><option value="">Choisir…</option>{roles.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}</Select>
        </div>
      </div>
      {role && <p className="mt-2 rounded-lg bg-[#F8FAFF] px-3 py-2 text-[12.5px] text-[#475569]">{role.description || 'Rôle personnalisé.'} Il pourra ouvrir : {Object.entries(role.perms).filter(([, v]) => v.view).length} section(s).</p>}
      {err && <p className="mt-2 text-[13px] text-[#C0392B]">{err}</p>}
      <button type="button" disabled={busy || !f.role_id || (!user && !f.email.includes('@'))} onClick={save} className="mt-3 flex w-full items-center justify-center gap-2 rounded-lg py-2.5 text-[13.5px] font-semibold text-white disabled:opacity-50" style={{ background: BLUE }}>
        {busy && <Loader2 size={15} className="animate-spin" />} {user ? 'Enregistrer' : "Créer l'utilisateur"}</button>
    </Modal>
  );
}
