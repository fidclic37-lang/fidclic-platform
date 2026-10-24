import React, { useEffect, useState } from 'react';
import { X, Loader2, ShoppingBag, Store } from 'lucide-react';
import { ownerAPI } from '../lib/api';
import ClientProfile from './ClientProfile';

/* « Historique d'achats » of one client (user, 2026-10-15): every visit, newest
   first — the day and the hour (Paris), the establishment, what was taken
   from the catalogue with quantities, the amount, and the tampons / points
   the card got. Totals on top: visits, spent, average basket.
   It opens on « Profil » (FidClic IA, 2026-10-24): what the visits say about
   the client; « Historique d'achats » is the tab beside it. */

const TZ = 'Europe/Paris';
const eur = (n) => `${new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n ?? 0)} €`;
const day = (iso) => {
  if (!iso) return '—';
  const t = new Date(iso).toLocaleDateString('fr-FR', { timeZone: TZ, weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' });
  return t.charAt(0).toUpperCase() + t.slice(1);     // « Jeu. 15 oct. 2026 », not « Jeu. 15 Oct. »
};
const hour = (iso) => (iso ? new Date(iso).toLocaleTimeString('fr-FR', { timeZone: TZ, hour: '2-digit', minute: '2-digit' }) : '');
const shortDay = (iso) => (iso ? new Date(iso).toLocaleDateString('fr-FR', { timeZone: TZ }) : '—');

export default function ClientPurchases({ clientId, onClose, initialTab = 'profil' }) {
  const [d, setD] = useState(null);
  const [page, setPage] = useState(1);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState(initialTab);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    ownerAPI.clientPurchases(clientId, { page, per_page: 20 })
      .then(({ data }) => { if (alive) { setD(data); setError(''); } })
      .catch((e) => { if (alive) setError(e?.response?.data?.detail || "L'historique n'a pas pu être chargé."); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [clientId, page]);
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const unit = d?.unit === 'stamps' ? 'stamps' : 'points';
  const gain = (r) => {
    const v = r[unit];
    if (v === null || v === undefined) return null;
    const word = unit === 'stamps' ? (Math.abs(v) > 1 ? 'tampons' : 'tampon') : (Math.abs(v) > 1 ? 'points' : 'point');
    return `${v > 0 ? '+' : ''}${v} ${word}`;
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-[#0B1C3F]/30" onClick={onClose}>
      <aside role="dialog" aria-modal="true" aria-label={tab === 'profil' ? 'Profil client' : "Historique d'achats"} onClick={(e) => e.stopPropagation()}
             className="flex h-full w-full max-w-[560px] flex-col bg-white shadow-[0_40px_90px_-30px_rgba(11,28,63,.6)]">
        <header className="flex items-start justify-between gap-3 border-b border-[#EEF3FB] px-6 py-5">
          <div className="min-w-0">
            <p className="text-[12px] font-semibold uppercase tracking-[0.04em] text-[#64748B]">{tab === 'profil' ? 'Profil client' : <>Historique d&apos;achats</>}</p>
            <h2 translate="no" className="notranslate truncate text-[19px] font-bold text-[#0B1C3F]">{d?.client?.name || '…'}</h2>
            {d?.client?.barcode_id && <p className="text-[12px] text-[#94A3B8]">{d.client.barcode_id}</p>}
          </div>
          <button type="button" onClick={onClose} aria-label="Fermer"
                  className="flex h-9 w-9 items-center justify-center rounded-lg text-[#64748B] hover:bg-[#F4F7FC]"><X size={18} /></button>
        </header>

        <div role="tablist" className="flex gap-1 border-b border-[#EEF3FB] px-6">
          {[['profil', 'Profil'], ['achats', "Historique d'achats"]].map(([k, l]) => (
            <button key={k} type="button" role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
                    className={`-mb-px border-b-2 px-3 py-2.5 text-[13px] font-semibold ${tab === k ? 'border-[#2F6BFF] text-[#2F6BFF]' : 'border-transparent text-[#64748B] hover:text-[#0B1C3F]'}`}>
              {l}
            </button>
          ))}
        </div>

        {tab === 'profil' && (
          <div className="flex-1 overflow-y-auto px-6 py-4"><ClientProfile clientId={clientId} /></div>
        )}
        {tab === 'achats' && (<>

        {d && (
          <div className="grid grid-cols-3 gap-3 border-b border-[#EEF3FB] px-6 py-4" data-testid="purchase-totals">
            {[['Visites', String(d.totals.visits)], ['Total dépensé', eur(d.totals.spent)], ['Panier moyen', eur(d.totals.average)]].map(([l, v]) => (
              <div key={l} className="rounded-xl bg-[#F6F9FF] px-3 py-2.5">
                <p className="text-[11.5px] text-[#64748B]">{l}</p>
                <p className="text-[16px] font-bold tabular-nums text-[#0B1C3F]">{v}</p>
              </div>
            ))}
            {d.totals.visits > 0 && (
              <p className="col-span-3 text-[12px] text-[#64748B]">
                Première visite le {shortDay(d.totals.first)} · dernière le {shortDay(d.totals.last)}
              </p>
            )}
          </div>
        )}

        <div className="flex-1 overflow-y-auto px-6 py-4">
          {loading && !d && <p className="flex items-center gap-2 text-[13px] text-[#64748B]"><Loader2 size={16} className="animate-spin" /> Chargement…</p>}
          {error && <p className="rounded-lg bg-[#FEF2F2] px-3 py-2.5 text-[13px] text-[#B91C1C]">{error}</p>}
          {d && d.rows.length === 0 && (
            <p className="rounded-xl border border-dashed border-[#DCE7FB] px-4 py-8 text-center text-[13px] text-[#64748B]">
              Aucun achat enregistré pour ce client pour l&apos;instant.
            </p>
          )}
          <ul className="space-y-3">
            {(d?.rows || []).map((r) => (
              <li key={r.id} className="rounded-xl border border-[#EEF3FB] p-4" data-testid="purchase-row">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-[13.5px] font-semibold text-[#0B1C3F]">{day(r.at)}</p>
                    <p className="text-[12px] text-[#64748B]">
                      à {hour(r.at)}
                      {r.store && <span className="ml-1.5 inline-flex items-center gap-1"><Store size={12} /> {r.store}</span>}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="text-[16px] font-bold tabular-nums text-[#0B1C3F]">{r.amount === null ? '—' : eur(r.amount)}</p>
                    {gain(r) && <p className="text-[12px] font-semibold text-[#0F8B58]">{gain(r)}</p>}
                  </div>
                </div>
                {r.items.length > 0 ? (
                  <ul className="mt-3 space-y-1 border-t border-[#F4F7FC] pt-3">
                    {r.items.map((it, i) => (
                      <li key={`${it.name}-${i}`} className="flex justify-between gap-3 text-[12.5px] text-[#334155]">
                        <span className="flex min-w-0 items-center gap-1.5"><ShoppingBag size={13} className="shrink-0 text-[#94A3B8]" />
                          <span className="truncate">{it.qty} × {it.name}</span></span>
                        <span className="tabular-nums text-[#64748B]">{eur(it.total)}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-2 text-[12px] text-[#94A3B8]">Montant saisi à la caisse, sans détail des produits.</p>
                )}
              </li>
            ))}
          </ul>
        </div>

        {d && d.pages > 1 && (
          <footer className="flex items-center justify-between border-t border-[#EEF3FB] px-6 py-3 text-[13px]">
            <button type="button" disabled={page <= 1 || loading} onClick={() => setPage(page - 1)}
                    className="rounded-lg border border-[#E2E8F0] px-3 py-1.5 font-semibold text-[#334155] disabled:opacity-40">Plus récents</button>
            <span className="text-[#64748B]">Page {d.page} / {d.pages}</span>
            <button type="button" disabled={page >= d.pages || loading} onClick={() => setPage(page + 1)}
                    className="rounded-lg border border-[#E2E8F0] px-3 py-1.5 font-semibold text-[#334155] disabled:opacity-40">Plus anciens</button>
          </footer>
        )}
        </>)}
      </aside>
    </div>
  );
}
