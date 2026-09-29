import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Users, UserPlus, Crown, ShieldCheck, User, Search, ChevronDown, SlidersHorizontal, Pencil,
  MoreVertical, KeyRound, Power, Trash2, X, Check, Loader2, Copy, Hourglass, Settings, Building2,
  Store, Send,
} from 'lucide-react';
import { ownerAPI } from '../lib/api';

/* Paramètres › Équipe & accès — the franchise's accounts, their roles and
   their establishments.

   Propriétaire → creates Administrateurs; an Administrateur → the Managers
   (and Employés) of its establishments; a Manager → the Employés of its
   establishment. Each hands over the email and the password shown once —
   no invitation e-mail. Everyone sees and manages only the accounts below
   them, inside their own establishments (enforced by the server). */

const ROLE_STYLE = {
  business_owner: { icon: Crown, fg: '#2F6BFF', bg: '#EAF1FF', tint: '#F4F8FF' },
  administrateur: { icon: ShieldCheck, fg: '#10A36B', bg: '#E7F7EE', tint: '#F3FBF6' },
  manager: { icon: Users, fg: '#E8741A', bg: '#FFF1E4', tint: '#FFF8F0' },
  staff: { icon: User, fg: '#7C3AED', bg: '#F1EBFF', tint: '#F8F4FF' },
};
const AVATARS = ['#2F6BFF', '#3B82F6', '#EC4899', '#A855F7', '#22C55E', '#EAB308', '#F97316', '#14B8A6'];
const avatarColour = (s) => AVATARS[[...(s || '?')].reduce((a, c) => a + c.charCodeAt(0), 0) % AVATARS.length];

function lastLogin(iso) {
  if (!iso) return ['Jamais', ''];
  const d = new Date(iso);
  const now = new Date();
  const time = d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
  const days = Math.floor((new Date(now.toDateString()) - new Date(d.toDateString())) / 86400000);
  if (days <= 0) return ["Aujourd'hui", time];
  if (days === 1) return ['Hier', time];
  if (days < 30) return [`Il y a ${days} jours`, time];
  return [d.toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric' }), time];
}

function Toggle({ on, onChange, label, disabled }) {
  return (
    <button type="button" role="switch" aria-checked={on} aria-label={label} disabled={disabled}
      onClick={() => onChange(!on)}
      className="relative h-[24px] w-[42px] shrink-0 rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-60"
      style={{ background: on ? '#2F6BFF' : '#D5DCE6' }}>
      <span className="absolute top-[3px] h-[18px] w-[18px] rounded-full bg-white shadow transition-all" style={{ left: on ? 21 : 3 }} />
    </button>
  );
}

function RolePill({ role, label }) {
  const st = ROLE_STYLE[role] || ROLE_STYLE.staff;
  const Icon = st.icon;
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-md px-2.5 py-1 text-[12.5px] font-medium" style={{ background: st.bg, color: st.fg }}>
      <Icon size={14} /> {label}
    </span>
  );
}

function Avatar({ name, size = 36 }) {
  return (
    <span className="flex shrink-0 items-center justify-center rounded-full font-semibold text-white"
          style={{ width: size, height: size, background: avatarColour(name), fontSize: size * 0.42 }}>
      {(name || '?').slice(0, 1).toUpperCase()}
    </span>
  );
}

function Modal({ title, subtitle, onClose, children, width = 'max-w-[520px]' }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0B1C3F]/40 p-4" role="dialog" aria-modal="true" aria-label={title}>
      <div className={`max-h-[92vh] w-full ${width} overflow-y-auto rounded-2xl bg-white p-6 shadow-[0_40px_90px_-40px_rgba(11,28,63,.6)]`}>
        <div className="mb-5 flex items-start justify-between gap-3">
          <div>
            <h2 className="text-[19px] font-bold text-[#0B1C3F]">{title}</h2>
            {subtitle && <p className="mt-0.5 text-[13px] text-[#64748B]">{subtitle}</p>}
          </div>
          <button type="button" onClick={onClose} aria-label="Fermer" className="flex h-9 w-9 items-center justify-center rounded-lg text-[#64748B] hover:bg-[#F4F7FC]"><X size={18} /></button>
        </div>
        {children}
      </div>
    </div>
  );
}

const field = 'h-11 w-full rounded-lg border border-[#E2E8F0] bg-white px-3 text-[13.5px] text-[#0B1C3F] outline-none focus:border-[#2F6BFF]';
const btnPrimary = 'inline-flex h-11 items-center justify-center gap-2 rounded-xl bg-[#2F6BFF] px-5 text-[14px] font-semibold text-white hover:bg-[#2559DB] disabled:opacity-60';
const btnGhost = 'inline-flex h-11 items-center justify-center rounded-xl border border-[#E2E8F0] bg-white px-5 text-[14px] font-semibold text-[#334155]';

/* Establishments: one for a manager / an employé, several for an administrateur. */
function StorePicker({ role, stores, value, onChange, compact = false, disabled = false }) {
  const [open, setOpen] = useState(false);
  const box = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const away = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', away);
    return () => document.removeEventListener('mousedown', away);
  }, [open]);
  const names = Object.fromEntries(stores.map((s) => [s.id, s.name]));
  const height = compact ? 'h-9 text-[12.5px]' : 'h-11 text-[13.5px]';
  if (role !== 'administrateur') {
    return (
      <span className="relative block">
        <select value={value[0] || ''} disabled={disabled} onChange={(e) => onChange([e.target.value])}
                className={`${height} w-full appearance-none rounded-lg border border-[#E2E8F0] bg-white pl-3 pr-8 text-[#0B1C3F] outline-none focus:border-[#2F6BFF] disabled:bg-[#F8FAFC]`}>
          {!value[0] && <option value="">Choisir…</option>}
          {stores.map((s) => <option key={s.id} value={s.id}>{s.name}{s.city ? ` - ${s.city}` : ''}</option>)}
        </select>
        <ChevronDown size={15} className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-[#334155]" />
      </span>
    );
  }
  const label = value.length === 0 ? 'Choisir…' : value.length === 1 ? names[value[0]] || '1 établissement' : `${value.length} établissements`;
  return (
    <div ref={box} className="relative">
      <button type="button" disabled={disabled} onClick={() => setOpen((v) => !v)}
              className={`${height} flex w-full items-center justify-between rounded-lg border border-[#E2E8F0] bg-white pl-3 pr-2.5 text-left text-[#0B1C3F] disabled:bg-[#F8FAFC]`}>
        <span className="truncate">{label}</span><ChevronDown size={15} className="shrink-0 text-[#334155]" />
      </button>
      {open && (
        <div className="absolute left-0 right-0 z-30 mt-1 max-h-60 overflow-y-auto rounded-xl border border-[#E6EEFB] bg-white py-1 shadow-[0_18px_40px_-20px_rgba(11,28,63,.45)]">
          {stores.map((s) => {
            const on = value.includes(s.id);
            return (
              <label key={s.id} className="flex cursor-pointer items-center gap-2.5 px-3 py-2 text-[13px] text-[#0B1C3F] hover:bg-[#F6F9FF]">
                <input type="checkbox" checked={on} className="h-4 w-4 accent-[#2F6BFF]"
                       onChange={() => onChange(on ? value.filter((x) => x !== s.id) : [...value, s.id])} />
                {s.name}{s.city ? <span className="text-[#94A3B8]"> · {s.city}</span> : null}
              </label>
            );
          })}
        </div>
      )}
    </div>
  );
}

function Credentials({ creds, onClose }) {
  const text = `Votre accès FidClic\nAdresse : ${window.location.origin}/login\nEmail : ${creds.email}\nMot de passe : ${creds.password}`;
  const [copied, setCopied] = useState(false);
  return (
    <Modal title="Identifiants prêts" subtitle="Transmettez-les à votre collaborateur. Ce mot de passe ne sera plus affiché." onClose={onClose}>
      <div className="rounded-xl border border-[#BFEBD3] bg-[#F0FDF6] p-4 font-mono text-[13px] leading-7 text-[#0B1C3F]">
        <div><span className="text-[#64748B]">Adresse :</span> {window.location.origin}/login</div>
        <div><span className="text-[#64748B]">Email :</span> {creds.email}</div>
        <div><span className="text-[#64748B]">Mot de passe :</span> <b>{creds.password}</b></div>
      </div>
      <div className="mt-4 flex flex-wrap justify-end gap-2">
        <a href={`https://wa.me/?text=${encodeURIComponent(text)}`} target="_blank" rel="noreferrer" className={btnGhost}>
          <Send size={15} className="mr-2" /> WhatsApp
        </a>
        <button type="button" className={btnPrimary}
                onClick={async () => { try { await navigator.clipboard.writeText(text); setCopied(true); } catch { /* manual */ } }}>
          {copied ? <Check size={16} /> : <Copy size={16} />} {copied ? 'Copié' : 'Tout copier'}
        </button>
      </div>
    </Modal>
  );
}

function EditModal({ user, d, onClose, onSaved }) {
  const [first, setFirst] = useState(user.first_name || user.name.split(' ')[0] || '');
  const [last, setLast] = useState(user.last_name || user.name.split(' ').slice(1).join(' ') || '');
  const [role, setRole] = useState(user.role);
  const [ids, setIds] = useState(user.branch_ids);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const roles = d.roles.filter((r) => d.me.can_create.includes(r.key));
  const save = async (e) => {
    e.preventDefault();
    setSaving(true); setError('');
    try {
      const { data } = await ownerAPI.teamUpdate(user.id, { first_name: first, last_name: last, role,
        branch_ids: role === 'administrateur' ? ids : ids.slice(0, 1) });
      onSaved(data, 'Utilisateur mis à jour');
    } catch (err) { setError(err?.response?.data?.detail || 'Enregistrement impossible.'); setSaving(false); }
  };
  return (
    <Modal title="Modifier l'utilisateur" subtitle={user.email} onClose={onClose}>
      <form onSubmit={save}>
        <div className="mb-4 grid gap-3 sm:grid-cols-2">
          <label className="block"><span className="mb-1.5 block text-[13px] font-semibold text-[#334155]">Prénom</span>
            <input value={first} onChange={(e) => setFirst(e.target.value)} className={field} /></label>
          <label className="block"><span className="mb-1.5 block text-[13px] font-semibold text-[#334155]">Nom</span>
            <input value={last} onChange={(e) => setLast(e.target.value)} className={field} /></label>
        </div>
        <div className="mb-5 grid gap-3 sm:grid-cols-2">
          <label className="block"><span className="mb-1.5 block text-[13px] font-semibold text-[#334155]">Rôle</span>
            <span className="relative block">
              <select value={role} onChange={(e) => setRole(e.target.value)} className={`${field} appearance-none pr-8`}>
                {roles.map((r) => <option key={r.key} value={r.key}>{r.label}</option>)}
              </select>
              <ChevronDown size={15} className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2" />
            </span></label>
          <div><span className="mb-1.5 block text-[13px] font-semibold text-[#334155]">Établissement(s)</span>
            <StorePicker role={role} stores={d.stores} value={ids} onChange={setIds} /></div>
        </div>
        {error && <p className="mb-4 rounded-lg bg-[#FEF2F2] px-3 py-2.5 text-[13px] text-[#B91C1C]">{error}</p>}
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className={btnGhost}>Annuler</button>
          <button type="submit" disabled={saving} className={btnPrimary}>{saving ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />} Enregistrer</button>
        </div>
      </form>
    </Modal>
  );
}

function RowMenu({ u, onAction }) {
  const [open, setOpen] = useState(false);
  const box = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const away = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', away);
    return () => document.removeEventListener('mousedown', away);
  }, [open]);
  if (!u.manageable) return <span className="inline-block h-9 w-9" />;
  const item = (icon, label, key, danger) => (
    <button key={key} type="button" onClick={() => { setOpen(false); onAction(key, u); }}
            className={`flex w-full items-center gap-2.5 px-3.5 py-2 text-left text-[13px] hover:bg-[#F6F9FF] ${danger ? 'text-[#E11D48]' : 'text-[#0B1C3F]'}`}>{icon}{label}</button>
  );
  return (
    <div ref={box} className="relative">
      <button type="button" onClick={() => setOpen((v) => !v)} aria-label={`Actions — ${u.name}`}
              className="flex h-9 w-9 items-center justify-center rounded-lg text-[#0B1C3F] hover:bg-[#F4F7FC]"><MoreVertical size={18} /></button>
      {open && (
        <div className="absolute right-0 top-10 z-30 w-60 overflow-hidden rounded-xl border border-[#E6EEFB] bg-white py-1 shadow-[0_18px_40px_-20px_rgba(11,28,63,.45)]">
          {item(<KeyRound size={15} />, 'Nouveau mot de passe', 'password')}
          {item(<Power size={15} />, u.active ? 'Désactiver le compte' : 'Réactiver le compte', 'toggle')}
          {item(<Trash2 size={15} />, 'Supprimer le compte', 'delete', true)}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ page -- */
export default function EquipeAccesPage() {
  const [d, setD] = useState(null);
  const [error, setError] = useState('');
  const [tab, setTab] = useState('users');
  const [q, setQ] = useState('');
  const [roleFilter, setRoleFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [showStatus, setShowStatus] = useState(false);
  const [creds, setCreds] = useState(null);
  const [editing, setEditing] = useState(null);
  const [confirm, setConfirm] = useState(null);
  const [toast, setToast] = useState('');
  const [invite, setInvite] = useState({ name: '', email: '', role: '', branch_ids: [] });
  const [inviteError, setInviteError] = useState('');
  const [inviting, setInviting] = useState(false);
  const [storeSel, setStoreSel] = useState('');
  const inviteBox = useRef(null);
  const toastTimer = useRef(null);

  const say = (m) => { setToast(m); clearTimeout(toastTimer.current); toastTimer.current = setTimeout(() => setToast(''), 2600); };
  useEffect(() => () => clearTimeout(toastTimer.current), []);

  const load = useCallback(() => {
    ownerAPI.teamAccess()
      .then(({ data }) => { setD(data); setError(''); })
      .catch((e) => setError(e?.response?.data?.detail || "Impossible de charger l'équipe."));
  }, []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!d) return;
    setInvite((v) => ({ ...v, role: v.role || d.me.can_create[0] || '',
      branch_ids: v.branch_ids.length ? v.branch_ids : (d.stores.length === 1 ? [d.stores[0].id] : []) }));
    setStoreSel((v) => v || d.stores[0]?.id || '');
  }, [d]);

  const run = async (fn, msg) => {
    try { const { data } = await fn(); setD(data); if (data.credentials) setCreds(data.credentials); if (msg) say(msg); return true; }
    catch (e) { say(typeof e?.response?.data?.detail === 'string' ? e.response.data.detail : 'Action impossible.'); return false; }
  };

  const rows = useMemo(() => {
    if (!d) return [];
    const needle = q.trim().toLowerCase();
    return d.users.filter((u) => (!needle || `${u.name} ${u.email}`.toLowerCase().includes(needle))
      && (!roleFilter || u.role === roleFilter)
      && (!statusFilter || (statusFilter === 'active' ? u.active : !u.active)));
  }, [d, q, roleFilter, statusFilter]);

  const onAction = (key, u) => {
    if (key === 'password') setConfirm({ title: `Nouveau mot de passe pour ${u.name} ?`, body: "L'ancien ne fonctionnera plus. Le nouveau s'affichera une seule fois.", cta: 'Générer', danger: false,
      go: () => run(() => ownerAPI.teamPassword(u.id)) });
    if (key === 'toggle') run(() => ownerAPI.teamStatus(u.id, !u.active), u.active ? 'Compte désactivé' : 'Compte réactivé');
    if (key === 'delete') setConfirm({ title: `Supprimer le compte de ${u.name} ?`, body: 'Il ne pourra plus se connecter. Cette action est définitive.', cta: 'Supprimer', danger: true,
      go: () => run(() => ownerAPI.teamDelete(u.id), 'Compte supprimé') });
  };

  const create = async (e) => {
    e.preventDefault();
    setInviting(true); setInviteError('');
    const [first, ...rest] = invite.name.trim().split(/\s+/);
    try {
      const { data } = await ownerAPI.teamCreate({ email: invite.email, role: invite.role, first_name: first || '',
        last_name: rest.join(' '), branch_ids: invite.role === 'administrateur' ? invite.branch_ids : invite.branch_ids.slice(0, 1) });
      setD(data); setCreds(data.credentials);
      setInvite({ name: '', email: '', role: invite.role, branch_ids: d.stores.length === 1 ? [d.stores[0].id] : [] });
    } catch (err) {
      setInviteError(typeof err?.response?.data?.detail === 'string' ? err.response.data.detail : 'Création impossible.');
    } finally { setInviting(false); }
  };

  if (!d) {
    return error ? <p className="rounded-xl bg-[#FEF2F2] px-4 py-3 text-[13.5px] text-[#B91C1C]">{error}</p> : (
      <div className="flex items-center justify-center gap-2 rounded-2xl border border-[#E6EEFB] bg-white py-24 text-[13px] text-[#64748B]">
        <Loader2 size={16} className="animate-spin" /> Chargement…
      </div>
    );
  }

  const roleLabel = Object.fromEntries(d.roles.map((r) => [r.key, r.label]));
  const canCreate = d.me.can_create.length > 0;
  const TABS = [
    { key: 'users', label: 'Utilisateurs', icon: Users },
    { key: 'pending', label: 'Invitations en attente', icon: Hourglass, count: d.pending.length },
    { key: 'permissions', label: 'Permissions', icon: Settings },
    { key: 'stores', label: 'Accès par établissement', icon: Building2 },
  ];
  const cardHead = (Icon, title, sub, right) => (
    <div className="mb-4 flex flex-wrap items-start gap-3">
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#EAF1FF] text-[#2F6BFF]"><Icon size={19} /></span>
      <div className="min-w-0 flex-1"><h3 className="text-[15.5px] font-bold text-[#0B1C3F]">{title}</h3>
        {sub && <p className="mt-0.5 text-[12.5px] text-[#64748B]">{sub}</p>}</div>
      {right}
    </div>
  );

  const StoreAccess = ({ compact }) => {
    const sid = storeSel || d.stores[0]?.id;
    const list = d.users;
    return (
      <div>
        <span className="relative mb-3 block">
          <select value={sid} onChange={(e) => setStoreSel(e.target.value)} className={`${field} ${compact ? 'h-10' : ''} appearance-none pr-8`}>
            {d.stores.map((s) => <option key={s.id} value={s.id}>{s.name}{s.city ? ` - ${s.city}` : ''}</option>)}
          </select>
          <ChevronDown size={15} className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2" />
        </span>
        <ul className="space-y-1">
          {list.map((u) => {
            const on = u.role === 'business_owner' || u.branch_ids.includes(sid);
            const locked = !u.manageable || u.role === 'business_owner';
            const single = u.role === 'manager' || u.role === 'staff';
            return (
              <li key={u.id} className="flex items-center gap-3 rounded-lg px-1 py-1.5">
                <Avatar name={u.name} size={compact ? 24 : 30} />
                <span className="min-w-0 flex-1 truncate text-[13px] text-[#0B1C3F]">
                  <b className="font-semibold">{u.name}</b> <span className="text-[#64748B]">({u.role_label})</span>
                </span>
                <span title={locked ? (u.role === 'business_owner' ? 'Le propriétaire a accès à tout.' : 'Hors de votre périmètre.')
                  : single && on ? 'Un manager ou un employé a un seul établissement : choisissez-en un autre pour le déplacer.' : ''}>
                  <Toggle on={on} label={`Accès de ${u.name} à cet établissement`} disabled={locked || (single && on)}
                          onChange={(v) => run(() => ownerAPI.teamStoreAccess(sid, u.id, v), v ? 'Accès donné' : 'Accès retiré')} />
                </span>
              </li>
            );
          })}
        </ul>
      </div>
    );
  };

  return (
    <div>
      <header className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-start gap-3.5">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-[#E6EEFB] text-[#2F6BFF]"><Users size={22} /></span>
          <div>
            <h2 className="text-[21px] font-bold leading-tight text-[#0B1C3F]">Équipe &amp; accès</h2>
            <p className="mt-0.5 text-[14px] text-[#475569]">Gérez les personnes qui utilisent FidClic, leurs rôles et leurs permissions.</p>
          </div>
        </div>
        {canCreate && (
          <button type="button" onClick={() => { setTab('users'); setTimeout(() => inviteBox.current?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 50); }}
                  className="inline-flex h-11 items-center gap-2 rounded-xl bg-[#2F6BFF] px-5 text-[14.5px] font-medium text-white shadow-[0_10px_24px_-14px_rgba(47,107,255,.9)] hover:bg-[#2559DB]">
            <UserPlus size={17} /> Inviter un utilisateur
          </button>
        )}
      </header>

      {/* the four roles */}
      <div className="mb-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {d.roles.map((r) => {
          const st = ROLE_STYLE[r.key]; const Icon = st.icon;
          return (
            <div key={r.key} className="flex gap-4 rounded-2xl border border-[#E6EEFB] p-4" style={{ background: st.tint }}>
              <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-white" style={{ color: st.fg }}><Icon size={24} /></span>
              <div>
                <p className="text-[15px] font-bold text-[#0B1C3F]">{r.label}</p>
                <p className="text-[13.5px] text-[#475569]">{r.count} utilisateur{r.count > 1 ? 's' : ''}</p>
                <p className="mt-2 text-[12px] leading-snug text-[#64748B]">{r.description}</p>
              </div>
            </div>
          );
        })}
      </div>

      <nav className="mb-4 flex gap-1 overflow-x-auto border-b border-[#E6EEFB]" role="tablist">
        {TABS.map((t) => {
          const on = tab === t.key; const Icon = t.icon;
          return (
            <button key={t.key} type="button" role="tab" aria-selected={on} onClick={() => setTab(t.key)}
                    className={`inline-flex shrink-0 items-center gap-2 border-b-2 px-4 py-3 text-[13.5px] font-medium transition ${on ? 'border-[#2F6BFF] text-[#2F6BFF]' : 'border-transparent text-[#334155] hover:text-[#0B1C3F]'}`}>
              <Icon size={16} /> {t.label}
              {t.count > 0 && <span className="rounded-md bg-[#EAF1FF] px-1.5 text-[12px] font-semibold text-[#2F6BFF]">{t.count}</span>}
            </button>
          );
        })}
      </nav>

      {tab === 'users' && (
        <section className="rounded-2xl border border-[#E6EEFB] bg-white p-4 sm:p-5">
          {cardHead(UserPlus, 'Liste des utilisateurs', 'Gérez les membres de votre équipe et leurs accès.', (
            <div className="flex flex-wrap items-center gap-2.5">
              <label className="relative">
                <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
                <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Rechercher un utilisateur..."
                       className="h-10 w-[260px] rounded-lg bg-[#F4F7FC] pl-9 pr-3 text-[13px] outline-none placeholder:text-[#94A3B8] focus:ring-2 focus:ring-[#2F6BFF]/20" />
              </label>
              <span className="relative">
                <select value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)}
                        className="h-10 w-[170px] appearance-none rounded-lg border border-[#E2E8F0] bg-white pl-3 pr-8 text-[13px] text-[#0B1C3F] outline-none">
                  <option value="">Tous les rôles</option>
                  {d.roles.map((r) => <option key={r.key} value={r.key}>{r.label}</option>)}
                </select>
                <ChevronDown size={15} className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2" />
              </span>
              <span className="relative">
                <button type="button" onClick={() => setShowStatus((v) => !v)} aria-label="Filtrer par statut"
                        className={`flex h-10 w-10 items-center justify-center rounded-lg border ${statusFilter ? 'border-[#2F6BFF] text-[#2F6BFF]' : 'border-[#E2E8F0] text-[#334155]'} bg-white`}>
                  <SlidersHorizontal size={16} />
                </button>
                {showStatus && (
                  <div className="absolute right-0 z-30 mt-1 w-40 overflow-hidden rounded-xl border border-[#E6EEFB] bg-white py-1 shadow-lg">
                    {[['', 'Tous les statuts'], ['active', 'Actifs'], ['inactive', 'Inactifs']].map(([k, l]) => (
                      <button key={k} type="button" onClick={() => { setStatusFilter(k); setShowStatus(false); }}
                              className={`block w-full px-3.5 py-2 text-left text-[13px] hover:bg-[#F6F9FF] ${statusFilter === k ? 'font-semibold text-[#2F6BFF]' : 'text-[#0B1C3F]'}`}>{l}</button>
                    ))}
                  </div>
                )}
              </span>
            </div>
          ))}
          <div className="overflow-x-auto rounded-xl border border-[#EEF3FB]">
            <table className="w-full min-w-[1080px] text-[13.5px]">
              <thead>
                <tr className="border-b border-[#EEF3FB] text-left text-[13px] font-medium text-[#0B1C3F]">
                  <th className="py-3 pl-4 font-medium">Utilisateur</th><th className="font-medium">Rôle</th>
                  <th className="font-medium">Établissement(s)</th><th className="font-medium">Permissions</th>
                  <th className="font-medium">Statut</th><th className="font-medium">Dernière connexion</th>
                  <th className="pr-4 text-center font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((u) => {
                  const [day, time] = lastLogin(u.last_login_at);
                  return (
                    <tr key={u.id} className="border-b border-[#F1F5F9] last:border-0">
                      <td className="py-2.5 pl-4">
                        <div className="flex items-center gap-3">
                          <Avatar name={u.name} />
                          <div className="min-w-0"><p className="truncate text-[14.5px] font-semibold text-[#0B1C3F]">{u.name}{u.is_me && <span className="ml-1.5 text-[11.5px] font-normal text-[#94A3B8]">(vous)</span>}</p>
                            <p className="truncate text-[12.5px] text-[#64748B]">{u.email}</p></div>
                        </div>
                      </td>
                      <td><RolePill role={u.role} label={u.role_label} /></td>
                      <td className="w-[190px] pr-3">
                        {u.role === 'business_owner' || !u.manageable ? <span className="text-[#0B1C3F]">{u.stores_label || 'Tous'}</span> : (
                          <StorePicker compact role={u.role} stores={d.stores} value={u.branch_ids}
                                       onChange={(ids) => ids.length && run(() => ownerAPI.teamUpdate(u.id, { first_name: u.first_name, last_name: u.last_name, role: u.role, branch_ids: ids }), 'Établissements mis à jour')} />
                        )}
                      </td>
                      <td>
                        <div className="flex flex-wrap items-center gap-1.5">
                          {u.permissions.slice(0, 2).map((p) => <span key={p} className="rounded-md bg-[#EAF1FF] px-2 py-1 text-[12px] text-[#2F6BFF]">{p}</span>)}
                          {u.permissions.length > 2 && <span title={u.permissions.slice(2).join(', ')} className="rounded-md bg-[#F1F5F9] px-2 py-1 text-[12px] text-[#475569]">+{u.permissions.length - 2}</span>}
                        </div>
                      </td>
                      <td>
                        <div className="flex items-center gap-2.5">
                          <Toggle on={u.active} disabled={!u.manageable} label={`Compte de ${u.name}`}
                                  onChange={(v) => run(() => ownerAPI.teamStatus(u.id, v), v ? 'Compte réactivé' : 'Compte désactivé')} />
                          <span className={`rounded-md px-2 py-0.5 text-[12px] font-medium ${u.active ? 'bg-[#E7F7EE] text-[#0F8B58]' : 'bg-[#F1F5F9] text-[#64748B]'}`}>{u.active ? 'Actif' : 'Inactif'}</span>
                        </div>
                      </td>
                      <td className="leading-tight"><p className="text-[#0B1C3F]">{day}</p>{time && <p className="text-[12.5px] text-[#64748B]">{time}</p>}</td>
                      <td className="pr-4">
                        <div className="flex items-center justify-center gap-2">
                          {u.manageable ? (
                            <button type="button" onClick={() => setEditing(u)} aria-label={`Modifier ${u.name}`}
                                    className="flex h-9 w-9 items-center justify-center rounded-lg border border-[#E2E8F0] bg-white text-[#0B1C3F] hover:border-[#2F6BFF] hover:text-[#2F6BFF]"><Pencil size={16} /></button>
                          ) : <span className="inline-block h-9 w-9" />}
                          <RowMenu u={u} onAction={onAction} />
                        </div>
                      </td>
                    </tr>
                  );
                })}
                {!rows.length && <tr><td colSpan={7} className="py-12 text-center text-[13.5px] text-[#64748B]">Aucun utilisateur ne correspond.</td></tr>}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {tab === 'pending' && (
        <section className="rounded-2xl border border-[#E6EEFB] bg-white p-5">
          {cardHead(Hourglass, 'Invitations en attente', "Comptes créés dont la personne ne s'est pas encore connectée.")}
          {!d.pending.length ? (
            <p className="rounded-xl border border-dashed border-[#E6EEFB] py-10 text-center text-[13.5px] text-[#64748B]">Aucune invitation en attente.</p>
          ) : (
            <ul className="divide-y divide-[#EEF3FB]">
              {d.pending.map((u) => (
                <li key={u.id} className="flex flex-wrap items-center gap-4 py-3">
                  <Avatar name={u.name} />
                  <div className="min-w-[180px] flex-1"><p className="font-semibold text-[#0B1C3F]">{u.name}</p><p className="text-[12.5px] text-[#64748B]">{u.email}</p></div>
                  <RolePill role={u.role} label={u.role_label} />
                  <span className="min-w-[140px] text-[13px] text-[#475569]">{u.stores_label}</span>
                  <span className="text-[12.5px] text-[#64748B]">Créé {u.created_at ? `le ${new Date(u.created_at).toLocaleDateString('fr-FR')}` : ''}{u.created_by ? ` par ${u.created_by}` : ''}</span>
                  {u.manageable && (
                    <div className="flex gap-2">
                      <button type="button" onClick={() => onAction('password', u)} className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-[#E2E8F0] px-3 text-[12.5px] font-semibold text-[#0B1C3F] hover:border-[#2F6BFF]"><KeyRound size={14} /> Nouveau mot de passe</button>
                      <button type="button" onClick={() => onAction('delete', u)} className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-[#FECACA] bg-[#FEF2F2] px-3 text-[12.5px] font-semibold text-[#E11D48]"><Trash2 size={14} /> Supprimer</button>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {tab === 'permissions' && (
        <section className="rounded-2xl border border-[#E6EEFB] bg-white p-5">
          {cardHead(ShieldCheck, 'Permissions par rôle', 'Ce que chaque rôle peut faire, et sur quels établissements.')}
          <div className="overflow-x-auto rounded-xl border border-[#EEF3FB]">
            <table className="w-full min-w-[760px] text-[13.5px]">
              <thead><tr className="border-b border-[#EEF3FB]">
                <th className="py-3 pl-4 text-left font-medium text-[#0B1C3F]">Permission</th>
                {d.roles.map((r) => <th key={r.key} className="px-3 py-3"><RolePill role={r.key} label={r.label} /></th>)}
              </tr></thead>
              <tbody>
                {d.permissions.map((p) => (
                  <tr key={p.key} className="border-b border-[#F1F5F9] last:border-0">
                    <td className="py-3 pl-4 text-[#0B1C3F]">{p.full}</td>
                    {d.roles.map((r) => {
                      const v = d.matrix[r.key][p.key];
                      return (
                        <td key={r.key} className="px-3 py-3 text-center">
                          {v ? (
                            <span className="inline-flex items-center gap-1.5 text-[12.5px] font-medium" style={{ color: v === 'all' ? '#2F6BFF' : '#0F8B58' }}>
                              <Check size={15} /> {v === 'all' ? 'Tous les établissements' : r.key === 'administrateur' ? 'Ses établissements' : 'Son établissement'}
                            </span>
                          ) : <X size={15} className="mx-auto text-[#CBD5E1]" />}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <ul className="mt-4 grid gap-2 text-[12.5px] text-[#475569] md:grid-cols-2">
            {d.roles.map((r) => <li key={r.key}><b className="text-[#0B1C3F]">{r.label} :</b> {d.notes[r.key]}</li>)}
          </ul>
        </section>
      )}

      {tab === 'stores' && (
        <section className="rounded-2xl border border-[#E6EEFB] bg-white p-5">
          {cardHead(Building2, 'Accès par établissement', 'Définissez quels utilisateurs peuvent accéder à chaque établissement.')}
          <div className="max-w-2xl"><StoreAccess /></div>
        </section>
      )}

      {/* the three cards of the design, under the list */}
      {tab === 'users' && (
        <div className="mt-4 grid gap-4 xl:grid-cols-3">
          <section ref={inviteBox} className="rounded-2xl border border-[#E6EEFB] bg-white p-5">
            {cardHead(UserPlus, 'Inviter un utilisateur', canCreate ? 'Créez son accès et transmettez-lui ses identifiants.' : "Votre rôle ne permet pas de créer d'accès.")}
            {canCreate && (
              <form onSubmit={create}>
                <div className="mb-3 grid gap-3 sm:grid-cols-2">
                  <label className="block"><span className="mb-1.5 block text-[13px] font-semibold text-[#0B1C3F]">Nom</span>
                    <input value={invite.name} onChange={(e) => setInvite({ ...invite, name: e.target.value })} placeholder="Prénom Nom" className={`${field} h-10`} /></label>
                  <label className="block"><span className="mb-1.5 block text-[13px] font-semibold text-[#0B1C3F]">Adresse email</span>
                    <input type="email" required value={invite.email} onChange={(e) => setInvite({ ...invite, email: e.target.value })} placeholder="exemple@entreprise.fr" className={`${field} h-10`} /></label>
                </div>
                <div className="mb-4 grid gap-3 sm:grid-cols-2">
                  <label className="block"><span className="mb-1.5 block text-[13px] font-semibold text-[#0B1C3F]">Rôle</span>
                    <span className="relative block">
                      <select value={invite.role} onChange={(e) => setInvite({ ...invite, role: e.target.value, branch_ids: e.target.value === 'administrateur' ? invite.branch_ids : invite.branch_ids.slice(0, 1) })}
                              className={`${field} h-10 appearance-none pr-8`}>
                        {d.me.can_create.map((k) => <option key={k} value={k}>{roleLabel[k]}</option>)}
                      </select>
                      <ChevronDown size={15} className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2" />
                    </span></label>
                  <div><span className="mb-1.5 block text-[13px] font-semibold text-[#0B1C3F]">Établissement(s)</span>
                    <StorePicker compact role={invite.role} stores={d.stores} value={invite.branch_ids} onChange={(ids) => setInvite({ ...invite, branch_ids: ids })} /></div>
                </div>
                {inviteError && <p className="mb-3 rounded-lg bg-[#FEF2F2] px-3 py-2 text-[12.5px] text-[#B91C1C]">{inviteError}</p>}
                <button type="submit" disabled={inviting} className="inline-flex h-10 items-center gap-2 rounded-lg bg-[#2F6BFF] px-4 text-[13.5px] font-semibold text-white hover:bg-[#2559DB] disabled:opacity-60">
                  {inviting ? <Loader2 size={15} className="animate-spin" /> : <Send size={15} />} Créer l&apos;accès
                </button>
              </form>
            )}
          </section>
          <section className="rounded-2xl border border-[#E6EEFB] bg-white p-5">
            {cardHead(ShieldCheck, 'Permissions par rôle', 'Consultez les permissions de chaque rôle.', (
              <button type="button" onClick={() => setTab('permissions')} className="text-[12.5px] font-semibold text-[#2F6BFF] hover:underline">Détail</button>
            ))}
            <ul className="space-y-3">
              {d.roles.map((r) => (
                <li key={r.key} className="grid grid-cols-[150px_1fr] items-start gap-3">
                  <span className="inline-flex items-center gap-2 text-[13px] font-semibold" style={{ color: ROLE_STYLE[r.key].fg }}>
                    {React.createElement(ROLE_STYLE[r.key].icon, { size: 15 })} {r.label}
                  </span>
                  <span className="text-[12px] text-[#475569]">{({ business_owner: 'Toutes les permissions', administrateur: 'Tout sur ses établissements, sauf la facturation et la suppression', manager: 'Clients, campagnes et employés de son établissement', staff: 'Scan des cartes clients' })[r.key]}</span>
                </li>
              ))}
            </ul>
          </section>
          <section className="rounded-2xl border border-[#E6EEFB] bg-white p-5">
            {cardHead(Store, 'Accès par établissement', 'Définissez quels utilisateurs peuvent accéder à chaque établissement.')}
            <StoreAccess compact />
          </section>
        </div>
      )}

      <div aria-live="polite" className="pointer-events-none fixed bottom-5 left-1/2 z-40 -translate-x-1/2 transition-opacity" style={{ opacity: toast ? 1 : 0 }}>
        <span className="inline-flex items-center gap-2 rounded-full bg-[#0B1C3F] px-4 py-2 text-[13px] font-medium text-white shadow-lg"><Check size={14} /> {toast}</span>
      </div>
      {creds && <Credentials creds={creds} onClose={() => setCreds(null)} />}
      {editing && <EditModal user={editing} d={d} onClose={() => setEditing(null)} onSaved={(data, msg) => { setD(data); setEditing(null); say(msg); }} />}
      {confirm && (
        <Modal title={confirm.title} onClose={() => setConfirm(null)} width="max-w-[440px]">
          <p className="text-[13.5px] text-[#475569]">{confirm.body}</p>
          <div className="mt-5 flex justify-end gap-2">
            <button type="button" onClick={() => setConfirm(null)} className={btnGhost}>Annuler</button>
            <button type="button" onClick={() => { const go = confirm.go; setConfirm(null); go(); }}
                    className={`inline-flex h-11 items-center rounded-xl px-5 text-[14px] font-semibold text-white ${confirm.danger ? 'bg-[#EF4444] hover:bg-[#DC2626]' : 'bg-[#2F6BFF] hover:bg-[#2559DB]'}`}>{confirm.cta}</button>
          </div>
        </Modal>
      )}
    </div>
  );
}
