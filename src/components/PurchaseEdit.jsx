import React, { useMemo, useState } from 'react';
import { Loader2, Minus, Plus, Search, Trash2, X, AlertTriangle } from 'lucide-react';
import { ownerAPI } from '../lib/api';

/* Historique d'achats › Modifier un achat (user, 2026-11-26): the business
   corrects what the client bought — the products come from ITS catalogue
   (the server prices them), the quantities, the amount the till really took,
   the day and the hour — or deletes the purchase. The client's total and
   palier follow on the server; tampons and points already given do not move.
   Inline, under the row; big hit areas (44px) because it is used on phones. */

const TZ = 'Europe/Paris';
const eur = (n) => `${new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n ?? 0)} €`;
const pad = (n) => String(n).padStart(2, '0');
// an ISO instant → the <input type="datetime-local"> value, in the browser's zone
const toLocalInput = (iso) => {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
};
const sameLines = (a, b) => a.length === b.length && a.every((x, i) => x.item_id === b[i].item_id && x.qty === b[i].qty);
const err = (e, fallback) => e?.response?.data?.detail || fallback;

const btn = 'inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg text-[14px] font-semibold transition disabled:opacity-40';

export default function PurchaseEdit({ clientId, row, catalogue, onClose, onSaved, onDeleted }) {
  const original = useMemo(() => (row.items || []).map((it) => ({
    item_id: it.item_id || null, name: it.name, price: it.price ?? 0, qty: it.qty || 1,
    stale: !it.item_id || !(catalogue || []).some((p) => p.id === it.item_id),
  })), [row, catalogue]);
  const [lines, setLines] = useState(original);
  const [manual, setManual] = useState(Boolean(row.amount_manual) || original.length === 0);
  const [amount, setAmount] = useState(row.amount === null || row.amount === undefined ? '' : String(row.amount));
  const [when, setWhen] = useState(toLocalInput(row.at));
  const [reason, setReason] = useState('');
  const [q, setQ] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const [confirmDelete, setConfirmDelete] = useState(false);

  const catalogTotal = useMemo(() => lines.reduce((s, l) => s + (l.price || 0) * (l.qty || 0), 0), [lines]);
  const total = manual ? Number(String(amount).replace(',', '.')) : catalogTotal;
  const linesChanged = !sameLines(lines, original);
  const hasStale = lines.some((l) => l.stale);
  const cat = catalogue || [];
  // the WHOLE catalogue, by category, as the Scan page's picker (user,
  // 2026-11-26): the list scrolls inside its box so the amount and the
  // buttons below never leave the screen
  const groups = useMemo(() => {
    const s = q.trim().toLowerCase();
    const pool = s ? cat.filter((p) => p.name.toLowerCase().includes(s) || (p.category || '').toLowerCase().includes(s)) : cat;
    const m = new Map();
    pool.forEach((p) => { const k = (p.category || '').trim() || 'Autres'; if (!m.has(k)) m.set(k, []); m.get(k).push(p); });
    return [...m.entries()];
  }, [q, cat]);
  const qtyOf = (id) => lines.find((l) => l.item_id === id)?.qty || 0;

  const bump = (i, d) => setLines((ls) => ls.map((l, j) => (j === i ? { ...l, qty: Math.max(0, Math.min(999, l.qty + d)) } : l)).filter((l) => l.qty > 0));
  const remove = (i) => setLines((ls) => ls.filter((_l, j) => j !== i));
  const add = (p) => {
    setLines((ls) => {
      const i = ls.findIndex((l) => l.item_id === p.id);
      if (i >= 0) return ls.map((l, j) => (j === i ? { ...l, qty: Math.min(999, l.qty + 1) } : l));
      return [...ls, { item_id: p.id, name: p.name, price: p.price, qty: 1, stale: false }];
    });
    setQ('');
  };

  const save = async () => {
    setMsg('');
    const body = {};
    if (linesChanged || (manual && lines.length === 0 && original.length > 0)) {
      if (hasStale) { setMsg("Une ligne n'est plus dans votre catalogue : retirez-la ou remplacez-la avant d'enregistrer."); return; }
      body.items = lines.map((l) => ({ item_id: l.item_id, qty: l.qty }));
    }
    if (manual) {
      const a = Number(String(amount).replace(',', '.'));
      if (!Number.isFinite(a) || a < 0) { setMsg('Indiquez le montant encaissé (0 ou plus).'); return; }
      if (a !== row.amount || !row.amount_manual || body.items) { body.amount_paid = Math.round(a * 100) / 100; body.amount_manual = true; }
    } else if (row.amount_manual && !body.items) {
      // the till's figure dropped: the catalogue's total again
      body.items = lines.map((l) => ({ item_id: l.item_id, qty: l.qty }));
    }
    if (when && when !== toLocalInput(row.at)) {
      const d = new Date(when);
      if (Number.isNaN(d.getTime())) { setMsg('Date invalide.'); return; }
      body.visit_time = d.toISOString();
    }
    if (!Object.keys(body).length) { onClose(); return; }
    if (reason.trim()) body.reason = reason.trim();
    setBusy(true);
    try {
      const { data } = await ownerAPI.editClientPurchase(clientId, row.id, body);
      onSaved(data);
    } catch (e) { setMsg(err(e, "L'achat n'a pas pu être modifié.")); } finally { setBusy(false); }
  };

  const del = async () => {
    setBusy(true); setMsg('');
    try {
      const { data } = await ownerAPI.cancelClientPurchase(clientId, row.id, reason.trim() ? { reason: reason.trim() } : {});
      onDeleted(data);
    } catch (e) { setMsg(err(e, "L'achat n'a pas pu être supprimé.")); } finally { setBusy(false); }
  };

  return (
    <div data-testid="purchase-editor" className="mt-3 space-y-4 rounded-xl border border-[#DCE7FB] bg-[#F8FAFF] p-3 sm:p-4" onClick={(e) => e.stopPropagation()}>
      <div className="flex items-center justify-between gap-2">
        <p className="text-[13px] font-bold text-[#0B1C3F]">Modifier cet achat</p>
        <button type="button" onClick={onClose} aria-label="Fermer la modification" className={`${btn} text-[#64748B] hover:bg-white`}><X size={18} /></button>
      </div>

      <label className="block">
        <span className="mb-1 block text-[12px] font-semibold text-[#475569]">Date et heure</span>
        <input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} max={toLocalInput(new Date().toISOString())}
               className="min-h-[44px] w-full rounded-lg border border-[#E2E8F0] bg-white px-3 text-[14px] text-[#0B1C3F]" />
      </label>

      <div>
        <p className="mb-1 text-[12px] font-semibold text-[#475569]">Produits</p>
        {lines.length === 0 && <p className="rounded-lg border border-dashed border-[#DCE7FB] bg-white px-3 py-3 text-[12.5px] text-[#64748B]">Aucun produit : ajoutez-en depuis le catalogue, ou indiquez seulement le montant.</p>}
        <ul className="space-y-2">
          {lines.map((l, i) => (
            <li key={`${l.item_id || l.name}-${i}`} className="flex flex-wrap items-center gap-2 rounded-lg border border-[#E2E8F0] bg-white px-2 py-1.5">
              <div className="min-w-0 flex-1 basis-[140px]">
                <p className="truncate text-[13.5px] font-semibold text-[#0B1C3F]">{l.name}</p>
                <p className="text-[12px] text-[#64748B]">{eur(l.price)} l&apos;unité{l.stale && <span className="ml-1 inline-flex items-center gap-1 text-[#B45309]"><AlertTriangle size={12} /> plus au catalogue</span>}</p>
              </div>
              <div className="flex items-center gap-1">
                <button type="button" onClick={() => bump(i, -1)} aria-label={`Retirer un ${l.name}`} className={`${btn} border border-[#E2E8F0] text-[#0B1C3F] hover:bg-[#F4F7FC]`}><Minus size={16} /></button>
                <span className="w-8 text-center text-[15px] font-bold tabular-nums text-[#0B1C3F]" aria-label="Quantité">{l.qty}</span>
                <button type="button" onClick={() => bump(i, 1)} aria-label={`Ajouter un ${l.name}`} className={`${btn} border border-[#E2E8F0] text-[#0B1C3F] hover:bg-[#F4F7FC]`}><Plus size={16} /></button>
                <button type="button" onClick={() => remove(i)} aria-label={`Supprimer la ligne ${l.name}`} className={`${btn} text-[#B91C1C] hover:bg-[#FEF2F2]`}><Trash2 size={16} /></button>
              </div>
              <span className="w-full text-right text-[13px] font-semibold tabular-nums text-[#334155] sm:w-auto sm:basis-[80px]">{eur(l.price * l.qty)}</span>
            </li>
          ))}
        </ul>

        <div className="relative mt-2">
          <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ajouter un produit du catalogue…" disabled={cat.length === 0}
                 className="min-h-[44px] w-full rounded-lg border border-[#E2E8F0] bg-white pl-9 pr-3 text-[14px] text-[#0B1C3F] disabled:bg-[#F4F7FC]" />
        </div>
        {cat.length === 0 ? (
          <p className="mt-1.5 text-[12px] text-[#64748B]">Votre catalogue est vide : ajoutez vos produits dans « Catalogue produits » pour les choisir ici.</p>
        ) : (
          <div className="mt-1.5 max-h-72 overflow-y-auto rounded-lg border border-[#E2E8F0] bg-white">
            <ul aria-label="Produits du catalogue">
              {groups.map(([category, items]) => (
                <React.Fragment key={category}>
                  <li role="presentation" className="sticky top-0 z-[1] border-b border-[#F1F5F9] bg-[#F8FAFC] px-3 py-1.5 text-[11px] font-bold uppercase tracking-wider text-[#64748B]">
                    {category}
                  </li>
                  {items.map((p) => {
                    const n = qtyOf(p.id);
                    return (
                      <li key={p.id}>
                        <button type="button" onClick={() => add(p)}
                                className="flex min-h-[44px] w-full items-center gap-3 border-b border-[#F1F5F9] px-3 py-2 text-left hover:bg-[#F4F7FC] last:border-b-0">
                          <span className="min-w-0 flex-1 truncate text-[14px] text-[#0B1C3F]">{p.name}</span>
                          {n > 0 && <span className="rounded-full bg-[#2F6BFF] px-2 py-0.5 text-[11.5px] font-bold text-white" aria-label={`${n} dans cet achat`}>× {n}</span>}
                          <span className="w-20 shrink-0 text-right font-mono text-[13px] text-[#475569]">{eur(p.price)}</span>
                          <Plus size={16} className="shrink-0 text-[#10A36B]" />
                        </button>
                      </li>
                    );
                  })}
                </React.Fragment>
              ))}
              {q.trim() && groups.length === 0 && <li className="px-3 py-3 text-[12px] text-[#64748B]">Aucun produit ne correspond.</li>}
            </ul>
          </div>
        )}
      </div>

      <div className="rounded-lg bg-white px-3 py-2.5">
        <div className="flex items-center justify-between text-[13px] text-[#334155]">
          <span>Total catalogue</span><span className="font-semibold tabular-nums">{eur(catalogTotal)}</span>
        </div>
        <label className="mt-2 flex min-h-[44px] items-center gap-2 text-[13px] text-[#0B1C3F]">
          <input type="checkbox" checked={manual} disabled={lines.length === 0} onChange={(e) => setManual(e.target.checked)} className="h-5 w-5" />
          Montant encaissé différent du catalogue
        </label>
        {manual && (
          <label className="block">
            <span className="mb-1 block text-[12px] font-semibold text-[#475569]">Montant encaissé (€)</span>
            <input type="number" inputMode="decimal" min="0" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)}
                   aria-label="Montant encaissé (€)"
                   className="min-h-[44px] w-full rounded-lg border border-[#E2E8F0] px-3 text-[15px] font-semibold tabular-nums text-[#0B1C3F]" />
          </label>
        )}
        <div className="mt-2 flex items-center justify-between border-t border-[#EEF3FB] pt-2 text-[14px] font-bold text-[#0B1C3F]" data-testid="editor-total">
          <span>Montant de l&apos;achat</span><span className="tabular-nums">{Number.isFinite(total) ? eur(total) : '—'}</span>
        </div>
        <p className="mt-1.5 text-[11.5px] text-[#64748B]">Le total dépensé et le palier du client suivent. Les tampons et points déjà crédités ne changent pas.</p>
      </div>

      <label className="block">
        <span className="mb-1 block text-[12px] font-semibold text-[#475569]">Raison (facultatif)</span>
        <input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={300} aria-label="Raison (facultatif)" placeholder="Erreur de caisse, produit oublié…"
               className="min-h-[44px] w-full rounded-lg border border-[#E2E8F0] bg-white px-3 text-[14px] text-[#0B1C3F]" />
      </label>

      {msg && <p role="alert" className="rounded-lg bg-[#FEF2F2] px-3 py-2.5 text-[13px] text-[#B91C1C]">{msg}</p>}

      <div className="flex flex-wrap items-center justify-between gap-2">
        {!confirmDelete ? (
          <button type="button" onClick={() => setConfirmDelete(true)} disabled={busy} className={`${btn} px-3 text-[#B91C1C] hover:bg-[#FEF2F2]`}>
            <Trash2 size={15} className="mr-1.5" /> Supprimer cet achat
          </button>
        ) : (
          <div className="flex flex-wrap items-center gap-2 rounded-lg bg-[#FEF2F2] px-3 py-2">
            <span className="text-[12.5px] text-[#991B1B]">La visite, son montant et ce qu&apos;elle a donné à la carte seront retirés.</span>
            <button type="button" onClick={del} disabled={busy} className={`${btn} bg-[#B91C1C] px-3 text-white hover:bg-[#991B1B]`}>
              {busy && <Loader2 size={14} className="mr-1.5 animate-spin" />}Confirmer la suppression
            </button>
            <button type="button" onClick={() => setConfirmDelete(false)} disabled={busy} className={`${btn} px-3 text-[#334155]`}>Garder</button>
          </div>
        )}
        <div className="flex gap-2">
          <button type="button" onClick={onClose} disabled={busy} className={`${btn} border border-[#E2E8F0] bg-white px-4 text-[#334155]`}>Annuler</button>
          <button type="button" onClick={save} disabled={busy} className={`${btn} bg-[#2F6BFF] px-4 text-white hover:bg-[#1E56E0]`}>
            {busy && <Loader2 size={14} className="mr-1.5 animate-spin" />}Enregistrer
          </button>
        </div>
      </div>
    </div>
  );
}
