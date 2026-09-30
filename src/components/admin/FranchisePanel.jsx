import React, { useCallback, useEffect, useState } from 'react';
import { Building2, Inbox, Loader2, Pencil, X } from 'lucide-react';
import { adminAPI } from '../../lib/api';

/* Offre Franchise — sur devis. The requests businesses sent from their
   Abonnement page, the franchises signed, and each one's agreed price and
   limits (set here, applied everywhere through the backend). */

const BLUE = '#2F6BFF';
const inputCls = 'h-10 w-full rounded-lg border border-[#DCE3EE] bg-white px-3 text-[13.5px] text-[#0B1C3F] outline-none focus:border-[#2F6BFF]';
const nf = (n) => (n == null ? '—' : Number(n).toLocaleString('fr-FR'));

export function FranchiseTermsModal({ tenant, onClose, onSaved }) {
  const t = tenant.terms || {};
  const [f, setF] = useState({ price: t.price ?? '', establishments: t.establishments ?? tenant.stores ?? 3, max_customers: t.max_customers ?? '',
                               new_cards_per_month: t.new_cards_per_month ?? '', staff_accounts: t.staff_accounts ?? '', notes: t.notes || '' });
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const num = (v) => (v === '' || v == null ? null : Number(v));
  const save = async () => {
    setBusy(true); setErr('');
    try {
      await adminAPI.setFranchise(tenant.id, { price: Number(f.price), establishments: Number(f.establishments), max_customers: num(f.max_customers),
                                                new_cards_per_month: num(f.new_cards_per_month), staff_accounts: num(f.staff_accounts), notes: f.notes, activate: true });
      onSaved();
    } catch (e) { setErr(e?.response?.data?.detail?.[0]?.msg || e?.response?.data?.detail || 'Enregistrement impossible.'); setBusy(false); }
  };
  const field = (k, label, hint) => (
    <label className="block"><span className="mb-1 block text-[11.5px] text-[#64748B]">{label}</span>
      <input type="number" min={0} className={inputCls} value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} placeholder={hint} /></label>
  );
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-[#0B1C3F]/30 sm:items-center sm:p-6" onClick={onClose}>
      <div className="max-h-[92vh] w-full max-w-lg overflow-y-auto rounded-t-2xl bg-white p-5 shadow-2xl sm:rounded-2xl" onClick={(e) => e.stopPropagation()}>
        <header className="mb-3 flex items-center justify-between">
          <h3 className="text-[16px] font-bold text-[#0B1C3F]">Conditions Franchise — {tenant.name}</h3>
          <button type="button" aria-label="Fermer" onClick={onClose} className="text-[#94A3B8]"><X size={18} /></button>
        </header>
        <p className="mb-3 text-[12.5px] text-[#475569]">Le prix convenu et les limites de ce réseau. Laisser une limite vide garde la valeur par défaut de l'offre Franchise.</p>
        <div className="grid gap-2 sm:grid-cols-2">
          {field('price', 'Prix mensuel (€ HT)', 'ex. 450')}
          {field('establishments', 'Établissements inclus', 'ex. 5')}
          {field('max_customers', 'Clients actifs max.', 'défaut : 50 000')}
          {field('new_cards_per_month', 'Nouvelles cartes / mois', 'défaut : 20 000')}
          {field('staff_accounts', 'Comptes équipe', 'défaut : 50')}
        </div>
        <label className="mt-2 block"><span className="mb-1 block text-[11.5px] text-[#64748B]">Notes internes</span>
          <textarea className={`${inputCls} h-20 py-2`} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} placeholder="Ex. devis du 12/10, engagement 12 mois" /></label>
        <p className="mt-2 text-[12px] text-[#64748B]">Le commerce passe en offre Franchise et son abonnement devient actif. Le paiement : un prix personnalisé dans Stripe, ou une facture à la main.</p>
        {err && <p className="mt-2 text-[13px] text-[#C0392B]">{String(err)}</p>}
        <button type="button" disabled={busy || f.price === '' || !f.establishments} onClick={save} className="mt-3 flex w-full items-center justify-center gap-2 rounded-lg py-2.5 text-[13.5px] font-semibold text-white disabled:opacity-50" style={{ background: BLUE }}>
          {busy && <Loader2 size={15} className="animate-spin" />} Enregistrer les conditions</button>
      </div>
    </div>
  );
}

export default function FranchisePanel() {
  const [d, setD] = useState(null);
  const [edit, setEdit] = useState(null);
  const load = useCallback(() => { adminAPI.franchise().then(({ data }) => setD(data)).catch(() => setD({ requests: [], franchises: [] })); }, []);
  useEffect(() => { load(); }, [load]);
  if (!d) return null;
  return (
    <section className="rounded-2xl border border-[#E6EEFB] bg-white p-5">
      <h2 className="mb-1 flex items-center gap-2 text-[16px] font-bold text-[#0B1C3F]"><Building2 size={18} className="text-[#2F6BFF]" /> Offre Franchise — sur devis</h2>
      <p className="mb-4 text-[13px] text-[#475569]">Pas de prix public : chaque réseau a son devis. Fixez ici le prix et les limites de chaque franchise.</p>
      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <p className="mb-2 flex items-center gap-2 text-[13px] font-semibold text-[#0B1C3F]"><Inbox size={15} /> Demandes en attente ({d.requests.length})</p>
          <ul className="space-y-2">
            {d.requests.map((r) => (
              <li key={r.id} className="rounded-xl border border-[#EDF1F7] p-3 text-[13px]">
                <p className="flex items-center justify-between gap-2"><strong className="text-[#0B1C3F]">{r.tenant_name}</strong><span className="text-[11.5px] text-[#94A3B8]">{r.created_at ? new Date(r.created_at).toLocaleDateString('fr-FR') : ''}</span></p>
                {r.message && <p className="mt-1 text-[12.5px] text-[#475569]">{r.message}</p>}
                <button type="button" onClick={() => setEdit({ id: r.tenant_id, name: r.tenant_name, terms: {} })} className="mt-2 rounded-lg px-3 py-1.5 text-[12.5px] font-medium text-white" style={{ background: BLUE }}>Fixer les conditions</button>
              </li>
            ))}
            {!d.requests.length && <li className="rounded-xl bg-[#F8FAFF] p-3 text-[12.5px] text-[#64748B]">Aucune demande pour l'instant.</li>}
          </ul>
        </div>
        <div>
          <p className="mb-2 text-[13px] font-semibold text-[#0B1C3F]">Franchises ({d.franchises.length})</p>
          <ul className="space-y-2">
            {d.franchises.map((t) => (
              <li key={t.id} className="flex items-center gap-3 rounded-xl border border-[#EDF1F7] p-3 text-[13px]">
                <span className="min-w-0 flex-1"><strong className="block truncate text-[#0B1C3F]">{t.name}</strong>
                  <span className="text-[12px] text-[#64748B]">{t.effective.price ? `${nf(t.effective.price)} € HT / mois` : 'Prix à fixer'} · {t.stores}/{nf(t.effective.establishments)} établissements · {nf(t.effective.max_customers)} clients</span></span>
                <button type="button" aria-label="Modifier" onClick={() => setEdit(t)} className="rounded-lg border border-[#DCE3EE] p-2 text-[#2F6BFF]"><Pencil size={14} /></button>
              </li>
            ))}
            {!d.franchises.length && <li className="rounded-xl bg-[#F8FAFF] p-3 text-[12.5px] text-[#64748B]">Aucune franchise signée.</li>}
          </ul>
        </div>
      </div>
      {edit && <FranchiseTermsModal tenant={edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); load(); }} />}
    </section>
  );
}
