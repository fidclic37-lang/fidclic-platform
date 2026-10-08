import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Plus, MoreHorizontal, Home, Store, User, BarChart3, Sparkles, Megaphone, Bell, CreditCard, Shield, BrainCircuit,
  UsersRound, Receipt, LifeBuoy, ShieldCheck, Settings2, Trash2, CheckCircle2, Eye, Pencil, Loader2, Lock, UserPlus, XCircle, ClipboardCheck,
} from 'lucide-react';
import { securityAPI } from '../../../lib/api';
import { useAuth } from '../../../contexts/AuthContext';
import { Card, Loading, Breadcrumb, Modal, Select, useToast, BLUE, inputCls } from '../../crm/ui';
import { TONES, RoleIcon, ROLE_ICONS, UserModal, PasswordOnce, SecuTabs } from './shared';

/* Super admin › Sécurité › Rôles & Permissions — built to the approved
   mockup, with two switches per section (decided with the user): Voir and
   Modifier. Only the super admin changes them; the server applies them. */

const MOD_ICON = { dashboard: Home, commerces: Store, clients: User, analytics: BarChart3, insights: Sparkles, campagnes: Megaphone,
  notifications: Bell, abonnements: CreditCard, plan_limits: Shield, ai: BrainCircuit, crm: UsersRound,
  facturation: Receipt, support: LifeBuoy, securite: ShieldCheck, parametres: Settings2, equipe: ClipboardCheck };

function Switch({ on, onChange, disabled, label, title }) {
  return (
    <button type="button" role="switch" aria-checked={on} aria-label={label} title={title} disabled={disabled} onClick={() => onChange(!on)}
            className={`relative h-6 w-11 shrink-0 rounded-full transition ${on ? 'bg-[#10B981]' : 'bg-[#E2E8F0]'} ${disabled ? 'cursor-not-allowed opacity-50' : ''}`}>
      <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition ${on ? 'left-[22px]' : 'left-0.5'}`} />
    </button>
  );
}

export default function RolesPage() {
  const { user } = useAuth();
  const boss = user?.role === 'super_admin';
  const [d, setD] = useState(null);
  const [users, setUsers] = useState([]);
  const [sel, setSel] = useState('super_admin');
  const [tab, setTab] = useState('role');
  const [module, setModule] = useState('');
  const [draft, setDraft] = useState(null);
  const [saving, setSaving] = useState(false);
  const [modal, setModal] = useState(null);
  const [menu, setMenu] = useState(null);
  const [err, setErr] = useState('');
  const [say, toast] = useToast();

  const load = useCallback(() => {
    securityAPI.roles().then(({ data }) => setD(data)).catch((e) => setErr(e?.response?.data?.detail || 'Impossible de charger les rôles.'));
    securityAPI.users().then(({ data }) => setUsers(data.rows)).catch(() => {});
  }, []);
  useEffect(() => { load(); }, [load]);
  const role = d?.roles.find((r) => r.id === sel) || d?.roles[0];
  useEffect(() => { setDraft(role ? JSON.parse(JSON.stringify(role.perms)) : null); }, [role?.id, d]); // eslint-disable-line react-hooks/exhaustive-deps
  const dirty = useMemo(() => role && draft && JSON.stringify(draft) !== JSON.stringify(role.perms), [role, draft]);
  const act = async (fn, m) => { try { const r = await fn(); if (m) say(m); load(); return r; } catch (e) { say(e?.response?.data?.detail || 'Action impossible.'); return null; } };

  if (!d) return err ? <p className="rounded-xl bg-[#FEF2F2] px-4 py-3 text-[13.5px] text-[#B91C1C]">{err}</p> : <Loading />;
  const modules = d.modules.filter((m) => !module || m.key === module);
  const setPerm = (k, level, v) => {
    const cur = draft[k] || { view: false, edit: false };
    const next = level === 'edit' ? { view: v ? true : cur.view, edit: v } : { view: v, edit: v ? cur.edit : false };   // Modifier needs Voir
    setDraft({ ...draft, [k]: next });
  };
  const save = async () => {
    setSaving(true);
    await act(() => securityAPI.editRole(role.id, { perms: draft }), `Permissions de « ${role.name} » enregistrées — elles s'appliquent tout de suite.`);
    setSaving(false);
  };
  const [bg, fg] = TONES[role.tone] || TONES.blue;
  const included = d.modules.filter((m) => role.perms[m.key]?.view);

  return (
    <div className="crm" onClick={() => setMenu(null)}>
      <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <Breadcrumb items={[['Super Admin', '/admin'], ['Admin', '/admin/securite'], ['Rôles & Permissions']]} />
          <h1 className="text-[28px] font-bold leading-tight text-[#0B1C3F]">Rôles & Permissions</h1>
          <p className="text-[15px] text-[#475569]">Définissez les rôles et contrôlez les accès aux différentes fonctionnalités de la plateforme.</p>
        </div>
        {boss && <button type="button" onClick={() => setModal({ type: 'role' })} className="inline-flex h-11 items-center gap-2 rounded-xl px-5 text-[14px] font-medium text-white" style={{ background: BLUE }}><Plus size={17} /> Ajouter un rôle</button>}
      </header>
      <Card className="mb-4 p-0" onClick={(e) => e.stopPropagation()}><SecuTabs /></Card>

      <div className="flex gap-3 overflow-x-auto pb-1">
        {d.roles.map((r) => { const [b, f] = TONES[r.tone] || TONES.blue; const on = r.id === role.id; return (
          <button key={r.id} type="button" onClick={() => setSel(r.id)} className={`relative w-[230px] shrink-0 rounded-2xl border bg-white p-4 text-left transition ${on ? 'border-[#2F6BFF] shadow-[0_0_0_3px_rgba(47,107,255,.12)]' : 'border-[#EDF1F7] hover:border-[#BFD3FF]'}`}>
            <span className="flex items-start gap-3">
              <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl" style={{ background: b, color: f }}><RoleIcon icon={r.icon} size={20} /></span>
              <span className="min-w-0 flex-1"><span className="block truncate text-[15px] font-bold text-[#0B1C3F]">{r.name}</span><span className="text-[12.5px] text-[#64748B]">{r.users} utilisateur{r.users > 1 ? 's' : ''}</span></span>
            </span>
            <span className="mt-2 line-clamp-2 block text-[12px] text-[#64748B]">{r.description || 'Rôle personnalisé.'}</span>
          </button>); })}
      </div>

      <div className="mt-4 grid items-start gap-4 xl:grid-cols-[1fr_380px]">
        <Card className="min-w-0 p-0">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#EDF1F7] px-3">
            <nav className="flex gap-1">
              {[['role', 'Permissions par rôle'], ['compare', 'Comparaison des rôles']].map(([k, l]) => (
                <button key={k} type="button" onClick={() => setTab(k)} className={`border-b-2 px-3 py-3 text-[14px] ${tab === k ? 'border-[#2F6BFF] font-medium text-[#2F6BFF]' : 'border-transparent text-[#0B1C3F]'}`}>{l}</button>
              ))}
            </nav>
            <Select value={module} onChange={setModule} className="my-2 w-44"><option value="">Tous les modules</option>{d.modules.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}</Select>
          </div>

          {tab === 'role' ? (
            <div className="p-3">
              <div className="mb-2 flex flex-wrap items-center gap-2 rounded-xl px-3 py-2" style={{ background: bg }}>
                <span style={{ color: fg }}><RoleIcon icon={role.icon} size={18} /></span>
                <span className="font-semibold text-[#0B1C3F]">{role.name}</span>
                {role.locked && <span className="flex items-center gap-1 text-[12px] text-[#64748B]"><Lock size={12} /> Accès complet, non modifiable</span>}
                {!boss && <span className="text-[12px] text-[#64748B]">Seul le Super Admin peut modifier les permissions.</span>}
              </div>
              <table className="w-full text-[13.5px]">
                <thead><tr className="border-b border-[#EDF1F7] text-left text-[#64748B]"><th className="px-2 py-2 font-medium">Fonctionnalités</th><th className="w-28 px-2 py-2 text-center font-medium">Voir</th><th className="w-28 px-2 py-2 text-center font-medium">Modifier</th></tr></thead>
                <tbody>
                  {modules.map((m) => { const I = MOD_ICON[m.key] || Shield; const p = draft?.[m.key] || { view: false, edit: false }; const lock = !boss || role.locked; return (
                    <tr key={m.key} className="border-b border-[#F4F7FC]">
                      <td className="px-2 py-2.5"><span className="flex items-center gap-2.5 text-[#0B1C3F]"><I size={16} className="text-[#64748B]" /> {m.label}</span></td>
                      <td className="px-2 py-2.5"><span className="flex justify-center"><Switch on={p.view} disabled={lock} label={`${m.label} — voir`} onChange={(v) => setPerm(m.key, 'view', v)} /></span></td>
                      <td className="px-2 py-2.5"><span className="flex justify-center"><Switch on={p.edit} disabled={lock || m.super_only_edit} label={`${m.label} — modifier`} title={m.super_only_edit ? 'Gérer les utilisateurs, les rôles et la sécurité reste réservé au Super Admin.' : undefined} onChange={(v) => setPerm(m.key, 'edit', v)} /></span></td>
                    </tr>); })}
                </tbody>
              </table>
              <p className="mt-2 text-[11.5px] text-[#94A3B8]">« Modifier » inclut « Voir ». Admin : modifier les utilisateurs, les rôles et les paramètres reste réservé au Super Admin, pour que personne ne puisse s'accorder plus d'accès.</p>
              {dirty && (
                <div className="sticky bottom-3 mt-3 flex items-center justify-end gap-2 rounded-xl border border-[#BFD3FF] bg-white/95 p-2 shadow-lg">
                  <span className="mr-auto pl-2 text-[12.5px] text-[#475569]">Modifications non enregistrées</span>
                  <button type="button" onClick={() => setDraft(JSON.parse(JSON.stringify(role.perms)))} className="rounded-lg border border-[#DCE3EE] px-3 py-2 text-[13px]">Annuler</button>
                  <button type="button" disabled={saving} onClick={save} className="inline-flex items-center gap-2 rounded-lg px-4 py-2 text-[13px] font-semibold text-white" style={{ background: BLUE }}>{saving && <Loader2 size={14} className="animate-spin" />} Enregistrer</button>
                </div>
              )}
            </div>
          ) : (
            <div className="overflow-x-auto p-3">
              <table className="w-full min-w-[760px] text-[13px]">
                <thead>
                  <tr><th className="px-2 py-2 text-left font-semibold text-[#0B1C3F]">Fonctionnalités</th>
                    {d.roles.map((r) => { const [b, f] = TONES[r.tone] || TONES.blue; return (
                      <th key={r.id} className="px-1 py-2"><button type="button" onClick={() => { setSel(r.id); setTab('role'); }} className="flex w-full flex-col items-center gap-1 rounded-xl py-2 text-[12px] font-medium" style={{ background: b, color: f }}><RoleIcon icon={r.icon} size={16} />{r.name}</button></th>); })}
                  </tr>
                </thead>
                <tbody>
                  {modules.map((m) => { const I = MOD_ICON[m.key] || Shield; return (
                    <tr key={m.key} className="border-b border-[#F4F7FC]">
                      <td className="whitespace-nowrap px-2 py-2.5"><span className="flex items-center gap-2 text-[#0B1C3F]"><I size={15} className="text-[#64748B]" /> {m.label}</span></td>
                      {d.roles.map((r) => { const p = r.perms[m.key]; return (
                        <td key={r.id} className="px-1 py-2.5 text-center">
                          <span className="inline-flex gap-1">
                            <span title="Voir" className={`grid h-6 w-6 place-items-center rounded-md ${p.view ? 'bg-[#E7F7EE] text-[#0F8B58]' : 'bg-[#F1F5F9] text-[#CBD5E1]'}`}><Eye size={13} /></span>
                            <span title="Modifier" className={`grid h-6 w-6 place-items-center rounded-md ${p.edit ? 'bg-[#E7F7EE] text-[#0F8B58]' : 'bg-[#F1F5F9] text-[#CBD5E1]'}`}><Pencil size={13} /></span>
                          </span>
                        </td>); })}
                    </tr>); })}
                </tbody>
              </table>
              <p className="mt-2 flex gap-4 text-[11.5px] text-[#64748B]"><span className="flex items-center gap-1"><Eye size={12} /> Voir</span><span className="flex items-center gap-1"><Pencil size={12} /> Modifier</span></p>
            </div>
          )}
        </Card>

        <div className="space-y-4">
          <Card>
            <div className="mb-3 flex items-center justify-between"><h2 className="text-[16px] font-bold text-[#0B1C3F]">Détails du rôle</h2>
              {boss && !role.locked && (
                <span className="relative" onClick={(e) => e.stopPropagation()}>
                  <button type="button" aria-label="Plus d'actions" onClick={() => setMenu(menu === 'role' ? null : 'role')} className="rounded p-1 hover:bg-[#F4F7FC]"><MoreHorizontal size={16} /></button>
                  {menu === 'role' && <span className="absolute right-0 top-full z-20 flex w-44 flex-col overflow-hidden rounded-xl border border-[#E6EEFB] bg-white py-1 text-[13px] shadow-lg">
                    <button type="button" onClick={() => { setMenu(null); setModal({ type: 'role', role }); }} className="flex items-center gap-2 px-3 py-2 text-left hover:bg-[#F4F7FC]"><Pencil size={14} /> Renommer / décrire</button>
                  </span>}
                </span>
              )}
            </div>
            <div className="flex items-start gap-3">
              <span className="grid h-14 w-14 shrink-0 place-items-center rounded-2xl" style={{ background: bg, color: fg }}><RoleIcon icon={role.icon} size={26} /></span>
              <div><p className="text-[18px] font-bold text-[#0B1C3F]">{role.name}</p><p className="text-[13px] text-[#64748B]">{role.description || 'Rôle personnalisé.'}</p></div>
            </div>
            <p className="mt-3 flex justify-between rounded-xl border border-[#EDF1F7] px-3 py-2 text-[13px] text-[#475569]">Nombre d'utilisateurs <strong className="text-[#0B1C3F]">{role.users}</strong></p>
            <p className="mb-2 mt-4 text-[13.5px] font-semibold text-[#0B1C3F]">Permissions incluses</p>
            <ul className="space-y-1.5 text-[13px]">
              {included.map((m) => <li key={m.key} className="flex items-center gap-2 text-[#334155]"><CheckCircle2 size={16} className="text-white" fill="#10B981" />{m.label}<span className="ml-auto text-[11.5px] text-[#94A3B8]">{role.perms[m.key].edit ? 'voir + modifier' : 'voir'}</span></li>)}
              {!included.length && <li className="flex items-center gap-2 text-[#94A3B8]"><XCircle size={15} /> Aucun accès pour l'instant.</li>}
            </ul>
          </Card>

          <Card>
            <div className="mb-2 flex items-center justify-between"><h3 className="text-[14.5px] font-bold text-[#0B1C3F]">Utilisateurs avec ce rôle <span className="font-normal text-[#94A3B8]">({role.users})</span></h3>
              {boss && <button type="button" onClick={() => setModal({ type: 'assign' })} className="rounded-lg border border-[#DCE3EE] px-2.5 py-1 text-[12px] text-[#2F6BFF]">Assigner des utilisateurs</button>}</div>
            <table className="w-full text-[12.5px]">
              <thead><tr className="text-left text-[#64748B]"><th className="py-1.5 font-medium">Nom</th><th className="font-medium">Email</th><th className="font-medium">Statut</th></tr></thead>
              <tbody>{role.members.map((u) => (
                <tr key={u.email} className="border-t border-[#F4F7FC]"><td className="py-2 font-medium text-[#0B1C3F]">{u.name}</td><td className="max-w-[140px] truncate text-[#475569]">{u.email}</td>
                  <td><span className={`flex items-center gap-1.5 ${u.active ? 'text-[#0F8B58]' : 'text-[#94A3B8]'}`}><i className={`h-2 w-2 rounded-full ${u.active ? 'bg-[#10B981]' : 'bg-[#CBD5E1]'}`} />{u.active ? 'Actif' : 'Désactivé'}</span></td></tr>))}
                {!role.members.length && <tr><td colSpan={3} className="py-4 text-center text-[#94A3B8]">Personne pour l'instant.</td></tr>}
              </tbody>
            </table>
            {boss && <button type="button" onClick={() => setModal({ type: 'user' })} className="mt-3 inline-flex items-center gap-1.5 text-[12.5px] text-[#2F6BFF]"><UserPlus size={14} /> Créer un utilisateur avec ce rôle</button>}
          </Card>

          {boss && !role.system && (
            <Card>
              <p className="flex items-center justify-between gap-2"><span className="flex items-center gap-2 text-[13.5px] font-semibold text-[#E11D48]"><Trash2 size={16} /> Supprimer ce rôle</span>
                <button type="button" disabled={role.users > 0} onClick={() => { if (window.confirm(`Supprimer le rôle « ${role.name} » ?`)) act(() => securityAPI.deleteRole(role.id), 'Rôle supprimé.').then(() => setSel('super_admin')); }}
                        className="rounded-lg border border-[#FCA5A5] px-3 py-1.5 text-[12.5px] text-[#E11D48] disabled:opacity-40">Supprimer</button></p>
              <p className="mt-1 text-[12px] text-[#64748B]">{role.users > 0 ? 'Réassignez d\'abord ses utilisateurs à un autre rôle.' : 'Cette action ne peut pas être annulée.'}</p>
            </Card>
          )}
        </div>
      </div>

      {toast}
      {modal?.type === 'role' && <RoleModal role={modal.role} roles={d.roles} onClose={() => setModal(null)} onDone={(r, m) => { setModal(null); say(m); load(); if (r?.id) setSel(r.id); }} />}
      {modal?.type === 'assign' && <AssignModal role={role} users={users} onClose={() => setModal(null)} onDone={(m) => { setModal(null); say(m); load(); }} />}
      {modal?.type === 'user' && <UserModal roles={d.roles} user={null} onClose={() => setModal(null)} onDone={(created) => { load(); if (created) setModal({ type: 'pw', data: created }); }} />}
      {modal?.type === 'pw' && <PasswordOnce email={modal.data.email} password={modal.data.password} onClose={() => setModal(null)} />}
    </div>
  );
}

function RoleModal({ role, roles, onClose, onDone }) {
  const [f, setF] = useState({ name: role?.name || '', description: role?.description || '', icon: role?.icon || 'shield', tone: role?.tone || 'blue', from: '' });
  const [err, setErr] = useState('');
  const save = async () => {
    setErr('');
    try {
      if (role) { await securityAPI.editRole(role.id, { name: f.name, description: f.description, icon: f.icon, tone: f.tone }); onDone(role, 'Rôle modifié.'); }
      else {
        const perms = f.from ? roles.find((r) => r.id === f.from)?.perms : {};
        const { data } = await securityAPI.addRole({ name: f.name, description: f.description, icon: f.icon, tone: f.tone, perms });
        onDone(data, `Rôle « ${data.name} » créé : choisissez maintenant ses accès.`);
      }
    } catch (e) { setErr(e?.response?.data?.detail || 'Enregistrement impossible.'); }
  };
  return (
    <Modal title={role ? `Modifier — ${role.name}` : 'Ajouter un rôle'} onClose={onClose}>
      <div className="space-y-2">
        <label className="block"><span className="mb-1 block text-[11.5px] text-[#64748B]">Nom du rôle</span><input className={inputCls} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="Ex. Stagiaire CRM" /></label>
        <label className="block"><span className="mb-1 block text-[11.5px] text-[#64748B]">Description</span><input className={inputCls} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} placeholder="Ex. Suit les prospects, sans rien supprimer." /></label>
        <div><span className="mb-1 block text-[11.5px] text-[#64748B]">Icône et couleur</span>
          <div className="flex flex-wrap gap-1.5">{Object.keys(ROLE_ICONS).map((k) => <button key={k} type="button" onClick={() => setF({ ...f, icon: k })} className={`grid h-9 w-9 place-items-center rounded-lg border ${f.icon === k ? 'border-[#2F6BFF] bg-[#EAF1FF] text-[#2F6BFF]' : 'border-[#DCE3EE] text-[#64748B]'}`}><RoleIcon icon={k} /></button>)}</div>
          <div className="mt-2 flex gap-1.5">{Object.entries(TONES).map(([k, [b, c]]) => <button key={k} type="button" aria-label={k} onClick={() => setF({ ...f, tone: k })} className={`h-7 w-7 rounded-full border-2 ${f.tone === k ? 'border-[#0B1C3F]' : 'border-transparent'}`} style={{ background: c }} />)}</div>
        </div>
        {!role && <Select label="Partir des accès de (facultatif)" value={f.from} onChange={(v) => setF({ ...f, from: v })}><option value="">Aucun accès au départ</option>{roles.filter((r) => r.id !== 'super_admin').map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}</Select>}
      </div>
      {err && <p className="mt-2 text-[13px] text-[#C0392B]">{err}</p>}
      <button type="button" disabled={!f.name.trim()} onClick={save} className="mt-4 w-full rounded-lg py-2.5 text-[13.5px] font-semibold text-white disabled:opacity-50" style={{ background: BLUE }}>{role ? 'Enregistrer' : 'Créer le rôle'}</button>
    </Modal>
  );
}

function AssignModal({ role, users, onClose, onDone }) {
  const [picked, setPicked] = useState([]);
  const [err, setErr] = useState('');
  const candidates = users.filter((u) => u.role_id !== role.id);
  const go = async () => {
    try { const { data } = await securityAPI.assignRole(role.id, picked); onDone(`${data.assigned} utilisateur(s) passé(s) au rôle « ${role.name} ».`); }
    catch (e) { setErr(e?.response?.data?.detail || 'Assignation impossible.'); }
  };
  return (
    <Modal title={`Assigner au rôle « ${role.name} »`} onClose={onClose}>
      <ul className="max-h-[50vh] divide-y divide-[#F1F5F9] overflow-y-auto">
        {candidates.map((u) => (
          <li key={u.email}><label className="flex cursor-pointer items-center gap-3 py-2 text-[13px]">
            <input type="checkbox" className="accent-[#2F6BFF]" checked={picked.includes(u.email)} onChange={(e) => setPicked(e.target.checked ? [...picked, u.email] : picked.filter((x) => x !== u.email))} />
            <span className="flex-1"><span className="block font-medium text-[#0B1C3F]">{u.name}</span><span className="text-[12px] text-[#64748B]">{u.email} · actuellement {u.role_name}</span></span>
          </label></li>
        ))}
        {!candidates.length && <li className="py-6 text-center text-[13px] text-[#94A3B8]">Tout le monde a déjà ce rôle.</li>}
      </ul>
      <p className="mt-2 text-[12px] text-[#64748B]">Le nouveau rôle s'applique tout de suite ; leurs sessions ouvertes se ferment.</p>
      {err && <p className="mt-2 text-[13px] text-[#C0392B]">{err}</p>}
      <button type="button" disabled={!picked.length} onClick={go} className="mt-3 w-full rounded-lg py-2.5 text-[13.5px] font-semibold text-white disabled:opacity-50" style={{ background: BLUE }}>Assigner {picked.length || ''}</button>
    </Modal>
  );
}
