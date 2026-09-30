import React, { useEffect, useMemo, useState } from 'react';
import { ShieldAlert, Globe2, BellRing, Lock, Unlock, Loader2, Search, X, Info } from 'lucide-react';
import { securityAPI } from '../../../lib/api';
import { useAuth } from '../../../contexts/AuthContext';
import { Card, Head, Loading, Breadcrumb, useToast, BLUE, inputCls } from '../../crm/ui';
import { flag } from './shared';

/* Super admin › Sécurité › Paramètres sécurité — decided with the user:
   blocked after N wrong passwords, an alert on a new country, and the
   countries the team may sign in from. Only the super admin changes them. */

const CODES = ('AD AE AF AG AL AM AO AR AT AU AZ BA BB BD BE BF BG BH BI BJ BN BO BR BS BT BW BY BZ CA CD CF CG CH CI CL CM CN CO CR CU CV CY CZ '
  + 'DE DJ DK DM DO DZ EC EE EG ER ES ET FI FJ FR GA GB GD GE GH GM GN GQ GR GT GW GY HK HN HR HT HU ID IE IL IN IQ IR IS IT JM JO JP KE KG KH '
  + 'KM KN KR KW KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MG MK ML MM MN MR MT MU MV MW MX MY MZ NA NE NG NI NL NO NP NZ OM PA PE PG PH '
  + 'PK PL PT PY QA RE RO RS RU RW SA SC SD SE SG SI SK SL SM SN SO SR SS ST SV SY SZ TD TG TH TJ TL TM TN TR TT TW TZ UA UG US UY UZ VA VC VE '
  + 'VN YE ZA ZM ZW GP MQ GF YT NC PF').split(' ');
const names = (() => { try { return new Intl.DisplayNames(['fr'], { type: 'region' }); } catch { return null; } })();
const cname = (c) => names?.of(c) || c;

export default function SecuritySettingsPage() {
  const { user } = useAuth();
  const boss = user?.role === 'super_admin';
  const [s, setS] = useState(null);
  const [locked, setLocked] = useState([]);
  const [limit, setLimit] = useState(false);
  const [q, setQ] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [say, toast] = useToast();
  const load = () => {
    securityAPI.settings().then(({ data }) => { setS(data); setLimit(data.allowed_countries.length > 0); }).catch((e) => setErr(e?.response?.data?.detail || 'Impossible de charger.'));
    securityAPI.users().then(({ data }) => setLocked(data.rows.filter((u) => u.locked_until && new Date(u.locked_until) > new Date()))).catch(() => {});
  };
  useEffect(load, []);
  const sorted = useMemo(() => [...CODES].sort((a, b) => cname(a).localeCompare(cname(b), 'fr')), []);
  if (!s) return err ? <p className="rounded-xl bg-[#FEF2F2] px-4 py-3 text-[13.5px] text-[#B91C1C]">{err}</p> : <Loading />;
  const chosen = s.allowed_countries;
  const toggle = (c) => setS({ ...s, allowed_countries: chosen.includes(c) ? chosen.filter((x) => x !== c) : [...chosen, c] });
  const save = async () => {
    setErr(''); setBusy(true);
    try {
      const { data } = await securityAPI.saveSettings({ max_failed: Number(s.max_failed), lock_minutes: Number(s.lock_minutes), alert_new_country: s.alert_new_country,
                                                         allowed_countries: limit ? chosen : [] });
      setS({ ...s, ...data }); say('Paramètres de sécurité enregistrés.');
    } catch (e) { setErr(e?.response?.data?.detail?.[0]?.msg || e?.response?.data?.detail || 'Enregistrement impossible.'); }
    setBusy(false);
  };
  const results = sorted.filter((c) => !q || cname(c).toLowerCase().includes(q.toLowerCase()) || c.toLowerCase() === q.toLowerCase()).slice(0, 40);

  return (
    <div className="crm">
      <header className="mb-4">
        <Breadcrumb items={[['Super Admin', '/admin'], ['Sécurité', '/admin/securite'], ['Paramètres sécurité']]} />
        <h1 className="text-[28px] font-bold leading-tight text-[#0B1C3F]">Paramètres sécurité</h1>
        <p className="text-[15px] text-[#475569]">Protégez les comptes de l'équipe FidClic. {!boss && 'Seul le Super Admin peut modifier ces réglages.'}</p>
      </header>
      <fieldset disabled={!boss} className="grid items-start gap-4 xl:grid-cols-[1fr_1fr]">
        <Card>
          <Head icon={Lock} title="Blocage après plusieurs erreurs" />
          <p className="mb-3 text-[13px] text-[#475569]">Après trop de mots de passe (ou de codes 2FA) erronés, le compte est bloqué un moment, même avec le bon mot de passe.</p>
          <div className="grid gap-3 sm:grid-cols-2">
            <label><span className="mb-1 block text-[12px] text-[#64748B]">Nombre d'erreurs avant blocage</span><input type="number" min={2} max={20} className={inputCls} value={s.max_failed} onChange={(e) => setS({ ...s, max_failed: e.target.value })} /></label>
            <label><span className="mb-1 block text-[12px] text-[#64748B]">Durée du blocage (minutes)</span><input type="number" min={1} max={1440} className={inputCls} value={s.lock_minutes} onChange={(e) => setS({ ...s, lock_minutes: e.target.value })} /></label>
          </div>
          <div className="mt-4">
            <p className="mb-2 text-[13px] font-semibold text-[#0B1C3F]">Comptes bloqués en ce moment</p>
            <ul className="space-y-1.5">
              {locked.map((u) => (
                <li key={u.email} className="flex items-center gap-2 rounded-lg border border-[#FCA5A5] bg-[#FEF2F2] px-3 py-2 text-[13px]">
                  <ShieldAlert size={15} className="text-[#E11D48]" /><span className="flex-1">{u.name} <span className="text-[#64748B]">— jusqu'à {new Date(u.locked_until).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}</span></span>
                  {boss && <button type="button" onClick={() => securityAPI.unlock(u.email).then(() => { say('Compte débloqué.'); load(); })} className="inline-flex items-center gap-1 text-[12.5px] text-[#2F6BFF]"><Unlock size={13} /> Débloquer</button>}
                </li>
              ))}
              {!locked.length && <li className="text-[12.5px] text-[#94A3B8]">Aucun compte bloqué.</li>}
            </ul>
          </div>
        </Card>

        <Card>
          <Head icon={BellRing} title="Connexion depuis un nouveau pays" />
          <label className="flex items-start gap-3 text-[13.5px] text-[#334155]">
            <input type="checkbox" className="mt-1 accent-[#2F6BFF]" checked={s.alert_new_country} onChange={(e) => setS({ ...s, alert_new_country: e.target.checked })} />
            <span>M'alerter quand un membre de l'équipe se connecte depuis un pays où il ne s'était jamais connecté. La connexion passe, elle est marquée « suspecte » et une alerte arrive dans la cloche du Super Admin.</span>
          </label>
        </Card>

        <Card className="xl:col-span-2">
          <Head icon={Globe2} title="Pays autorisés" />
          <label className="mb-3 flex items-start gap-3 text-[13.5px] text-[#334155]">
            <input type="checkbox" className="mt-1 accent-[#2F6BFF]" checked={limit} onChange={(e) => setLimit(e.target.checked)} />
            <span>Limiter les connexions de l'équipe FidClic à certains pays. Depuis tout autre pays, la connexion est refusée (« Bloquée ») et vous êtes alerté.</span>
          </label>
          {limit && (
            <>
              <div className="mb-3 flex flex-wrap gap-1.5">
                {chosen.map((c) => <span key={c} className="inline-flex items-center gap-1.5 rounded-full bg-[#EAF1FF] px-2.5 py-1 text-[12.5px] text-[#2F6BFF]">{flag(c)} {cname(c)}{boss && <button type="button" aria-label={`Retirer ${cname(c)}`} onClick={() => toggle(c)}><X size={13} /></button>}</span>)}
                {!chosen.length && <span className="text-[12.5px] text-[#D97706]">Choisissez au moins un pays.</span>}
              </div>
              <label className="relative block max-w-md"><Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
                <input className={`${inputCls} pl-9`} placeholder="Chercher un pays…" value={q} onChange={(e) => setQ(e.target.value)} /></label>
              <div className="mt-2 grid max-h-64 gap-1 overflow-y-auto sm:grid-cols-2 lg:grid-cols-4">
                {results.map((c) => (
                  <label key={c} className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-[13px] hover:bg-[#F4F7FC]">
                    <input type="checkbox" className="accent-[#2F6BFF]" checked={chosen.includes(c)} onChange={() => toggle(c)} />{flag(c)} {cname(c)}
                  </label>
                ))}
              </div>
            </>
          )}
          <p className="mt-3 flex items-start gap-2 rounded-lg bg-[#F8FAFF] px-3 py-2 text-[12.5px] text-[#475569]"><Info size={14} className="mt-0.5 shrink-0" />
            {s.current_country ? <>Vous êtes actuellement en {flag(s.current_country)} <strong>{cname(s.current_country)}</strong> : ce pays doit rester dans la liste.</> : "Pays actuel inconnu (développement local) : rien n'est bloqué quand le pays n'est pas connu."} Les commerces ne sont pas concernés.
          </p>
        </Card>
      </fieldset>
      {boss && (
        <div className="mt-4 flex items-center justify-end gap-3">
          {err && <p className="text-[13px] text-[#C0392B]">{err}</p>}
          <button type="button" disabled={busy || (limit && !chosen.length)} onClick={save} className="inline-flex h-11 items-center gap-2 rounded-xl px-6 text-[14px] font-semibold text-white disabled:opacity-50" style={{ background: BLUE }}>{busy && <Loader2 size={15} className="animate-spin" />} Enregistrer</button>
        </div>
      )}
      {toast}
    </div>
  );
}
