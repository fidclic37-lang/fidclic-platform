import React, { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ReceiptText, ShieldCheck, ArrowLeft, Plus, Send, RefreshCw, AlertTriangle, Copy,
} from 'lucide-react';
import { facturationAPI } from '../lib/api';
import LiveText from '../components/LiveText';
import {
  BUSINESS_PROFILES, LEGAL_FORMS, VAT_REGIMES, ENTERPRISE_SIZES, getProfile,
  validateSiren, validateSiret, validateVatNumber, validateNaf, deriveVatNumber,
  SAMPLE_IDENTITY,
} from '../lib/frenchIdentifiers';
import {
  VAT_RATES, OPERATION_CATEGORIES, PAYMENT_TERMS,
  computeTotals, legalMentions, validateInvoice, addDays, todayIso,
} from '../lib/invoiceMentions';

/**
 * FacturationHome — the Facturation module's home screen.
 *
 * Two states:
 *  - NOT enabled -> activation gate: capture legal identity (SIREN…) + opt in.
 *  - Enabled     -> dashboard: Bouclier Fiscal (coherence), counts, invoice
 *                   list + a "Nouvelle facture" quick-create (create + send via
 *                   the PdpConnector — Mock by default, so it works end-to-end
 *                   today without a PA/SIREN).
 *
 * The Bouclier Fiscal score is an INFORMATIONAL indicator, not tax advice /
 * not an ECF — the disclaimer is shown under it.
 */

const BAND = {
  green: { c: '#2F7A52', bg: 'rgba(63,156,107,.12)', label: 'Conforme' },
  amber: { c: '#B8860B', bg: 'rgba(224,169,43,.14)', label: 'À vérifier' },
  red: { c: '#C0392B', bg: 'rgba(192,57,43,.12)', label: 'Action requise' },
};

export default function FacturationHome() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [enabled, setEnabled] = useState(false);
  const [status, setStatus] = useState(null);
  const [coh, setCoh] = useState(null);
  const [invoices, setInvoices] = useState([]);
  const [showCreate, setShowCreate] = useState(false);
  const [acctEmail, setAcctEmail] = useState('');
  const [acctMsg, setAcctMsg] = useState('');
  const [acctPw, setAcctPw] = useState(null);       // { email, pw } shown once, copyable
  // Visible feedback for the test/action buttons so a click is never silent.
  const [flash, setFlash] = useState(null);        // { type:'ok'|'err', text }
  const [avoired, setAvoired] = useState({});       // { [invoiceId]: creditNoteNumber }
  const [creditNotes, setCreditNotes] = useState([]);
  const [lastReport, setLastReport] = useState(null); // { period, state }
  const [busy, setBusy] = useState('');             // which action is running

  const showFlash = useCallback((type, text) => {
    setFlash({ type, text });
    window.clearTimeout(showFlash._t);
    showFlash._t = window.setTimeout(() => setFlash(null), 6000);
  }, []);

  const loadDashboard = useCallback(async () => {
    const [st, co, inv, cn] = await Promise.all([
      facturationAPI.status().catch(() => null),
      facturationAPI.coherence().catch(() => null),
      facturationAPI.listInvoices().catch(() => null),
      facturationAPI.listCreditNotes().catch(() => null),
    ]);
    setStatus(st?.data || null);
    setCoh(co?.data || null);
    setInvoices(inv?.data?.invoices || []);
    const notes = cn?.data?.credit_notes || [];
    setCreditNotes(notes);
    // rebuild the "which invoice already has an avoir" map from the server
    setAvoired(Object.fromEntries(notes.map((n) => [n.original_invoice_id, n.number])));
  }, []);

  const boot = useCallback(async () => {
    setLoading(true);
    try {
      const a = await facturationAPI.availability();
      const on = !!a.data?.enabled;
      setEnabled(on);
      if (on) await loadDashboard();
    } finally {
      setLoading(false);
    }
  }, [loadDashboard]);

  useEffect(() => { boot(); }, [boot]);

  if (loading) {
    return (
      <Shell>
        <div className="text-center text-[#8B8680] py-24 text-sm">Chargement…</div>
      </Shell>
    );
  }

  if (!enabled) return <ActivationGate onDone={boot} onBack={() => navigate('/modules')} />;

  const band = BAND[coh?.band] || BAND.amber;

  const activateDGFiP = async () => {
    setBusy('dgfip');
    try {
      await facturationAPI.activate({ start_date: '2026-09-01', type_operation: 'services', enterprise_size: 'pme' });
      await loadDashboard();
      showFlash('ok', 'Conformité DGFiP activée ✓ — l’alerte « DGFiP non activée » disparaît et le score du Bouclier remonte.');
    } catch (e) {
      showFlash('err', 'Échec de l’activation DGFiP.');
    } finally { setBusy(''); }
  };
  const simulateReceived = async () => {
    setBusy('received');
    try {
      const r = await facturationAPI.seedReceived({ supplier_name: 'Fournisseur Test SARL', total_ht: 900 });
      await loadDashboard();
      showFlash('ok', `Facture fournisseur reçue ✓ ${r.data?.received?.number ? '(' + r.data.received.number + ') ' : ''}— le compteur « Factures reçues » augmente.`);
    } catch (e) {
      showFlash('err', 'Échec de la simulation de facture reçue.');
    } finally { setBusy(''); }
  };
  const testEreporting = async () => {
    setBusy('ereport');
    try {
      const r = await facturationAPI.sendEreporting({ period_start: '2026-07-01', period_end: '2026-07-31', totals_by_vat: { '20': 5000, '10': 2000 } });
      const st = r.data?.ereport?.state || 'queued';
      setLastReport({ period: '01–31 juil. 2026', state: st });
      showFlash('ok', `E-reporting B2C envoyé ✓ — période 01–31 juil. 2026, état : ${st}.`);
    } catch (e) {
      showFlash('err', 'Échec de l’envoi de l’e-reporting.');
    } finally { setBusy(''); }
  };
  const makeAvoir = async (inv) => {
    setBusy('avoir-' + inv.id);
    try {
      const r = await facturationAPI.creditNote(inv.id, { reason: 'Correction (test)' });
      const num = r.data?.credit_note?.number || ('AV-' + inv.number);
      setAvoired((m) => ({ ...m, [inv.id]: num }));
      await loadDashboard();
      const wasRefused = ['refused', 'error'].includes(inv.state);
      showFlash('ok', `Avoir ${num} créé pour ${inv.number} ✓ — note de crédit qui corrige la facture d’origine.${wasRefused ? ' La facture refusée n’est plus comptée : le score du Bouclier remonte.' : ''}`);
    } catch (e) {
      showFlash('err', `Échec de la création de l’avoir pour ${inv.number}.`);
    } finally { setBusy(''); }
  };
  const inviteAccountant = async () => {
    setAcctMsg(''); setAcctPw(null);
    try {
      const r = await facturationAPI.inviteAccountant(acctEmail);
      const tp = r.data?.temp_password;
      if (tp) setAcctPw({ email: r.data?.email || acctEmail, pw: tp });
      else setAcctMsg('Comptable déjà relié à votre dossier — il utilise son mot de passe existant.');
      setAcctEmail('');
    } catch (e) {
      setAcctMsg("Échec de l'invitation (email déjà utilisé par un autre type de compte ?).");
    }
  };
  const copyPw = async () => {
    try {
      await navigator.clipboard.writeText(acctPw.pw);
      showFlash('ok', 'Mot de passe copié dans le presse-papiers.');
    } catch (_) {
      showFlash('err', 'Copie impossible — sélectionnez le mot de passe manuellement.');
    }
  };

  return (
    <Shell onBack={() => navigate('/modules')}>
      {/* Toast — visible confirmation for every action so a click is never silent */}
      {flash && (
        <div className="mb-4 rounded-2xl px-4 py-3 text-sm flex items-start gap-2 border"
             style={flash.type === 'ok'
               ? { background: 'rgba(63,156,107,.10)', borderColor: 'rgba(63,156,107,.35)', color: '#2F7A52' }
               : { background: 'rgba(192,57,43,.08)', borderColor: 'rgba(192,57,43,.30)', color: '#C0392B' }}>
          <span className="shrink-0">{flash.type === 'ok' ? '✓' : '⚠'}</span>
          <LiveText className="flex-1">{flash.text}</LiveText>
          <button onClick={() => setFlash(null)} className="opacity-60 hover:opacity-100">✕</button>
        </div>
      )}
      {/* Bouclier Fiscal */}
      <div
        className="rounded-3xl bg-white border p-6 mb-5"
        style={{ borderColor: '#ECE3D2' }}
      >
        <div className="flex items-start gap-5">
          <div className="shrink-0 text-center">
            <div
              className="w-24 h-24 rounded-full flex items-center justify-center"
              style={{ background: `conic-gradient(${band.c} ${(coh?.score ?? 0)}%, #EEF1F4 0)` }}
            >
              <div className="w-[74px] h-[74px] rounded-full bg-white flex flex-col items-center justify-center">
                <span className="text-2xl font-extrabold" style={{ color: band.c }}>
                  {coh?.score ?? '—'}
                </span>
                <span className="text-[10px] text-[#8B8680]">/100</span>
              </div>
            </div>
            <div className="mt-2 text-xs font-bold" style={{ color: band.c }}>
              <ShieldCheck size={12} className="inline mr-1" /><LiveText>{band.label}</LiveText>
            </div>
          </div>
          <div className="flex-1">
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-lg font-bold" style={{ color: '#1C1917' }}>Bouclier Fiscal</h2>
              <button onClick={loadDashboard} className="text-[#8B8680] hover:text-[#1C1917]">
                <RefreshCw size={16} />
              </button>
            </div>
            {(coh?.alerts || []).length === 0 ? (
              <div className="text-sm text-[#2F7A52]">✅ Aucune incohérence détectée.</div>
            ) : (
              <ul className="space-y-2">
                {coh.alerts.map((a, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm">
                    <span style={{ color: BAND[a.level]?.c || '#B8860B' }}>
                      <AlertTriangle size={15} className="mt-0.5" />
                    </span>
                    <LiveText className="text-[#44403C]">{a.message}</LiveText>
                  </li>
                ))}
              </ul>
            )}

            {/* Why this score? — transparent breakdown so 75/100 is never a black box */}
            {(coh?.breakdown || []).length > 0 && (
              <div className="mt-3 rounded-xl border p-3" style={{ borderColor: '#F2ECE0', background: '#FCFAF5' }}>
                <div className="text-[11px] font-semibold text-[#8B8680] mb-1.5 uppercase tracking-wide">
                  Pourquoi ce score ?
                </div>
                <ul className="space-y-1">
                  <li className="flex items-center justify-between text-xs">
                    <span className="text-[#57534E]">Base</span>
                    <span className="font-semibold text-[#1C1917]">100</span>
                  </li>
                  {coh.breakdown.map((r, i) => (
                    <li key={i} className="flex items-center justify-between text-xs">
                      <span className="flex items-center gap-1.5" style={{ color: BAND[r.level]?.c || '#57534E' }}>
                        <span className="w-1.5 h-1.5 rounded-full" style={{ background: BAND[r.level]?.c || '#8B8680' }} />
                        <LiveText>{r.label}</LiveText>
                      </span>
                      <span className="font-semibold" style={{ color: r.points < 0 ? '#C0392B' : '#2F7A52' }}>
                        {r.points < 0 ? r.points : (r.points === 0 ? '±0' : '+' + r.points)}
                      </span>
                    </li>
                  ))}
                  <li className="flex items-center justify-between text-xs pt-1 mt-1 border-t" style={{ borderColor: '#EFE7D7' }}>
                    <span className="font-bold text-[#1C1917]">Score</span>
                    <span className="font-bold" style={{ color: band.c }}>{coh?.score ?? '—'}/100</span>
                  </li>
                </ul>
              </div>
            )}

            <p className="text-[11px] text-[#A8A29E] mt-3 italic">
              Indicateur informatif de cohérence — ni conseil fiscal, ni ECF.
            </p>
          </div>
        </div>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-2">
        <Kpi label="e-invoicing (B2B)" value={status?.counts?.einvoicing ?? 0}
             sub="factures vers entreprises" />
        <Kpi label="e-reporting (B2C)" value={status?.counts?.ereporting ?? 0}
             sub="ventes aux particuliers" />
        <Kpi label="Factures reçues" value={status?.counts?.received ?? 0}
             sub="fournisseurs" />
        <Kpi label="Conformité DGFiP" value={status?.dgfip_activated ? 'Activée' : 'Non activée'}
             tone={status?.dgfip_activated ? '#2F7A52' : '#B8860B'} />
      </div>
      <p className="text-[11px] text-[#A8A29E] mb-5">
        e-invoicing = factures B2B envoyées via la plateforme (PA). e-reporting = données de vente B2C transmises à la DGFiP (pas de facture électronique pour les particuliers).
      </p>

      {/* Actions & tests */}
      <div className="flex flex-wrap gap-2 mb-5">
        {!status?.dgfip_activated && (
          <button onClick={activateDGFiP} disabled={busy === 'dgfip'}
            className="text-sm font-semibold px-3 py-2 rounded-xl text-white disabled:opacity-50"
            style={{ background: 'linear-gradient(135deg,#3F9C6B,#2F7A52)' }}>
            {busy === 'dgfip' ? 'Activation…' : 'Activer conformité DGFiP'}
          </button>
        )}
        <button onClick={simulateReceived} disabled={busy === 'received'}
          className="text-sm px-3 py-2 rounded-xl border disabled:opacity-50" style={{ borderColor: '#E7E1D5', color: '#57534E' }}>
          {busy === 'received' ? 'Simulation…' : 'Simuler une facture reçue'}
        </button>
        <button onClick={testEreporting} disabled={busy === 'ereport'}
          className="text-sm px-3 py-2 rounded-xl border disabled:opacity-50" style={{ borderColor: '#E7E1D5', color: '#57534E' }}>
          {busy === 'ereport' ? 'Envoi…' : 'Envoyer un e-reporting (test)'}
        </button>
      </div>

      {lastReport && (
        <div className="mb-5 -mt-2 text-xs text-[#57534E]">
          Dernier e-reporting : {lastReport.period} · état <b>{lastReport.state}</b>
        </div>
      )}

      {/* Invoices */}
      <div className="rounded-3xl bg-white border" style={{ borderColor: '#ECE3D2' }}>
        <div className="flex items-center justify-between px-5 py-4 border-b" style={{ borderColor: '#F2ECE0' }}>
          <h3 className="font-bold text-[#1C1917]">Factures émises</h3>
          <button
            onClick={() => setShowCreate(true)}
            className="inline-flex items-center gap-1.5 text-white text-sm font-semibold px-3.5 py-2 rounded-xl"
            style={{ background: 'linear-gradient(135deg,#2F6FB3,#1E4E86)' }}
          >
            <Plus size={16} /> Nouvelle facture
          </button>
        </div>
        {invoices.length === 0 ? (
          <div className="px-5 py-10 text-center text-sm text-[#8B8680]">
            Aucune facture pour l'instant. Créez votre première facture.
          </div>
        ) : (
          <div className="divide-y" style={{ borderColor: '#F2ECE0' }}>
            {invoices.map((inv) => (
              <div key={inv.id} className="px-5 py-3 flex items-center gap-3 text-sm">
                <span className="font-semibold text-[#1C1917] w-28">{inv.number}</span>
                <span className="flex-1 text-[#57534E] truncate flex items-center gap-2">
                  {inv.buyer?.name || '—'} <ChannelTag channel={inv.channel} />
                </span>
                <span className="text-[#1C1917] w-24 text-right">{(inv.total_ttc ?? 0).toFixed(2)} €</span>
                <StatusChips inv={inv} />
                {avoired[inv.id] ? (
                  <span className="text-xs px-2 py-1 rounded-lg font-semibold"
                        style={{ color: '#2F7A52', background: 'rgba(63,156,107,.12)' }}
                        title={avoired[inv.id]}>
                    Avoiré ✓
                  </span>
                ) : (
                  <button onClick={() => makeAvoir(inv)} disabled={busy === 'avoir-' + inv.id}
                    className="text-xs px-2 py-1 rounded-lg border disabled:opacity-50" style={{ borderColor: '#E7E1D5', color: '#8B8680' }}>
                    {busy === 'avoir-' + inv.id ? '…' : 'Avoir'}
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Avoirs émis (credit notes) — shown as real, negative-amount entries */}
      {creditNotes.length > 0 && (
        <div className="rounded-3xl bg-white border mt-5" style={{ borderColor: '#ECE3D2' }}>
          <div className="px-5 py-4 border-b" style={{ borderColor: '#F2ECE0' }}>
            <h3 className="font-bold text-[#1C1917]">Avoirs émis</h3>
            <p className="text-xs text-[#8B8680] mt-0.5">
              Un avoir (note de crédit) annule ou corrige une facture déjà envoyée — on ne supprime jamais une facture, on l’annule par un avoir.
            </p>
          </div>
          <div className="divide-y" style={{ borderColor: '#F2ECE0' }}>
            {creditNotes.map((cn) => (
              <div key={cn.id} className="px-5 py-3 flex items-center gap-3 text-sm">
                <span className="font-semibold text-[#1C1917] w-32">{cn.number}</span>
                <span className="flex-1 text-[#57534E] truncate">
                  corrige <b>{cn.original_number}</b>{cn.buyer?.name ? ` · ${cn.buyer.name}` : ''}
                </span>
                <span className="w-24 text-right font-semibold" style={{ color: '#C0392B' }}>
                  −{Math.abs(cn.amount_ttc ?? 0).toFixed(2)} €
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Mon comptable */}
      <div className="rounded-3xl bg-white border mt-5 p-5" style={{ borderColor: '#ECE3D2' }}>
        <h3 className="font-bold text-[#1C1917] mb-1">Mon comptable</h3>
        <p className="text-sm text-[#57534E] mb-3">
          Donnez accès à votre expert-comptable — il verra votre conformité depuis son Espace Cabinet.
        </p>
        <div className="flex gap-2">
          <input className="fld-a flex-1" value={acctEmail} inputMode="email"
                 onChange={(e) => setAcctEmail(e.target.value)}
                 placeholder="email@cabinet-comptable.fr" />
          <button onClick={inviteAccountant} disabled={!acctEmail.includes('@')}
                  className="text-sm font-semibold px-4 rounded-xl text-white disabled:opacity-50"
                  style={{ background: 'linear-gradient(135deg,#7A3E70,#4E1F44)' }}>
            Inviter
          </button>
        </div>
        {acctMsg && <div className="text-xs mt-2" style={{ color: '#57534E' }}>{acctMsg}</div>}
        {acctPw && (
          <div className="mt-3 rounded-xl border p-3" style={{ borderColor: 'rgba(122,62,112,.30)', background: 'rgba(122,62,112,.05)' }}>
            <div className="text-xs font-semibold text-[#7A3E70] mb-1">
              Compte comptable créé pour {acctPw.email}
            </div>
            <div className="text-[11px] text-[#8B8680] mb-2">
              Transmettez ce mot de passe temporaire une seule fois. Il ne sera plus affiché ensuite.
            </div>
            <div className="flex items-center gap-2">
              <input readOnly value={acctPw.pw} onFocus={(e) => e.target.select()}
                     className="flex-1 font-mono text-sm px-3 py-2 rounded-lg border select-all"
                     style={{ borderColor: '#E7E1D5', background: '#fff', color: '#1C1917' }} />
              <button onClick={copyPw}
                      className="inline-flex items-center gap-1.5 text-sm font-semibold px-3 py-2 rounded-lg text-white"
                      style={{ background: 'linear-gradient(135deg,#7A3E70,#4E1F44)' }}>
                <Copy size={14} /> Copier
              </button>
            </div>
          </div>
        )}
        <style>{`.fld-a{border:1px solid #E7E1D5;border-radius:12px;padding:10px 12px;font-size:14px;color:#1C1917;background:#FCFAF5;outline:none}.fld-a:focus{border-color:#7A3E70}`}</style>
      </div>

      {showCreate && (
        <CreateInvoiceModal
          seller={status}
          onClose={() => setShowCreate(false)}
          onCreated={async () => { setShowCreate(false); await loadDashboard(); }}
        />
      )}
    </Shell>
  );
}

/* ---------------- shell / small pieces ---------------- */

function Shell({ children, onBack }) {
  return (
    <div
      className="min-h-screen"
      style={{
        background:
          'radial-gradient(1200px 500px at 85% -10%, rgba(47,111,179,.06), transparent 60%),' +
          'radial-gradient(1000px 500px at -10% 110%, rgba(107,46,90,.05), transparent 60%), #FBF7EF',
      }}
    >
      <header className="flex items-center gap-3 px-6 py-4">
        {onBack && (
          <button onClick={onBack} className="text-[#57534E] hover:text-[#1C1917]">
            <ArrowLeft size={20} />
          </button>
        )}
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-xl flex items-center justify-center"
               style={{ background: 'linear-gradient(135deg,#2F6FB3,#1E4E86)' }}>
            <ReceiptText size={16} color="#fff" />
          </div>
          <span className="font-bold text-[#1C1917]">Facturation</span>
        </div>
      </header>
      <main className="max-w-3xl mx-auto px-4 pb-16">{children}</main>
    </div>
  );
}

function Kpi({ label, value, tone = '#1C1917', sub }) {
  return (
    <div data-currency="eur" className="rounded-2xl bg-white border p-4" style={{ borderColor: '#ECE3D2' }}>
      <LiveText as="div" className="text-xl font-bold" style={{ color: tone }}>{value}</LiveText>
      <div className="text-xs text-[#8B8680] mt-0.5">{label}</div>
      {sub && <div className="text-[10px] text-[#B4ADA2] mt-0.5">{sub}</div>}
    </div>
  );
}

function ChannelTag({ channel }) {
  const b2b = channel === 'e-invoicing';
  return (
    <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded"
      style={b2b
        ? { color: '#2F6FB3', background: 'rgba(47,111,179,.10)' }
        : { color: '#7A3E70', background: 'rgba(122,62,112,.10)' }}
      title={b2b ? 'Facture B2B transmise via la plateforme' : 'Vente B2C — e-reporting à la DGFiP'}>
      {b2b ? 'e-invoicing' : 'e-reporting'}
    </span>
  );
}

/**
 * S1 — an invoice has FOUR independent lives. Showing them side by side is the
 * whole point: an invoice can be refused by the PA, validated by the accountant,
 * half-paid, and failed-to-export — all at once. One pill could never say that.
 */
const FAMILY_LABELS = {
  pa: { label: 'PA', map: {
    draft: ['Brouillon', '#8B8680'], sent: ['Envoyée', '#2F6FB3'],
    received: ['Reçue', '#2F6FB3'], accepted: ['Acceptée', '#2F7A52'],
    refused: ['Refusée', '#C0392B'], paid: ['Payée', '#2F7A52'],
    error: ['Erreur', '#C0392B'],
  } },
  review: { label: 'Révision', map: {
    unreviewed: ['Non revue', '#8B8680'],
    pending_validation: ['À valider', '#B8860B'],
    correction_required: ['À corriger', '#C0392B'],
    validated: ['Validée', '#2F7A52'],
  } },
  payment: { label: 'Paiement', map: {
    unpaid: ['Impayée', '#8B8680'], partially_paid: ['Partielle', '#B8860B'],
    paid: ['Payée', '#2F7A52'], overdue: ['En retard', '#C0392B'],
    disputed: ['En litige', '#C0392B'],
  } },
  export: { label: 'Export', map: {
    not_ready: ['—', '#B4ADA2'], ready: ['Prête', '#2F6FB3'],
    queued: ['En file', '#B8860B'], exported: ['Exportée', '#2F7A52'],
    failed: ['Échec', '#C0392B'],
  } },
};

function StatusChips({ inv }) {
  const rows = [
    ['pa', inv.pa_status || inv.state],
    ['review', inv.review_status],
    ['payment', inv.payment_status],
    ['export', inv.export_status],
  ];
  return (
    <span className="flex items-center gap-1 flex-wrap">
      {rows.map(([fam, val]) => {
        const cfg = FAMILY_LABELS[fam];
        const [label, color] = cfg.map[val] || [val || '—', '#8B8680'];
        if (fam === 'export' && (!val || val === 'not_ready')) return null;
        return (
          <span key={fam} title={`${cfg.label} : ${label}`}
                className="text-[10px] font-semibold px-1.5 py-0.5 rounded"
                style={{ color, background: color + '1A' }}>
            <LiveText>{label}</LiveText>
          </span>
        );
      })}
    </span>
  );
}

function StatePill({ state }) {
  const map = {
    draft: ['Brouillon', '#8B8680', 'rgba(139,134,128,.12)'],
    sent: ['Envoyée', '#2F6FB3', 'rgba(47,111,179,.12)'],
    received: ['Reçue', '#2F6FB3', 'rgba(47,111,179,.12)'],
    accepted: ['Acceptée', '#2F7A52', 'rgba(63,156,107,.12)'],
    refused: ['Refusée', '#C0392B', 'rgba(192,57,43,.12)'],
    paid: ['Payée', '#2F7A52', 'rgba(63,156,107,.14)'],
    error: ['Erreur', '#C0392B', 'rgba(192,57,43,.12)'],
  };
  const [label, c, bg] = map[state] || [state, '#8B8680', 'rgba(139,134,128,.12)'];
  return (
    <span className="text-xs font-semibold px-2 py-1 rounded-full" style={{ color: c, background: bg }}>
      {label}
    </span>
  );
}

/* ---------------- activation gate ---------------- */

/**
 * ActivationGate — captures the LEGAL IDENTITY before the module turns on.
 *
 * WHY IT IS PROFILE-DRIVEN
 *   Asking a baker for a "numéro de TVA intracommunautaire" is how you lose a
 *   signup. Asking "vous êtes auto-entrepreneur ou société ?" is a question
 *   they can answer. The profile then decides which identifiers are required,
 *   which are optional, and which are irrelevant.
 *
 * WHY THE VALIDATION MATTERS
 *   A wrong SIREN/SIRET is the number one cause of e-invoice rejection: the
 *   Annuaire cannot route the invoice. Catching it here (Luhn key check) costs
 *   nothing; catching it after a rejection costs a support case and a resend.
 *   The TVA number is DERIVED from the SIREN, so it can never disagree with it.
 */
function ActivationGate({ onDone, onBack }) {
  const [step, setStep] = useState(1);                   // 1 = profile, 2 = identity
  const [profileId, setProfileId] = useState('');
  const [form, setForm] = useState({
    legal_name: '', legal_form: '', siren: '', siret: '', vat_number: '',
    naf_code: '', enterprise_size: 'tpe', vat_regime: 'reel_normal_mensuel',
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [touched, setTouched] = useState({});

  const profile = profileId ? getProfile(profileId) : null;
  const needs = profile?.needs || {};

  const chooseProfile = (id) => {
    const p = getProfile(id);
    setProfileId(id);
    setForm((f) => ({ ...f, vat_regime: p.defaultVatRegime }));
    setStep(2);
  };

  // Live field validation — errors only surface once a field has been touched,
  // so the form never scolds someone who has not typed yet.
  const vSiren = validateSiren(form.siren);
  const vSiret = validateSiret(form.siret, form.siren);
  const vVat = validateVatNumber(form.vat_number, form.siren);
  const vNaf = validateNaf(form.naf_code);
  const show = (key, res) => (touched[key] && res.error ? res.error : null);
  const mark = (key) => setTouched((t) => ({ ...t, [key]: true }));

  // Derive the VAT number the moment a valid SIREN exists — one less thing to
  // look up, and impossible to mistype.
  const suggestVat = () => {
    const derived = deriveVatNumber(form.siren);
    if (derived) setForm((f) => ({ ...f, vat_number: derived }));
  };

  const vatRequired = needs.vat === true
    || (needs.vat === 'conditional' && form.vat_regime !== 'franchise');

  const canSubmit =
    form.legal_name.trim()
    && vSiren.ok
    && (!needs.siret || vSiret.ok)
    && (!vatRequired || vVat.ok)
    && (!form.naf_code || vNaf.ok)
    && !busy;

  const submit = async () => {
    setBusy(true); setErr('');
    try {
      await facturationAPI.enable({ plan: 'addon', business_profile: profileId, ...form });
      await onDone();
    } catch (e) {
      setErr(e?.response?.data?.detail || "L'activation a échoué. Réessayez.");
    } finally {
      setBusy(false);
    }
  };

  /* ---------------- STEP 1 — which kind of business are you? ---------------- */
  if (step === 1) {
    return (
      <Shell onBack={onBack}>
        <div className="rounded-3xl bg-white border p-7 mt-6" style={{ borderColor: '#ECE3D2' }}>
          <div className="w-12 h-12 rounded-2xl flex items-center justify-center mb-4"
               style={{ background: 'linear-gradient(135deg,#2F6FB3,#1E4E86)' }}>
            <ReceiptText size={22} color="#fff" />
          </div>
          <h1 className="text-2xl font-bold mb-1" style={{ color: '#1C1917' }}>
            Activer la Facturation électronique
          </h1>
          <p className="text-sm text-[#57534E] mb-6">
            Première question, la plus simple : quel type d'entreprise êtes-vous ?
            Nous ne vous demanderons ensuite que ce qui vous concerne réellement.
          </p>

          <div className="space-y-2.5">
            {BUSINESS_PROFILES.map((p) => (
              <button key={p.id} onClick={() => chooseProfile(p.id)}
                      className="w-full text-left rounded-2xl border p-4 transition-all hover:-translate-y-0.5 hover:shadow-sm"
                      style={{ borderColor: '#E7E1D5', background: '#FCFAF5' }}>
                <div className="font-semibold text-[#1C1917]">{p.label}</div>
                <div className="text-xs text-[#8B8680] mt-0.5">{p.hint}</div>
              </button>
            ))}
          </div>
          <p className="text-[11px] text-[#A8A29E] mt-5 text-center">
            Vous pourrez modifier ces informations à tout moment dans les paramètres.
          </p>
        </div>
        <style>{FLD_CSS}</style>
      </Shell>
    );
  }

  /* ---------------- STEP 2 — the identifiers this profile actually needs ---- */
  return (
    <Shell onBack={() => setStep(1)}>
      <div className="rounded-3xl bg-white border p-7 mt-6" style={{ borderColor: '#ECE3D2' }}>
        <button onClick={() => setStep(1)} className="text-xs text-[#2F6FB3] mb-3">
          ‹ Changer de profil
        </button>
        <h1 className="text-2xl font-bold mb-1" style={{ color: '#1C1917' }}>
          Votre identité légale
        </h1>
        <p className="text-sm text-[#57534E] mb-1">
          Profil : <b>{profile.label}</b>
        </p>
        <p className="text-xs text-[#8B8680] mb-6">
          Ces informations figureront sur vos factures et servent à vous identifier
          auprès de l'administration. Nous vérifions leur validité immédiatement.
        </p>

        <div className="space-y-3">
          <Field label="Raison sociale / Nom">
            <input className="fld" value={form.legal_name}
                   onChange={(e) => setForm({ ...form, legal_name: e.target.value })}
                   placeholder="Ex. Café Lumière SARL" />
          </Field>

          {needs.legalForm && (
            <Field label="Forme juridique">
              <select className="fld" value={form.legal_form}
                      onChange={(e) => setForm({ ...form, legal_form: e.target.value })}>
                <option value="">Sélectionner…</option>
                {LEGAL_FORMS.map((f) => <option key={f} value={f}>{f}</option>)}
              </select>
            </Field>
          )}

          <Field label={`SIREN — identifie votre entreprise (${form.siren.length}/9 chiffres)`}>
            <input className="fld" value={form.siren} inputMode="numeric" maxLength={9}
                   onBlur={() => mark('siren')}
                   onChange={(e) => setForm({ ...form, siren: e.target.value.replace(/\D/g, '') })}
                   placeholder="552100554" />
            <Hint error={show('siren', vSiren)}
                  ok={vSiren.ok && 'SIREN valide — clé de contrôle vérifiée'}
                  info={!form.siren && "9 chiffres, sur votre Kbis ou votre avis de situation INSEE."} />
            {/* A tester who invents digits will always fail the checksum; without
                this the validation looks broken rather than strict. */}
            {vSiren.code === 'checksum' && touched.siren && (
              <button type="button"
                      onClick={() => setForm({ ...form, siren: SAMPLE_IDENTITY.siren, siret: '', vat_number: '' })}
                      className="text-[11px] mt-1 underline" style={{ color: '#2F6FB3' }}>
                Vous testez ? Utiliser un numéro d'exemple valide ({SAMPLE_IDENTITY.siren})
              </button>
            )}
          </Field>

          {needs.siret && (
            <Field label={`SIRET — identifie votre établissement (${form.siret.length}/14 chiffres)`}>
              <input className="fld" value={form.siret} inputMode="numeric" maxLength={14}
                     onBlur={() => mark('siret')}
                     onChange={(e) => setForm({ ...form, siret: e.target.value.replace(/\D/g, '') })}
                     placeholder={form.siren ? `${form.siren}00013` : '55210055400013'} />
              <Hint error={show('siret', vSiret)}
                    ok={vSiret.ok && 'SIRET valide'}
                    info={!form.siret && "Vos 9 chiffres de SIREN, puis 5 chiffres propres à l'établissement — 14 au total. Les factures électroniques sont routées à ce niveau."} />
              {vSiret.code === 'checksum' && touched.siret && form.siren === SAMPLE_IDENTITY.siren && (
                <button type="button"
                        onClick={() => setForm({ ...form, siret: SAMPLE_IDENTITY.siret })}
                        className="text-[11px] mt-1 underline" style={{ color: '#2F6FB3' }}>
                  Utiliser le SIRET d'exemple ({SAMPLE_IDENTITY.siret})
                </button>
              )}
            </Field>
          )}

          <Field label="Régime de TVA">
            <select className="fld" value={form.vat_regime}
                    onChange={(e) => setForm({ ...form, vat_regime: e.target.value })}>
              {VAT_REGIMES.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
            </select>
            <Hint info={VAT_REGIMES.find((r) => r.id === form.vat_regime)?.hint} />
          </Field>

          {/* TVA number is hidden entirely when the regime makes it meaningless */}
          {needs.vat && form.vat_regime !== 'franchise' && (
            <Field label={`Numéro de TVA intracommunautaire${vatRequired ? '' : ' (optionnel)'}`}>
              <div className="flex gap-2">
                <input className="fld flex-1" value={form.vat_number}
                       onBlur={() => mark('vat')}
                       onChange={(e) => setForm({ ...form, vat_number: e.target.value.toUpperCase() })}
                       placeholder="FR32123456789" />
                <button type="button" onClick={suggestVat} disabled={!vSiren.ok}
                        className="text-xs font-semibold px-3 rounded-xl border disabled:opacity-40 whitespace-nowrap"
                        style={{ borderColor: '#E7E1D5', color: '#2F6FB3' }}>
                  Calculer
                </button>
              </div>
              <Hint error={show('vat', vVat)}
                    ok={vVat.ok && 'Numéro cohérent avec le SIREN'}
                    info={!form.vat_number && vSiren.ok && "Il se calcule à partir de votre SIREN — cliquez sur « Calculer »."} />
            </Field>
          )}

          <Field label="Code NAF / APE (optionnel)">
            <input className="fld" value={form.naf_code} maxLength={5}
                   onBlur={() => mark('naf')}
                   onChange={(e) => setForm({ ...form, naf_code: e.target.value.toUpperCase() })}
                   placeholder="5610A" />
            <Hint error={show('naf', vNaf)} info={!form.naf_code && "Votre code d'activité, sur votre avis de situation INSEE."} />
          </Field>

          <Field label="Taille de l'entreprise">
            <select className="fld" value={form.enterprise_size}
                    onChange={(e) => setForm({ ...form, enterprise_size: e.target.value })}>
              {ENTERPRISE_SIZES.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
            </select>
            <Hint info={`Obligation d'émission : ${ENTERPRISE_SIZES.find((s) => s.id === form.enterprise_size)?.emission}. La réception, elle, concerne tout le monde dès le 1er septembre 2026.`} />
          </Field>
        </div>

        {profile.note && (
          <div className="mt-4 rounded-xl p-3 text-xs" style={{ background: '#EAF1F9', color: '#1E4E86' }}>
            {profile.note}
          </div>
        )}
        {form.vat_regime === 'reel_simplifie' && (
          <div className="mt-3 rounded-xl p-3 text-xs" style={{ background: 'rgba(224,169,43,.14)', color: '#8A6508' }}>
            <b>À noter :</b> le régime réel simplifié disparaît au 1<sup>er</sup> janvier 2027.
            Vous passerez à des déclarations trimestrielles (CA3). Nous vous préviendrons
            à l'avance — et le Bouclier Fiscal suivra la transition.
          </div>
        )}

        {err && <div className="text-sm text-[#C0392B] mt-3">{err}</div>}

        <button onClick={submit} disabled={!canSubmit}
          className="w-full mt-6 text-white font-semibold py-3 rounded-2xl disabled:opacity-50"
          style={{ background: 'linear-gradient(135deg,#2F6FB3,#1E4E86)' }}>
          {busy ? 'Activation…' : 'Activer le module'}
        </button>
        <p className="text-[11px] text-[#A8A29E] mt-3 text-center">
          La configuration de la plateforme agréée et de la conformité DGFiP se fait ensuite.
        </p>
      </div>

      <style>{FLD_CSS}</style>
    </Shell>
  );
}

const FLD_CSS = `.fld{width:100%;border:1px solid #E7E1D5;border-radius:12px;padding:10px 12px;font-size:14px;color:#1C1917;background:#FCFAF5;outline:none}.fld:focus{border-color:#2F6FB3}`;

/**
 * Inline field feedback: red on error, green on success, grey for guidance.
 *
 * The `key` is derived from the message itself. That looks redundant but is the
 * fix for a real bug: the page runs through a Google-Translate layer, which
 * swaps text nodes in place. When React only CHANGES a node's text, the
 * translator can keep showing its previously cached translation — so a user
 * typing a valid-length-but-invalid SIREN still saw "must contain 9 digits".
 * Changing the key forces a fresh node, which the translator re-processes.
 */
function Hint({ error, ok, info }) {
  const msg = error || (ok && `✓ ${ok}`) || info || null;
  if (!msg) return null;
  const color = error ? '#C0392B' : ok ? '#2F7A52' : '#8B8680';
  return <div key={msg} className="text-[11px] mt-1 leading-snug" style={{ color }}>{msg}</div>;
}

function Field({ label, children }) {
  return (
    <label className="block">
      <span className="text-xs font-semibold text-[#57534E] mb-1 block">{label}</span>
      {children}
    </label>
  );
}

/* ---------------- create invoice modal ---------------- */

/**
 * CreateInvoiceModal — a legally complete French invoice, not a demo form.
 *
 * WHY IT IS THIS LONG
 *   A French invoice must carry ~25 mandatory mentions (art. 242 nonies A CGI,
 *   art. L441-9 Code de commerce), and the 2026 reform adds more: the buyer's
 *   SIREN, the delivery address, and the category of operation. A missing
 *   mention is not cosmetic — the recipient's platform rejects the invoice, or
 *   an auditor finds a non-compliant document years later.
 *
 *   Everything about the SELLER is filled automatically from the tenant, so the
 *   user only ever types what only they can know. Everything mandatory is
 *   validated BEFORE sending, because a rejection costs a support case and a
 *   resend, while a validation message costs nothing.
 */
export function CreateInvoiceModal({ onClose, onCreated, seller, tenantId }) {
  // tenantId set => a cabinet member is invoicing FOR a client (mandate path);
  // the server re-verifies the mandate and stamps the audit "on behalf of".
  const sellerRegime = seller?.vat_regime || 'reel_normal_mensuel';
  const isFranchise = sellerRegime === 'franchise';

  const [buyer, setBuyer] = useState({
    name: '', siren: '', siret: '', vat_number: '', address: '',
    delivery_address: '', is_company: true,
  });
  const [invoice, setInvoice] = useState({
    issue_date: todayIso(),
    supply_date: todayIso(),
    payment_term: 'net30',
    due_date: addDays(todayIso(), 30),
    operation_category: 'services',
    vat_on_debits: false,
    purchase_order: '',
    notes: '',
  });
  const [lines, setLines] = useState([
    { description: '', quantity: '1', unit_price: '', vat_rate: isFranchise ? 0 : 20 },
  ]);
  const [sameDelivery, setSameDelivery] = useState(true);
  const [simulate, setSimulate] = useState(false);
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState([]);

  const totals = computeTotals(lines);
  const mentions = legalMentions({
    vatRegime: sellerRegime,
    isCompany: buyer.is_company,
    operationCategory: invoice.operation_category,
    vatOnDebits: invoice.vat_on_debits,
  });

  /* Payment terms drive the due date — the user picks a term, not a date. */
  const setTerm = (termId) => {
    const term = PAYMENT_TERMS.find((t) => t.id === termId);
    setInvoice((i) => ({
      ...i, payment_term: termId,
      due_date: addDays(i.issue_date, term?.days ?? 30),
    }));
  };
  const setIssueDate = (d) => {
    const term = PAYMENT_TERMS.find((t) => t.id === invoice.payment_term);
    setInvoice((i) => ({ ...i, issue_date: d, due_date: addDays(d, term?.days ?? 30) }));
  };

  const setLine = (idx, patch) =>
    setLines((ls) => ls.map((l, i) => (i === idx ? { ...l, ...patch } : l)));
  const addLine = () =>
    setLines((ls) => [...ls, { description: '', quantity: '1', unit_price: '',
                               vat_rate: isFranchise ? 0 : 20 }]);
  const removeLine = (idx) =>
    setLines((ls) => (ls.length > 1 ? ls.filter((_, i) => i !== idx) : ls));

  const submit = async () => {
    const found = validateInvoice({ buyer, invoice, lines, sellerVatRegime: sellerRegime });
    setErrors(found);
    if (found.length) return;

    setBusy(true);
    try {
      await facturationAPI.createInvoice({
        ...(tenantId ? { tenant_id: tenantId } : {}),
        buyer: {
          ...buyer,
          delivery_address: sameDelivery ? buyer.address : buyer.delivery_address,
        },
        date: invoice.issue_date,
        supply_date: invoice.supply_date,
        due_date: invoice.due_date,
        payment_term: invoice.payment_term,
        operation_category: invoice.operation_category,
        vat_on_debits: invoice.vat_on_debits,
        purchase_order: invoice.purchase_order || undefined,
        notes: invoice.notes || undefined,
        legal_mentions: mentions.map((m) => m.text),
        lines: lines
          .filter((l) => l.description?.trim() && parseFloat(l.unit_price || 0) > 0)
          .map((l) => ({
            description: l.description,
            quantity: parseFloat(l.quantity || 1),
            unit_price: parseFloat(l.unit_price || 0),
            vat_rate: parseFloat(l.vat_rate ?? 0),
          })),
        send: true,
        simulate: simulate ? 'reject' : undefined,
      });
      await onCreated();
    } catch (e) {
      setErrors([e?.response?.data?.detail || "L'envoi a échoué. Vérifiez les champs."]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center p-3 overflow-y-auto"
         style={{ background: 'rgba(28,25,23,.45)' }} onClick={onClose}>
      <div className="bg-white rounded-3xl w-full max-w-2xl my-6" onClick={(e) => e.stopPropagation()}>
        <div className="px-6 pt-6 pb-4 border-b sticky top-0 bg-white rounded-t-3xl z-10"
             style={{ borderColor: '#F2ECE0' }}>
          <h3 className="text-lg font-bold" style={{ color: '#1C1917' }}>Nouvelle facture</h3>
          <p className="text-xs text-[#8B8680] mt-0.5">
            Vos informations d'entreprise sont ajoutées automatiquement. Tous les
            champs marqués sont obligatoires pour une facture conforme.
          </p>
        </div>

        <div className="px-6 py-5 space-y-6">
          {/* ---------------- CLIENT ---------------- */}
          <section>
            <SectionTitle>Client</SectionTitle>
            <div className="space-y-3">
              <div className="grid md:grid-cols-3 gap-3">
                <div className="md:col-span-2">
                  <Field label="Nom / Raison sociale *">
                    <input className="fld" value={buyer.name}
                           onChange={(e) => setBuyer({ ...buyer, name: e.target.value })}
                           placeholder="Solutions RH SARL" />
                  </Field>
                </div>
                <Field label="Type de client *">
                  <select className="fld" value={buyer.is_company ? '1' : '0'}
                          onChange={(e) => setBuyer({ ...buyer, is_company: e.target.value === '1' })}>
                    <option value="1">Entreprise (B2B)</option>
                    <option value="0">Particulier (B2C)</option>
                  </select>
                </Field>
              </div>

              <Field label="Adresse de facturation *">
                <textarea className="fld" rows={2} value={buyer.address}
                          onChange={(e) => setBuyer({ ...buyer, address: e.target.value })}
                          placeholder={"12 rue de la Paix\n75002 Paris"} />
              </Field>

              {buyer.is_company && (
                <div className="grid md:grid-cols-2 gap-3">
                  <Field label={`SIREN client * (${buyer.siren.length}/9)`}>
                    <input className="fld" value={buyer.siren} inputMode="numeric" maxLength={9}
                           onChange={(e) => setBuyer({ ...buyer, siren: e.target.value.replace(/\D/g, '') })}
                           placeholder="552100554" />
                    <Hint info="Obligatoire sur les factures B2B depuis la réforme 2026." />
                  </Field>
                  <Field label={`SIRET client (recommandé) — ${buyer.siret.length}/14`}>
                    <input className="fld" value={buyer.siret} inputMode="numeric" maxLength={14}
                           onChange={(e) => setBuyer({ ...buyer, siret: e.target.value.replace(/\D/g, '') })}
                           placeholder="55210055400013" />
                    {/* Not legally mandatory, but the Annuaire routes at SIRET
                        level: with it, the invoice reaches the right site of a
                        multi-establishment client instead of the head office. */}
                    <Hint info="L'annuaire achemine les factures au niveau de l'établissement. Sans SIRET, un client multi-sites peut recevoir la facture au mauvais endroit." />
                  </Field>
                </div>
              )}

              {buyer.is_company && (
                <div className="grid md:grid-cols-2 gap-3">
                  <Field label="N° TVA du client (optionnel)">
                    <input className="fld" value={buyer.vat_number}
                           onChange={(e) => setBuyer({ ...buyer, vat_number: e.target.value.toUpperCase() })}
                           placeholder="FR96552100554" />
                  </Field>
                </div>
              )}

              <label className="flex items-center gap-2 text-xs text-[#57534E] cursor-pointer">
                <input type="checkbox" checked={sameDelivery}
                       onChange={(e) => setSameDelivery(e.target.checked)} />
                L'adresse de livraison / d'exécution est identique
              </label>
              {!sameDelivery && (
                <Field label="Adresse de livraison ou d'exécution *">
                  <textarea className="fld" rows={2} value={buyer.delivery_address}
                            onChange={(e) => setBuyer({ ...buyer, delivery_address: e.target.value })}
                            placeholder="Lieu où le bien est livré ou la prestation réalisée" />
                  <Hint info="Nouvelle mention obligatoire en 2026 lorsqu'elle diffère de l'adresse de facturation." />
                </Field>
              )}
            </div>
          </section>

          {/* ---------------- DATES & NATURE ---------------- */}
          <section>
            <SectionTitle>Dates et nature de l'opération</SectionTitle>
            <div className="grid md:grid-cols-3 gap-3">
              <Field label="Date d'émission *">
                <input className="fld" type="date" value={invoice.issue_date}
                       onChange={(e) => setIssueDate(e.target.value)} />
              </Field>
              <Field label="Date de vente / prestation *">
                <input className="fld" type="date" value={invoice.supply_date}
                       onChange={(e) => setInvoice({ ...invoice, supply_date: e.target.value })} />
                <Hint info="Distincte de la date d'émission — c'est celle-ci qui compte pour la TVA." />
              </Field>
              <Field label="Conditions de paiement *">
                <select className="fld" value={invoice.payment_term}
                        onChange={(e) => setTerm(e.target.value)}>
                  {PAYMENT_TERMS.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
                </select>
                <Hint info={`Échéance : ${invoice.due_date}`} />
              </Field>
            </div>
            <div className="grid md:grid-cols-2 gap-3 mt-3">
              <Field label="Catégorie d'opération *">
                <select className="fld" value={invoice.operation_category}
                        onChange={(e) => setInvoice({ ...invoice, operation_category: e.target.value })}>
                  {OPERATION_CATEGORIES.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
                </select>
                <Hint info={OPERATION_CATEGORIES.find((c) => c.id === invoice.operation_category)?.hint} />
              </Field>
              <Field label="Bon de commande / référence (optionnel)">
                <input className="fld" value={invoice.purchase_order}
                       onChange={(e) => setInvoice({ ...invoice, purchase_order: e.target.value })}
                       placeholder="BC-2026-114" />
              </Field>
            </div>
            {invoice.operation_category === 'services' && !isFranchise && (
              <label className="flex items-center gap-2 mt-3 text-xs text-[#57534E] cursor-pointer">
                <input type="checkbox" checked={invoice.vat_on_debits}
                       onChange={(e) => setInvoice({ ...invoice, vat_on_debits: e.target.checked })} />
                J'ai opté pour le paiement de la TVA sur les débits
              </label>
            )}
          </section>

          {/* ---------------- LIGNES ---------------- */}
          <section>
            <SectionTitle>Détail des prestations</SectionTitle>
            <div className="space-y-2">
              {lines.map((l, i) => (
                <div key={i} className="grid grid-cols-12 gap-2 items-start">
                  <div className="col-span-12 md:col-span-5">
                    <input className="fld" value={l.description}
                           onChange={(e) => setLine(i, { description: e.target.value })}
                           placeholder="Description de la prestation ou du bien" />
                  </div>
                  <div className="col-span-3 md:col-span-2">
                    <input className="fld" value={l.quantity} inputMode="decimal"
                           onChange={(e) => setLine(i, { quantity: e.target.value })}
                           placeholder="Qté" />
                  </div>
                  <div className="col-span-4 md:col-span-2">
                    <input className="fld" value={l.unit_price} inputMode="decimal"
                           onChange={(e) => setLine(i, { unit_price: e.target.value })}
                           placeholder="P.U. HT" />
                  </div>
                  <div className="col-span-4 md:col-span-2">
                    <select className="fld" value={l.vat_rate} disabled={isFranchise}
                            onChange={(e) => setLine(i, { vat_rate: e.target.value })}>
                      {VAT_RATES.map((r) => (
                        <option key={r.value} value={r.value}>{r.value} %</option>
                      ))}
                    </select>
                  </div>
                  <div className="col-span-1 flex justify-end">
                    {lines.length > 1 && (
                      <button type="button" onClick={() => removeLine(i)}
                              className="text-[#C0392B] text-lg leading-none px-1"
                              title="Supprimer la ligne">×</button>
                    )}
                  </div>
                </div>
              ))}
            </div>
            <button type="button" onClick={addLine}
                    className="text-xs font-semibold mt-2" style={{ color: '#2F6FB3' }}>
              + Ajouter une ligne
            </button>
            {isFranchise && (
              <Hint info="Franchise en base : la TVA est forcée à 0 % et la mention légale est ajoutée automatiquement." />
            )}
          </section>

          {/* ---------------- TOTAUX ---------------- */}
          <section className="rounded-2xl p-4" style={{ background: '#FCFAF5' }}>
            <div className="flex justify-between text-sm py-0.5">
              <span className="text-[#57534E]">Total HT</span>
              <span className="font-semibold">{totals.total_ht.toFixed(2)} €</span>
            </div>
            {totals.vat_breakdown.filter((b) => b.base > 0).map((b) => (
              <div key={b.rate} className="flex justify-between text-xs py-0.5 text-[#8B8680]">
                <span>TVA {b.rate} % sur {b.base.toFixed(2)} €</span>
                <span>{b.vat.toFixed(2)} €</span>
              </div>
            ))}
            <div className="flex justify-between text-base pt-2 mt-1 border-t font-bold"
                 style={{ borderColor: '#EFE7D7' }}>
              <span>Total TTC</span>
              <span style={{ color: '#2F6FB3' }}>{totals.total_ttc.toFixed(2)} €</span>
            </div>
          </section>

          {/* ---------------- MENTIONS LÉGALES ---------------- */}
          {mentions.length > 0 && (
            <section>
              <SectionTitle>Mentions légales ajoutées automatiquement</SectionTitle>
              <ul className="space-y-1">
                {mentions.map((m) => (
                  <li key={m.id} className="text-[11px] text-[#57534E] flex gap-1.5">
                    <span style={{ color: '#2F7A52' }}>✓</span> {m.text}
                  </li>
                ))}
              </ul>
            </section>
          )}

          <Field label="Note pour le client (optionnel)">
            <textarea className="fld" rows={2} value={invoice.notes}
                      onChange={(e) => setInvoice({ ...invoice, notes: e.target.value })}
                      placeholder="Merci de votre confiance." />
          </Field>

          <label className="flex items-center gap-2 text-xs text-[#8B8680] cursor-pointer">
            <input type="checkbox" checked={simulate} onChange={(e) => setSimulate(e.target.checked)} />
            Simuler un rejet (test — voir le message + le bouton de correction)
          </label>

          {errors.length > 0 && (
            <div className="rounded-2xl p-3 border" style={{ background: '#FBEAE8', borderColor: 'rgba(192,57,43,.3)' }}>
              <div className="text-xs font-bold mb-1" style={{ color: '#C0392B' }}>
                Facture non conforme — à corriger avant l'envoi :
              </div>
              <ul className="space-y-0.5">
                {errors.map((e, i) => (
                  <li key={i} className="text-[11px]" style={{ color: '#C0392B' }}>• {e}</li>
                ))}
              </ul>
            </div>
          )}
        </div>

        <div className="px-6 pb-6 pt-2 flex gap-3 sticky bottom-0 bg-white rounded-b-3xl">
          <button onClick={onClose} className="flex-1 py-3 rounded-2xl border text-[#57534E]"
                  style={{ borderColor: '#E7E1D5' }}>Annuler</button>
          <button onClick={submit} disabled={busy}
                  className="flex-1 py-3 rounded-2xl text-white font-semibold inline-flex items-center justify-center gap-1.5 disabled:opacity-50"
                  style={{ background: 'linear-gradient(135deg,#2F6FB3,#1E4E86)' }}>
            <Send size={15} /> {busy ? 'Envoi…' : 'Créer & envoyer'}
          </button>
        </div>
      </div>
      <style>{FLD_CSS}</style>
    </div>
  );
}

function SectionTitle({ children }) {
  return (
    <div className="text-[11px] font-bold uppercase tracking-wide mb-2.5" style={{ color: '#7A3E70' }}>
      {children}
    </div>
  );
}
