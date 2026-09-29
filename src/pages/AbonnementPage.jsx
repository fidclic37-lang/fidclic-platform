import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  CreditCard, Crown, Repeat, Receipt, Wallet, FileText, FileX2, CheckCircle2, BarChart3, ChevronRight,
  Rocket, ArrowRight, CalendarDays, MoreVertical, Pencil, Download, BadgeCheck, ExternalLink, TrendingUp,
  XCircle, AlertTriangle, Send, Users, Store, Loader2, Check, Info,
} from 'lucide-react';
import { ownerAPI } from '../lib/api';

/* Paramètres › Abonnement & facturation — built to the approved mockup:
   six tabs, « Aperçu » as drawn. Invoices are FidClic's, one per payment,
   downloadable as a PDF that carries the mentions French law requires
   (features/invoices.py). Payment itself runs through Stripe (Checkout,
   customer portal); until Stripe is set up the page says so instead of
   pretending. */

const BLUE = '#2F6BFF';
const nf = (n) => (n ?? 0).toLocaleString('fr-FR');
const eur = (n) => `${(n ?? 0).toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`;
const dmy = (iso) => (iso ? new Date(iso).toLocaleDateString('fr-FR') : '—');
const longDate = (iso) => (iso ? new Date(iso).toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' }) : '—');

const TABS = [
  ['apercu', 'Aperçu', Crown], ['offre', "Changer d'offre", Repeat], ['facturation', 'Facturation', Receipt],
  ['paiement', 'Moyens de paiement', CreditCard], ['factures', 'Historique des factures', FileText],
  ['resiliation', 'Résiliation', FileX2],
];
const USAGE_ICON = { new_cards: [CreditCard, '#10B981', '#E7F7EE'], campaigns: [Send, BLUE, '#EAF1FF'],
                     customers: [Users, '#8B5CF6', '#F3EEFF'], establishments: [Store, '#F59E0B', '#FFF4DB'] };

const Card = ({ children, className = '' }) => (
  <section className={`rounded-2xl border border-[#EDF1F7] bg-white p-4 shadow-[0_1px_2px_rgba(11,28,63,.03)] ${className}`}>{children}</section>
);
const Head = ({ icon: Icon, title, sub, right, tone = BLUE, bg = '#EEF4FF' }) => (
  <header className="mb-3 flex items-start gap-3">
    <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl" style={{ background: bg, color: tone }}><Icon size={21} /></span>
    <div className="min-w-0 flex-1">
      <h2 className="text-[15.5px] font-bold text-[#0B1C3F]">{title}</h2>
      {sub && <p className="text-[12.5px] leading-snug text-[#64748B]">{sub}</p>}
    </div>
    {right}
  </header>
);

async function download(fetcher, name) {
  const { data } = await fetcher();
  const url = URL.createObjectURL(new Blob([data], { type: 'application/pdf' }));
  const a = document.createElement('a');
  a.href = url; a.download = `${name}.pdf`; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

export default function AbonnementPage() {
  const [tab, setTab] = useState('apercu');
  const [d, setD] = useState(null);
  const [invoices, setInvoices] = useState(null);
  const [issuerReady, setIssuerReady] = useState(true);
  const [err, setErr] = useState('');
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState('');
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [reason, setReason] = useState('');

  const load = useCallback(() => {
    ownerAPI.billingOverview().then(({ data }) => setD(data)).catch((e) => setErr(e?.response?.data?.detail || "Impossible de charger l'abonnement."));
    ownerAPI.invoices().then(({ data }) => { setInvoices(data.invoices || []); setIssuerReady(data.issuer_ready); }).catch(() => setInvoices([]));
  }, []);
  useEffect(() => { load(); }, [load]);

  const act = async (key, fn, ok) => {
    setBusy(key); setErr(''); setMsg('');
    try { const r = await fn(); if (r?.data?.url) { window.location.href = r.data.url; return; } if (ok) setMsg(ok); load(); }
    catch (e) { setErr(e?.response?.data?.detail || "L'action n'a pas abouti."); }
    finally { setBusy(''); }
  };
  const pdf = (inv) => act(`pdf-${inv.id}`, () => download(() => ownerAPI.invoicePdf(inv.id), inv.number));

  if (!d) {
    return err ? <p className="rounded-xl bg-[#FEF2F2] px-4 py-3 text-[13.5px] text-[#B91C1C]">{err}</p>
      : <div className="flex items-center justify-center gap-2 rounded-2xl border border-[#E6EEFB] bg-white py-24 text-[13px] text-[#64748B]"><Loader2 size={16} className="animate-spin" /> Chargement…</div>;
  }
  const latest = d.latest_invoice;
  const pm = d.payment_method;
  const notConfigured = !d.configured;

  const PlanBlock = () => (
    <Card>
      <Head icon={Crown} title="Votre offre actuelle" sub="Détails de votre abonnement FIDCLIC." />
      <div className="rounded-xl bg-[#F8FAFF] p-4">
        <p className="mb-3 flex items-center gap-2 text-[17px] font-bold text-[#0B1C3F]">
          <Crown size={20} /> {d.plan.label}
          <span className="rounded-md bg-[#EAF1FF] px-2 py-0.5 text-[12px] font-medium text-[#2F6BFF]">Offre actuelle</span>
          {d.plan.price ? <span className="ml-auto text-[13px] font-medium text-[#64748B]">{d.plan.price} € HT / mois</span> : null}
        </p>
        <ul className="space-y-2">
          {d.plan.features.map((f) => (
            <li key={f} className="flex items-center gap-2.5 text-[13px] text-[#475569]"><CheckCircle2 size={17} className="text-white" fill={BLUE} /> {f}</li>
          ))}
        </ul>
        <button type="button" onClick={() => setTab('offre')}
                className="mt-4 w-full rounded-xl border border-[#2F6BFF] bg-white py-2.5 text-[13px] font-medium text-[#2F6BFF]">Voir toutes les fonctionnalités</button>
      </div>
    </Card>
  );

  const UsageBlock = () => (
    <Card>
      <Head icon={BarChart3} title="Utilisation de votre offre" sub="Suivez votre utilisation et vos limites incluses."
            right={<span className="rounded-lg border border-[#DCE3EE] px-2.5 py-1.5 text-[12.5px] text-[#0B1C3F]">Période actuelle</span>} />
      <div className="space-y-2.5">
        {d.usage.map((u) => {
          const [Icon, fg, bg] = USAGE_ICON[u.key] || [BarChart3, BLUE, '#EAF1FF'];
          const pct = u.limit ? Math.min(100, Math.round((u.used / u.limit) * 100)) : null;
          return (
            <div key={u.key} className="flex items-center gap-3 rounded-xl border border-[#EDF1F7] p-3">
              <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl" style={{ background: bg, color: fg }}><Icon size={22} /></span>
              <div className="min-w-0 flex-1">
                <p className="text-[12.5px] text-[#0B1C3F]">{u.label}</p>
                <p className="flex items-baseline justify-between">
                  <span className="text-[15px] font-bold text-[#0B1C3F]">{nf(u.used)} <span className="font-medium">/ {u.limit ? nf(u.limit) : 'illimité'}</span></span>
                  {pct !== null && <span className="text-[12px] text-[#64748B]">{pct}%</span>}
                </p>
                <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-[#EEF2F8]">
                  <div className="h-full rounded-full" style={{ width: `${pct ?? 0}%`, background: fg }} />
                </div>
              </div>
              <ChevronRight size={16} className="text-[#0B1C3F]" />
            </div>
          );
        })}
      </div>
    </Card>
  );

  const Upsell = () => (
    <section className="rounded-2xl border border-[#D5F0E0] bg-[#F1FBF5] p-4">
      <header className="mb-3 flex items-center gap-3">
        <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-[#DDF4E7] text-[#10B981]"><Rocket size={22} /></span>
        <h2 className="text-[15.5px] font-bold text-[#0B1C3F]">Besoin de plus ?</h2>
      </header>
      <p className="mb-3 text-[13.5px] leading-snug text-[#475569]">Passez à une offre supérieure pour augmenter vos limites (cartes, campagnes, établissements…) et accéder à plus de fonctionnalités.</p>
      <ul className="mb-4 space-y-1.5">
        {['Plus de cartes de fidélité', 'Plus de campagnes', "Plus d'établissements", 'Fonctionnalités avancées', 'Support étendu'].map((x) => (
          <li key={x} className="flex items-center gap-2 text-[13px] text-[#475569]"><CheckCircle2 size={17} className="text-white" fill="#10B981" /> {x}</li>
        ))}
      </ul>
      <button type="button" onClick={() => setTab('offre')} className="flex w-full items-center justify-center gap-2 rounded-xl py-2.5 text-[14px] font-medium text-white" style={{ background: BLUE }}>
        Voir les offres disponibles <ArrowRight size={16} />
      </button>
    </section>
  );

  const PaymentBlock = ({ big }) => (
    <Card>
      <Head icon={Wallet} title="Moyen(s) de paiement" sub="Gérez vos moyens de paiement." />
      {pm ? (
        <div className="flex items-center gap-3 rounded-xl border border-[#EDF1F7] p-3">
          <span className="flex h-9 w-12 items-center justify-center rounded-md bg-[#0B1C3F] text-[11px] font-bold uppercase italic text-white">{pm.brand || 'Carte'}</span>
          <div className="flex-1"><p className="text-[14px] font-semibold text-[#0B1C3F]">•••• ••• {pm.last4}</p><p className="text-[12.5px] text-[#64748B]">Expire le {pm.exp}</p></div>
          <MoreVertical size={18} className="text-[#0B1C3F]" />
        </div>
      ) : (
        <p className="rounded-xl bg-[#F4F7FC] px-3 py-3 text-[12.5px] text-[#475569]">
          {notConfigured ? 'Le paiement en ligne sera disponible prochainement.' : 'Aucune carte enregistrée pour le moment.'}
        </p>
      )}
      <button type="button" disabled={notConfigured || busy === 'portal'} onClick={() => act('portal', ownerAPI.billingPortal)}
              className={`mt-3 flex w-full items-center justify-center gap-2 rounded-xl border border-[#2F6BFF] py-2.5 text-[13.5px] font-medium text-[#2F6BFF] disabled:opacity-50 ${big ? '' : ''}`}>
        {busy === 'portal' ? <Loader2 size={15} className="animate-spin" /> : <Pencil size={15} />} Modifier le moyen de paiement
      </button>
    </Card>
  );

  return (
    <div className="abo" data-currency="eur">
      <header className="mb-4 flex items-start gap-3">
        <span className="mt-0.5 flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-[#EAF1FF] text-[#2F6BFF]"><CreditCard size={22} /></span>
        <div>
          <h1 className="text-[28px] font-bold leading-tight tracking-[-0.01em] text-[#0B1C3F]">Abonnement & facturation</h1>
          <p className="text-[15px] text-[#475569]">Gérez votre offre, vos paiements et vos factures.</p>
        </div>
      </header>

      <nav className="mb-4 flex gap-1 overflow-x-auto rounded-2xl border border-[#EDF1F7] bg-white px-2" role="tablist">
        {TABS.map(([key, label, Icon]) => (
          <button key={key} type="button" role="tab" aria-selected={tab === key} onClick={() => setTab(key)}
                  className={`flex shrink-0 items-center gap-2 border-b-2 px-4 py-3.5 text-[14px] transition ${tab === key ? 'border-[#2F6BFF] text-[#2F6BFF]' : 'border-transparent text-[#0B1C3F] hover:text-[#2F6BFF]'}`}>
            <Icon size={17} /> {label}
          </button>
        ))}
      </nav>
      {err && <p className="mb-4 rounded-xl bg-[#FEF2F2] px-4 py-2.5 text-[13px] text-[#B91C1C]">{err}</p>}
      {msg && <p className="mb-4 rounded-xl bg-[#E7F7EE] px-4 py-2.5 text-[13px] text-[#0F8B58]">{msg}</p>}
      {d.cancel_at_period_end && (
        <p className="mb-4 flex items-center gap-2 rounded-xl border border-[#FCD9D9] bg-[#FEF4F4] px-4 py-2.5 text-[13px] text-[#B42318]">
          <AlertTriangle size={16} /> Résiliation demandée : votre accès reste actif jusqu'au {longDate(d.renews_on)}.
        </p>
      )}

      {tab === 'apercu' && (
        <>
          <div className="grid gap-4 xl:grid-cols-[1fr_1fr_0.82fr]"><PlanBlock /><UsageBlock /><Upsell /></div>
          <div className="mt-4 grid gap-4 xl:grid-cols-3">
            <Card>
              <Head icon={CalendarDays} title="Prochaine échéance" sub="Date de renouvellement de votre abonnement." tone="#10B981" bg="#E7F7EE" />
              <div className="flex items-center justify-between rounded-xl border border-[#EDF1F7] p-3.5">
                <div>
                  <p className="text-[13px] text-[#0B1C3F]">{d.status === 'trialing' ? "Fin de l'essai" : 'Date de renouvellement'}</p>
                  <p className="text-[17px] font-bold text-[#0B1C3F]">{longDate(d.renews_on)}</p>
                </div>
                {d.days_left != null && <span className="rounded-lg bg-[#E7F7EE] px-2.5 py-1 text-[12.5px] text-[#0F8B58]">Dans {d.days_left} jour{d.days_left > 1 ? 's' : ''}</span>}
              </div>
            </Card>
            <PaymentBlock />
            <Card>
              <Head icon={FileText} title="Facture actuelle" sub="Consultez et téléchargez votre dernière facture." />
              {latest ? (
                <div className="flex items-center gap-3 rounded-xl border border-[#EDF1F7] p-3">
                  <div className="min-w-0 flex-1">
                    <p className="text-[14px] font-medium text-[#0B1C3F]">{latest.number ? `#${latest.number}` : 'En cours d’émission'}</p>
                    <p className="text-[12.5px] text-[#64748B]">{dmy(latest.paid_at)}</p>
                  </div>
                  <span className="inline-flex items-center gap-1 rounded-lg bg-[#E7F7EE] px-2 py-1 text-[12px] text-[#0F8B58]"><BadgeCheck size={14} /> Payée</span>
                  <button type="button" disabled={!latest.number} onClick={() => pdf(latest)} aria-label="Télécharger"
                          className="flex h-10 w-10 items-center justify-center rounded-lg border border-[#DCE3EE] text-[#2F6BFF] disabled:opacity-40">
                    {busy === `pdf-${latest.id}` ? <Loader2 size={16} className="animate-spin" /> : <Download size={17} />}
                  </button>
                </div>
              ) : <p className="rounded-xl bg-[#F4F7FC] px-3 py-3 text-[12.5px] text-[#475569]">Aucune facture pour le moment : elle apparaîtra ici après votre premier paiement.</p>}
              <button type="button" onClick={() => setTab('factures')}
                      className="mt-3 flex w-full items-center justify-center gap-2 rounded-xl border border-[#DCE3EE] py-2.5 text-[13.5px] font-medium text-[#2F6BFF]">
                Voir toutes les factures <ArrowRight size={15} />
              </button>
            </Card>
          </div>
          <div className="mt-4 grid gap-4 xl:grid-cols-2">
            <Card>
              <Head icon={TrendingUp} title="Changer d'offre" sub="Passez à une offre supérieure à tout moment." />
              <div className="flex flex-wrap items-center gap-3 rounded-xl bg-[#F4F7FC] p-3.5">
                <BarChart3 size={30} className="text-[#2F6BFF]" />
                <div className="min-w-0 flex-1"><p className="text-[15px] font-bold text-[#2F6BFF]">Débloquez plus de possibilités</p>
                  <p className="text-[12.5px] text-[#64748B]">Augmentez vos limites (cartes, campagnes, établissements) et accédez à des fonctionnalités avancées.</p></div>
                <button type="button" onClick={() => setTab('offre')} className="inline-flex items-center gap-2 rounded-xl px-5 py-3 text-[13.5px] font-medium text-white" style={{ background: BLUE }}>Voir les offres <ArrowRight size={15} /></button>
              </div>
            </Card>
            <Card>
              <Head icon={XCircle} title="Résiliation" sub="Gérez la résiliation de votre abonnement." tone="#E11D48" bg="#FDECEF" />
              <div className="flex flex-wrap items-center gap-3 rounded-xl bg-[#FEF4F4] p-3.5">
                <AlertTriangle size={28} className="text-[#E11D48]" />
                <div className="min-w-0 flex-1"><p className="text-[14px] font-medium text-[#B42318]">Résilier votre abonnement</p>
                  <p className="text-[12.5px] text-[#64748B]">Vous pouvez résilier à tout moment. Votre accès restera actif jusqu'à la fin de la période en cours.</p></div>
                <button type="button" onClick={() => setTab('resiliation')} className="rounded-xl border border-[#E11D48] bg-white px-5 py-3 text-[13.5px] font-medium text-[#E11D48]">Résilier l'abonnement</button>
              </div>
            </Card>
          </div>
        </>
      )}

      {tab === 'offre' && (
        <div className="grid gap-4 lg:grid-cols-3">
          {d.catalogue.map((p) => (
            <Card key={p.key} className={p.current ? 'ring-2 ring-[#2F6BFF]' : ''}>
              <p className="flex items-center gap-2 text-[17px] font-bold text-[#0B1C3F]"><Crown size={18} /> {p.label}
                {p.current && <span className="rounded-md bg-[#EAF1FF] px-2 py-0.5 text-[11.5px] font-medium text-[#2F6BFF]">Offre actuelle</span>}</p>
              <p className="mt-1 text-[26px] font-bold text-[#0B1C3F]">{p.price} € <span className="text-[13px] font-medium text-[#64748B]">HT / mois</span></p>
              <ul className="my-3 space-y-1.5 text-[12.5px] text-[#475569]">
                <li>{p.limits.max_customers ? `${nf(p.limits.max_customers)} clients actifs` : 'Clients illimités'}</li>
                <li>{p.limits.push_per_month ? `${nf(p.limits.push_per_month)} notifications / mois` : 'Notifications illimitées'}</li>
                <li>{p.limits.campaigns_per_month ? `${nf(p.limits.campaigns_per_month)} campagnes / mois` : 'Campagnes illimitées'}</li>
                <li>{p.limits.establishments} établissement{p.limits.establishments > 1 ? 's' : ''} · {p.limits.staff_accounts} comptes</li>
              </ul>
              <ul className="mb-4 space-y-1.5">
                {p.features.map((f) => <li key={f} className="flex items-start gap-2 text-[12.5px] text-[#475569]"><Check size={15} className="mt-px shrink-0 text-[#10B981]" /> {f}</li>)}
              </ul>
              <button type="button" disabled={p.current || notConfigured || busy === p.key} onClick={() => act(p.key, () => ownerAPI.billingCheckout(p.key))}
                      className="w-full rounded-xl py-2.5 text-[13.5px] font-medium text-white disabled:opacity-50" style={{ background: BLUE }}>
                {p.current ? 'Votre offre' : busy === p.key ? 'Redirection…' : 'Choisir cette offre'}
              </button>
            </Card>
          ))}
          {notConfigured && <p className="lg:col-span-3 flex items-center gap-2 text-[12.5px] text-[#64748B]"><Info size={14} /> Le paiement en ligne sera activé prochainement. En attendant, contactez le support FidClic pour changer d'offre.</p>}
        </div>
      )}

      {tab === 'facturation' && (
        <Card className="max-w-2xl">
          <Head icon={Receipt} title="Informations de facturation" sub="Ce qui figure sur vos factures FidClic, en tant que client." />
          <dl className="grid gap-x-6 gap-y-2.5 text-[13.5px] sm:grid-cols-2">
            {[['Raison sociale', d.buyer.name], ['Nom commercial', d.buyer.trade_name], ['Adresse', d.buyer.address],
              ['Code postal / Ville', `${d.buyer.postal_code} ${d.buyer.city}`.trim()], ['Pays', d.buyer.country],
              ['SIRET', d.buyer.siret], ['N° de TVA', d.buyer.vat_number], ['E-mail', d.buyer.email]].map(([k, v]) => (
              <div key={k}><dt className="text-[12px] text-[#64748B]">{k}</dt><dd className="text-[#0B1C3F]">{v || <span className="text-[#B45309]">À compléter</span>}</dd></div>
            ))}
          </dl>
          <Link to="/dashboard/parametres/etablissement" className="mt-4 inline-flex items-center gap-1.5 text-[13px] font-semibold text-[#2F6BFF] hover:underline">
            Modifier dans Établissement <ExternalLink size={13} />
          </Link>
          <p className="mt-2 text-[12px] text-[#94A3B8]">Une facture déjà émise n'est jamais modifiée : les changements valent pour les suivantes.</p>
        </Card>
      )}

      {tab === 'paiement' && <div className="max-w-xl"><PaymentBlock big /></div>}

      {tab === 'factures' && (
        <Card>
          <Head icon={FileText} title="Historique des factures" sub="Toutes vos factures FidClic, au format PDF." />
          {!issuerReady && <p className="mb-3 rounded-xl bg-[#FFF7E6] px-3 py-2.5 text-[12.5px] text-[#92400E]">Vos paiements sont enregistrés ; les factures correspondantes sont en cours d'émission.</p>}
          {invoices === null ? <p className="py-8 text-center text-[13px] text-[#64748B]"><Loader2 size={15} className="mr-1 inline animate-spin" /> Chargement…</p>
            : invoices.length === 0 ? <p className="py-10 text-center text-[13px] text-[#64748B]">Aucune facture pour le moment.</p> : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[560px] text-[13.5px]">
                <thead><tr className="border-b border-[#EDF1F7] text-left text-[12.5px] text-[#64748B]">
                  <th className="py-2.5 font-medium">N° de facture</th><th className="py-2.5 font-medium">Date</th><th className="py-2.5 font-medium">Montant TTC</th>
                  <th className="py-2.5 font-medium">Statut</th><th className="py-2.5 text-right font-medium">PDF</th></tr></thead>
                <tbody>
                  {invoices.map((inv) => (
                    <tr key={inv.id} className="border-b border-[#F4F7FC] last:border-0">
                      <td className="py-3 font-medium text-[#0B1C3F]">{inv.number || '—'}</td>
                      <td className="py-3 text-[#475569]">{dmy(inv.paid_at)}</td>
                      <td className="py-3 text-[#0B1C3F]">{eur(inv.total_ttc)}</td>
                      <td className="py-3">{inv.number ? <span className="inline-flex items-center gap-1 rounded-md bg-[#E7F7EE] px-2 py-0.5 text-[12px] text-[#0F8B58]"><BadgeCheck size={13} /> Payée</span>
                        : <span className="rounded-md bg-[#FFF7E6] px-2 py-0.5 text-[12px] text-[#92400E]">En cours d'émission</span>}</td>
                      <td className="py-3 text-right">
                        <button type="button" disabled={!inv.number} onClick={() => pdf(inv)}
                                className="inline-flex items-center gap-1.5 rounded-lg border border-[#DCE3EE] px-3 py-1.5 text-[12.5px] text-[#2F6BFF] disabled:opacity-40">
                          {busy === `pdf-${inv.id}` ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />} Télécharger
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}

      {tab === 'resiliation' && (
        <Card className="max-w-2xl">
          <Head icon={XCircle} title="Résiliation" sub="Vous pouvez résilier à tout moment. Votre accès reste actif jusqu'à la fin de la période payée." tone="#E11D48" bg="#FDECEF" />
          {d.cancel_at_period_end ? (
            <div className="space-y-3">
              <p className="text-[13.5px] text-[#475569]">La résiliation est programmée pour le <strong>{longDate(d.renews_on)}</strong>.</p>
              <button type="button" disabled={busy === 'resume'} onClick={() => act('resume', ownerAPI.resumeSubscription, 'Votre abonnement continue.')}
                      className="rounded-xl px-5 py-2.5 text-[13.5px] font-medium text-white" style={{ background: BLUE }}>Annuler la résiliation</button>
            </div>
          ) : !confirmCancel ? (
            <button type="button" disabled={notConfigured} onClick={() => setConfirmCancel(true)}
                    className="rounded-xl border border-[#E11D48] px-5 py-2.5 text-[13.5px] font-medium text-[#E11D48] disabled:opacity-50">Résilier l'abonnement</button>
          ) : (
            <div className="space-y-3">
              <label className="block text-[13px] text-[#0B1C3F]">Pourquoi partez-vous ? (facultatif)
                <textarea value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500}
                          className="mt-1 min-h-[80px] w-full rounded-lg border border-[#DCE3EE] px-3 py-2 text-[13.5px] outline-none focus:border-[#2F6BFF]" /></label>
              <div className="flex gap-2">
                <button type="button" onClick={() => setConfirmCancel(false)} className="rounded-xl border border-[#DCE3EE] px-4 py-2.5 text-[13.5px]">Garder mon abonnement</button>
                <button type="button" disabled={busy === 'cancel'} onClick={() => act('cancel', () => ownerAPI.cancelSubscription(reason), 'Résiliation enregistrée : votre accès reste actif jusqu’à la fin de la période.').then(() => setConfirmCancel(false))}
                        className="rounded-xl bg-[#E11D48] px-4 py-2.5 text-[13.5px] font-medium text-white">Confirmer la résiliation</button>
              </div>
            </div>
          )}
          {notConfigured && <p className="mt-3 text-[12.5px] text-[#64748B]">Le paiement en ligne n'est pas encore activé : aucune résiliation n'est nécessaire.</p>}
        </Card>
      )}
    </div>
  );
}
