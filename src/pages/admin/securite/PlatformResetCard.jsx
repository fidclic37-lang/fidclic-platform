import React, { useEffect, useState } from 'react';
import { AlertTriangle, Download, Loader2, Trash2, CheckCircle2 } from 'lucide-react';
import { securityAPI } from '../../../lib/api';
import { Card, Head, inputCls } from '../../crm/ui';

/* Super admin › Sécurité › Paramètres — « Remise à zéro de la plateforme »
   (user, 2026-10-04: « sab saaf … brand new fresh start »).
   Three gates, in order: see what goes → download the backup (Atlas backups
   are off: this file is the only way back) → type SUPPRIMER. Settings and
   the super admin running it stay. */
const RED = '#C0392B';
const fmt = (n) => Number(n || 0).toLocaleString('fr-FR');

export default function PlatformResetCard() {
  const [crm, setCrm] = useState(true);
  const [keep, setKeep] = useState([]);           // other super admins who stay
  const [pv, setPv] = useState(null);
  const [token, setToken] = useState('');
  const [phrase, setPhrase] = useState('');
  const [busy, setBusy] = useState('');
  const [err, setErr] = useState('');
  const [done, setDone] = useState(null);
  const [details, setDetails] = useState(false);

  const load = () => {
    setErr(''); setToken('');
    securityAPI.resetPreview(crm, keep).then((r) => setPv(r.data)).catch((e) => setErr(e?.response?.data?.detail || 'Aperçu impossible.'));
  };
  useEffect(() => { if (pv) load(); }, [crm, keep.join(',')]); // eslint-disable-line react-hooks/exhaustive-deps

  const backup = async () => {
    setBusy('backup'); setErr('');
    try {
      const r = await securityAPI.resetBackup(crm, keep);
      const t = r.headers?.['x-reset-token'];
      const name = (r.headers?.['content-disposition'] || '').match(/filename="([^"]+)"/)?.[1] || 'fidclic-sauvegarde.json.gz';
      const url = URL.createObjectURL(r.data);
      const a = document.createElement('a'); a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 5000);
      setToken({ value: t, name, size: r.data.size });
    } catch (e) {
      setErr('La sauvegarde n’a pas pu être téléchargée. Rien n’a été supprimé.');
    } finally { setBusy(''); }
  };

  const wipe = async () => {
    setBusy('reset'); setErr('');
    try {
      const r = await securityAPI.reset({ token: token.value, confirm: phrase.trim(), include_crm: crm, keep });
      setDone(r.data);
    } catch (e) {
      setErr(e?.response?.data?.detail || 'La remise à zéro a échoué. Rien n’a été supprimé.');
    } finally { setBusy(''); }
  };

  if (done) {
    return (
      <Card className="mt-6 border-[#BFE3CC]">
        <div className="flex items-start gap-3">
          <CheckCircle2 className="mt-0.5 text-[#16803C]" size={22} />
          <div>
            <p className="text-[15px] font-bold text-[#0B1C3F]">Plateforme remise à zéro — {fmt(done.total)} éléments supprimés.</p>
            <p className="mt-1 text-[13px] text-[#475569]">Comptes conservés : {(done.kept_logins || [done.kept_login]).join(', ')} — et les paramètres. Les nouveaux commerces s’inscrivent sur /register.</p>
            <button type="button" onClick={() => { window.location.href = '/admin'; }} className="mt-3 rounded-xl bg-[#2F6BFF] px-4 py-2 text-[13px] font-semibold text-white">Retour au tableau de bord</button>
          </div>
        </div>
      </Card>
    );
  }

  return (
    <Card className="mt-6" >
      <div style={{ borderLeft: `3px solid ${RED}` }} className="-ml-1 pl-4">
        <Head icon={AlertTriangle} tone={RED} title="Remise à zéro de la plateforme"
              sub="Supprime définitivement tous les commerces, leurs clients et données, et tous les comptes sauf le vôtre. Les paramètres (formules, rôles, sécurité, facturation) sont conservés." />

        {!pv ? (
          <button type="button" onClick={load} className="mt-3 rounded-xl border border-[#F1C4BE] px-4 py-2 text-[13px] font-semibold" style={{ color: RED }}>
            Voir ce qui sera supprimé
          </button>
        ) : (
          <div className="mt-3 space-y-4 text-[13.5px]">
            <div className="grid gap-3 sm:grid-cols-3">
              {[['Commerces', pv.businesses], ['Clients', pv.customers], ['Comptes supprimés', pv.logins_deleted]].map(([l, v]) => (
                <div key={l} className="rounded-xl bg-[#FDF3F2] px-4 py-3"><div className="text-[22px] font-bold" style={{ color: RED }}>{fmt(v)}</div><div className="text-[12.5px] text-[#475569]">{l}</div></div>
              ))}
            </div>
            <p className="text-[#475569]">Au total <b>{fmt(pv.total)}</b> éléments. Conservés : <b>{(pv.kept_logins || [pv.kept_login]).join(', ')}</b> et les paramètres.{' '}
              <button type="button" onClick={() => setDetails((d) => !d)} className="font-semibold text-[#2F6BFF]">{details ? 'Masquer le détail' : 'Voir le détail'}</button></p>
            {details && (
              <div className="grid max-h-56 gap-x-6 gap-y-1 overflow-y-auto rounded-xl bg-[#F8FAFF] p-3 text-[12.5px] sm:grid-cols-3">
                {Object.entries(pv.collections).map(([k, v]) => <div key={k} className="flex justify-between gap-2"><span className="truncate text-[#475569]">{k}</span><b>{fmt(v)}</b></div>)}
              </div>
            )}
            <div className="rounded-xl border border-[#E6EEFB] p-3">
              <p className="mb-1.5 font-semibold text-[#0B1C3F]">Comptes Super Admin à conserver</p>
              {(pv.super_admins || []).map((a) => (
                <label key={a.email} className="flex items-center gap-2.5 py-0.5">
                  <input type="checkbox" className="accent-[#2F6BFF]" disabled={a.you} checked={a.you || keep.includes(a.email)}
                         onChange={(e) => setKeep((k) => (e.target.checked ? [...k, a.email] : k.filter((x) => x !== a.email)))} />
                  <span>{a.email}{a.you ? ' — vous (toujours conservé)' : ''}</span>
                </label>
              ))}
              <p className="mt-1 text-[12px] text-[#64748B]">Tous les autres comptes (commerces, équipes, comptables, Super Admins non cochés) sont supprimés.</p>
            </div>
            <label className="flex items-start gap-2.5">
              <input type="checkbox" className="mt-0.5 accent-[#C0392B]" checked={crm} onChange={(e) => setCrm(e.target.checked)} />
              <span>Supprimer aussi le <b>CRM de prospection</b> (prospects, séquences, appels, tâches){Object.keys(pv.crm || {}).length ? ` — ${fmt(Object.values(pv.crm).reduce((a, b) => a + b, 0))} éléments` : ''}.</span>
            </label>

            <div className="rounded-xl border border-[#E6EEFB] p-4">
              <p className="font-semibold text-[#0B1C3F]">1. Téléchargez la sauvegarde</p>
              <p className="mt-1 text-[12.5px] text-[#64748B]">Les sauvegardes automatiques de la base sont désactivées : ce fichier est la seule façon de revenir en arrière. Gardez-le en lieu sûr.</p>
              {token ? (
                <p className="mt-2 flex items-center gap-2 text-[13px] text-[#16803C]"><CheckCircle2 size={16} /> {token.name} ({fmt(Math.round((token.size || 0) / 1024))} Ko) — valable 30 minutes.</p>
              ) : (
                <button type="button" onClick={backup} disabled={busy === 'backup'} className="mt-2 inline-flex items-center gap-2 rounded-xl bg-[#0B1C3F] px-4 py-2 text-[13px] font-semibold text-white disabled:opacity-60">
                  {busy === 'backup' ? <Loader2 size={15} className="animate-spin" /> : <Download size={15} />} Télécharger la sauvegarde
                </button>
              )}
            </div>

            <div className={`rounded-xl border p-4 ${token ? 'border-[#F1C4BE]' : 'border-[#E6EEFB] opacity-50'}`}>
              <p className="font-semibold text-[#0B1C3F]">2. Confirmez</p>
              <p className="mt-1 text-[12.5px] text-[#64748B]">Tapez <b>{pv.phrase}</b> pour supprimer définitivement. Cette action ne peut pas être annulée.</p>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <input className={`${inputCls} max-w-[220px]`} disabled={!token} value={phrase} onChange={(e) => setPhrase(e.target.value)} placeholder={pv.phrase} aria-label="Confirmation" />
                <button type="button" onClick={wipe} disabled={!token || phrase.trim() !== pv.phrase || busy === 'reset'}
                        className="inline-flex items-center gap-2 rounded-xl px-4 py-2.5 text-[13px] font-semibold text-white disabled:opacity-40" style={{ background: RED }}>
                  {busy === 'reset' ? <Loader2 size={15} className="animate-spin" /> : <Trash2 size={15} />} Tout supprimer définitivement
                </button>
              </div>
            </div>
          </div>
        )}
        {err && <p className="mt-3 text-[13px]" style={{ color: RED }}>{err}</p>}
      </div>
    </Card>
  );
}
