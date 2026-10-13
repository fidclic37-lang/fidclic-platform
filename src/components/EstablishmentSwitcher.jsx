import React, { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ChevronDown, Check, Plus, Store, Link2 } from 'lucide-react';
import { ownerAPI } from '../lib/api';
import { useBranch, allowedStores } from '../contexts/BranchContext';
import { useAuth } from '../contexts/AuthContext';

/**
 * EstablishmentSwitcher — the line under the FidClic mark in the sidebar.
 *
 * This is the franchise control: it names the shop whose figures are on
 * screen, and picking another one filters every page at once, because it
 * writes to the same BranchContext the whole dashboard already reads.
 *
 * It replaces the pills that used to sit in the top bar — choosing which shop
 * you are looking at belongs next to the brand, not in the search bar.
 *
 * A single-shop account still sees its own name, because that is useful, but
 * gets no menu to open: there is nothing to switch to. "Ajouter un
 * établissement" is always offered, so a shop that grows can find it.
 */
export default function EstablishmentSwitcher({ tenant, collapsed }) {
  const navigate = useNavigate();
  const { branchId, setBranchId, branches, setBranches } = useBranch();
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  const box = useRef(null);

  useEffect(() => {
    let alive = true;
    ownerAPI.getBranches()
      .then(({ data }) => { if (alive) setBranches(data?.branches || data || []); })
      .catch(() => { /* no branches feature on this plan — the name still shows */ });
    return () => { alive = false; };
  }, [setBranches]);

  useEffect(() => {
    const away = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', away);
    return () => document.removeEventListener('mousedown', away);
  }, []);

  // What this account may pick: the owner every establishment, an
  // administrateur only its own, a manager or an employé none — they work in
  // one establishment and see its name, without a menu.
  // « Toutes les branches » is gone (user, 2026-10-12): one establishment is
  // always chosen (StoreGate, after login); this menu switches to another.
  const role = user?.role;
  const list = allowedStores(branches, user);
  const fixed = role === 'manager' || role === 'staff';
  const active = branchId ? list.find((b) => b.id === branchId) : null;
  const label = active?.name || list[0]?.name || tenant?.name || 'Mon établissement';

  if (fixed && !collapsed) {
    return (
      <div className="px-3 pb-2">
        <span className="flex items-center gap-1.5 px-1.5 py-1 text-[12.5px] font-medium text-[#475569]">
          <Store size={13} className="shrink-0 text-[#94A3B8]" />
          <span className="min-w-0 truncate" translate="no">{label}</span>
        </span>
      </div>
    );
  }

  if (collapsed) {
    return (
      <div className="flex justify-center px-2 pb-2" title={label}>
        <span className="flex h-7 w-7 items-center justify-center rounded-lg"
              style={{ background: '#EAF1FF', color: '#2F6BFF' }}>
          <Store size={14} />
        </span>
      </div>
    );
  }

  const pick = (id) => { setBranchId(id); setOpen(false); };

  return (
    <div className="relative px-3 pb-2" ref={box}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="flex w-full items-center gap-1.5 rounded-lg px-1.5 py-1 text-left transition-colors hover:bg-[#F4F7FC]"
      >
        <span className="min-w-0 flex-1 truncate text-[12.5px] font-medium" style={{ color: '#475569' }} translate="no">
          {label}
        </span>
        <ChevronDown size={14} className="shrink-0" style={{ color: '#94A3B8' }} />
      </button>

      {open && (
        <div className="absolute left-3 right-3 top-full z-40 mt-1 overflow-hidden rounded-xl border border-[#E6EEFB] bg-white py-1 shadow-[0_24px_60px_-28px_rgba(11,28,63,.5)]">
          {list.map((b) => (
            <button key={b.id} type="button" onClick={() => pick(b.id)}
                    className="flex w-full items-center gap-2 px-3 py-2 text-left text-[12.5px] text-[#334155] hover:bg-[#F4F7FC]">
              <span className="w-4 shrink-0">{branchId === b.id && <Check size={14} className="text-[#2F6BFF]" />}</span>
              <span className="min-w-0 flex-1 truncate" translate="no">{b.name}</span>
            </button>
          ))}
          {list.length === 0 && (
            <p className="px-3 py-2 text-[12px] leading-snug text-[#94A3B8]">
              Un seul établissement pour l'instant.
            </p>
          )}

          {tenant?.slug && (
            <>
              <span className="my-1 block h-px bg-[#EEF3FB]" />
              {/* the chosen establishment's own signup link (multi-store, 2026-10-12) */}
              <a href={`/join/${tenant.slug}${list.length > 1 && active?.slug ? `/${active.slug}` : ''}`} target="_blank" rel="noreferrer"
                 className="flex w-full items-center gap-2 px-3 py-2 text-left text-[12px] text-[#64748B] hover:bg-[#F4F7FC]">
                <Link2 size={13} className="shrink-0" />
                <span className="min-w-0 flex-1 truncate font-mono">/join/{tenant.slug}{list.length > 1 && active?.slug ? `/${active.slug}` : ''}</span>
              </a>
            </>
          )}

          {role === 'business_owner' && <span className="my-1 block h-px bg-[#EEF3FB]" />}
          {role === 'business_owner' && <button type="button"
                  onClick={() => { setOpen(false); navigate('/dashboard/parametres/etablissement'); }}
                  className="flex w-full items-center gap-2 px-3 py-2 text-left text-[12.5px] font-semibold text-[#2F6BFF] hover:bg-[#F4F7FC]">
            <Plus size={14} className="shrink-0" /> Ajouter un établissement
          </button>}
        </div>
      )}
    </div>
  );
}
