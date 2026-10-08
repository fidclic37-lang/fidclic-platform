import React, { useEffect, useState } from 'react';
import { Loader2, User, UserPlus, Users, AlertTriangle } from 'lucide-react';
import { teamAPI, securityAPI } from '../../../lib/api';
import { PasswordOnce } from '../securite/shared';
import { Avatar, PeoplePicker, Shell, field, frDateTime } from './shared';
import { ListPicker } from './Lists';

/* Super admin › Suivi d'équipe — who is on the team (user, 2026-10-08):
   add someone who already has a FidClic team account, or create the account
   right here (super admin), each with a fonction from the team's list;
   change a fonction; take someone off the team — their open tasks are handed
   over first (compulsory for the ones only they held). */

const err = (e, f) => e?.response?.data?.detail || f;
const Label = ({ children }) => <span className="mb-1 block text-[12px] font-semibold text-[#475569]">{children}</span>;

export function AddMember({ board, onClose, onDone, onRefresh, onManage }) {
  const [tab, setTab] = useState('existing');
  const [rows, setRows] = useState(null);
  const [pick, setPick] = useState('');
  const [fonction, setFonction] = useState('');
  const [roles, setRoles] = useState([]);
  const [f, setF] = useState({ first_name: '', last_name: '', email: '', role_id: '' });
  const [created, setCreated] = useState(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  useEffect(() => { teamAPI.candidates().then(({ data }) => setRows(data.rows)).catch(() => setRows([])); }, []);
  useEffect(() => {
    if (tab === 'new' && board.can_create_users && !roles.length) {
      securityAPI.roles().then(({ data }) => setRoles(data.roles || [])).catch(() => setRoles([]));
    }
  }, [tab]); // eslint-disable-line react-hooks/exhaustive-deps
  const chosen = rows?.find((r) => r.email === pick);
  const role = roles.find((r) => r.id === f.role_id);
  const roleSeesTasks = role && (role.id === 'super_admin' || role.perms?.equipe?.view);

  const addExisting = async () => {
    setBusy(true); setMsg('');
    try { await teamAPI.addMember({ email: pick, fonction_id: fonction || null }); onDone(`${chosen?.name || 'Membre'} ajouté à l'équipe.`); }
    catch (e) { setMsg(err(e, 'Ajout impossible.')); } finally { setBusy(false); }
  };
  const createAccount = async () => {
    setMsg('');
    if (!f.first_name.trim() || !f.email.trim() || !f.role_id) { setMsg('Prénom, e-mail et rôle sont obligatoires.'); return; }
    setBusy(true);
    try {
      const { data } = await securityAPI.addUser({ ...f, email: f.email.trim() });
      await teamAPI.addMember({ email: data.email, fonction_id: fonction || null });
      setCreated(data);                       // the password, shown once
    } catch (e) { setMsg(err(e, 'Création impossible.')); } finally { setBusy(false); }
  };

  if (created) {
    return <PasswordOnce email={created.email} password={created.password} title="Compte créé et ajouté à l'équipe"
                         onClose={() => onDone(`${f.first_name} ajouté à l'équipe.`)} />;
  }
  return (
    <Shell title="Ajouter à l'équipe" onClose={onClose}>
      {board.can_create_users && (
        <div className="mb-4 inline-flex rounded-xl bg-[#F1F5F9] p-1">
          {[['existing', 'Compte existant', Users], ['new', 'Nouveau compte', UserPlus]].map(([k, l, I]) => (
            <button key={k} type="button" onClick={() => { setTab(k); setMsg(''); }}
                    className={`inline-flex h-8 items-center gap-1.5 rounded-lg px-3 text-[12.5px] font-semibold ${tab === k ? 'bg-white text-[#0B1C3F] shadow-sm' : 'text-[#64748B]'}`}><I size={14} />{l}</button>
          ))}
        </div>
      )}
      {tab === 'existing' ? (
        <>
          <p className="mb-3 text-[12.5px] text-[#64748B]">Les utilisateurs de l'équipe FidClic (Admin › Utilisateurs) qui ne sont pas encore là.</p>
          {!rows ? <Loader2 size={16} className="animate-spin text-[#64748B]" /> : !rows.length
            ? <p className="text-[13px] text-[#64748B]">Tous les utilisateurs de l'équipe sont déjà là.{board.can_create_users ? ' Créez un nouveau compte.' : ''}</p>
            : (
              <ul className="max-h-64 space-y-1 overflow-y-auto">
                {rows.map((r) => (
                  <li key={r.email}>
                    <button type="button" onClick={() => setPick(r.email)}
                            className={`flex w-full items-center gap-3 rounded-xl border px-3 py-2 text-left ${pick === r.email ? 'border-[#2F6BFF] bg-[#F4F8FF]' : 'border-transparent hover:bg-[#F8FAFD]'}`}>
                      <Avatar name={r.name} size={32} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[13px] font-semibold text-[#0B1C3F]">{r.name}</span>
                        <span className="block truncate text-[11.5px] text-[#64748B]">{r.email}{r.role ? ` · ${r.role}` : ''}</span>
                      </span>
                      {!r.access && <span className="rounded-md bg-[#FFF6DE] px-1.5 py-0.5 text-[10.5px] font-semibold text-[#B7791F]">Sans accès</span>}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          {chosen && !chosen.access && (
            <p className="mt-2 flex items-start gap-1.5 rounded-lg bg-[#FFF8E6] px-3 py-2 text-[12px] text-[#92400E]"><User size={14} className="mt-0.5 shrink-0" />
              Son rôle ne donne pas accès à Suivi d'équipe : il ne verra pas ses tâches tant que l'accès n'est pas donné dans Admin › Rôles.</p>
          )}
        </>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          <label><Label>Prénom</Label><input value={f.first_name} onChange={(e) => setF({ ...f, first_name: e.target.value })} maxLength={60} className={field} /></label>
          <label><Label>Nom</Label><input value={f.last_name} onChange={(e) => setF({ ...f, last_name: e.target.value })} maxLength={60} className={field} /></label>
          <label className="sm:col-span-2"><Label>E-mail (identifiant de connexion)</Label><input type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} maxLength={200} className={field} /></label>
          <label className="sm:col-span-2"><Label>Rôle (ce qu'il pourra voir et modifier)</Label>
            <select value={f.role_id} onChange={(e) => setF({ ...f, role_id: e.target.value })} className={field}>
              <option value="">— choisir —</option>
              {roles.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
            </select>
          </label>
          {role && !roleSeesTasks && (
            <p className="flex items-start gap-1.5 rounded-lg bg-[#FFF8E6] px-3 py-2 text-[12px] text-[#92400E] sm:col-span-2"><User size={14} className="mt-0.5 shrink-0" />
              Ce rôle ne donne pas accès à Suivi d'équipe : activez « Suivi d'équipe » (Voir / Modifier) pour ce rôle dans Admin › Rôles.</p>
          )}
        </div>
      )}
      {(tab === 'new' || chosen) && (
        <div className="mt-3"><Label>Fonction (affichée sous le nom)</Label>
          <ListPicker kind="fonctions" items={board.fonctions} value={fonction} onChange={setFonction} placeholder="Sans fonction" canEdit
                      onAdded={onRefresh} onManage={onManage && (() => onManage('fonctions'))} />
        </div>
      )}
      {msg && <p className="mt-3 rounded-lg bg-[#FEF2F2] px-3 py-2 text-[12.5px] text-[#B91C1C]">{msg}</p>}
      <div className="mt-4 flex justify-end gap-2">
        <button type="button" onClick={onClose} className="h-10 rounded-xl border border-[#E3E9F3] px-4 text-[13px] font-semibold text-[#475569]">Annuler</button>
        {tab === 'existing'
          ? <button type="button" disabled={!pick || busy} onClick={addExisting} className="inline-flex h-10 items-center gap-2 rounded-xl bg-[#2F6BFF] px-5 text-[13px] font-semibold text-white disabled:opacity-50">{busy && <Loader2 size={14} className="animate-spin" />}Ajouter</button>
          : <button type="button" disabled={busy} onClick={createAccount} className="inline-flex h-10 items-center gap-2 rounded-xl bg-[#2F6BFF] px-5 text-[13px] font-semibold text-white disabled:opacity-50">{busy && <Loader2 size={14} className="animate-spin" />}Créer le compte et ajouter</button>}
      </div>
    </Shell>
  );
}

export function FonctionModal({ member, board, onClose, onDone, onRefresh, onManage }) {
  const [v, setV] = useState(member.fonction_id || '');
  const [msg, setMsg] = useState('');
  const save = async () => {
    try { await teamAPI.editMember(member.email, { email: member.email, fonction_id: v || null }); onDone('Fonction enregistrée.'); }
    catch (e) { setMsg(err(e, 'Action impossible.')); }
  };
  return (
    <Shell title={`Fonction de ${member.name}`} onClose={onClose}>
      <ListPicker kind="fonctions" items={board.fonctions} value={v} onChange={setV} placeholder="Sans fonction" canEdit
                  onAdded={onRefresh} onManage={onManage && (() => onManage('fonctions'))} />
      {msg && <p className="mt-3 rounded-lg bg-[#FEF2F2] px-3 py-2 text-[12.5px] text-[#B91C1C]">{msg}</p>}
      <div className="mt-4 flex justify-end gap-2">
        <button type="button" onClick={onClose} className="h-10 rounded-xl border border-[#E3E9F3] px-4 text-[13px] font-semibold text-[#475569]">Annuler</button>
        <button type="button" onClick={save} className="h-10 rounded-xl bg-[#2F6BFF] px-5 text-[13px] font-semibold text-white">Enregistrer</button>
      </div>
    </Shell>
  );
}

/* « Retirer de l'équipe »: their open tasks first. */
export function RemoveMember({ member, board, onClose, onDone }) {
  const others = board.members.filter((m) => m.email !== member.email);
  const [u, setU] = useState(null);
  const [to, setTo] = useState([]);
  const [moves, setMoves] = useState({});
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  useEffect(() => { teamAPI.memberUsage(member.email).then(({ data }) => setU(data)).catch((e) => setMsg(err(e, 'Impossible de vérifier.'))); }, [member.email]);
  const sole = u ? u.tasks.filter((t) => t.sole) : [];
  const shared = u ? u.tasks.filter((t) => !t.sole) : [];
  // compulsory: every task only they hold gets someone, and so do their repeats
  const ok = u && sole.every((t) => (moves[t.id]?.length) || to.length) && (!u.series || to.length);
  const go = async () => {
    setBusy(true); setMsg('');
    try { await teamAPI.removeMember(member.email, { to, moves }); onDone(`${member.name} retiré(e) de l'équipe.`); }
    catch (e) { setMsg(err(e, 'Retrait impossible.')); } finally { setBusy(false); }
  };
  return (
    <Shell title={`Retirer ${member.name} de l'équipe`} onClose={onClose} wide>
      {!u ? <p className="flex items-center gap-2 text-[13px] text-[#64748B]"><Loader2 size={15} className="animate-spin" /> Vérification…</p> : (
        <>
          {!u.tasks.length && !u.series
            ? <p className="text-[13px] text-[#475569]">Aucune tâche en cours : {member.name} peut être retiré(e). Ses tâches terminées et l'historique gardent son nom.</p>
            : (
              <>
                <p className="mb-3 flex items-start gap-2 rounded-lg bg-[#FFF8E6] px-3 py-2 text-[12.5px] text-[#92400E]"><AlertTriangle size={15} className="mt-0.5 shrink-0" />
                  {sole.length ? `${sole.length} tâche(s) n'ont que ${member.name} : attribuez-les à d'autres membres (obligatoire). ` : ''}
                  {shared.length ? `Sur ${shared.length} tâche(s) partagée(s), ${member.name} est simplement retiré(e). ` : ''}
                  {u.series ? `${u.series} tâche(s) répétée(s) passeront à la personne choisie ci-dessous.` : ''}
                </p>
                {!others.length && <p className="mb-3 text-[12.5px] text-[#B91C1C]">Ajoutez d'abord un autre membre à l'équipe.</p>}
                <Label>Attribuer {sole.length ? 'le reste' : 'ses tâches répétées'} à</Label>
                <PeoplePicker members={others} value={to} onChange={setTo} placeholder="— choisir —" className="mb-3 sm:max-w-[60%]" />
                {sole.length > 0 && (
                  <div className="max-h-[40vh] overflow-y-auto rounded-xl border border-[#EEF2F8]">
                    <table className="w-full border-collapse text-[12.5px]">
                      <thead><tr className="border-b border-[#EEF2F8] text-left text-[11.5px] text-[#64748B]"><th className="px-3 py-2">Tâche</th><th className="px-3 py-2">Attribuer à (une par une)</th></tr></thead>
                      <tbody>
                        {sole.map((t) => (
                          <tr key={t.id} className="border-b border-[#F4F7FC] last:border-b-0">
                            <td className="px-3 py-2"><span className="block font-medium text-[#0B1C3F]">{t.title}</span><span className="text-[11px] text-[#94A3B8]">{frDateTime(t.due_at)}</span></td>
                            <td className="w-[260px] px-3 py-2">
                              <PeoplePicker members={others} value={moves[t.id] || []} onChange={(v) => setMoves({ ...moves, [t.id]: v })}
                                            placeholder={to.length ? `(${others.filter((m) => to.includes(m.email)).map((m) => m.name.split(' ')[0]).join(', ')})` : '— choisir —'} />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </>
            )}
        </>
      )}
      {msg && <p className="mt-3 rounded-lg bg-[#FEF2F2] px-3 py-2 text-[12.5px] text-[#B91C1C]">{msg}</p>}
      <div className="mt-4 flex justify-end gap-2">
        <button type="button" onClick={onClose} className="h-10 rounded-xl border border-[#E3E9F3] px-4 text-[13px] font-semibold text-[#475569]">Annuler</button>
        <button type="button" disabled={!u || busy || !ok} onClick={go}
                className="inline-flex h-10 items-center gap-2 rounded-xl bg-[#DC2626] px-5 text-[13px] font-semibold text-white disabled:opacity-50">
          {busy && <Loader2 size={14} className="animate-spin" />}{u?.tasks.length ? 'Attribuer et retirer' : 'Retirer'}
        </button>
      </div>
    </Shell>
  );
}
