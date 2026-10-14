import React, { createContext, useContext, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Lock, Sparkles, X, ArrowRight, AlertTriangle } from 'lucide-react';
import { ownerAPI } from '../lib/api';

/* What the business's plan includes (Super admin › Plan Limits).
   A section the plan does not include stays in the menu with a lock; opening
   it — or any call the server refuses with PLAN_FEATURE_DISABLED — shows the
   upgrade prompt. The server enforces it too (features/plan_limits.py). */

const OWNER_ROLES = ['business_owner', 'administrateur', 'manager', 'staff', 'membre'];
export const PlanAccessContext = createContext(null);
export const usePlanAccess = () => useContext(PlanAccessContext);

// /dashboard/<section> → the key used by /owner/plan-access « sections ».
export const sectionOf = (path) => {
  const m = /^\/dashboard\/([^/?#]+)/.exec(path || '');
  return m ? m[1] : null;
};

export function usePlanAccessState(role) {
  const [access, setAccess] = useState(null);
  useEffect(() => {
    if (!OWNER_ROLES.includes(role)) { setAccess(null); return undefined; }
    let alive = true;
    // If the plan cannot be read, nothing is locked here (the server still is).
    const load = () => ownerAPI.planAccess().then(({ data }) => { if (alive) setAccess(data); })
      .catch(() => { if (alive) setAccess((a) => a || { sections: {}, features: {}, locked: {} }); });
    load();
    window.addEventListener('fidclic:plan-changed', load);
    return () => { alive = false; window.removeEventListener('fidclic:plan-changed', load); };
  }, [role]);
  const lockOf = (path) => {
    const s = sectionOf(path);
    if (!access || !s || !(s in (access.sections || {})) || access.sections[s]) return null;
    const key = { analytics: 'advanced_analytics', insights: 'advanced_analytics', map: 'geo_proximity', 'ai-assistant': 'ai', history: 'crm_advanced' }[s] || s;
    return access.locked?.[key] || { code: 'PLAN_FEATURE_DISABLED', feature: key, message: "Cette fonctionnalité n'est pas incluse dans votre offre." };
  };
  const has = (key) => (access ? access.features?.[key] !== false : true);
  return access ? { ...access, ready: true, lockOf, has, locked: access.locked || {} }
    : { ready: !OWNER_ROLES.includes(role), lockOf: () => null, has: () => true, locked: {} };
}

export const openUpgrade = (detail) => window.dispatchEvent(new CustomEvent('fidclic:plan-locked', { detail }));

function UpgradeBody({ detail, onGo }) {
  const up = detail?.upgrade;
  const quota = detail?.code === 'PLAN_QUOTA_REACHED';
  return (
    <div className="text-center">
      <span className="mx-auto mb-3 grid h-14 w-14 place-items-center rounded-2xl bg-[#EAF1FF] text-[#2F6BFF]">{quota ? <AlertTriangle size={26} /> : <Lock size={26} />}</span>
      <h2 className="text-[20px] font-bold text-[#0B1C3F]">{quota ? 'Limite atteinte' : `${detail?.label || 'Cette fonctionnalité'} — offre supérieure`}</h2>
      <p className="mx-auto mt-1.5 max-w-md text-[14px] text-[#475569]">{detail?.message}</p>
      {up && <p className="mt-3 text-[13.5px] text-[#0B1C3F]">Disponible avec l'offre <strong>{up.label}</strong>{up.price ? <> à <strong>{up.price}€</strong> / mois</> : null}.</p>}
      <button type="button" onClick={onGo} className="mt-5 inline-flex items-center gap-2 rounded-xl bg-[#2F6BFF] px-5 py-2.5 text-[14px] font-semibold text-white hover:bg-[#2559DB]">
        <Sparkles size={16} /> {up ? `Passer à ${up.label}` : 'Voir les offres'} <ArrowRight size={16} />
      </button>
    </div>
  );
}

/* The upgrade prompt, mounted once in the dashboard layout. */
export function UpgradeModal() {
  const [detail, setDetail] = useState(null);
  const navigate = useNavigate();
  useEffect(() => {
    const on = (e) => setDetail(e.detail || {});
    window.addEventListener('fidclic:plan-locked', on);
    return () => window.removeEventListener('fidclic:plan-locked', on);
  }, []);
  if (!detail) return null;
  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-[#0B1C3F]/40 p-4" onClick={() => setDetail(null)}>
      <div className="relative w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <button type="button" aria-label="Fermer" onClick={() => setDetail(null)} className="absolute right-3 top-3 rounded-lg p-1 text-[#94A3B8] hover:bg-[#F4F7FC]"><X size={18} /></button>
        <UpgradeBody detail={detail} onGo={() => { setDetail(null); navigate('/dashboard/parametres/abonnement'); }} />
      </div>
    </div>
  );
}

/* Shown in place of a section the plan does not include. */
export function LockedSection({ detail }) {
  const navigate = useNavigate();
  return (
    <div className="mx-auto mt-10 max-w-lg rounded-2xl border border-[#E6EEFB] bg-white p-8 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
      <UpgradeBody detail={detail} onGo={() => navigate('/dashboard/parametres/abonnement')} />
    </div>
  );
}

/* « Vous avez utilisé 80 % de votre limite… » — Super admin › Plan Limits › Messages de limite. */
export function LimitBanner() {
  const [alerts, setAlerts] = useState([]);
  const navigate = useNavigate();
  const today = new Date().toISOString().slice(0, 10);
  const [hidden, setHidden] = useState(() => { try { return localStorage.getItem('fidclic:limit-banner') === today; } catch { return false; } });
  useEffect(() => { ownerAPI.limitAlerts().then(({ data }) => setAlerts(data.alerts || [])).catch(() => {}); }, []);
  if (hidden || !alerts.length) return null;
  const a = alerts.slice().sort((x, y) => y.pct - x.pct)[0];
  const hide = () => { setHidden(true); try { localStorage.setItem('fidclic:limit-banner', today); } catch { /* private mode */ } };
  return (
    <div className="mx-4 mt-3 flex flex-wrap items-center gap-3 rounded-xl border border-[#FDE68A] bg-[#FFFBEB] px-4 py-3 text-[13.5px] text-[#92400E]">
      <AlertTriangle size={17} className="shrink-0" />
      <span className="min-w-0 flex-1 whitespace-pre-line">{a.message}{alerts.length > 1 ? ` (+${alerts.length - 1} autre${alerts.length > 2 ? 's' : ''} limite${alerts.length > 2 ? 's' : ''})` : ''}</span>
      <button type="button" onClick={() => navigate('/dashboard/parametres/abonnement')} className="rounded-lg bg-[#2F6BFF] px-3 py-1.5 text-[12.5px] font-semibold text-white">{a.upgrade ? `Passer à ${a.upgrade.label}` : 'Voir mon abonnement'}</button>
      <button type="button" aria-label="Masquer" onClick={hide} className="rounded-lg p-1 hover:bg-[#FEF3C7]"><X size={15} /></button>
    </div>
  );
}
