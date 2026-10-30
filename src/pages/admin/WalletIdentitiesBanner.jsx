import React, { useEffect, useState } from 'react';
import { Wallet } from 'lucide-react';
import { adminAPI } from '../../lib/api';

/* Super Admin › Commerces: where each business's own Apple Wallet id stands
   (features/wallet_identities, 2026-10-30). The platform makes them by
   itself; this only says when it cannot — App Store Connect not set, or a
   business whose id Apple refused, with Apple's reason. */
export default function WalletIdentitiesBanner() {
  const [d, setD] = useState(null);
  useEffect(() => {
    let alive = true;
    adminAPI.walletIdentities?.().then(({ data }) => { if (alive) setD(data); }).catch(() => {});
    return () => { alive = false; };
  }, []);
  if (!d) return null;
  const failed = (d.rows || []).filter((r) => r.status === 'failed');
  const tone = !d.configured || failed.length ? { bg: '#FFF4DB', fg: '#92400E' } : { bg: '#E7F7EE', fg: '#0F7A45' };
  return (
    <div className="mt-4 rounded-2xl px-4 py-3 text-[13px]" style={{ background: tone.bg, color: tone.fg }} data-testid="wallet-identities">
      <p className="flex items-center gap-2 font-semibold">
        <Wallet size={15} />
        {!d.configured
          ? 'Apple Wallet : App Store Connect n’est pas configuré — les cartes restent sous l’identifiant commun.'
          : `Apple Wallet : ${d.counts?.ready || 0} commerce${(d.counts?.ready || 0) > 1 ? 's' : ''} avec leur propre identifiant`
            + (d.without ? ` · ${d.without} en attente` : '') + (failed.length ? ` · ${failed.length} en échec` : '')}
      </p>
      {failed.length > 0 && (
        <ul className="mt-1.5 space-y-0.5 pl-6">
          {failed.slice(0, 5).map((r) => (
            <li key={r.tenant_id}><span translate="no" className="notranslate font-medium">{r.name || r.tenant_id}</span> — {r.error} (nouvel essai automatique)</li>
          ))}
        </ul>
      )}
    </div>
  );
}
