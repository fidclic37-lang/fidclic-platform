import React, { useState } from 'react';
import { X, Repeat } from 'lucide-react';
import { cabinetOsAPI } from '../lib/api';
import DecimalInput from './DecimalInput';

/**
 * NewSubscriptionModal — write a standing instruction (S13).
 *
 * Creating this IS the approval: the EC/superviseur signs off once on
 * amount + client + day, and from then on the agent executes it monthly —
 * as a DRAFT that still passes the human review queue. Like a bank
 * standing order: sign once, the bank never edits the amount.
 */
export default function NewSubscriptionModal({ tenantId, onClose, onCreated }) {
  const [form, setForm] = useState({
    label: '', buyer_name: '', buyer_siren: '', buyer_address: '',
    description: '', unit_price: '', vat_rate: '20', day_of_month: '1',
    payment_term: 'net30',
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const ht = parseFloat(form.unit_price || 0);
  const ttc = ht * (1 + parseFloat(form.vat_rate || 0) / 100);

  const submit = async () => {
    setBusy(true); setErr('');
    try {
      await cabinetOsAPI.createSubscription(tenantId, {
        label: form.label,
        buyer: { name: form.buyer_name, siren: form.buyer_siren,
                 address: form.buyer_address, is_company: true },
        lines: [{ description: form.description || form.label, quantity: 1,
                  unit_price: parseFloat(form.unit_price || 0),
                  vat_rate: parseFloat(form.vat_rate || 0) }],
        day_of_month: parseInt(form.day_of_month, 10),
        payment_term: form.payment_term,
      });
      await onCreated();
    } catch (e) {
      setErr(e?.response?.data?.detail || 'Création impossible.');
    } finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
         style={{ background: 'rgba(4,6,15,.82)' }} onClick={onClose}>
      <div className="mc-surface rounded-3xl w-full max-w-lg max-h-[90vh] overflow-auto p-6"
           onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between mb-1">
          <div className="flex items-center gap-2">
            <div className="w-9 h-9 rounded-xl flex items-center justify-center"
                 style={{ background: 'linear-gradient(135deg,#7C7CF8,#5B5BE8)' }}>
              <Repeat size={16} color="#fff" />
            </div>
            <h3 className="text-lg font-bold text-[#F8FAFC]">Nouvel abonnement</h3>
          </div>
          <button onClick={onClose} className="text-[#7C879F] hover:text-[#F8FAFC]"><X size={18} /></button>
        </div>
        <p className="text-xs text-[#7C879F] mb-4">
          Vous approuvez UNE FOIS le montant, le client et le jour. Ensuite l'agent
          prépare la facture chaque mois — en brouillon, à valider par un humain.
          L'agent n'inventera jamais un chiffre : il recopie cette instruction.
        </p>

        <div className="space-y-2.5">
          <label className="block">
            <span className="lbl">Nom de l'abonnement *</span>
            <input className="fld" value={form.label} onChange={set('label')}
                   placeholder="Adhésion mensuelle — Gym Metro" />
          </label>
          <label className="block">
            <span className="lbl">Client facturé (nom) *</span>
            <input className="fld" value={form.buyer_name} onChange={set('buyer_name')}
                   placeholder="Gym Metro SARL" />
          </label>
          <div className="grid grid-cols-2 gap-2.5">
            <label className="block">
              <span className="lbl">SIREN du client *</span>
              <input className="fld" value={form.buyer_siren} onChange={set('buyer_siren')}
                     placeholder="552100554" maxLength={9} />
            </label>
            <label className="block">
              <span className="lbl">Jour du mois (1-28) *</span>
              <input className="fld" type="number" min="1" max="28"
                     value={form.day_of_month} onChange={set('day_of_month')} />
            </label>
          </div>
          <label className="block">
            <span className="lbl">Adresse du client *</span>
            <input className="fld" value={form.buyer_address} onChange={set('buyer_address')}
                   placeholder="12 rue du Sport, 37000 Tours" />
          </label>
          <label className="block">
            <span className="lbl">Description de la ligne</span>
            <input className="fld" value={form.description} onChange={set('description')}
                   placeholder="Abonnement mensuel — accès salle" />
          </label>
          <div className="grid grid-cols-3 gap-2.5">
            <label className="block">
              <span className="lbl">Montant HT (€) *</span>
              <DecimalInput className="fld" value={form.unit_price}
                     onChange={(v) => setForm((f) => ({ ...f, unit_price: v }))} placeholder="450" />
            </label>
            <label className="block">
              <span className="lbl">TVA</span>
              <select className="fld" value={form.vat_rate} onChange={set('vat_rate')}>
                <option value="20">20 %</option>
                <option value="10">10 %</option>
                <option value="5.5">5,5 %</option>
                <option value="0">0 %</option>
              </select>
            </label>
            <label className="block">
              <span className="lbl">Échéance</span>
              <select className="fld" value={form.payment_term} onChange={set('payment_term')}>
                <option value="net30">30 jours</option>
                <option value="net45">45 jours</option>
                <option value="net60">60 jours</option>
                <option value="immediate">Comptant</option>
              </select>
            </label>
          </div>
          {ht > 0 && (
            <div className="text-xs text-[#B9C2D6]">
              Chaque mois : <strong>{ht.toFixed(2)} € HT</strong> → {ttc.toFixed(2)} € TTC
            </div>
          )}
        </div>

        {err && <div className="text-sm mt-3" style={{ color: '#FF6B6B' }}>{err}</div>}

        <button onClick={submit}
                disabled={busy || !form.label || !form.buyer_name || !form.buyer_address || !(ht > 0)}
                className="w-full mt-4 py-3 rounded-2xl text-white font-semibold disabled:opacity-40"
                style={{ background: 'linear-gradient(135deg,#7C7CF8,#5B5BE8)' }}>
          {busy ? 'Enregistrement…' : "Approuver l'instruction permanente"}
        </button>

        <style>{`.lbl{font-size:11px;font-weight:500;color:#B9C2D6}.fld{width:100%;border:1px solid rgba(255,255,255,.10);border-radius:12px;padding:9px 12px;font-size:14px;color:#F8FAFC;background:rgba(255,255,255,.05);outline:none;margin-top:3px}.fld:focus{border-color:#7C7CF8}`}</style>
      </div>
    </div>
  );
}
