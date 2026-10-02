import React, { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { Users, ShieldCheck, Globe2, AlertTriangle, ShieldAlert, Plus, MoreHorizontal, Search, KeyRound, UserX, UserCheck, Unlock, Pencil } from 'lucide-react';
import { securityAPI } from '../../../lib/api';
import { useAuth } from '../../../contexts/AuthContext';
import { Card, Head, Kpi, Donut, Loading, Breadcrumb, Avatar, Select, useToast, nf, BLUE, inputCls } from '../../crm/ui';
import { RangePicker, useRange, SecuTabs, RoleBadge, flag, LOGIN_TONE, JOURNAL_TONE, Pill, when, UserModal, PasswordOnce } from './shared';

/* Super admin › Sécurité — built to the approved mockup. */

export default function SecuriteOverviewPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const boss = user?.role === 'super_admin';
  const [range, setRange] = useRange();
  const [d, setD] = useState(null);
  const [users, setUsers] = useState(null);
  const [roles, setRoles] = useState([]);
  const [err, setErr] = useState('');
  const [menu, setMenu] = useState(null);
  const [modal, setModal] = useState(null);
  const [jf, setJf] = useState({ q: '', user: '', category: '', status: '' });
  const [journal, setJournal] = useState([]);
  const [say, toast] = useToast();

  const load = useCallback(() => {
    securityAPI.overview(range).then(({ data }) => { setD(data); setErr(''); }).catch((e) => setErr(e?.response?.data?.detail || 'Impossible de charger la page.'));
    securityAPI.users().then(({ data }) => setUsers(data.rows)).catch(() => setUsers([]));
    securityAPI.roles().then(({ data }) => setRoles(data.roles)).catch(() => {});
  }, [range]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    securityAPI.journal({ ...range, ...jf, per_page: 5 }).then(({ data }) => setJournal(data.rows)).catch(() => setJournal([]));
  }, [range, jf]);
  const act = async (fn, m) => { try { const r = await fn(); if (m) say(m); load(); return r; } catch (e) { say(e?.response?.data?.detail || 'Action impossible.'); return null; } };

  if (!d || !users) return err ? <p className="rounded-xl bg-[#FEF2F2] px-4 py-3 text-[13.5px] text-[#B91C1C]">{err}</p> : <Loading />;
  const K = Object.fromEntries(d.cards.map((c) => [c.key, c]));
  const maxOrigin = Math.max(1, ...d.origins.map((o) => o.count));
  const people = Object.fromEntries(users.map((u) => [u.email, u.name]));

  return (
    <div className="crm" onClick={() => setMenu(null)}>
      <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <Breadcrumb items={[['Super Admin', '/admin'], ['Admin']]} />
          <h1 className="text-[28px] font-bold leading-tight text-[#0B1C3F]">Admin</h1>
          <p className="text-[15px] text-[#475569]">Gérez les utilisateurs, les rôles, les permissions et suivez toutes les activités sensibles.</p>
        </div>
        <RangePicker value={range} onChange={setRange} />
      </header>

      {/* The tabs sit right under the title, as on the other Admin pages. */}
      <Card className="mb-4 p-0" onClick={(e) => e.stopPropagation()}>
        <SecuTabs right={boss && <button type="button" onClick={() => setModal({ type: 'user' })} className="my-2 inline-flex h-10 items-center gap-2 rounded-xl px-4 text-[13.5px] font-medium text-white" style={{ background: BLUE }}><Plus size={16} /> Ajouter un utilisateur</button>} />
      </Card>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-5">
        <Kpi icon={Users} tone="#2F6BFF" bg="#EAF1FF" value={nf(K.users.value)} label="Utilisateurs de l'équipe" delta={K.users.delta} series={K.users.series} />
        <Kpi icon={ShieldCheck} tone="#10B981" bg="#E7F7EE" value={nf(K.actions.value)} label="Actions enregistrées" delta={K.actions.delta} series={K.actions.series} />
        <Kpi icon={Globe2} tone="#8B5CF6" bg="#F3EEFF" value={nf(K.logins.value)} label="Connexions" delta={K.logins.delta} series={K.logins.series} />
        <Kpi icon={AlertTriangle} tone="#F59E0B" bg="#FFF4DB" value={nf(K.suspicious.value)} label="Connexions suspectes" delta={K.suspicious.delta} series={K.suspicious.series} />
        <Kpi icon={ShieldAlert} tone="#E11D48" bg="#FDECEF" value={nf(K.failed.value)} label="Tentatives échouées" delta={K.failed.delta} series={K.failed.series} />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[1fr_1.35fr_1fr]">
        <Card><Head icon={ShieldCheck} title="Répartition des actions" /><Donut rows={d.actions_split} center={nf(d.actions_total)} sub="actions" /></Card>
        <Card>
          <Head icon={ShieldCheck} title="Activité des connexions" />
          <div className="mb-1 flex justify-center gap-4 text-[12px] text-[#475569]">
            <span className="flex items-center gap-1.5"><i className="h-2 w-2 rounded-full bg-[#2F6BFF]" />Connexions</span>
            <span className="flex items-center gap-1.5"><i className="h-2 w-2 rounded-full bg-[#E11D48]" />Connexions suspectes</span>
          </div>
          <div className="h-[200px]">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={d.logins_by_day.map((x) => ({ ...x, j: new Date(`${x.day}T12:00:00`).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' }) }))} margin={{ top: 8, right: 8, left: -24, bottom: 0 }}>
                <CartesianGrid stroke="#EEF2F7" vertical={false} />
                <XAxis dataKey="j" tick={{ fontSize: 11, fill: '#64748B' }} axisLine={false} tickLine={false} minTickGap={24} />
                <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: '#64748B' }} axisLine={false} tickLine={false} />
                <Tooltip formatter={(v, k) => [v, k === 'logins' ? 'Connexions' : 'Connexions suspectes']} />
                <Line type="monotone" dataKey="logins" stroke="#2F6BFF" strokeWidth={2} dot={{ r: 2.5 }} />
                <Line type="monotone" dataKey="suspicious" stroke="#E11D48" strokeWidth={2} dot={{ r: 2.5 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <Card>
          <Head icon={Globe2} title="Origine des connexions" />
          <ul className="space-y-4">
            {d.origins.map((o) => (
              <li key={o.label} className="grid grid-cols-[110px_1fr_76px] items-center gap-3 text-[13px]">
                <span className="flex items-center gap-2 text-[#334155]"><span className="text-[18px] leading-none">{o.cc ? flag(o.cc) : '🌐'}</span>{o.label}</span>
                <span className="h-3 overflow-hidden rounded-full bg-[#EEF2F8]"><span className="block h-full rounded-full bg-[#2F6BFF]" style={{ width: `${(o.count / maxOrigin) * 100}%` }} /></span>
                <span className="text-right text-[#475569]">{nf(o.count)} ({o.pct}%)</span>
              </li>
            ))}
            {!d.origins.length && <li className="py-6 text-center text-[12.5px] text-[#94A3B8]">Aucune connexion sur la période.</li>}
          </ul>
          <p className="mt-3 text-[11px] text-[#94A3B8]">Pays et ville donnés par l'hébergeur (Vercel) à chaque connexion.</p>
        </Card>
      </div>

      <div className="mt-4 grid items-start gap-4 xl:grid-cols-[1fr_390px]">
        <Card className="min-w-0">
          <Head icon={Users} title="Utilisateurs de l'équipe" sub={`${nf(users.length)} compte${users.length > 1 ? 's' : ''} FidClic`} />
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-[13px]">
              <thead><tr className="border-b border-[#EDF1F7] text-left text-[#64748B]">{['Nom', 'Email', 'Rôle', 'Statut', 'Dernière connexion', boss ? 'Actions' : ''].map((h) => <th key={h} className="px-2 py-2 font-medium">{h}</th>)}</tr></thead>
              <tbody>
                {users.map((u) => { const locked = u.locked_until && new Date(u.locked_until) > new Date(); return (
                  <tr key={u.email} className="border-b border-[#F4F7FC]">
                    <td className="px-2 py-2.5"><Avatar name={u.name} size={28} /></td>
                    <td className="px-2 py-2.5 text-[#475569]">{u.email}</td>
                    <td className="px-2 py-2.5"><RoleBadge name={u.role_name} tone={u.role_tone} icon={u.role_icon} /></td>
                    <td className="px-2 py-2.5">
                      {!u.active ? <span className="text-[12.5px] text-[#94A3B8]">Désactivé</span>
                        : locked ? <span className="flex items-center gap-1.5 text-[12.5px] text-[#E11D48]"><i className="h-2 w-2 rounded-full bg-[#E11D48]" />Bloqué</span>
                          : <span className={`flex items-center gap-1.5 text-[12.5px] ${u.online ? 'text-[#0F8B58]' : 'text-[#64748B]'}`}><i className={`h-2 w-2 rounded-full ${u.online ? 'bg-[#10B981]' : 'bg-[#94A3B8]'}`} />{u.online ? 'En ligne' : 'Hors ligne'}</span>}
                    </td>
                    <td className="whitespace-nowrap px-2 py-2.5 text-[#475569]">{u.last_login ? when(u.last_login) : 'Jamais'}</td>
                    <td className="relative px-2 py-2.5" onClick={(e) => e.stopPropagation()}>
                      {boss && (
                        <>
                          <button type="button" aria-label="Actions" onClick={() => setMenu(menu === u.email ? null : u.email)} className="rounded p-1 hover:bg-[#F4F7FC]"><MoreHorizontal size={16} /></button>
                          {menu === u.email && (
                            <span className="absolute right-2 top-full z-20 flex w-60 flex-col overflow-hidden rounded-xl border border-[#E6EEFB] bg-white py-1 shadow-lg">
                              <button type="button" onClick={() => { setMenu(null); setModal({ type: 'user', u }); }} className="flex items-center gap-2 px-3 py-2 text-left hover:bg-[#F4F7FC]"><Pencil size={14} /> Modifier / changer de rôle</button>
                              <button type="button" onClick={async () => { setMenu(null); if (!window.confirm(`Réinitialiser le mot de passe de ${u.name} ? Ses sessions seront fermées.`)) return; const r = await act(() => securityAPI.resetPassword(u.email)); if (r) setModal({ type: 'pw', data: r.data, title: 'Nouveau mot de passe' }); }} className="flex items-center gap-2 px-3 py-2 text-left hover:bg-[#F4F7FC]"><KeyRound size={14} /> Réinitialiser le mot de passe</button>
                              {locked && <button type="button" onClick={() => { setMenu(null); act(() => securityAPI.unlock(u.email), 'Compte débloqué.'); }} className="flex items-center gap-2 px-3 py-2 text-left hover:bg-[#F4F7FC]"><Unlock size={14} /> Débloquer</button>}
                              {u.email !== user?.email && (u.active
                                ? <button type="button" onClick={() => { setMenu(null); if (window.confirm(`Désactiver ${u.name} ? Ses sessions seront fermées tout de suite.`)) act(() => securityAPI.editUser(u.email, { active: false }), 'Utilisateur désactivé.'); }} className="flex items-center gap-2 px-3 py-2 text-left text-[#E11D48] hover:bg-[#FEF2F2]"><UserX size={14} /> Désactiver</button>
                                : <button type="button" onClick={() => { setMenu(null); act(() => securityAPI.editUser(u.email, { active: true }), 'Utilisateur réactivé.'); }} className="flex items-center gap-2 px-3 py-2 text-left text-[#0F8B58] hover:bg-[#F0FDF4]"><UserCheck size={14} /> Réactiver</button>)}
                            </span>
                          )}
                        </>
                      )}
                    </td>
                  </tr>); })}
              </tbody>
            </table>
          </div>
        </Card>

        <Card>
          <Head icon={ShieldCheck} title="Connexions récentes" right={<Link to="/admin/securite/connexions" className="rounded-lg border border-[#DCE3EE] px-2.5 py-1 text-[12px] text-[#2F6BFF]">Voir tout</Link>} />
          <ul className="divide-y divide-[#F1F5F9]">
            {d.recent_logins.map((l) => (
              <li key={l.id} className="flex items-center gap-3 py-2.5 text-[13px]">
                {l.suspicious || l.status === 'Bloquée' ? <AlertTriangle size={20} className="shrink-0 text-[#E11D48]" /> : <span className="text-[20px] leading-none">{flag(l.cc)}</span>}
                <span className="min-w-0 flex-1">
                  <span className={`block truncate font-medium ${l.suspicious || l.status === 'Bloquée' ? 'text-[#E11D48]' : 'text-[#0B1C3F]'}`}>{l.suspicious || l.status === 'Bloquée' ? 'Connexion suspecte' : l.user}</span>
                  <span className="block truncate text-[12px] text-[#64748B]">{l.suspicious || l.status === 'Bloquée' ? `${l.user} · ` : ''}{[l.city, l.country].filter(Boolean).join(', ')}</span>
                </span>
                <span className="shrink-0 text-[12px] text-[#475569]">{when(l.at)}</span>
                <Pill tone={LOGIN_TONE[l.status]}>{l.status}</Pill>
              </li>
            ))}
            {!d.recent_logins.length && <li className="py-6 text-center text-[12.5px] text-[#94A3B8]">Aucune connexion enregistrée pour l'instant.</li>}
          </ul>
        </Card>
      </div>

      <Card className="mt-4">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <h2 className="mr-auto flex items-center gap-2 text-[15px] font-bold text-[#0B1C3F]"><ShieldCheck size={17} className="text-[#2F6BFF]" /> Journal d'activité récent</h2>
          <label className="relative w-full sm:w-56"><Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8]" /><input className={`${inputCls} h-9 pl-8`} placeholder="Rechercher une action…" value={jf.q} onChange={(e) => setJf({ ...jf, q: e.target.value })} /></label>
          <Select value={jf.user} onChange={(v) => setJf({ ...jf, user: v })} className="w-44"><option value="">Tous les utilisateurs</option>{users.map((u) => <option key={u.email} value={u.email}>{u.name}</option>)}</Select>
          <Select value={jf.category} onChange={(v) => setJf({ ...jf, category: v })} className="w-44"><option value="">Toutes les actions</option>{(d.categories || []).map((c) => <option key={c}>{c}</option>)}</Select>
          <Select value={jf.status} onChange={(v) => setJf({ ...jf, status: v })} className="w-40"><option value="">Tous les statuts</option><option>Succès</option><option>Refusé</option><option>Bloqué</option></Select>
          <button type="button" onClick={() => navigate('/admin/securite/journal')} className="h-9 rounded-lg border border-[#DCE3EE] px-3 text-[12.5px] text-[#2F6BFF]">Voir tout</button>
        </div>
        <JournalTable rows={journal} people={people} />
      </Card>

      {toast}
      {modal?.type === 'user' && <UserModal user={modal.u} roles={roles} onClose={() => setModal(null)} onDone={(created) => { load(); if (created) setModal({ type: 'pw', data: created }); else { setModal(null); say('Utilisateur modifié.'); } }} />}
      {modal?.type === 'pw' && <PasswordOnce email={modal.data.email} password={modal.data.password} title={modal.title} onClose={() => setModal(null)} />}
    </div>
  );
}

export function JournalTable({ rows }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[960px] text-[12.5px]">
        <thead><tr className="border-b border-[#EDF1F7] text-left text-[#64748B]">{['Date & heure', 'Utilisateur', 'Action', 'Détails', 'Cible', 'Adresse IP', 'Statut'].map((h) => <th key={h} className="px-2 py-2 font-medium">{h}</th>)}</tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className="border-b border-[#F4F7FC]">
              <td className="whitespace-nowrap px-2 py-2 text-[#475569]">{when(r.at)}</td>
              <td className="px-2 py-2">{r.category === 'Sécurité' && r.status !== 'Succès' ? <span className="flex items-center gap-2 text-[#E11D48]"><AlertTriangle size={15} /> {r.user}</span> : <Avatar name={r.user} size={22} />}</td>
              <td className="px-2 py-2 font-medium text-[#0B1C3F]">{r.verb}</td>
              <td className="px-2 py-2 text-[#2F6BFF]">{r.label}{r.detail ? <span className="text-[#64748B]"> — {r.detail}</span> : null}</td>
              <td className="max-w-[160px] truncate px-2 py-2 text-[#475569]">{r.target || r.category}</td>
              <td className="px-2 py-2 font-mono text-[12px] text-[#475569]">{r.ip || '—'}</td>
              <td className="px-2 py-2"><Pill tone={JOURNAL_TONE[r.status] || JOURNAL_TONE.Succès}>{r.status}</Pill></td>
            </tr>
          ))}
          {!rows.length && <tr><td colSpan={7} className="py-8 text-center text-[#94A3B8]">Aucune action sur la période.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}
