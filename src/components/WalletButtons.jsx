import React, { useEffect, useState } from 'react';
import api from '../lib/api';

/**
 * WalletButtons — "Ajouter à Apple Wallet" / "Ajouter à Google Wallet" on the
 * customer's card page. Rendered only for the wallets the backend reports as
 * configured (GET /api/wallet/config), so nothing fake is ever shown.
 *
 *   Apple  → a direct link to /api/card/<id>/apple-wallet.pkpass. Safari on
 *            iOS opens the signed pass in Wallet's "Add" sheet.
 *   Google → GET /api/card/<id>/google-wallet returns the signed
 *            "Save to Google Wallet" URL (loyalty object created on demand).
 *
 * Badge artwork follows Apple's / Google's guidelines (black pill, wallet
 * glyph, French label); swap in the official SVG assets from their brand
 * kits when the marketing site ships them.
 */
export default function WalletButtons({ barcodeId, onError }) {
  const [cfg, setCfg] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.get('/wallet/config').then((r) => setCfg(r.data || {})).catch(() => setCfg({}));
  }, []);

  if (!cfg || (!cfg.apple && !cfg.google)) return null;

  const isApple = /iPad|iPhone|iPod|Macintosh/.test(navigator.userAgent);
  const isAndroid = /Android/.test(navigator.userAgent);
  // Show the wallet that matches the phone first; both on desktop.
  const order = isAndroid ? ['google', 'apple'] : ['apple', 'google'];

  const saveGoogle = async () => {
    setBusy(true);
    try {
      const r = await api.get(`/card/${barcodeId}/google-wallet`);
      window.location.href = r.data.url;
    } catch (e) {
      onError?.(e?.response?.data?.detail || 'Google Wallet indisponible pour le moment.');
    } finally {
      setBusy(false);
    }
  };

  const pill = 'inline-flex w-full items-center justify-center gap-2.5 rounded-xl py-3 text-[14px] font-semibold transition hover:opacity-90 disabled:opacity-60';
  return (
    <div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-2">
      {order.map((k) => {
        if (k === 'apple' && cfg.apple) {
          return (
            <a key="apple" href={`/api/card/${barcodeId}/apple-wallet.pkpass`}
               className={`${pill} bg-black text-white`} style={{ order: isApple ? 0 : 1 }}>
              <svg width="20" height="16" viewBox="0 0 24 20" aria-hidden="true">
                <rect x="1" y="1" width="22" height="18" rx="3" fill="#fff" />
                <rect x="1" y="4" width="22" height="4" fill="#F59E0B" /><rect x="1" y="8" width="22" height="4" fill="#22C55E" />
                <rect x="1" y="12" width="22" height="7" rx="2" fill="#3B82F6" />
              </svg>
              Ajouter à Apple Wallet
            </a>
          );
        }
        if (k === 'google' && cfg.google) {
          return (
            <button key="google" type="button" onClick={saveGoogle} disabled={busy}
                    className={`${pill} bg-[#1F1F1F] text-white`}>
              <svg width="20" height="16" viewBox="0 0 24 20" aria-hidden="true">
                <rect x="1" y="1" width="22" height="18" rx="4" fill="#fff" />
                <path d="M3 8c0-2 1.5-3.5 3.5-3.5H21v4H3z" fill="#EA4335" /><path d="M3 8h18v4H3z" fill="#FBBC05" />
                <path d="M3 12h18v2.5c0 2-1.5 3.5-3.5 3.5H3z" fill="#34A853" /><path d="M3 8v10h6V8z" fill="#4285F4" />
              </svg>
              {busy ? 'Ouverture…' : 'Ajouter à Google Wallet'}
            </button>
          );
        }
        return null;
      })}
    </div>
  );
}
