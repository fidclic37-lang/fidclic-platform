import React, { useEffect, useState } from 'react';
import { Users, UserPlus, Trash2, Shield, Copy, KeyRound, X } from 'lucide-react';
import { ownerAPI } from '../lib/api';
import { C } from './PageShell';

/**
 * CredentialsCard — small panel that shows freshly-issued staff credentials
 * with copy buttons. Shown for ~2 minutes after creation / reset, then
 * dismissed. The plaintext password is NEVER stored on the server beyond
 * the hash, so the owner has to grab it now or reset again.
 */
const CredentialsCard = ({ creds, onDismiss }) => {
  if (!creds) return null;
  const loginUrl = `${window.location.origin}/login`;
  const copy = (txt) => {
    try { navigator.clipboard.writeText(txt); } catch { /* ignore */ }
  };
  return (
    <div
      className="rounded-xl p-4 relative"
      style={{ background: 'color-mix(in srgb, var(--flc-accent, #C73E2C) 12%, var(--flc-card, #FFFFFF))', border: '1px solid color-mix(in srgb, var(--flc-accent, #B85C38) 33%, transparent)' }}
    >
      <button
        onClick={onDismiss}
        className="absolute top-2 right-2 w-6 h-6 rounded-full hover:bg-white/40"
        aria-label="Dismiss"
      >
        <X size={12} className="mx-auto" style={{ color: 'var(--flc-accent-deep, #9C4427)' }} />
      </button>
      <p className="text-xs font-bold uppercase tracking-wider mb-2" style={{ color: 'var(--flc-accent-deep, #9C4427)' }}>
        🔐 Identifiants prêts — partagez-les avec votre collaborateur
      </p>
      <div className="space-y-1.5 font-mono text-sm">
        <div className="flex items-center gap-2 bg-white px-3 py-2 rounded-lg">
          <span className="text-[10px] font-bold uppercase tracking-wider w-20 shrink-0" style={{ color: '#8D857D' }}>URL</span>
          <span className="flex-1 truncate" style={{ color: '#171412' }}>{loginUrl}</span>
          <button onClick={() => copy(loginUrl)} className="text-xs px-2 py-1 rounded" style={{ background: 'color-mix(in srgb, var(--flc-accent, #C73E2C) 12%, var(--flc-card, #FFFFFF))', color: 'var(--flc-accent-deep, #9C4427)' }}>
            <Copy size={11} className="inline -mt-0.5" /> Copier
          </button>
        </div>
        <div className="flex items-center gap-2 bg-white px-3 py-2 rounded-lg">
          <span className="text-[10px] font-bold uppercase tracking-wider w-20 shrink-0" style={{ color: '#8D857D' }}>Email</span>
          <span className="flex-1 truncate" style={{ color: '#171412' }}>{creds.email}</span>
          <button onClick={() => copy(creds.email)} className="text-xs px-2 py-1 rounded" style={{ background: 'color-mix(in srgb, var(--flc-accent, #C73E2C) 12%, var(--flc-card, #FFFFFF))', color: 'var(--flc-accent-deep, #9C4427)' }}>
            <Copy size={11} className="inline -mt-0.5" /> Copier
          </button>
        </div>
        <div className="flex items-center gap-2 bg-white px-3 py-2 rounded-lg">
          <span className="text-[10px] font-bold uppercase tracking-wider w-20 shrink-0" style={{ color: '#8D857D' }}>Mot de passe</span>
          <span className="flex-1 truncate font-bold" style={{ color: '#171412' }}>{creds.password}</span>
          <button onClick={() => copy(creds.password)} className="text-xs px-2 py-1 rounded" style={{ background: 'color-mix(in srgb, var(--flc-accent, #C73E2C) 12%, var(--flc-card, #FFFFFF))', color: 'var(--flc-accent-deep, #9C4427)' }}>
            <Copy size={11} className="inline -mt-0.5" /> Copier
          </button>
        </div>
      </div>
      <button
        onClick={() => copy(`Connexion FidClic\n${loginUrl}\nEmail : ${creds.email}\nMot de passe : ${creds.password}`)}
        className="mt-3 w-full text-sm font-semibold text-white py-2 rounded-lg"
        style={{ background: '#B85C38' }}
      >
        📋 Tout copier — pour WhatsApp / SMS
      </button>
      <p className="text-[10px] mt-2 text-center" style={{ color: 'var(--flc-accent-deep, #9C4427)' }}>
        Ce mot de passe ne sera plus affiché après fermeture. Si oublié, utilisez "Réinitialiser" sur la ligne du membre.
      </p>
    </div>
  );
};

/**
 * TeamCard — Settings card for owner-side staff management.
 *
 * Wraps the existing /api/owner/team endpoints (already implemented).
 * Owners can create staff (scan-only) and manager (full read) accounts
 * scoped to their tenant. New users log in via /login with their own
 * credentials and only see what their role allows.
 */
const ROLES = [
  { value: 'staff',   label: 'Staff (scan uniquement)' },
  { value: 'manager', label: 'Manager (lecture complète, sauf paramètres)' },
];

const TeamCard = ({ id }) => {
  const [team, setTeam] = useState([]);
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState({ email: '', password: '', role: 'staff' });
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  // After create / reset, hold the plaintext password in memory ONLY in this
  // session, so the owner can copy + share. Cleared on dismiss or page reload.
  const [issuedCreds, setIssuedCreds] = useState(null);  // { email, password }
  const [resettingFor, setResettingFor] = useState('');  // email currently being reset

  const load = async () => {
    setLoading(true);
    try {
      const r = await ownerAPI.listTeam();
      setTeam(r.data?.members || r.data || []);
    } catch (e) {
      setError(e?.response?.data?.detail || e.message || 'Chargement échoué');
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []);

  const add = async (e) => {
    e.preventDefault();
    setError(''); setSuccess('');
    if (!form.email || !form.password) {
      setError('Email et mot de passe requis.');
      return;
    }
    if (form.password.length < 6) {
      setError('Mot de passe trop court (6 caractères minimum).');
      return;
    }
    setAdding(true);
    try {
      await ownerAPI.addTeamMember(form);
      // Stash the plaintext creds for sharing — cleared on dismiss.
      setIssuedCreds({ email: form.email, password: form.password });
      setSuccess(`${form.email} ajouté · partagez les identifiants ci-dessous.`);
      setForm({ email: '', password: '', role: 'staff' });
      load();
    } catch (e) {
      setError(e?.response?.data?.detail || e.message || 'Échec de l\'ajout');
    } finally {
      setAdding(false);
    }
  };

  const resetPassword = async (email) => {
    if (!confirm(`Générer un nouveau mot de passe pour ${email} ?\n\nLe précédent ne fonctionnera plus.`)) return;
    setResettingFor(email);
    setError('');
    try {
      const r = await ownerAPI.resetTeamPassword(email);  // server-generated
      setIssuedCreds({ email: r.data.email, password: r.data.new_password });
      setSuccess(`Nouveau mot de passe généré pour ${email}.`);
    } catch (e) {
      setError(e?.response?.data?.detail || e.message || 'Échec de la réinitialisation');
    } finally {
      setResettingFor('');
    }
  };

  const remove = async (email) => {
    if (!confirm(`Retirer ${email} de l'équipe ?`)) return;
    try {
      await ownerAPI.removeTeamMember(email);
      setTeam((p) => p.filter((m) => m.email !== email));
    } catch (e) {
      setError(e?.response?.data?.detail || e.message || 'Échec du retrait');
    }
  };

  return (
    <section
      id={id}
      className="rounded-2xl p-6 space-y-4"
      style={{ background: 'var(--flc-card, #FFFFFF)', border: `1px solid ${C.hairline}`, boxShadow: '0 1px 2px rgba(28,25,23,0.04)' }}
    >
      <header>
        <h2 className="text-2xl font-semibold flex items-center gap-2"
            style={{ fontFamily: 'Cormorant Garamond', color: C.inkDeep }}>
          <Users size={20} style={{ color: C.terracotta }} /> Équipe & accès
        </h2>
        <p className="text-sm mt-1" style={{ color: C.inkMute }}>
          Créez un compte par employé. Le staff voit seulement la page Scan,
          le manager voit toutes les analyses sauf les paramètres.
        </p>
      </header>

      {/* Add form */}
      <form onSubmit={add} className="grid grid-cols-1 md:grid-cols-4 gap-2 items-end">
        <label className="md:col-span-2 block">
          <span className="text-[10px] font-bold uppercase tracking-wider" style={{ color: C.inkMute }}>
            Email du collaborateur
          </span>
          <input
            type="email"
            placeholder="staff@cafelumiere.fr"
            value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
            className="mt-1 w-full px-3 py-2 rounded-lg border text-sm"
            style={{ borderColor: C.hairline, color: C.inkDeep }}
          />
        </label>
        <label className="block">
          <span className="text-[10px] font-bold uppercase tracking-wider" style={{ color: C.inkMute }}>
            Mot de passe initial
          </span>
          <input
            type="password"
            placeholder="≥ 6 caractères"
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
            className="mt-1 w-full px-3 py-2 rounded-lg border text-sm"
            style={{ borderColor: C.hairline, color: C.inkDeep }}
          />
        </label>
        <label className="block">
          <span className="text-[10px] font-bold uppercase tracking-wider" style={{ color: C.inkMute }}>
            Rôle
          </span>
          <select
            value={form.role}
            onChange={(e) => setForm({ ...form, role: e.target.value })}
            className="mt-1 w-full px-3 py-2 rounded-lg border text-sm bg-white"
            style={{ borderColor: C.hairline, color: C.inkDeep }}
          >
            {ROLES.map((r) => (
              <option key={r.value} value={r.value}>{r.label}</option>
            ))}
          </select>
        </label>
        <button
          type="submit"
          disabled={adding}
          className="md:col-span-4 inline-flex items-center justify-center gap-2 mt-1 px-4 py-2.5 rounded-lg text-sm font-semibold text-white transition disabled:opacity-60"
          style={{ background: C.terracotta }}
        >
          <UserPlus size={14} /> {adding ? 'Ajout en cours…' : 'Ajouter au compte'}
        </button>
      </form>

      {error && <p className="text-xs" style={{ color: C.terracotta }}>⚠ {error}</p>}
      {success && (
        <p className="text-xs flex items-center gap-1.5" style={{ color: C.sage }}>
          <Shield size={13} /> {success}
        </p>
      )}

      {/* Credentials panel — shown after a successful create or reset. */}
      <CredentialsCard creds={issuedCreds} onDismiss={() => setIssuedCreds(null)} />

      {/* Existing team */}
      <div className="rounded-xl p-4" style={{ background: 'var(--flc-paper2, #FAFAF8)', border: `1px solid ${C.hairline}` }}>
        <p className="text-xs font-bold uppercase tracking-wider mb-2" style={{ color: C.inkMute }}>
          Membres de l'équipe ({team.length})
        </p>
        {loading ? (
          <p key="loading" className="text-sm" style={{ color: C.inkMute }}>Chargement…</p>
        ) : team.length === 0 ? (
          <p className="text-sm italic" style={{ color: C.inkMute }}>
            Aucun membre. Ajoutez votre premier collaborateur ci-dessus.
          </p>
        ) : (
          <ul className="space-y-1.5">
            {team.map((m) => (
              <li
                key={m.email}
                className="flex items-center justify-between gap-2 bg-white px-3 py-2 rounded-lg"
              >
                <div className="min-w-0">
                  <p className="text-sm font-semibold truncate" style={{ color: C.inkDeep }}>
                    {m.email}
                  </p>
                  <p className="text-[11px]" style={{ color: C.inkMute }}>
                    Rôle : <b>{m.role}</b>
                  </p>
                </div>
                <div className="flex items-center gap-1.5 shrink-0">
                  <button
                    onClick={() => resetPassword(m.email)}
                    disabled={resettingFor === m.email}
                    className="text-xs px-2.5 py-1 rounded-md transition disabled:opacity-50"
                    style={{ background: '#FEF3C7', color: '#854F0B' }}
                    title="Générer un nouveau mot de passe (l'ancien sera révoqué)"
                  >
                    <KeyRound size={11} className="inline -mt-0.5" />{' '}
                    {resettingFor === m.email ? 'Réinit…' : 'Réinitialiser'}
                  </button>
                  <button
                    onClick={() => remove(m.email)}
                    className="text-xs px-2.5 py-1 rounded-md transition"
                    style={{ background: '#FCEBEB', color: '#791F1F' }}
                  >
                    <Trash2 size={11} className="inline -mt-0.5" /> Retirer
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
};

export default TeamCard;
