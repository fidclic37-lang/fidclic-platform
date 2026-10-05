import React, { useEffect } from 'react';
import { VIEW_KEY } from '../../lib/api';

/* « Accéder au compte »: the super admin's tab lands here with the account's
   token (full access, or read-only for a team member who may only look) in the URL fragment (never sent to a server, never in a log). It is
   kept for this tab only, then the business's dashboard opens. */
export default function ViewAsEntry() {
  useEffect(() => {
    const t = new URLSearchParams(window.location.hash.slice(1)).get('t');
    window.history.replaceState(null, '', '/voir-compte');
    if (t) {
      try { sessionStorage.setItem(VIEW_KEY, t); } catch (_e) { /* ignore */ }
      window.location.replace('/dashboard');
    }
  }, []);
  return <p className="p-10 text-center text-[14px] text-[#64748B]">Ouverture du compte…</p>;
}
