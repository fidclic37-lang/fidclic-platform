import React, { useEffect, useState } from 'react';
import { Store, Check, ArrowRight } from 'lucide-react';
import { ownerAPI } from '../lib/api';
import { useBranch, allowedStores, PICK_KEY } from '../contexts/BranchContext';
import { useAuth } from '../contexts/AuthContext';

/**
 * « Choisissez votre établissement » (user, 2026-10-12: « Toutes les branches
 * hata do — login k baad store choose kro »). An account working in several
 * establishments picks one after each login, and whenever the remembered one
 * is not theirs; every page then shows that establishment only, and the
 * sidebar switches to another. One establishment (or a one-shop account): it
 * is chosen for them, no screen.
 */
export default function StoreGate({ children }) {
  const { user } = useAuth();
  const { branchId, setBranchId, branches, setBranches, loaded } = useBranch();
  const [askNow, setAskNow] = useState(() => {
    try { return sessionStorage.getItem(PICK_KEY) === '1'; } catch { return false; }
  });
  const [err, setErr] = useState('');

  useEffect(() => {
    if (loaded) return;
    ownerAPI.getBranches().then(({ data }) => setBranches(data?.branches || data || []))
      .catch(() => { setBranches([]); setErr(''); });
  }, [loaded, setBranches]);

  const list = allowedStores(branches, user);
  const valid = list.some((b) => b.id === branchId);

  // a single establishment is chosen for them; a stale or foreign choice is dropped
  useEffect(() => {
    if (!loaded) return;
    if (list.length === 1 && branchId !== list[0].id) setBranchId(list[0].id);
    else if (list.length === 0 && branchId) setBranchId(null);
  }, [loaded, list.length, branchId]); // eslint-disable-line react-hooks/exhaustive-deps

  const pick = (id) => {
    setBranchId(id);
    try { sessionStorage.removeItem(PICK_KEY); } catch { /* ignore */ }
    setAskNow(false);
  };

  if (!loaded) {
    return <div role="status" aria-label="Chargement" className="flex min-h-[50vh] items-center justify-center"><span className="h-7 w-7 animate-spin rounded-full border-[3px] border-[#DCE6FA] border-t-[#2F6BFF]" /></div>;
  }
  if (list.length < 2 || (valid && !askNow)) return children;

  return (
    <div className="mx-auto flex min-h-[60vh] max-w-xl flex-col justify-center px-4 py-10">
      <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-[#EEF4FF] text-[#2F6BFF]"><Store size={28} /></div>
      <h1 className="text-center text-[24px] font-extrabold text-[#0B1C3F]">Choisissez votre établissement</h1>
      <p className="mx-auto mt-1 max-w-md text-center text-[14px] text-[#475569]">
        Tout ce que vous verrez — clients, visites, carte, campagnes — sera celui de cet établissement. Vous pourrez en changer à tout moment dans le menu.
      </p>
      {err && <p className="mt-3 text-center text-[13px] text-[#B91C1C]">{err}</p>}
      <div className="mt-6 space-y-2" role="listbox" aria-label="Établissements">
        {list.map((b) => {
          const last = b.id === branchId;
          return (
            <button key={b.id} type="button" role="option" aria-selected={last} onClick={() => pick(b.id)}
                    className={`flex w-full items-center gap-3 rounded-2xl border bg-white px-4 py-3.5 text-left transition hover:border-[#2F6BFF] hover:shadow-[0_10px_30px_-20px_rgba(47,107,255,.8)] ${last ? 'border-[#2F6BFF]' : 'border-[#E6EEFB]'}`}>
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#F4F7FC] text-[#2F6BFF]"><Store size={19} /></span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[15px] font-bold text-[#0B1C3F]" translate="no">{b.name || b.id}</span>
                {(b.city || b.street) && <span className="block truncate text-[12.5px] text-[#64748B]">{[b.street, b.city].filter(Boolean).join(', ')}</span>}
              </span>
              {last ? <span className="inline-flex items-center gap-1 text-[12px] font-semibold text-[#2F6BFF]"><Check size={14} /> Dernier choisi</span>
                : <ArrowRight size={17} className="text-[#94A3B8]" />}
            </button>
          );
        })}
      </div>
    </div>
  );
}
