import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, BarChart, Bar } from 'recharts';
import {
  Users, UserCheck, UserX, Store, Target, Gift, RefreshCcw, ExternalLink, Mail, Pencil, MoreHorizontal, LayoutDashboard,
  Heart, Megaphone, Bell, Gauge, CreditCard, Settings, TrendingUp, PieChart as PieIcon, MapPinned, Award, Star, Crown,
  AlertTriangle, Send, Eye, MousePointerClick, ArrowRight, CalendarDays, BadgeCheck, Receipt, PauseCircle, PlayCircle,
  Building2, Search, Loader2, Repeat, Clock, Ban, Undo2,
} from 'lucide-react';
import { adminAPI } from '../../lib/api';
import { protectNames } from '../../lib/translator';
import { Card, Head, Kpi, Donut, Select, Loading, Breadcrumb, Pager, Modal, useToast, nf, BLUE, inputCls } from '../crm/ui';
import { ComposeEmail } from '../crm/emailUi';
import { FranchiseTermsModal } from '../../components/admin/FranchisePanel';
import { StatusPill, PlanPill, CommerceLogo, SuspendModal, ResilierModal, openViewAs, weekly } from './CommercesPage';

/* Super admin › Commerces › one business — built to the approved « Café
   Lumière » mockup. Every figure is counted from the business's own data. */

const TABS = [['apercu', "Vue d'ensemble", LayoutDashboard], ['clients', 'Clients', Users], ['fidelite', 'Fidélité', Heart],
  ['campagnes', 'Campagnes', Megaphone], ['notifications', 'Notifications', Bell], ['utilisation', 'Utilisation', Gauge],
  ['abonnement', 'Abonnement', CreditCard], ['parametres', 'Paramètres', Settings]];
const MONTHS = ['Janv', 'Févr', 'Mars', 'Avr', 'Mai', 'Juin', 'Juil', 'Août', 'Sept', 'Oct', 'Nov', 'Déc'];
const mLabel = (ym) => MONTHS[Number(ym.slice(5, 7)) - 1];
const dateFr = (iso, long) => (iso ? new Date(iso).toLocaleDateString('fr-FR', long ? { day: 'numeric', month: 'short', year: 'numeric' } : undefined) : '—');
const STATUS_FR = { active: 'Actif', trialing: 'Essai gratuit', onboarding: 'Inscription en cours', past_due: 'Paiement en retard', canceled: 'Résilié', expired: 'Expiré' };

export default function CommerceDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  // A super admin reads other businesses' names, which nothing registers:
  // the layout only protects the signed-in shop's own. Without this the
  // translator reaches them wherever they sit inside a sentence — a modal
  // title, a confirmation (user, 2026-10-13).
  const [d, setD] = useState(null);
  const [x, setX] = useState(null);
  const [err, setErr] = useState('');
  const [tab, setTab] = useState('apercu');
  const [menu, setMenu] = useState(false);
  const [modal, setModal] = useState(null);
  // Offers created on Plan Limits are offered too (active ones).
  useEffect(() => {
    if (modal?.type !== 'plan' || modal.custom) return;
    adminAPI.planLimits().then(({ data }) => setModal((m) => (m?.type === 'plan' ? { ...m, custom: data.plans.filter((p) => p.custom && p.active) } : m))).catch(() => {});
  }, [modal]);
  const [say, toast] = useToast();
  const load = useCallback(() => {
    adminAPI.commerce(id).then(({ data }) => { protectNames([data?.name]); setD(data); }).catch((e) => setErr(e?.response?.data?.detail || 'Commerce introuvable.'));
    adminAPI.commerceDetails(id).then(({ data }) => setX(data)).catch(() => {});
  }, [id]);
  useEffect(() => { load(); }, [load]);
  // FIDCLIC AI › « Contacter » / « Relancer » open this page with ?contact=…
  const [params, setParams] = useSearchParams();
  const ask = params.get('contact');
  useEffect(() => {
    if (!ask || !d) return;
    params.delete('contact'); setParams(params, { replace: true });
    contact(ask === 'relance' ? { subject: 'Relancez vos clients avec une campagne FidClic',
      body: `Bonjour {prenom},\n\nVos clients n'ont pas reçu de campagne depuis un moment. Une offre simple (un café offert, -10 % le week-end…) envoyée depuis FidClic les fait revenir.\n\nVoulez-vous que nous en préparions une ensemble ?\n\nL'équipe FIDCLIC` } : null);
  }, [ask, d]); // eslint-disable-line react-hooks/exhaustive-deps
  const act = async (fn, m) => { try { await fn(); say(m); load(); } catch (e) { say(e?.response?.data?.detail || 'Action impossible.'); } };

  if (!d) return err ? <p className="rounded-xl bg-[#FEF2F2] px-4 py-3 text-[13.5px] text-[#B91C1C]">{err}</p> : <Loading />;
  const contact = (preset) => {
    if (d.crm_prospect_id) setModal({ type: 'email', preset });
    else if (d.owner.email) window.location.href = `mailto:${d.owner.email}${preset ? `?subject=${encodeURIComponent(preset.subject)}&body=${encodeURIComponent(preset.body)}` : ''}`;
  };
  return (
    <div className="crm" onClick={() => setMenu(false)}>
      <Breadcrumb items={[['Commerces', '/admin/commerces'], [d.name]]} />
      <header className="mb-4 mt-2 flex flex-wrap items-start gap-4">
        <CommerceLogo c={d} size={84} />
        <div className="min-w-0 flex-1">
          <h1 className="flex flex-wrap items-center gap-3 text-[28px] font-bold leading-tight text-[#0B1C3F]"><span translate="no">{d.name}</span> <StatusPill s={d.status} label={d.status_label} /></h1>
          <p className="mt-1 text-[14px] text-[#64748B]">{[d.sector, d.city && `${d.city}${d.postal_code ? ` (${d.postal_code})` : ''}`].filter(Boolean).join(' • ') || '—'}</p>
          <p className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-[13px] text-[#475569]">
            <span className="flex items-center gap-1.5"><CreditCard size={14} /> Plan : <strong className="text-[#2F6BFF]">{d.plan?.label}</strong></span>
            <span className="flex items-center gap-1.5"><CalendarDays size={14} /> Inscrit le {dateFr(d.created_at, true)}</span>
            {d.renews_on && <span className="flex items-center gap-1.5"><Repeat size={14} /> {d.subscription_status === 'trialing' ? "Fin de l'essai" : 'Prochain renouvellement'} : {dateFr(d.renews_on, true)}</span>}
            {weekly(d) && <span className="flex items-center gap-1.5" title="Le plus faible des deux décide du statut"><TrendingUp size={14} /> {weekly(d)}</span>}
          </p>
          {d.suspended && <p className="mt-2 inline-flex items-center gap-2 rounded-lg bg-[#FEF2F2] px-3 py-1.5 text-[12.5px] text-[#B91C1C]"><PauseCircle size={14} /> Suspendu le {dateFr(d.suspended_at, true)}{d.suspended_reason ? ` — ${d.suspended_reason}` : ''}. L'équipe ne peut pas se connecter ; les cartes des clients fonctionnent.</p>}
          {d.resiliated && (
            <p className="mt-2 flex flex-wrap items-center gap-2 rounded-lg bg-[#0B1C3F] px-3 py-2 text-[12.5px] text-white">
              <Ban size={14} /> Résilié le {dateFr(d.resiliated_at, true)}{d.resiliation_reason ? ` — ${d.resiliation_reason}` : ''}. Compte fermé, cartes des clients désactivées.
              <button type="button" onClick={() => { if (window.confirm(`Annuler la résiliation de ${d.name} ? Le compte et les cartes des clients fonctionneront de nouveau.`)) act(() => adminAPI.annulerResiliation(d.id), 'Résiliation annulée.'); }}
                      className="ml-auto inline-flex items-center gap-1 rounded-md bg-white/15 px-2 py-1 font-medium hover:bg-white/25"><Undo2 size={13} /> Annuler la résiliation</button>
            </p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={() => openViewAs(d.id, say)} className="inline-flex h-10 items-center gap-2 rounded-xl border border-[#2F6BFF] bg-white px-4 text-[13.5px] font-medium text-[#2F6BFF]"><ExternalLink size={15} /> Accéder au compte</button>
          <button type="button" onClick={() => contact()} className="inline-flex h-10 items-center gap-2 rounded-xl border border-[#DCE3EE] bg-white px-4 text-[13.5px] font-medium text-[#0B1C3F]"><Mail size={15} /> Contacter</button>
          <button type="button" onClick={() => setModal({ type: 'edit' })} className="inline-flex h-10 items-center gap-2 rounded-xl border border-[#DCE3EE] bg-white px-4 text-[13.5px] font-medium text-[#0B1C3F]"><Pencil size={15} /> Modifier</button>
          <span className="relative" onClick={(e) => e.stopPropagation()}>
            <button type="button" aria-label="Plus d'actions" onClick={() => setMenu((v) => !v)} className="h-10 rounded-xl border border-[#DCE3EE] bg-white px-3 text-[#0B1C3F]"><MoreHorizontal size={16} /></button>
            {menu && (
              <span className="absolute right-0 top-full z-30 mt-1 flex w-56 flex-col overflow-hidden rounded-xl border border-[#E6EEFB] bg-white py-1 text-[13px] shadow-lg">
                <button type="button" onClick={() => { setMenu(false); setModal({ type: 'plan' }); }} className="flex items-center gap-2 px-3 py-2 text-left hover:bg-[#F4F7FC]"><CreditCard size={14} /> Changer de plan</button>
                <button type="button" onClick={() => { setMenu(false); setModal({ type: 'franchise' }); }} className="flex items-center gap-2 px-3 py-2 text-left hover:bg-[#F4F7FC]"><Building2 size={14} /> Conditions Franchise</button>
                {d.suspended
                  ? <button type="button" onClick={() => { setMenu(false); act(() => adminAPI.reactivateCommerce(d.id), 'Commerce réactivé.'); }} className="flex items-center gap-2 px-3 py-2 text-left text-[#0F8B58] hover:bg-[#F0FDF4]"><PlayCircle size={14} /> Réactiver</button>
                  : <button type="button" onClick={() => { setMenu(false); setModal({ type: 'suspend' }); }} className="flex items-center gap-2 px-3 py-2 text-left text-[#E11D48] hover:bg-[#FEF2F2]"><PauseCircle size={14} /> Suspendre</button>}
                {d.resiliated
                  ? <button type="button" onClick={() => { setMenu(false); if (window.confirm(`Annuler la résiliation de ${d.name} ?`)) act(() => adminAPI.annulerResiliation(d.id), 'Résiliation annulée.'); }} className="flex items-center gap-2 px-3 py-2 text-left text-[#0F8B58] hover:bg-[#F0FDF4]"><Undo2 size={14} /> Annuler la résiliation</button>
                  : <button type="button" onClick={() => { setMenu(false); setModal({ type: 'resilier' }); }} className="flex items-center gap-2 px-3 py-2 text-left text-[#0B1C3F] hover:bg-[#F4F7FC]"><Ban size={14} /> Résilier…</button>}
              </span>
            )}
          </span>
        </div>
      </header>

      <nav className="mb-4 flex gap-1 overflow-x-auto rounded-2xl border border-[#EDF1F7] bg-white px-3">
        {TABS.map(([k, l, I]) => (
          <button key={k} type="button" onClick={() => setTab(k)} className={`flex shrink-0 items-center gap-2 border-b-2 px-3 py-3 text-[13.5px] ${tab === k ? 'border-[#2F6BFF] font-medium text-[#2F6BFF]' : 'border-transparent text-[#0B1C3F]'}`}><I size={15} /> {l}</button>
        ))}
      </nav>

      {tab === 'apercu' && <Overview d={d} setTab={setTab} setModal={setModal} />}
      {tab === 'clients' && <ClientsTab id={id} />}
      {tab !== 'apercu' && tab !== 'clients' && !x && <Loading />}
      {tab === 'fidelite' && x && <FideliteTab d={d} x={x.fidelite} />}
      {tab === 'campagnes' && x && <CampagnesTab rows={x.campagnes} />}
      {tab === 'notifications' && x && <NotificationsTab n={x.notifications} />}
      {tab === 'utilisation' && <UsageCard d={d} big />}
      {tab === 'abonnement' && x && <AbonnementTab d={d} a={x.abonnement} setModal={setModal} />}
      {tab === 'parametres' && x && <ParametresTab p={x.parametres} />}

      {toast}
      {modal?.type === 'email' && <ComposeEmail prospect={{ id: d.crm_prospect_id, name: d.name, email: d.owner.email }} initial={modal.preset} onClose={() => setModal(null)} onSent={(m) => { setModal(null); say(m); }} />}
      {modal?.type === 'edit' && <EditModal d={d} onClose={() => setModal(null)} onDone={() => { setModal(null); say('Commerce modifié.'); load(); }} />}
      {modal?.type === 'suspend' && <SuspendModal c={d} onClose={() => setModal(null)} onDone={(m) => { setModal(null); say(m); load(); }} />}
      {modal?.type === 'resilier' && <ResilierModal c={d} onClose={() => setModal(null)} onDone={(m) => { setModal(null); say(m); load(); }} />}
      {modal?.type === 'franchise' && <FranchiseTermsModal tenant={{ id: d.id, name: d.name, stores: d.stores, terms: d.franchise_terms }} onClose={() => setModal(null)} onSaved={() => { setModal(null); say('Conditions Franchise enregistrées.'); load(); }} />}
      {modal?.type === 'plan' && (
        <Modal title={`Changer le plan — ${d.name}`} onClose={() => setModal(null)}>
          <div className="space-y-2">
            {[['silver', 'Starter'], ['gold', 'Pro'], ['vip', 'Pro AI'], ...(modal.custom || []).map((p) => [p.key, `${p.label} — ${p.price}€`])].map(([k, l]) => (
              <button key={k} type="button" disabled={d.plan_key === k} onClick={() => { setModal(null); act(() => adminAPI.commercePlan(d.id, k), `Plan ${l} appliqué.`); }}
                      className="flex w-full items-center justify-between rounded-xl border border-[#DCE3EE] px-3 py-2.5 text-left text-[13.5px] hover:border-[#2F6BFF] disabled:opacity-50">{l}{d.plan_key === k && <span className="text-[12px] text-[#2F6BFF]">Plan actuel</span>}</button>
            ))}
            <button type="button" onClick={() => setModal({ type: 'franchise' })} className="flex w-full items-center justify-between rounded-xl border border-[#DCE3EE] px-3 py-2.5 text-left text-[13.5px] hover:border-[#7C3AED]">Franchise — sur devis <ArrowRight size={14} /></button>
            <p className="pt-1 text-[12px] text-[#64748B]">Le changement s'applique tout de suite aux limites du commerce. La facturation Stripe, elle, reste à ajuster dans Stripe si le commerce a un abonnement.</p>
          </div>
        </Modal>
      )}
    </div>
  );
}

function Overview({ d, setTab, setModal }) {
  const K = Object.fromEntries(d.kpis.map((k) => [k.key, k]));
  const cards = [
    ['clients', 'Clients total', Users, '#2F6BFF', '#EAF1FF'], ['actifs', 'Clients actifs', UserCheck, '#10B981', '#E7F7EE'],
    ['dormants', 'Clients dormants', UserX, '#E11D48', '#FDECEF'], ['visites', 'Visites (30 j)', Store, '#0EA5E9', '#E0F2FE'],
    ['points', 'Points distribués', Target, '#8B5CF6', '#F3EEFF'], ['recompenses', 'Récompenses utilisées', Gift, '#F59E0B', '#FFF4DB'],
    ['retour', 'Taux de retour', RefreshCcw, '#10B981', '#E7F7EE'],
  ];
  const fid = [['cartes_actives', 'Cartes actives', BadgeCheck, '#10B981'], ['fideles', 'Clients fidèles', Star, '#2F6BFF'], ['reguliers', 'Clients réguliers', Crown, '#8B5CF6'], ['attrition', "Taux d'attrition", AlertTriangle, '#E11D48']];
  return (
    <>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 2xl:grid-cols-7">
        {cards.map(([k, l, I, c, bg]) => <Kpi key={k} icon={I} tone={c} bg={bg} value={k === 'retour' ? `${K[k].value}%` : nf(K[k].value)} label={l} delta={K[k].delta} series={K[k].series || []} />)}
      </div>
      <div className="mt-4 grid gap-4 xl:grid-cols-[1.25fr_1fr_1fr]">
        <Card>
          <Head icon={TrendingUp} title="Évolution des clients et des visites" sub="6 derniers mois" />
          <div className="mb-1 flex flex-wrap gap-3 text-[12px] text-[#475569]">
            {[['#2F6BFF', 'Nouveaux clients'], ['#10B981', 'Clients actifs'], ['#8B5CF6', 'Visites']].map(([c, l]) => <span key={l} className="flex items-center gap-1.5"><i className="h-2 w-2 rounded-full" style={{ background: c }} />{l}</span>)}
          </div>
          <div className="h-[220px]">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={d.months.map((m) => ({ ...m, m: mLabel(m.month) }))} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
                <CartesianGrid stroke="#EEF2F7" vertical={false} />
                <XAxis dataKey="m" tick={{ fontSize: 11, fill: '#64748B' }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 11, fill: '#64748B' }} axisLine={false} tickLine={false} allowDecimals={false} />
                <Tooltip formatter={(v, k) => [nf(v), { nouveaux: 'Nouveaux clients', actifs: 'Clients actifs', visites: 'Visites' }[k]]} />
                <Line type="monotone" dataKey="nouveaux" stroke="#2F6BFF" strokeWidth={2} dot={{ r: 3 }} />
                <Line type="monotone" dataKey="actifs" stroke="#10B981" strokeWidth={2} dot={{ r: 3 }} />
                <Line type="monotone" dataKey="visites" stroke="#8B5CF6" strokeWidth={2} dot={{ r: 3 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <Card><Head icon={PieIcon} title="Répartition des clients" /><Donut rows={d.repartition} center={nf(d.total_clients)} sub="clients" /></Card>
        <Card><Head icon={MapPinned} title="Zone de chalandise" sub="clients des 12 derniers mois" /><Zone id={d.id} /></Card>
      </div>
      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <Card>
          <Head icon={Award} title="Performances fidélité" />
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {fid.map(([k, l, I, c]) => (
              <div key={k} className="rounded-xl border border-[#EDF1F7] p-3"><I size={18} style={{ color: c }} /><p className="mt-2 text-[20px] font-bold text-[#0B1C3F]">{d.fidelite[k]}%</p><p className="text-[12px] text-[#64748B]">{l}</p></div>
            ))}
          </div>
        </Card>
        <Card>
          <Head icon={Megaphone} title="Campagnes" right={<button type="button" onClick={() => setTab('campagnes')} className="text-[12.5px] text-[#2F6BFF]">Voir tout →</button>} />
          <div className="grid grid-cols-3 gap-2">
            {[[Send, nf(d.campagnes.this_month), 'Campagnes envoyées ce mois', '#2F6BFF'], [Eye, `${d.campagnes.open_rate}%`, "Taux d'ouverture", '#10B981'], [MousePointerClick, `${d.campagnes.click_rate}%`, 'Taux de clic', '#8B5CF6']].map(([I, v, l, c]) => (
              <div key={l} className="rounded-xl border border-[#EDF1F7] p-3"><I size={18} style={{ color: c }} /><p className="mt-2 text-[20px] font-bold text-[#0B1C3F]">{v}</p><p className="text-[12px] text-[#64748B]">{l}</p></div>
            ))}
          </div>
        </Card>
        <UsageCard d={d} onMore={() => setTab('utilisation')} />
      </div>
      <div className="mt-4 grid gap-4 xl:grid-cols-[1.6fr_1fr]">
        <Card>
          <Head icon={Megaphone} title="Dernières campagnes" right={<button type="button" onClick={() => setTab('campagnes')} className="text-[12.5px] text-[#2F6BFF]">Voir tout →</button>} />
          <CampTable rows={d.campagnes.recent} />
        </Card>
        <Card>
          <Head icon={Receipt} title="Informations & abonnement" right={<button type="button" onClick={() => setModal({ type: 'edit' })} aria-label="Modifier" className="text-[#2F6BFF]"><Pencil size={15} /></button>} />
          <dl className="space-y-2.5 text-[13px]">
            <div className="flex items-center justify-between gap-2"><dt className="text-[#64748B]">Plan actuel</dt><dd className="flex items-center gap-2"><PlanPill p={d.plan} /><button type="button" onClick={() => setModal({ type: 'plan' })} className="rounded-lg px-3 py-1.5 text-[12.5px] font-medium text-white" style={{ background: BLUE }}>Changer de plan</button></dd></div>
            <Row k="Prix" v={d.on_quote ? (d.price ? `${nf(d.price)} € HT / mois (franchise)` : 'Sur devis — à fixer') : d.price ? `${nf(d.price)} € HT / mois` : '—'} />
            <Row k="Date de début" v={dateFr(d.created_at, true)} />
            <Row k={d.subscription_status === 'trialing' ? "Fin de l'essai" : 'Renouvellement'} v={dateFr(d.renews_on, true)} />
            <Row k="Statut" v={STATUS_FR[d.subscription_status] || d.subscription_status || '—'} />
            <Row k="Méthode de paiement" v={d.payment_method ? `${d.payment_method.brand || 'Carte'} •••• ${d.payment_method.last4}` : 'Aucune'} />
            <Row k="Propriétaire" v={[d.owner.name, d.owner.email].filter(Boolean).join(' — ') || '—'} />
            <div className="flex justify-between"><dt className="text-[#64748B]">Factures</dt><dd><button type="button" onClick={() => setTab('abonnement')} className="text-[#2F6BFF]">Voir l'historique →</button></dd></div>
          </dl>
        </Card>
      </div>
    </>
  );
}

const Row = ({ k, v }) => <div className="flex justify-between gap-3"><dt className="shrink-0 text-[#64748B]">{k}</dt><dd className="truncate text-right font-medium text-[#0B1C3F]">{v}</dd></div>;

function UsageCard({ d, onMore, big }) {
  const color = (p) => (p == null ? '#94A3B8' : p >= 100 ? '#E11D48' : p >= 80 ? '#F59E0B' : '#2F6BFF');
  return (
    <Card className={big ? 'max-w-3xl' : ''}>
      <Head icon={Gauge} title={`Utilisation du plan ${d.plan_label}`} right={onMore && <button type="button" onClick={onMore} className="text-[12.5px] text-[#2F6BFF]">Voir détail →</button>} />
      <ul className="space-y-3">
        {d.usage.map((u) => (
          <li key={u.key} className="grid grid-cols-[110px_1fr_64px] items-center gap-3 text-[13px]">
            <span className="text-[#475569]">{u.label}</span>
            <span>
              <span className="mb-0.5 block text-right text-[11px] text-[#64748B]">{nf(u.used)}{u.limit ? ` / ${nf(u.limit)}` : ' · illimité'}</span>
              <span className="block h-2.5 overflow-hidden rounded-full bg-[#EEF2F8]"><span className="block h-full rounded-full" style={{ width: `${Math.min(100, u.pct ?? 0)}%`, background: color(u.pct) }} /></span>
            </span>
            <span className="text-right font-semibold" style={{ color: color(u.pct) }}>{u.pct == null ? '—' : `${u.pct}%`}</span>
          </li>
        ))}
      </ul>
      {d.usage.some((u) => (u.pct ?? 0) >= 100) && <p className="mt-3 flex items-center gap-1.5 text-[12px] text-[#B91C1C]"><AlertTriangle size={13} /> Limite dépassée : proposez un plan supérieur.</p>}
    </Card>
  );
}

/* The same Leaflet copy as Établissement: rings of travel time, a dot per client. */
function Zone({ id }) {
  const [z, setZ] = useState(null);
  const box = useRef(null);
  const map = useRef(null);
  useEffect(() => { adminAPI.commerceZone(id).then(({ data }) => setZ(data)).catch(() => setZ({ bands: [], points: [] })); }, [id]);
  useEffect(() => {
    const L = window.L;
    if (!z || !L || !box.current || map.current || z.shop?.lat == null) return undefined;
    map.current = L.map(box.current, { attributionControl: false, zoomControl: false, scrollWheelZoom: false }).setView([z.shop.lat, z.shop.lng], 12);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19 }).addTo(map.current);
    [...(z.bands || [])].slice(0, 3).reverse().forEach((b, i) => L.circle([z.shop.lat, z.shop.lng], { radius: b.radius_km * 1000, color: '#2F6BFF', weight: 1, fillColor: '#2F6BFF', fillOpacity: 0.08 + i * 0.06 }).addTo(map.current));
    (z.points || []).forEach((p) => L.circleMarker([p.lat, p.lng], { radius: 2.5, color: '#2F6BFF', weight: 0, fillOpacity: 0.7 }).addTo(map.current));
    L.circleMarker([z.shop.lat, z.shop.lng], { radius: 7, color: '#fff', weight: 3, fillColor: '#2F6BFF', fillOpacity: 1 }).addTo(map.current);
    setTimeout(() => map.current && map.current.invalidateSize(), 60);
    return () => { map.current && map.current.remove(); map.current = null; };
  }, [z]);
  if (!z) return <p className="py-10 text-center text-[12px] text-[#94A3B8]"><Loader2 size={14} className="inline animate-spin" /></p>;
  const bands = (z.bands || []).slice(0, 3);
  return (
    <div className="flex flex-wrap gap-3">
      {z.shop?.lat != null
        ? <div ref={box} style={{ height: 190, isolation: 'isolate' }} className="relative z-0 min-w-[180px] flex-1 overflow-hidden rounded-xl bg-[#EAF1FB]" />
        : <p className="flex min-h-[190px] flex-1 items-center justify-center rounded-xl bg-[#F8FAFF] p-3 text-center text-[12px] text-[#64748B]">Adresse du commerce inconnue : la carte apparaîtra quand elle sera renseignée.</p>}
      <ul className="w-[120px] space-y-3 text-[12px]">
        {bands.map((b, i) => (
          <li key={b.minutes}><p className="flex items-center gap-1.5 font-medium text-[#0B1C3F]"><i className="h-2.5 w-2.5 rounded-full bg-[#2F6BFF]" style={{ opacity: 1 - i * 0.3 }} />{i ? bands[i - 1].minutes : 0}-{b.minutes} min</p><p className="pl-4 text-[#64748B]">{nf(b.clients)} clients</p></li>
        ))}
        <li className="text-[10.5px] text-[#94A3B8]">Temps en voiture estimés à vol d'oiseau.</li>
      </ul>
    </div>
  );
}

function CampTable({ rows }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[620px] text-[12.5px]">
        <thead><tr className="border-b border-[#EDF1F7] text-left text-[#64748B]">{['#', 'Campagne', 'Type', 'Destinataires', 'Ouverture', 'Clic', 'Date', 'Statut'].map((h) => <th key={h} className="px-2 py-2 font-medium">{h}</th>)}</tr></thead>
        <tbody>
          {rows.map((c, i) => (
            <tr key={c.id || i} className="border-b border-[#F4F7FC]">
              <td className="px-2 py-2 text-[#94A3B8]">{i + 1}</td><td translate="no" className="max-w-[220px] truncate px-2 py-2 font-medium text-[#0B1C3F]">{c.name}</td>
              <td className="px-2 py-2 text-[#475569]">{c.type}</td><td className="px-2 py-2">{nf(c.recipients)}</td><td className="px-2 py-2">{c.open_rate}%</td><td className="px-2 py-2">{c.click_rate}%</td>
              <td className="whitespace-nowrap px-2 py-2 text-[#475569]">{dateFr(c.sent_at, true)}</td>
              <td className="px-2 py-2"><span className="rounded-md bg-[#E7F7EE] px-2 py-0.5 text-[11.5px] text-[#0F8B58]">{c.status}</span></td>
            </tr>
          ))}
          {!rows.length && <tr><td colSpan={8} className="py-8 text-center text-[#94A3B8]">Aucune campagne envoyée.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

function ClientsTab({ id }) {
  const [d, setD] = useState(null);
  const [q, setQ] = useState('');
  const [page, setPage] = useState(1);
  useEffect(() => { adminAPI.commerceClients(id, { q, page, per_page: 20 }).then(({ data }) => setD(data)).catch(() => setD({ rows: [], total: 0, pages: 1 })); }, [id, q, page]);
  if (!d) return <Loading />;
  return (
    <Card>
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <label className="relative w-full max-w-sm"><Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8]" /><input className={`${inputCls} pl-9`} placeholder="Rechercher un client…" value={q} onChange={(e) => { setPage(1); setQ(e.target.value); }} /></label>
        <p className="text-[12px] text-[#64748B]">Coordonnées masquées : les clients appartiennent au commerce.</p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-[13px]">
          <thead><tr className="border-b border-[#EDF1F7] text-left text-[#64748B]">{['Client', 'Palier', 'Visites', 'Points', 'Carte', 'Dernière visite', 'Inscrit le'].map((h) => <th key={h} className="px-2 py-2 font-medium">{h}</th>)}</tr></thead>
          <tbody>{d.rows.map((c) => (
            <tr key={c.id} className="border-b border-[#F4F7FC]">
              <td translate="no" className="px-2 py-2 font-medium text-[#0B1C3F]">{c.name}</td><td className="px-2 py-2 capitalize">{c.tier || 'bronze'}</td><td className="px-2 py-2">{nf(c.visits)}</td>
              <td className="px-2 py-2">{nf(c.points)}</td><td className="px-2 py-2">{c.pass_issued ? 'Sur le téléphone' : '—'}</td>
              <td className="px-2 py-2 text-[#475569]">{dateFr(c.last_visit_date)}</td><td className="px-2 py-2 text-[#475569]">{dateFr(c.created_at)}</td>
            </tr>))}
            {!d.rows.length && <tr><td colSpan={7} className="py-8 text-center text-[#94A3B8]">Aucun client.</td></tr>}
          </tbody>
        </table>
      </div>
      <Pager page={page} pages={d.pages} total={d.total} perPage={20} onPage={setPage} what="clients" />
    </Card>
  );
}

function FideliteTab({ d, x }) {
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card><Head icon={Crown} title="Clients par palier" /><Donut rows={x.tiers.map((t) => ({ ...t, pct: Math.round(t.count / Math.max(1, x.tiers.reduce((a, b) => a + b.count, 0)) * 100) }))} center={nf(x.tiers.reduce((a, b) => a + b.count, 0))} sub="clients" /></Card>
      <Card>
        <Head icon={Gift} title="Récompenses utilisées" sub="6 derniers mois" />
        <div className="h-[200px]"><ResponsiveContainer width="100%" height="100%"><BarChart data={x.rewards.map((r) => ({ ...r, m: mLabel(r.month) }))} margin={{ top: 8, right: 8, left: -24, bottom: 0 }}>
          <CartesianGrid stroke="#EEF2F7" vertical={false} /><XAxis dataKey="m" tick={{ fontSize: 11, fill: '#64748B' }} axisLine={false} tickLine={false} /><YAxis allowDecimals={false} tick={{ fontSize: 11, fill: '#64748B' }} axisLine={false} tickLine={false} />
          <Tooltip formatter={(v) => [v, 'Récompenses']} /><Bar dataKey="count" fill="#F59E0B" radius={[6, 6, 0, 0]} /></BarChart></ResponsiveContainer></div>
      </Card>
      <Card>
        <Head icon={Award} title="Programme" />
        <dl className="space-y-2.5 text-[13px]">
          <Row k="Mode" v={x.points_mode === 'per_euro' ? 'Points par euro' : 'Tampons par visite'} />
          <Row k="Récompense au bout de" v={x.reward_threshold ? `${x.reward_threshold} ${x.points_mode === 'per_euro' ? 'points' : 'tampons'}` : '—'} />
          <Row k="Récompense" v={x.reward_label || '—'} />
          {Object.entries(d.fidelite).map(([k, v]) => <Row key={k} k={{ cartes_actives: 'Cartes actives', fideles: 'Clients fidèles (5+ visites)', reguliers: 'Clients réguliers (30 j)', attrition: "Taux d'attrition (90 j)" }[k]} v={`${v}%`} />)}
        </dl>
      </Card>
    </div>
  );
}

function CampagnesTab({ rows }) {
  return <Card><Head icon={Megaphone} title={`Campagnes (${rows.length})`} /><CampTable rows={rows} /></Card>;
}

function NotificationsTab({ n }) {
  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_1.5fr]">
      <Card>
        <Head icon={Bell} title="Notifications activées" />
        <p className="text-[34px] font-bold text-[#0B1C3F]">{n.pct}%</p>
        <p className="text-[13px] text-[#64748B]">{nf(n.subscribed)} clients sur {nf(n.total)} reçoivent les notifications push.</p>
        <span className="mt-3 block h-2.5 overflow-hidden rounded-full bg-[#EEF2F8]"><span className="block h-full rounded-full bg-[#10B981]" style={{ width: `${n.pct}%` }} /></span>
      </Card>
      <Card>
        <Head icon={Send} title="Envois des 30 derniers jours" />
        <table className="w-full text-[13px]">
          <thead><tr className="border-b border-[#EDF1F7] text-left text-[#64748B]"><th className="py-2 font-medium">Type</th><th className="font-medium">Envoyées</th><th className="font-medium">Échecs</th></tr></thead>
          <tbody>{n.by_kind.map((k) => <tr key={k.kind} className="border-b border-[#F4F7FC]"><td className="py-2 capitalize">{k.kind.replace(/_/g, ' ')}</td><td>{nf(k.sent)}</td><td className={k.failed ? 'text-[#E11D48]' : ''}>{nf(k.failed)}</td></tr>)}
            {!n.by_kind.length && <tr><td colSpan={3} className="py-8 text-center text-[#94A3B8]">Aucun envoi ce mois-ci.</td></tr>}</tbody>
        </table>
      </Card>
    </div>
  );
}

function AbonnementTab({ d, a, setModal }) {
  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_1.4fr]">
      <Card>
        <Head icon={CreditCard} title="Abonnement" right={<button type="button" onClick={() => setModal({ type: 'plan' })} className="rounded-lg px-3 py-1.5 text-[12.5px] font-medium text-white" style={{ background: BLUE }}>Changer de plan</button>} />
        <dl className="space-y-2.5 text-[13px]">
          <Row k="Plan" v={a.plan} />
          <Row k="Prix" v={a.on_quote ? (a.price ? `${nf(a.price)} € HT / mois` : 'Sur devis — à fixer') : a.price ? `${nf(a.price)} € HT / mois` : '—'} />
          <Row k="Statut" v={STATUS_FR[a.status] || a.status || '—'} />
          {a.trial_ends_at && <Row k="Fin de l'essai" v={dateFr(a.trial_ends_at, true)} />}
          {a.renews_on && <Row k="Renouvellement" v={dateFr(a.renews_on, true)} />}
          <Row k="Client depuis" v={dateFr(a.since, true)} />
          <Row k="Paiement" v={a.payment_method ? `${a.payment_method.brand || 'Carte'} •••• ${a.payment_method.last4}` : 'Aucun moyen de paiement'} />
          {a.on_quote && <div className="rounded-xl bg-[#F3EEFF] p-3 text-[12.5px] text-[#5B21B6]">Franchise : {a.franchise_terms.establishments ? `${a.franchise_terms.establishments} établissements` : 'conditions à fixer'}{a.franchise_terms.notes ? ` — ${a.franchise_terms.notes}` : ''} <button type="button" onClick={() => setModal({ type: 'franchise' })} className="ml-1 underline">Modifier</button></div>}
        </dl>
      </Card>
      <Card>
        <Head icon={Receipt} title="Factures FidClic" />
        <table className="w-full text-[13px]">
          <thead><tr className="border-b border-[#EDF1F7] text-left text-[#64748B]"><th className="py-2 font-medium">Numéro</th><th className="font-medium">Date</th><th className="font-medium">Montant</th><th className="font-medium">Statut</th></tr></thead>
          <tbody>{a.invoices.map((i) => <tr key={i.number || i.paid_at} className="border-b border-[#F4F7FC]"><td className="py-2 font-medium">{i.number || 'En attente de numéro'}</td><td>{dateFr(i.paid_at)}</td><td>{i.amount != null ? `${Number(i.amount).toLocaleString('fr-FR', { minimumFractionDigits: 2 })} €` : '—'}</td><td>{i.status === 'issued' || i.status === 'paid' ? 'Payée' : i.status || '—'}</td></tr>)}
            {!a.invoices.length && <tr><td colSpan={4} className="py-8 text-center text-[#94A3B8]">Aucune facture pour l'instant.</td></tr>}</tbody>
        </table>
      </Card>
    </div>
  );
}

function ParametresTab({ p }) {
  const ROLE = { business_owner: 'Propriétaire', administrateur: 'Administrateur', manager: 'Manager', staff: 'Staff' };
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card>
        <Head icon={Store} title="Établissement" />
        <dl className="space-y-2.5 text-[13px]">
          <Row k="Adresse" v={[p.address, [p.postal_code, p.city].filter(Boolean).join(' ')].filter(Boolean).join(', ') || '—'} />
          <Row k="Téléphone" v={p.phone || '—'} /><Row k="Site web" v={p.website || '—'} />
          <Row k="Raison sociale" v={p.legal_name || '—'} /><Row k="SIRET" v={p.siret || '—'} />
          <Row k="Rayon de géolocalisation" v={p.geo_radius_meters ? `${p.geo_radius_meters} m` : '—'} />
          <Row k="Nom d'expéditeur" v={p.sender_name || '—'} />
        </dl>
      </Card>
      <Card>
        <Head icon={Building2} title={`Établissements (${p.stores.length || 1})`} />
        <ul className="space-y-2 text-[13px]">{(p.stores.length ? p.stores : [{ id: 'main', name: 'Établissement principal', status: 'open' }]).map((s) => (
          <li key={s.id} className="flex items-center justify-between rounded-lg border border-[#EDF1F7] px-3 py-2"><span className="font-medium text-[#0B1C3F]">{s.name}{s.city ? <span className="font-normal text-[#64748B]"> · {s.city}</span> : null}</span><span className={`text-[12px] ${s.status === 'closed' ? 'text-[#E11D48]' : 'text-[#0F8B58]'}`}>{s.status === 'closed' ? 'Fermé' : 'Ouvert'}</span></li>))}</ul>
      </Card>
      <Card>
        <Head icon={Users} title={`Équipe (${p.team.length})`} />
        <ul className="space-y-2 text-[13px]">{p.team.map((u) => (
          <li key={u.email} className="rounded-lg border border-[#EDF1F7] px-3 py-2"><p className="flex items-center justify-between gap-2"><span className="truncate font-medium text-[#0B1C3F]">{u.name || u.email}</span><span className="text-[12px] text-[#64748B]">{ROLE[u.role] || u.role}</span></p>
            <p className="text-[11.5px] text-[#94A3B8]">{u.email}{u.two_fa ? ' · 2FA' : ''}{!u.active ? ' · désactivé' : ''}</p></li>))}</ul>
      </Card>
    </div>
  );
}

function EditModal({ d, onClose, onDone }) {
  const [f, setF] = useState({ name: d.name || '', sector: d.sector || '', city: d.city || '', postal_code: d.postal_code || '', address: d.address || '', phone: d.phone || '', website: d.website || '' });
  const [err, setErr] = useState('');
  const save = async () => { try { await adminAPI.editCommerce(d.id, f); onDone(); } catch (e) { setErr(e?.response?.data?.detail || 'Enregistrement impossible.'); } };
  const inp = (k, l, cls = '') => <label className={`block ${cls}`}><span className="mb-1 block text-[11.5px] text-[#64748B]">{l}</span><input className={inputCls} value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} /></label>;
  return (
    <Modal title={`Modifier — ${d.name}`} onClose={onClose}>
      <div className="grid gap-2 sm:grid-cols-2">
        {inp('name', 'Nom', 'sm:col-span-2')}{inp('sector', 'Secteur')}{inp('city', 'Ville')}{inp('postal_code', 'Code postal')}{inp('phone', 'Téléphone')}
        {inp('address', 'Adresse', 'sm:col-span-2')}{inp('website', 'Site web', 'sm:col-span-2')}
      </div>
      {err && <p className="mt-2 text-[13px] text-[#C0392B]">{err}</p>}
      <button type="button" disabled={!f.name.trim()} onClick={save} className="mt-3 w-full rounded-lg py-2.5 text-[13.5px] font-semibold text-white disabled:opacity-50" style={{ background: BLUE }}>Enregistrer</button>
    </Modal>
  );
}
