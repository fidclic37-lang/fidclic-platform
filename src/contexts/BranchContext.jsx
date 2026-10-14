/**
 * BranchContext — app-wide selected-branch state.
 *
 * Per the v2 spec (item #18):
 *   "When the owner chooses a store on the dashboard, every page should
 *    automatically filter to that store. They should not have to re-select
 *    the branch on each page."
 *
 * Stored in localStorage (key: 'ft_selected_branch_v1') so reloads keep
 * the chosen branch. « Toutes les branches » is gone (user, 2026-10-12): with
 * several establishments one is always chosen — after login (StoreGate) and
 * from the sidebar. `null` only on a one-shop account (the shop itself).
 *
 * Usage:
 *   const { branchId, setBranchId, branches, setBranches } = useBranch();
 */
import React, { createContext, useCallback, useContext, useEffect, useState } from 'react';

const STORAGE_KEY = 'ft_selected_branch_v1';
export const PICK_KEY = 'ft_pick_store';          // set at login: choose the establishment first

/** The establishments this account works in: the owner all the open ones, an
 *  administrateur those the owner gave it, a manager / employé its one. */
export function allowedStores(branches, user) {
  const open = (Array.isArray(branches) ? branches : []).filter((b) => b && b.id && b.status !== 'closed');
  const mine = Array.isArray(user?.branch_ids) ? user.branch_ids : null;
  return user?.role === 'business_owner' || !mine ? open : open.filter((b) => mine.includes(b.id));
}

const BranchContext = createContext({
  branchId: null,
  setBranchId: () => {},
  branches: [],
  setBranches: () => {},
  loaded: false,
});

export const BranchProvider = ({ children }) => {
  // Read once on mount; ignore if storage is unavailable (e.g. private mode)
  const [branchId, _setBranchId] = useState(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw || raw === 'null' || raw === 'undefined') return null;
      return raw;
    } catch { return null; }
  });
  const [branches, _setBranches] = useState([]);
  const [loaded, setLoaded] = useState(false);       // the list came back (empty = a one-shop account)
  const setBranches = useCallback((list) => { _setBranches(Array.isArray(list) ? list : []); setLoaded(true); }, []);

  const setBranchId = (id) => {
    _setBranchId(id);
    try {
      if (id == null) localStorage.removeItem(STORAGE_KEY);
      else localStorage.setItem(STORAGE_KEY, id);
    } catch { /* ignore */ }
  };

  // If the selected branch disappears from the latest branch list, reset.
  useEffect(() => {
    if (branchId && branches.length > 0 && !branches.some((b) => b.id === branchId)) {
      setBranchId(null);
    }
  }, [branchId, branches]);

  return (
    <BranchContext.Provider value={{ branchId, setBranchId, branches, setBranches, loaded }}>
      {children}
    </BranchContext.Provider>
  );
};

export const useBranch = () => useContext(BranchContext);
