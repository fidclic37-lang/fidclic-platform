import React, { useEffect, useState } from 'react';
import { Receipt, Check, Loader2, Download, AlertTriangle, BadgeCheck } from 'lucide-react';
import { adminAPI } from '../lib/api';

/* Super-admin › Facturation — who issues FidClic's invoices. Decided with the
   user: the seller's legal details are entered here; until they are
   complete, payments are recorded and wait, and the moment they are, every
   waiting payment is invoiced and each new one is invoiced as it arrives
   (features/invoices.py). */

const inputCls = 'h-10 w-full rounded-lg border border-[#DCE3EE] bg-white px-3 text-[14px] text-[#0B1C3F] outline-none focus:border-[#2F6BFF]';
const FIELDS = [
  ['legal_name', 'Raison sociale', true], ['legal_form', 'Forme juridique (SAS, SARL, EI…)', true],
  ['share_capital', 'Capital social (ex. 10 000 €)', true], ['address', 'Adresse du siège', true],
  ['postal_code', 'Code postal', true], ['city', 'Ville', true], ['country', 'Pays', false],
  ['siren', 'SIREN (9 chiffres)', true], ['rcs_city', 'Ville du RCS', true],
  ['vat_number', 'N° de TVA intracommunautaire', false], ['email', 'E-mail de facturation', false],
  ['phone', 'Téléphone', false], ['website', 'Site web', false], ['iban', 'IBAN (facultatif)', false],
  ['prefix', 'Préfixe des numéros (ex. FAC)', false],
];
const eur = (n) => `${(n ?? 0).toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`;

export default function AdminInvoicingPage() {
  const [s, setS] = useState(null);
  const [meta, setMeta] = useState(null);
  const [list, setList] = useState([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const [err, setErr] = useState('');

  const load = () => {
    adminAPI.invoicingIssuer().then(({ data }) => { setS(data.issuer); setMeta(data); }).catch((e) => setErr(e?.response?.data?.detail || 'Chargement impossible.'));
    adminAPI.invoices().then(({ data }) => setList(data.invoices || [])).catch(() => {});
  };
  useEffect(load, []);

  const save = async () => {
    setBusy(true); setErr(''); setMsg('');
    try {
      const { data } = await adminAPI.saveInvoicingIssuer({ ...s, vat_rate: Number(s.vat_rate) || 0 });
      setS(data.issuer); setMeta(data);
      setMsg(data.complete ? `Émetteur complet.${data.issued_now ? ` ${data.issued_now} facture(s) émise(s) à l'instant.` : ''}` : 'Enregistré — il manque encore des informations obligatoires.');
      adminAPI.invoices().then(({ data: d }) => setList(d.invoices || []));
    } catch (e) { setErr(e?.response?.data?.detail || "L'enregistrement n'a pas abouti."); }
    finally { setBusy(false); }
  };
  const pdf = async (inv) => {
    const { data } = await adminAPI.invoicePdf(inv.id);
    const url = URL.createObjectURL(new Blob([data], { type: 'application/pdf' }));
    const a = document.createElement('a'); a.href = url; a.download = `${inv.number}.pdf`; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  };

  if (!s) return <div className="p-6 text-[13px] text-[#64748B]">{err || 'Chargement…'}</div>;
  return (
    <div className="mx-auto max-w-5xl p-4 sm:p-6">
      <header className="mb-5 flex items-start gap-3">
        <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-[#EAF1FF] text-[#2F6BFF]"><Receipt size={22} /></span>
        <div>
          <h1 className="text-[24px] font-bold text-[#0B1C3F]">Facturation FidClic</h1>
          <p className="text-[13.5px] text-[#64748B]">L'émetteur des factures envoyées aux commerçants, et toutes les factures émises.</p>
        </div>
      </header>
      {meta && !meta.complete && (
        <p className="mb-4 flex items-start gap-2 rounded-xl border border-[#FDE68A] bg-[#FFFBEB] px-4 py-3 text-[13px] text-[#92400E]">
          <AlertTriangle size={16} className="mt-0.5 shrink-0" />
          Informations incomplètes : aucune facture n'est émise. {meta.waiting ? `${meta.waiting} paiement(s) attendent leur facture.` : ''}
        </p>
      )}
      {msg && <p className="mb-4 rounded-xl bg-[#E7F7EE] px-4 py-2.5 text-[13px] text-[#0F8B58]">{msg}</p>}
      {err && <p className="mb-4 rounded-xl bg-[#FEF2F2] px-4 py-2.5 text-[13px] text-[#B91C1C]">{err}</p>}

      <section className="rounded-2xl border border-[#EDF1F7] bg-white p-5">
        <h2 className="mb-4 text-[16px] font-bold text-[#0B1C3F]">Émetteur des factures</h2>
        <div className="grid gap-3.5 sm:grid-cols-2">
          {FIELDS.map(([k, label, req]) => (
            <label key={k} className="block">
              <span className="mb-1 block text-[12.5px] text-[#334155]">{label}{req && <span className="text-[#E11D48]"> *</span>}</span>
              <input className={inputCls} value={s[k] ?? ''} onChange={(e) => setS({ ...s, [k]: e.target.value })} />
            </label>
          ))}
          <label className="flex items-center gap-2.5 text-[13.5px] text-[#0B1C3F]">
            <input type="checkbox" checked={!!s.vat_applicable} onChange={(e) => setS({ ...s, vat_applicable: e.target.checked })} className="h-4 w-4 accent-[#2F6BFF]" />
            Assujetti à la TVA (sinon : « TVA non applicable, art. 293 B du CGI »)
          </label>
          {s.vat_applicable && (
            <label className="block"><span className="mb-1 block text-[12.5px] text-[#334155]">Taux de TVA (%)</span>
              <input type="number" className={inputCls} value={s.vat_rate} onChange={(e) => setS({ ...s, vat_rate: e.target.value })} /></label>
          )}
        </div>
        <button type="button" onClick={save} disabled={busy}
                className="mt-5 inline-flex items-center gap-2 rounded-xl bg-[#2F6BFF] px-5 py-2.5 text-[14px] font-medium text-white disabled:opacity-60">
          {busy ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />} Enregistrer
        </button>
      </section>

      <section className="mt-5 rounded-2xl border border-[#EDF1F7] bg-white p-5">
        <h2 className="mb-3 text-[16px] font-bold text-[#0B1C3F]">Factures émises</h2>
        {list.length === 0 ? <p className="text-[13px] text-[#64748B]">Aucune facture pour le moment.</p> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[620px] text-[13.5px]">
              <thead><tr className="border-b border-[#EDF1F7] text-left text-[12.5px] text-[#64748B]">
                <th className="py-2 font-medium">N°</th><th className="py-2 font-medium">Commerce</th><th className="py-2 font-medium">Payée le</th>
                <th className="py-2 font-medium">TTC</th><th className="py-2 font-medium">Statut</th><th className="py-2 text-right font-medium">PDF</th></tr></thead>
              <tbody>{list.map((inv) => (
                <tr key={inv.id} className="border-b border-[#F4F7FC] last:border-0">
                  <td className="py-2.5 font-medium text-[#0B1C3F]">{inv.number || '—'}</td>
                  <td className="py-2.5 text-[#475569]">{inv.tenant}</td>
                  <td className="py-2.5 text-[#475569]">{inv.paid_at ? new Date(inv.paid_at).toLocaleDateString('fr-FR') : '—'}</td>
                  <td className="py-2.5">{eur(inv.total_ttc)}</td>
                  <td className="py-2.5">{inv.number ? <span className="inline-flex items-center gap-1 text-[12.5px] text-[#0F8B58]"><BadgeCheck size={14} /> Émise</span>
                    : <span className="text-[12.5px] text-[#92400E]">En attente de l'émetteur</span>}</td>
                  <td className="py-2.5 text-right">{inv.number && (
                    <button type="button" onClick={() => pdf(inv)} className="inline-flex items-center gap-1 rounded-lg border border-[#DCE3EE] px-2.5 py-1 text-[12.5px] text-[#2F6BFF]"><Download size={13} /> PDF</button>)}</td>
                </tr>))}</tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
