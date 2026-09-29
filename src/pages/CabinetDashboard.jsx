import React, { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Building2, ShieldCheck, AlertTriangle, Download, RefreshCw, X, ChevronRight, ArrowLeft,
} from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { comptableAPI, facturationAPI, cabinetExtraAPI, casesAPI, cabinetOsAPI } from '../lib/api';
import GrilleModal from '../components/GrilleModal';
import NewClientModal from '../components/NewClientModal';
import NewSubscriptionModal from '../components/NewSubscriptionModal';
import { CreateInvoiceModal } from './FacturationHome';
import LiveText from '../components/LiveText';
import AgentToolsPanel from '../components/AgentToolsPanel';
import WhatsAppIcon from '../components/WhatsAppIcon';
import GuideBox from '../components/GuideBox';
import AskPieceModal from '../components/AskPieceModal';
import { MC, glass, EASE, statusColor } from '../components/cabinet/mc';
import { AmbientCanvas, Rise, StatTile, Panel, Pill as McPill, McButton, LiveDot }
  from '../components/cabinet/Primitives';
import CoachMarks, { tourSeen, resetTour } from '../components/cabinet/CoachMarks';
import DemoMode from '../components/cabinet/DemoMode';
import Sidebar, { useSidebar } from '../components/cabinet/Sidebar';

/** Stat tile → which dossiers it filters to. */
const FILTERS = {
  all: { label: 'Tous les dossiers', match: () => true },
  red: { label: 'Action requise', match: (c) => c.band === 'red' },
  amber: { label: 'À vérifier', match: (c) => c.band === 'amber' },
  green: { label: 'Conformes', match: (c) => c.band === 'green' },
};

/** The guided tour — one step per real control, nothing left unexplained. */
const HOME_TOUR = [
  { sel: '[data-tour="hero"]', title: '1. Votre journée, en une ligne',
    body: "Qui vous êtes, et LA chose qui vous attend aujourd'hui. Si rien n'attend votre validation, c'est écrit en vert.",
    example: "un assistant voit « photographiez les factures », un expert-comptable voit « 2 factures à valider »." },
  { sel: '[data-tour="nightstrip"]', title: "2. L'agent travaille la nuit",
    body: "Pendant que le cabinet dort, l'agent relance les clients, lit les pièces, prépare les écritures et les contrôles. Cliquez pour revoir le déroulé, capture par capture.",
    example: "au réveil : 7 pièces lues, 7 écritures prêtes, 1 anomalie signalée — il ne reste qu'à valider." },
  { sel: '[data-tour="stats"]', title: '3. Les 4 chiffres — et ils filtrent',
    body: "Dossiers suivis, action requise (rouge), à vérifier (orange), conformes (vert). Cliquez un chiffre : la liste en dessous ne garde que ces dossiers-là.",
    example: "cliquez « À vérifier · 5 » → les 5 dossiers concernés s'affichent seuls." },
  { sel: '[data-tour="priority"]', title: '4. À traiter en priorité',
    body: "Ce que l'agent a repéré comme le plus urgent, tous dossiers confondus. Cliquez le nom du client pour ouvrir son dossier directement à l'endroit du problème.",
    example: "« BOUYGUES — Conformité DGFiP non activée » → un clic et vous y êtes." },
  { sel: '[data-tour="dossiers"]', title: '5. Vos dossiers clients',
    body: "Chaque ligne : la pastille de santé, le score sur 100, le travail en attente, et le volume de factures. Cliquez pour entrer dans le dossier.",
    example: "« BOUYGUES · 72/100 · 2 à revoir » — deux factures attendent une validation humaine." },
  { sel: '[data-tour="nav-home"]', title: '6. Le menu — Pilotage',
    body: "La colonne de gauche regroupe tout. « Accueil » remet la vue à zéro et enlève tout filtre.",
    example: null },
  { sel: '[data-tour="nav-dossiers"]', title: '7. Mes dossiers',
    body: "Le nombre de dossiers que suit le cabinet. Cliquez pour sauter directement à la liste.",
    example: null },
  { sel: '[data-tour="nav-review"]', title: '8. À valider — la règle des 4 yeux',
    body: "Au-dessus d'un seuil, celui qui prépare une facture ne peut pas la valider lui-même. Cette file, c'est ce qui attend VOTRE signature.",
    example: "Léa prépare une facture de 2 400 € → c'est Rousseau ou Sophie qui doit la valider." },
  { sel: '[data-tour="nav-cases"]', title: '9. Cas ouverts',
    body: "Le centre d'exceptions : chaque échec devient un cas daté et assignable — facture rejetée par la plateforme, pièce jamais reçue après 3 relances…",
    example: "3 relances sans réponse → un cas s'ouvre pour qu'un humain appelle le client." },
  { sel: '[data-tour="nav-team"]', title: '10. Mon équipe',
    body: "Créez les comptes de vos collaborateurs, choisissez leur rôle et leur pôle, attribuez les dossiers. Chacun ne voit que ce qui le concerne.",
    example: "un assistant produit mais ne valide pas ; l'expert-comptable est le seul à signer." },
  { sel: '[data-tour="nav-relances"]', title: '11. Lancer les relances',
    body: "Un clic et l'agent écrit à TOUS les clients qui doivent une pièce — au bon moment pour chacun, par email ou WhatsApp.",
    example: "un bon payeur est relancé doucement et tard ; un retardataire, tôt et fermement." },
  { sel: '[data-tour="nav-newclient"]', title: '12. Nouveau client',
    body: "Saisissez le SIREN : raison sociale, adresse et code NAF se remplissent tout seuls. Le dossier et le mandat sont créés en une étape.",
    example: null },
  { sel: '[data-tour="nav-import"]', title: '13. Importer des clients',
    body: "Un fichier CSV (raison sociale, SIREN, email, plateforme) et tous vos dossiers se créent d'un coup — avec leur plateforme agréée respective.",
    example: "45 clients importés en 30 secondes au lieu de 45 saisies manuelles." },
  { sel: '[data-tour="nav-export"]', title: '14. Exporter tout (CSV)',
    body: "L'ensemble de vos dossiers et de leurs indicateurs dans un fichier, pour votre tableur ou votre reporting interne.",
    example: null },
  { sel: '[data-tour="nav-demo"]', title: '15. Mode démo',
    body: "Rejouez une nuit complète de travail de l'agent, avec les captures réelles de chaque étape — parfait pour montrer FidClic sans toucher aux données d'un client.",
    example: null },
  { sel: '[data-tour="nav-tour"]', title: '16. Cette visite, quand vous voulez',
    body: "Ce bouton relance la visite guidée à tout moment. Vous pouvez aussi la quitter avec Échap et la reprendre plus tard.",
    example: null },
];

/**
 * CabinetDashboard — the expert-comptable control tower.
 * One login → every linked client's compliance health (Bouclier), red-first,
 * with per-client drill-down, a combined alert feed, and a single CSV export.
 */

const BAND = {
  red: { c: '#C0392B', bg: 'rgba(192,57,43,.12)', dot: '#C0392B', label: 'Action requise' },
  amber: { c: '#B8860B', bg: 'rgba(224,169,43,.14)', dot: '#E0A92B', label: 'À vérifier' },
  green: { c: '#2F7A52', bg: 'rgba(63,156,107,.12)', dot: '#3F9C6B', label: 'Conforme' },
};

export default function CabinetDashboard() {
  const navigate = useNavigate();
  const { logout } = useAuth();
  const [data, setData] = useState(null);
  const [alerts, setAlerts] = useState([]);
  const [drill, setDrill] = useState(null); // {summary, invoices}
  const [loading, setLoading] = useState(true);
  const [reviewing, setReviewing] = useState(null);   // invoice id being validated
  const [acting, setActing] = useState(null);         // action running for a client
  const [toast, setToast] = useState(null);
  const [crediting, setCrediting] = useState(null);
  const [openCases, setOpenCases] = useState(0);
  const [grilleFor, setGrilleFor] = useState(null);  // {tenant_id, name}
  const [teamMembers, setTeamMembers] = useState([]);
  const [showNewClient, setShowNewClient] = useState(false);
  const [invoiceFor, setInvoiceFor] = useState(null);   // tenant_id being invoiced
  const [docReqs, setDocReqs] = useState(null);         // {requests, reliability} for the drill
  const [subs, setSubs] = useState(null);               // subscriptions for the drill
  const [showNewSub, setShowNewSub] = useState(null);   // tenant_id
  const [runningAgent, setRunningAgent] = useState(false);
  const [reviewCount, setReviewCount] = useState(0);
  const [canOnboard, setCanOnboard] = useState(false);
  const [me, setMe] = useState(null);                 // my membership (role, name)
  const [askDocFor, setAskDocFor] = useState(null);   // {tenant_id, name} → AskPieceModal
  const [showTour, setShowTour] = useState(false);
  const [showDemo, setShowDemo] = useState(false);
  const [filter, setFilter] = useState('all');       // stat tiles filter the list
  const [sidebarOpen, toggleSidebar] = useSidebar();
  // Which sidebar entry is lit. On this route only "Accueil" and "Mes dossiers"
  // are reachable (the others navigate away), so it is local state, not a route.
  const [navSel, setNavSel] = useState('home');

  // The sidebar lives on every cabinet page, but the demo, the tour and the
  // "new client" form only exist here — so from another page those entries
  // navigate back with a flag, which we consume once and strip from the URL.
  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    if (!q.has('demo') && !q.has('tour') && !q.has('new')) return;
    if (q.has('demo')) setShowDemo(true);
    if (q.has('tour')) setShowTour(true);
    if (q.has('new')) setShowNewClient(true);
    window.history.replaceState({}, '', '/cabinet');
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    const [c, a] = await Promise.all([
      comptableAPI.clients().catch(() => null),
      comptableAPI.alerts().catch(() => null),
    ]);
    setData(c?.data || { clients: [], totals: {} });
    setAlerts(a?.data?.alerts || []);
    // Open-case badge lives in the header so the queue is never out of sight.
    casesAPI.list({ status: 'open' })
      .then((r) => setOpenCases(r?.data?.counts?.open ?? 0))
      .catch(() => {});
    cabinetOsAPI.team()
      .then((r) => setTeamMembers(r?.data?.members || []))
      .catch(() => {});
    comptableAPI.reviewQueue()
      .then((r) => setReviewCount(r?.data?.count ?? 0))
      .catch(() => {});
    cabinetOsAPI.me()
      .then((r) => { setCanOnboard(!!r?.data?.can?.assign); setMe(r?.data || null); })
      .catch(() => {});
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  // First visit → run the guided tour once the data (and therefore the anchors)
  // are on screen. Never auto-runs again; the "? Visite guidée" button replays it.
  useEffect(() => {
    if (loading || !data) return;
    if (tourSeen('cabinet-home')) return;
    const t = setTimeout(() => setShowTour(true), 900);
    return () => clearTimeout(t);
  }, [loading, data]);

  const openClient = async (tid) => {
    const r = await comptableAPI.client(tid).catch(() => null);
    if (r?.data) setDrill(r.data);
    cabinetOsAPI.docRequests(tid)
      .then((x) => setDocReqs(x?.data || null))
      .catch(() => setDocReqs(null));
    cabinetOsAPI.subscriptions(tid)
      .then((x) => setSubs(x?.data?.subscriptions || []))
      .catch(() => setSubs(null));
  };

  /**
   * S1 — the accountant validates a document. This ONLY touches review_status
   * (and, through it, export readiness); the PA lifecycle and payment state are
   * left untouched, which is why a refused invoice can still be validated.
   */
  const validateInvoice = async (invoiceId, target) => {
    setReviewing(invoiceId);
    try {
      await facturationAPI.setReview(invoiceId, { target });
      if (drill?.summary?.tenant_id) await openClient(drill.summary.tenant_id);
      await load();       // portfolio counters refresh (workload view)
    } catch (e) {
      // 409 = illegal transition (e.g. two-step review required)
      alert(e?.response?.data?.detail || 'Action impossible');
    } finally {
      setReviewing(null);
    }
  };

  /**
   * Issue a credit note for a rejected invoice — the action that actually
   * clears the Tax Shield alert. Validating only records that the accountant
   * reviewed it; only an avoir corrects it, as French law requires.
   */
  const createCreditNote = async (invoiceId, number) => {
    setCrediting(invoiceId);
    try {
      const r = await facturationAPI.creditNote(invoiceId, { reason: 'Correction' });
      setToast({ ok: true,
                 msg: `Avoir ${r.data?.credit_note?.number || ''} créé pour ${number}. L'alerte du Bouclier disparaît.` });
      if (drill?.summary?.tenant_id) await openClient(drill.summary.tenant_id);
      await load();
    } catch (e) {
      setToast({ ok: false, msg: e?.response?.data?.detail || "Création de l'avoir impossible." });
    } finally {
      setCrediting(null);
      setTimeout(() => setToast(null), 6000);
    }
  };

  /**
   * Perform a facturation action ON BEHALF OF a client dossier.
   * The server re-verifies the mandate and stamps the audit entry with
   * "on_behalf_of", so the history never reads as if the owner did it.
   */
  const actForClient = async (action, tenantId) => {
    setActing(action);
    try {
      if (action === 'ereporting') {
        const now = new Date();
        const from = new Date(now.getFullYear(), now.getMonth(), 1).toISOString().slice(0, 10);
        const to = new Date(now.getFullYear(), now.getMonth() + 1, 0).toISOString().slice(0, 10);
        const r = await cabinetExtraAPI.ereportingFor(tenantId, {
          period_start: from, period_end: to, totals_by_vat: {},
        });
        setToast({ ok: true, msg: `E-reporting transmis — état : ${r.data?.ereport?.state || 'queued'}` });
      } else if (action === 'activate') {
        await cabinetExtraAPI.activateFor(tenantId, {
          start_date: '2026-09-01', type_operation: 'services',
        });
        setToast({ ok: true, msg: 'Conformité DGFiP activée pour ce dossier.' });
      } else if (action === 'received') {
        await cabinetExtraAPI.seedReceivedFor(tenantId, {
          supplier_name: 'Fournisseur Test SARL', total_ht: 900,
        });
        setToast({ ok: true, msg: 'Facture fournisseur simulée pour ce dossier.' });
      }
      await openClient(tenantId);
      await load();
    } catch (e) {
      setToast({ ok: false, msg: e?.response?.data?.detail || 'Action impossible.' });
    } finally {
      setActing(null);
      setTimeout(() => setToast(null), 6000);
    }
  };

  const totals = data?.totals || {};
  const shownClients = (data?.clients || []).filter(FILTERS[filter].match);
  const shownAlerts = filter === 'all'
    ? alerts
    : alerts.filter((a) => shownClients.some((c) => c.tenant_id === a.tenant_id));
  const applyFilter = (f) => {
    setFilter(f);
    setTimeout(() => document.querySelector('[data-tour="dossiers"]')
      ?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 60);
  };

  return (
    <div data-currency="eur" className="mc-dark min-h-screen relative" style={{ color: MC.ink }}>
      <AmbientCanvas />
      <div className="relative">
      <div className="flex">
      <Sidebar
        open={sidebarOpen} onToggle={toggleSidebar} active={navSel} canOnboard={canOnboard}
        counts={{ dossiers: totals.count ?? 0, review: reviewCount, cases: openCases }}
        onHome={() => { setNavSel('home'); setFilter('all'); window.scrollTo({ top: 0, behavior: 'smooth' }); }}
        onDossiers={() => { setNavSel('dossiers'); setFilter('all');
          document.querySelector('[data-tour="dossiers"]')?.scrollIntoView({ behavior: 'smooth', block: 'start' }); }}
        onReview={() => navigate('/cabinet/revue')}
        onCases={() => navigate('/cabinet/cas')}
        onTeam={() => navigate('/cabinet/equipe')}
        onNewClient={() => setShowNewClient(true)}
        exportUrl={comptableAPI.exportUrl}
        relancesBusy={runningAgent}
        onRelances={async () => {
          setRunningAgent(true);
          try {
            const r = await cabinetOsAPI.runCollection();
            setToast({ ok: true, msg: `Agent : ${r.data.emails_sent} email(s) envoyé(s), ${r.data.cases_opened} cas escaladé(s), ${r.data.waiting_not_due} en attente (pas encore l'heure de relancer).` });
          } catch (e) {
            setToast({ ok: false, msg: e?.response?.data?.detail || 'Relances impossibles.' });
          } finally { setRunningAgent(false); setTimeout(() => setToast(null), 9000); }
        }}
        onImportClients={async (e) => {
          const f = e.target.files && e.target.files[0]; e.target.value = ''; if (!f) return;
          try {
            const text = await f.text();
            const r = await cabinetOsAPI.importClients(text);
            setToast({ ok: true, msg: `${r.data.created} client(s) importé(s)` + (r.data.skipped ? `, ${r.data.skipped} ignoré(s).` : '.') });
            await load();
          } catch (err) {
            setToast({ ok: false, msg: err?.response?.data?.detail || 'Import impossible.' });
          }
          setTimeout(() => setToast(null), 8000);
        }}
        onDemo={() => setShowDemo(true)}
        onTour={() => { resetTour('cabinet-home'); setShowTour(true); }}
        onLogout={() => { logout(); navigate('/login'); }} />

      <div className="flex-1 min-w-0">

      <main className="max-w-4xl mx-auto px-4 pb-16 pt-5">
        {toast && (
          <div className="mb-4 rounded-2xl px-4 py-3 text-sm"
               style={toast.ok
                 ? { background: 'rgba(61,220,151,.12)', border: '1px solid rgba(61,220,151,.35)', color: MC.green }
                 : { background: 'rgba(255,107,107,.10)', border: '1px solid rgba(255,107,107,.35)', color: MC.red }}>
            <LiveText>{(toast.ok ? '✓ ' : '⚠ ') + toast.msg}</LiveText>
          </div>
        )}

        {/* totals */}
        {/* Ma journée — role-aware greeting. KEYED by its dynamic content so a
            change REMOUNTS the subtree — the page translator replaces text
            nodes in place, and React's insertBefore crashes if we patch them
            (same bug LiveText fixes; here the whole card is the unit). */}
        <Rise>
          <div key={`hero-${me?.membership?.full_name || me?.full_name || ''}-${me?.membership?.role || me?.role || ''}-${reviewCount}`}
               data-tour="hero" className="p-5 mb-4 flex items-center gap-4 flex-wrap"
               style={glass('accent')}>
            <div className="w-12 h-12 rounded-2xl flex items-center justify-center font-bold shrink-0"
                 style={{ background: `linear-gradient(135deg, ${MC.indigo}, ${MC.plum})`, color: '#fff', fontSize: 18,
                          boxShadow: '0 12px 28px -14px rgba(124,124,248,.9)' }}>
              <LiveText>{String(me?.membership?.full_name || me?.full_name || 'C').charAt(0).toUpperCase()}</LiveText>
            </div>
            <div className="flex-1 min-w-[200px]">
              <LiveText as="div" style={{ fontWeight: 700, fontSize: 19, letterSpacing: '-.02em', color: MC.ink }}>
                {`Bonjour ${me?.membership?.full_name || me?.full_name || ''}`}
              </LiveText>
              <LiveText as="div" style={{ fontSize: 12, color: MC.ink3, marginTop: 2 }}>
                {`${{ expert_comptable: 'Expert-comptable', superviseur: 'Superviseur',
                      collaborateur: 'Collaborateur', assistant: 'Assistant' }[
                      me?.membership?.role || me?.role] || 'Cabinet'} · ${
                   new Date().toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long' })}`}
              </LiveText>
            </div>
            {(me?.membership?.role || me?.role) === 'assistant' ? (
              <LiveText as="span" style={{ fontSize: 12.5, color: MC.ink2, maxWidth: 260 }}>
                📷 Ouvrez un dossier et photographiez les factures — l'agent fait le reste.
              </LiveText>
            ) : reviewCount > 0 ? (
              <McButton variant="danger" onClick={() => navigate('/cabinet/revue')}>
                <LiveText>{`${reviewCount} facture(s) attendent votre validation →`}</LiveText>
              </McButton>
            ) : (
              <LiveText as="span" style={{ fontSize: 12.5, fontWeight: 600, color: MC.green }}>
                ✓ Rien n'attend votre validation
              </LiveText>
            )}
          </div>
        </Rise>

        {/* Ce que l'agent a fait cette nuit — the invisible work, made visible */}
        <Rise delay={60}>
          <button onClick={() => setShowDemo(true)} data-tour="nightstrip"
                  className="w-full text-left p-4 mb-4 flex items-center gap-3 flex-wrap transition-transform duration-200"
                  style={{ ...glass(), cursor: 'pointer' }}
                  onMouseEnter={(e) => (e.currentTarget.style.transform = 'translateY(-2px)')}
                  onMouseLeave={(e) => (e.currentTarget.style.transform = 'none')}>
            <LiveDot />
            <span style={{ fontSize: 13, color: MC.ink, fontWeight: 600 }}>
              L'agent a travaillé cette nuit
            </span>
            <span style={{ fontSize: 12, color: MC.ink3 }}>
              relances, lecture des pièces, écritures, contrôles — voir le déroulé
            </span>
            <span style={{ marginLeft: 'auto', fontSize: 12, color: MC.indigo, fontWeight: 700 }}>▶ Rejouer la nuit</span>
          </button>
        </Rise>

        {/* Clicking a tile FILTERS the dossier list below — the number and the
            list are the same fact, so they must be the same control. */}
        <div data-tour="stats" className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
          <StatTile label={filter === 'all' ? 'Dossiers suivis' : 'Tous les dossiers'}
                    value={totals.count ?? 0} delay={80}
                    active={filter === 'all'} onClick={() => applyFilter('all')} />
          <StatTile label="Action requise" value={totals.red ?? 0} tone="danger" delay={140}
                    active={filter === 'red'} onClick={() => applyFilter('red')} />
          <StatTile label="À vérifier" value={totals.amber ?? 0} tone="warn" delay={200}
                    active={filter === 'amber'} onClick={() => applyFilter('amber')} />
          <StatTile label="Conformes" value={totals.green ?? 0} tone="ok" delay={260}
                    active={filter === 'green'} onClick={() => applyFilter('green')} />
        </div>
        {filter !== 'all' && (
          <div className="mb-4 flex items-center gap-2">
            <span key={`f-${filter}-${shownClients.length}`}
                  style={{ fontSize: 12, color: MC.ink2 }}>
              {`Filtre : ${FILTERS[filter].label} — ${shownClients.length} dossier(s)`}
            </span>
            <button onClick={() => applyFilter('all')}
                    style={{ fontSize: 11.5, fontWeight: 700, color: MC.indigo, cursor: 'pointer',
                             background: 'rgba(124,124,248,.14)', border: '1px solid rgba(124,124,248,.35)',
                             borderRadius: 999, padding: '3px 10px' }}>
              ✕ Tout afficher
            </button>
          </div>
        )}

        {/* alerts feed */}
        {shownAlerts.length > 0 && (
          <Panel title="À traiter en priorité" delay={320} className="mb-5" tone="warn"
                 right={<button onClick={load} style={{ color: MC.ink3 }} aria-label="Rafraîchir"><RefreshCw size={15} /></button>}>
            <div data-tour="priority">
            <ul className="space-y-2">
              {shownAlerts.slice(0, 8).map((a, i) => (
                <li key={i} className="flex items-center gap-2 text-[13px]">
                  <AlertTriangle size={13} style={{ color: statusColor[a.level] || MC.amber }} className="shrink-0" />
                  <button onClick={() => openClient(a.tenant_id)}
                          style={{ fontWeight: 600, color: MC.ink, cursor: 'pointer' }}>{a.client}</button>
                  <LiveText style={{ color: MC.ink3 }}>{'— ' + a.message}</LiveText>
                </li>
              ))}
            </ul>
            </div>
          </Panel>
        )}

        {/* client list */}
        <Panel delay={380}
               title={filter === 'all' ? `Mes dossiers (${totals.count ?? 0})`
                                       : `${FILTERS[filter].label} (${shownClients.length})`}>
          <div data-tour="dossiers">
          {loading ? (
            <div className="py-10 text-center text-sm" style={{ color: MC.ink3 }}>Chargement…</div>
          ) : shownClients.length === 0 ? (
            <div className="py-10 text-center text-sm" style={{ color: MC.ink3 }}>
              {filter === 'all'
                ? 'Aucun dossier lié. Importez votre liste de clients, ou ajoutez-en un.'
                : 'Aucun dossier dans cette catégorie.'}
            </div>
          ) : (
            <div className="space-y-2">
              {shownClients.map((c, idx) => {
                const dot = statusColor[c.band] || MC.amber;
                return (
                  <button key={c.tenant_id} onClick={() => openClient(c.tenant_id)}
                          className="w-full px-3.5 py-3 flex items-center gap-3 text-sm text-left transition-transform duration-200"
                          style={{ background: 'rgba(255,255,255,.04)', border: `1px solid ${MC.stroke}`,
                                   borderRadius: 14, cursor: 'pointer',
                                   animation: `mcRise .45s ${EASE} both`, animationDelay: `${420 + idx * 45}ms` }}
                          onMouseEnter={(e) => { e.currentTarget.style.transform = 'translateX(3px)';
                                                 e.currentTarget.style.background = 'rgba(255,255,255,.075)'; }}
                          onMouseLeave={(e) => { e.currentTarget.style.transform = 'none';
                                                 e.currentTarget.style.background = 'rgba(255,255,255,.04)'; }}>
                    <span className="w-2 h-2 rounded-full shrink-0"
                          style={{ background: dot, boxShadow: `0 0 8px ${dot}` }} />
                    <span key={c.name} className="flex-1 truncate"
                          style={{ fontWeight: 600, color: MC.ink }}>{c.name}</span>
                    <McPill tone={c.band === 'green' ? 'ok' : c.band === 'red' ? 'danger' : 'warn'}>
                      {`${c.score}/100`}
                    </McPill>
                    {c.unreviewed > 0 && <McPill tone="warn">{`${c.unreviewed} à revoir`}</McPill>}
                    <span key={`io-${c.issued}-${c.received}`}
                          className="hidden md:block text-right"
                          style={{ color: MC.ink3, fontSize: 11.5, width: 110 }}>
                      {`${c.issued} émises · ${c.received} reçues`}
                    </span>
                    <ChevronRight size={16} style={{ color: MC.ink3 }} />
                  </button>
                );
              })}
            </div>
          )}
          </div>
        </Panel>

        <p className="mt-4 text-center italic" style={{ fontSize: 11, color: MC.ink3 }}>
          Indicateur informatif de cohérence — ni conseil fiscal, ni ECF.
        </p>
      </main>

      {drill && (
        <DrillModal data={drill} onClose={() => setDrill(null)}
                    onToast={(ok, msg) => { setToast({ ok, msg }); setTimeout(() => setToast(null), 7000); }}
                    onOcr={async (tid, file, vente) => {
                      try {
                        const dataUrl = await new Promise((res, rej) => {
                          const fr = new FileReader();
                          fr.onload = () => res(fr.result); fr.onerror = rej;
                          fr.readAsDataURL(file);
                        });
                        const r = vente
                          ? await cabinetOsAPI.ocrVente(tid, dataUrl)
                          : await cabinetOsAPI.ocrIngest(tid, { image: dataUrl });
                        const c = Math.round((r.data.confidence || 0) * 100);
                        setToast({ ok: true, msg: r.data.needs_review
                          ? `Lu (confiance ${c} %) — à vérifier.`
                          : `Lu (confiance ${c} %) — rangé ✓` });
                        await openClient(tid);
                      } catch (e) {
                        setToast({ ok: false, msg: e?.response?.data?.detail || 'Lecture impossible (OCR non configuré ?).' });
                      }
                      setTimeout(() => setToast(null), 7000);
                    }}
                    onSyncRec={async (tid) => {
                      try {
                        const r = await cabinetOsAPI.syncReceived(tid);
                        setToast({ ok: true, msg: `${r.data.synced} facture(s) fournisseur récupérée(s) (PA : ${r.data.pa_provider}).` });
                        await openClient(tid);
                      } catch (e) {
                        setToast({ ok: false, msg: e?.response?.data?.detail || 'Synchronisation impossible.' });
                      }
                      setTimeout(() => setToast(null), 7000);
                    }}
                    onReview={validateInvoice} reviewing={reviewing}
                    onActFor={actForClient} acting={acting}
                    onCreditNote={createCreditNote} crediting={crediting}
                    onOpenGrille={(tid, name) => setGrilleFor({ tenant_id: tid, name })}
                    onExportFec={async (tid, name) => {
                      try {
                        const resp = await comptableAPI.fec(tid);
                        const blob = new Blob([resp.data], { type: 'text/plain' });
                        const url = URL.createObjectURL(blob);
                        const a = document.createElement('a');
                        a.href = url; a.download = (name || 'dossier') + '-FEC.txt';
                        document.body.appendChild(a); a.click(); a.remove();
                        URL.revokeObjectURL(url);
                        setToast({ ok: true, msg: 'FEC généré — importable dans Sage/Cegid.' });
                      } catch (e) {
                        setToast({ ok: false, msg: e?.response?.data?.detail || 'Export FEC impossible.' });
                      }
                      setTimeout(() => setToast(null), 6000);
                    }}
                    onNewInvoice={(tid) => setInvoiceFor(tid)}
                    docReqs={docReqs}
                    subs={subs}
                    onNewSub={(tid) => setShowNewSub(tid)}
                    onToggleSub={async (tid, id, active) => {
                      try {
                        await cabinetOsAPI.toggleSubscription(id, active);
                        setToast({ ok: true, msg: active ? 'Abonnement réactivé.' : 'Abonnement mis en pause.' });
                        await openClient(tid);
                      } catch (e) {
                        setToast({ ok: false, msg: e?.response?.data?.detail || 'Action impossible.' });
                      }
                      setTimeout(() => setToast(null), 6000);
                    }}
                    onRunBilling={async (tid) => {
                      try {
                        const r = await cabinetOsAPI.runBilling();
                        setToast({ ok: true,
                                   msg: `Agent : ${r.data.invoices_drafted} brouillon(s) préparé(s), ${r.data.skipped} pas encore dus.` });
                        await openClient(tid); await load();
                      } catch (e) {
                        setToast({ ok: false, msg: e?.response?.data?.detail || 'Exécution impossible.' });
                      }
                      setTimeout(() => setToast(null), 8000);
                    }}
                    onAskDoc={(tid) => setAskDocFor({ tenant_id: tid,
                                                      name: drill?.summary?.name })}
                    onDocReceived={async (tid, id) => {
                      try {
                        const r = await cabinetOsAPI.markDocReceived(id);
                        setToast({ ok: true, msg: r.data.on_time ? 'Pièce reçue — dans les temps ✓ (score du client ↑)' : 'Pièce reçue (en retard — le score du client s\'en souviendra).' });
                        await openClient(tid);
                      } catch (e) {
                        setToast({ ok: false, msg: e?.response?.data?.detail || 'Action impossible.' });
                      }
                      setTimeout(() => setToast(null), 7000);
                    }}
                    />
      )}
      {invoiceFor && (
        <CreateInvoiceModal
          tenantId={invoiceFor}
          seller={{ vat_regime: 'reel_normal' }}
          onClose={() => setInvoiceFor(null)}
          onCreated={async () => {
            setInvoiceFor(null);
            setToast({ ok: true, msg: 'Facture créée et transmise pour ce dossier.' });
            setTimeout(() => setToast(null), 6000);
            if (drill?.summary?.tenant_id) await openClient(drill.summary.tenant_id);
            await load();
          }} />
      )}
      {showNewSub && (
        <NewSubscriptionModal tenantId={showNewSub}
          onClose={() => setShowNewSub(null)}
          onCreated={async () => {
            setShowNewSub(null);
            setToast({ ok: true, msg: "Abonnement enregistré — l'agent facturera chaque mois au jour choisi, en brouillon à valider." });
            setTimeout(() => setToast(null), 8000);
            if (drill?.summary?.tenant_id) await openClient(drill.summary.tenant_id);
          }} />
      )}
      {showNewClient && (
        <NewClientModal members={teamMembers}
                        onClose={() => setShowNewClient(false)}
                        onCreated={async (res) => {
                          setShowNewClient(false);
                          setToast({ ok: true,
                                     msg: res.client_account
                                       ? `Dossier créé. Accès client : ${res.client_account.email} / ${res.client_account.temp_password} — transmettez-le, il ne sera plus affiché.`
                                       : 'Dossier client créé et mandat activé.' });
                          setTimeout(() => setToast(null), 12000);
                          await load();
                        }} />
      )}
      {grilleFor && (
        <GrilleModal tenantId={grilleFor.tenant_id} clientName={grilleFor.name}
                     members={teamMembers} onClose={() => setGrilleFor(null)} />
      )}
      {showTour && (
        <CoachMarks steps={HOME_TOUR} storageKey="cabinet-home"
                    onClose={() => setShowTour(false)} />
      )}
      {showDemo && <DemoMode onClose={() => setShowDemo(false)} />}
      {askDocFor && (
        <AskPieceModal clientName={askDocFor.name}
                       onClose={() => setAskDocFor(null)}
                       onSubmit={async (body) => {
                         try {
                           await cabinetOsAPI.createDocRequest(askDocFor.tenant_id, body);
                           setToast({ ok: true, msg: `Demande enregistrée : « ${body.label} ». L'agent relancera au bon moment.` });
                           await openClient(askDocFor.tenant_id);
                         } catch (e) {
                           setToast({ ok: false, msg: e?.response?.data?.detail || 'Demande impossible.' });
                           throw e;
                         } finally {
                           setTimeout(() => setToast(null), 7000);
                         }
                       }} />
      )}
      </div>{/* flex-1 main column */}
      </div>{/* flex row with sidebar */}
      </div>{/* relative */}
    </div>
  );
}

function Pill({ state }) {
  const map = {
    draft: ['Brouillon', '#8B8680', 'rgba(139,134,128,.12)'],
    sent: ['Envoyée', '#2F6FB3', 'rgba(47,111,179,.12)'],
    accepted: ['Acceptée', '#2F7A52', 'rgba(63,156,107,.12)'],
    refused: ['Refusée', '#C0392B', 'rgba(192,57,43,.12)'],
    error: ['Erreur', '#C0392B', 'rgba(192,57,43,.12)'],
    paid: ['Payée', '#2F7A52', 'rgba(63,156,107,.14)'],
    credited: ['Avoirée', '#2F7A52', 'rgba(63,156,107,.12)'],
  };
  const [label, c, bg] = map[state] || [state || '—', '#8B8680', 'rgba(139,134,128,.12)'];
  return (
    <LiveText className="text-[11px] font-semibold px-2 py-0.5 rounded-full shrink-0"
              style={{ color: c, background: bg }}>{label}</LiveText>
  );
}

/** S1 — review + payment states, shown next to (not instead of) the PA state. */
const REVIEW_MAP = {
  unreviewed: ['Non revue', '#8B8680'],
  pending_validation: ['À valider', '#B8860B'],
  correction_required: ['À corriger', '#C0392B'],
  validated: ['Validée', '#2F7A52'],
};
const PAY_MAP = {
  unpaid: ['Impayée', '#8B8680'], partially_paid: ['Partielle', '#B8860B'],
  paid: ['Payée', '#2F7A52'], overdue: ['En retard', '#C0392B'],
  disputed: ['En litige', '#C0392B'],
};

function MiniChip({ value, map }) {
  const [label, c] = map[value] || [value || '—', '#8B8680'];
  return (
    <LiveText className="text-[10px] font-semibold px-1.5 py-0.5 rounded shrink-0"
              style={{ color: c, background: c + '1A' }}>{label}</LiveText>
  );
}

function Chan({ channel }) {
  const b2b = channel === 'e-invoicing';
  return (
    <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded shrink-0"
      style={b2b ? { color: '#2F6FB3', background: 'rgba(47,111,179,.10)' }
                 : { color: '#7A3E70', background: 'rgba(122,62,112,.10)' }}>
      {b2b ? 'e-invoicing' : 'e-reporting'}
    </span>
  );
}

function Stat({ label, value, tone = '#1C1917' }) {
  return (
    <div className="rounded-2xl bg-white border p-4 text-center" style={{ borderColor: '#ECE3D2' }}>
      <div className="text-2xl font-extrabold" style={{ color: tone }}>{value}</div>
      <div className="text-[11px] text-[#8B8680] mt-0.5">{label}</div>
    </div>
  );
}

function DrillModal({ data, onClose, onReview, reviewing, onActFor, acting,
                     onCreditNote, crediting, onOpenGrille, onExportFec, onNewInvoice,
                     docReqs, onAskDoc, onDocReceived, onToast, onOcr, onSyncRec,
                     subs, onNewSub, onToggleSub, onRunBilling }) {
  const s = data.summary || {};
  const b = BAND[s.band] || BAND.amber;
  // Hub navigation: the dossier opens on CARDS, one per "room". Clicking a card
  // shows ONLY that room, with a back button to the hub. No stacking.
  //
  // There used to be a fifth "Plus" tab that re-listed Indicateurs, Pièces and
  // Abonnements — the exact three cards already on this hub. A second door into
  // the same room is not extra navigation, it is a reason to hesitate. Plus is
  // gone; Export FEC and Répartition des tâches (its only unique entries) moved
  // onto the hub, which had the room for them.
  const [room, setRoom] = useState(null);
  const [agentN, setAgentN] = useState(0);
  const ROOM_TITLES = { agent: "L'agent a préparé", ventes: 'Ventes',
                        pieces: 'Pièces attendues', abos: 'Abonnements',
                        achats: 'Achats', indicateurs: 'Indicateurs' };
  // Ventes: unpaid first — "à encaisser d'abord" (MyFiteco: impayés en un clin d'œil)
  const sortedInv = [...(data.invoices || [])].sort((a, b) =>
    ((a.payment_status === 'paid') - (b.payment_status === 'paid'))
    || ((a.review_status === 'validated') - (b.review_status === 'validated')));
  const unpaid = (data.invoices || []).filter(
    (i) => i.review_status === 'validated' && i.payment_status !== 'paid');
  const unpaidTot = unpaid.reduce((a, i) => a + (i.total_ttc || 0), 0);
  return (
    <div className="mc-dark fixed inset-0 z-50 overflow-auto" style={{ background: MC.bg, color: MC.ink }}>
      <DossierSkin />
      <AmbientCanvas />
      <div className="min-h-full flex flex-col relative">
        {/* Top bar: home → CLIENT NAME, score chip right */}
        <div className="sticky top-0 z-10 mc-surface px-4 py-3 flex items-center gap-3"
             style={{ borderBottom: `1px solid ${MC.stroke}` }}>
          <button onClick={onClose} aria-label="Retour à la liste"
                  className="w-10 h-10 rounded-xl flex items-center justify-center text-white text-lg shrink-0 cursor-pointer"
                  style={{ background: `linear-gradient(135deg, ${MC.indigo}, #5B5BE8)`,
                           boxShadow: '0 8px 22px -10px rgba(124,124,248,.9)' }}>
            <ArrowLeft size={18} />
          </button>
          <span style={{ color: MC.ink3 }}>›</span>
          <span className="font-extrabold tracking-wide uppercase truncate"
                style={{ color: MC.ink }}>{s.name}</span>
          <span className="ml-auto text-[11px] font-bold px-2.5 py-1 rounded-full shrink-0"
                style={{ color: b.c, background: 'rgba(255,255,255,.07)',
                         border: `1px solid ${MC.stroke}` }}>
            <LiveText>{`${s.score}/100`}</LiveText>
          </span>
        </div>

        <div className="w-full max-w-2xl mx-auto px-4 pb-6 pt-5 flex-1">
        <h2 className="text-2xl font-extrabold text-[#F8FAFC] mb-4">
          <LiveText>{ROOM_TITLES[room] || 'Synthèse'}</LiveText>
        </h2>
        {['pieces', 'abos', 'indicateurs'].includes(room) && (
          <button onClick={() => setRoom(null)}
                  className="mb-3 text-xs font-semibold px-3 py-1.5 rounded-xl cursor-pointer"
                  style={{ border: `1px solid ${MC.stroke}`, background: 'rgba(255,255,255,.06)',
                           color: MC.ink2 }}>
            ← Synthèse
          </button>
        )}
        {room === null && (
          <div className="flex flex-col gap-3">
            {(s.alerts || []).length > 0 && (
              <ul className="space-y-1 mb-1">
                {s.alerts.slice(0, 3).map((a, i) => (
                  <li key={i} className="flex items-center gap-2 text-xs">
                    <AlertTriangle size={13} style={{ color: BAND[a.level]?.c }} />
                    <LiveText className="text-[#B9C2D6]">{a.message}</LiveText>
                  </li>
                ))}
              </ul>
            )}
            <HubCard icon="🤖" title="L'agent a préparé" desc="écritures, rapprochements, conseils — à valider"
                     badge={agentN} accent onClick={() => setRoom('agent')} />
            <HubCard icon="📤" title="Ventes" desc="créer, envoyer, suivre les paiements"
                     count={(data.invoices || []).length}
                     badge={(data.invoices || []).filter((i) => i.review_status !== 'validated').length}
                     onClick={() => setRoom('ventes')} />
            <HubCard icon="🛒" title="Achats" desc="factures reçues + tickets photographiés"
                     count={(data.received || []).length} onClick={() => setRoom('achats')} />
            <HubCard icon="📨" title="Pièces attendues" desc="l'agent relance le client tout seul"
                     badge={(docReqs?.requests || []).filter((r) => r.status === 'pending').length}
                     onClick={() => setRoom('pieces')} />
            <HubCard icon="📊" title="Indicateurs" desc="bouclier fiscal, reconstitution, impayés"
                     badge={(s.alerts || []).length} onClick={() => setRoom('indicateurs')} />
            <HubCard icon="🔁" title="Abonnements" desc="« chaque mois, le X, facturer Y à Z »"
                     count={(subs || []).length} onClick={() => setRoom('abos')} />
            {onOpenGrille && (
              <HubCard icon="👥" title="Répartition des tâches" desc="qui fait quoi sur ce dossier"
                       onClick={() => onOpenGrille(s.tenant_id, s.name)} />
            )}
            {onExportFec && (
              <HubCard icon="🧾" title="Export FEC" desc="le fichier que Sage / Cegid importent"
                       onClick={() => onExportFec(s.tenant_id, s.name)} />
            )}
          </div>
        )}

        <div className={room ? 'overflow-hidden' : ''}
             style={room ? { ...glass(), borderRadius: 20 } : undefined}>
        {/* S12 — pièces manquantes: what the agent is chasing for this client */}
        {room === 'pieces' && docReqs && (
          <div className="px-5 pt-4 pb-4 border-b" style={{ borderColor: 'rgba(255,255,255,.10)' }}>
            <GuideBox
              title="Pièces manquantes — comment ça marche ?"
              steps={[
                '« + Demander une pièce » : dites ce qui manque (ex. relevé bancaire juillet) + l\'email (et WhatsApp si vous voulez) du client.',
                'L\'agent relance TOUT SEUL au bon moment — doux avec les clients fiables, insistant avec les retardataires.',
                'Quand la pièce arrive, cliquez « Reçu ✓ » — le score de fiabilité du client s\'ajuste.',
                'Après 3 relances sans réponse, un Cas s\'ouvre pour qu\'un humain prenne le relais.',
              ]}
              example="« Relevé bancaire juillet » demandé le 1er → l'agent relance le 5, le 9… → reçu le 10 → vous cliquez Reçu ✓. Zéro email écrit à la main." />
            <div className="flex items-center justify-between mb-2">
              <div className="text-sm font-bold text-[#F8FAFC]">
                Pièces manquantes
                <span className="ml-2 text-[10px] font-semibold px-2 py-0.5 rounded-full"
                      style={{ color: docReqs.reliability >= 80 ? '#3DDC97' : docReqs.reliability >= 50 ? '#F5B851' : '#FF6B6B',
                               background: 'rgba(139,134,128,.10)' }}>
                  Fiabilité client : {docReqs.reliability}/100
                </span>
              </div>
              <button onClick={() => onAskDoc(s.tenant_id)}
                      className="text-xs font-semibold px-2.5 py-1.5 rounded-lg border"
                      style={{ borderColor: 'rgba(255,255,255,.18)', color: '#C77DFF' }}>
                + Demander une pièce
              </button>
            </div>
            {(docReqs.requests || []).length === 0 ? (
              <div className="text-xs text-[#7C879F]">Rien en attente.</div>
            ) : (
              <div className="space-y-1.5">
                {docReqs.requests.map((rq) => (
                  <div key={rq.id} className="flex items-center gap-2 text-xs flex-wrap">
                    <span className="w-2 h-2 rounded-full shrink-0"
                          style={{ background: rq.status === 'received' ? '#3DDC97'
                                   : rq.status === 'escalated' ? '#FF6B6B' : '#F5B851' }} />
                    <span className="font-semibold text-[#F8FAFC]">{rq.label}</span>
                    <span className="text-[#7C879F]">pour le {rq.due_date}</span>
                    {(rq.reminders || []).length > 0 && rq.status === 'pending' && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded-full inline-flex items-center gap-1"
                            style={{ color: '#B9C2D6', background: 'rgba(87,83,78,.08)' }}>
                        🤖 {rq.reminders.length} relance(s)
                        {(rq.reminders || []).some((rm) => rm.channel === 'whatsapp') && (
                          <WhatsAppIcon size={12} title="Relance envoyée par WhatsApp" />
                        )}
                      </span>
                    )}
                    {rq.status === 'escalated' && (
                      <span className="text-[10px] font-semibold" style={{ color: '#FF6B6B' }}>
                        escaladé — voir Cas
                      </span>
                    )}
                    {rq.status === 'pending' && (
                      <button onClick={() => onDocReceived(s.tenant_id, rq.id)}
                              className="ml-auto text-[10px] font-semibold px-2 py-1 rounded-lg border"
                              style={{ borderColor: 'rgba(61,220,151,.4)', color: '#3DDC97' }}>
                        Reçu ✓
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Chapter 4 + 8 + TVA — the agent's autonomous work for this dossier.
            Always mounted (so the hub badge knows the count on first open),
            but only VISIBLE in the 'agent' room. */}
        {s.tenant_id && (
          <div style={{ display: room === 'agent' ? 'block' : 'none' }}>
            <AgentToolsPanel tenantId={s.tenant_id} onToast={onToast} onCounts={setAgentN} />
          </div>
        )}

        {/* S13 — abonnements: the standing instructions the agent executes */}
        {room === 'abos' && subs !== null && (
          <div className="px-5 pt-4 pb-4 border-b" style={{ borderColor: 'rgba(255,255,255,.10)' }}>
            <div className="flex items-center justify-between mb-2">
              <div className="text-sm font-bold text-[#F8FAFC]">Abonnements (facturation récurrente)</div>
              <div className="flex gap-2">
                <button onClick={() => onRunBilling(s.tenant_id)}
                        className="text-xs px-2.5 py-1.5 rounded-lg border"
                        style={{ borderColor: 'rgba(255,255,255,.10)', color: '#B9C2D6' }}
                        title="Exécute toutes les instructions dues — l'agent prépare des brouillons, il ne transmet rien.">
                  🤖 Exécuter maintenant
                </button>
                <button onClick={() => onNewSub(s.tenant_id)}
                        className="text-xs font-semibold px-2.5 py-1.5 rounded-lg border"
                        style={{ borderColor: 'rgba(255,255,255,.18)', color: '#C77DFF' }}>
                  + Nouvel abonnement
                </button>
              </div>
            </div>
            {subs.length === 0 ? (
              <div className="text-xs text-[#7C879F]">
                Aucune instruction permanente — « chaque mois, le X, facturer Y à Z ».
              </div>
            ) : (
              <div className="space-y-1.5">
                {subs.map((sb) => {
                  const ht = (sb.lines || []).reduce((a, l) => a + (l.quantity || 1) * (l.unit_price || 0), 0);
                  return (
                    <div key={sb.id} className="flex items-center gap-2 text-xs flex-wrap">
                      <span className="w-2 h-2 rounded-full shrink-0"
                            style={{ background: sb.active ? '#3DDC97' : '#7C879F' }} />
                      <span className="font-semibold text-[#F8FAFC]">{sb.label}</span>
                      <span className="text-[#B9C2D6]">{ht.toFixed(2)} € HT · le {sb.day_of_month} du mois</span>
                      <span className="text-[#7C879F]">→ {sb.buyer?.name}</span>
                      {sb.last_run_ym && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded-full"
                              style={{ color: '#B9C2D6', background: 'rgba(87,83,78,.08)' }}>
                          dernier : {sb.last_run_ym}
                        </span>
                      )}
                      <button onClick={() => onToggleSub(s.tenant_id, sb.id, !sb.active)}
                              className="ml-auto text-[10px] px-2 py-1 rounded-lg border"
                              style={{ borderColor: 'rgba(255,255,255,.10)', color: '#B9C2D6' }}>
                        {sb.active ? 'Mettre en pause' : 'Réactiver'}
                      </button>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {/* Actions the cabinet can perform FOR this client. The legal duty sits
            with the business, but in practice the accountant is the one who
            tracks the deadline — so both sides get the button, and the audit log
            records who actually pressed it. */}
        {room === 'ventes' && onActFor && (
          <div className="px-5 pt-4 flex flex-wrap gap-2 border-b pb-4" style={{ borderColor: 'rgba(255,255,255,.10)' }}>
            {onNewInvoice && (
              <button onClick={() => onNewInvoice(s.tenant_id)}
                      className="text-xs font-semibold px-3 py-2 rounded-xl text-white"
                      style={{ background: 'linear-gradient(135deg,#7C7CF8,#5B5BE8)' }}>
                + Nouvelle facture
              </button>
            )}
            <button onClick={() => onActFor('ereporting', s.tenant_id)}
                    disabled={acting === 'ereporting'}
                    className="text-xs font-semibold px-3 py-2 rounded-xl text-white disabled:opacity-50"
                    style={{ background: 'linear-gradient(135deg,#C77DFF,#C77DFF)' }}>
              {acting === 'ereporting' ? 'Envoi…' : "Envoyer l'e-reporting"}
            </button>
            {!s.dgfip_activated && (
              <button onClick={() => onActFor('activate', s.tenant_id)}
                      disabled={acting === 'activate'}
                      className="text-xs font-semibold px-3 py-2 rounded-xl text-white disabled:opacity-50"
                      style={{ background: 'linear-gradient(135deg,#3DDC97,#3DDC97)' }}>
                {acting === 'activate' ? 'Activation…' : 'Activer conformité DGFiP'}
              </button>
            )}
            <button onClick={() => onActFor('received', s.tenant_id)}
                    disabled={acting === 'received'}
                    className="text-xs px-3 py-2 rounded-xl border disabled:opacity-50"
                    style={{ borderColor: 'rgba(255,255,255,.10)', color: '#B9C2D6' }}>
              {acting === 'received' ? 'Simulation…' : 'Simuler une facture reçue'}
            </button>
            <span className="text-[10px] self-center" style={{ color: '#7C879F' }}>
              Actions effectuées pour le compte du client — tracées dans l'historique.
            </span>
          </div>
        )}

        {room === 'ventes' && (
        <div className="p-5">
          <div className="grid grid-cols-3 gap-2 mb-4">
            <div className="rounded-xl border p-3" style={{ borderColor: unpaid.length ? 'rgba(255,107,107,.35)' : 'rgba(255,255,255,.10)' }}>
              <LiveText as="div" className="text-lg font-extrabold" style={{ color: unpaid.length ? '#FF6B6B' : '#3DDC97' }}>
                {`${unpaidTot.toFixed(0)} €`}
              </LiveText>
              <LiveText as="div" className="text-[10.5px] text-[#7C879F]">
                {`impayés (${unpaid.length} facture${unpaid.length > 1 ? 's' : ''})`}
              </LiveText>
            </div>
            <div className="rounded-xl border p-3" style={{ borderColor: 'rgba(255,255,255,.10)' }}>
              <LiveText as="div" className="text-lg font-extrabold text-[#F8FAFC]">{String((data.invoices || []).length)}</LiveText>
              <div className="text-[10.5px] text-[#7C879F]">factures émises</div>
            </div>
            <label className="rounded-xl border p-3 cursor-pointer text-center flex flex-col justify-center"
                   style={{ borderColor: 'rgba(255,255,255,.18)', borderStyle: 'dashed' }}>
              <span className="text-lg">📷</span>
              <span className="text-[10.5px] font-semibold" style={{ color: '#C77DFF' }}>
                Photographier une facture de vente (papier)
              </span>
              <input type="file" accept="image/*" className="hidden"
                     onChange={(e) => { const f = e.target.files && e.target.files[0]; e.target.value = '';
                       if (f && onOcr) onOcr(s.tenant_id, f, true); }} />
            </label>
          </div>
          {(s.alerts || []).length > 0 && (
            <ul className="space-y-1.5 mb-4">
              {s.alerts.map((a, i) => (
                <li key={i} className="flex items-center gap-2 text-sm">
                  <AlertTriangle size={14} style={{ color: BAND[a.level]?.c }} />
                  <LiveText className="text-[#B9C2D6]">{a.message}</LiveText>
                </li>
              ))}
            </ul>
          )}
          <h4 className="text-sm font-bold text-[#F8FAFC] mb-2">Factures émises</h4>
          {(data.invoices || []).length === 0 ? (
            <div className="text-sm text-[#7C879F]">Aucune facture.</div>
          ) : (
            <div className="divide-y" style={{ borderColor: 'rgba(255,255,255,.10)' }}>
              {sortedInv.map((inv) => {
                const credited = (data.credit_notes || []).some((c) => c.original_invoice_id === inv.id);
                const busy = reviewing === inv.id;
                return (
                  <div key={inv.id} className="py-2.5 flex items-center gap-2 text-sm flex-wrap">
                    <span className="font-semibold text-[#F8FAFC] w-24 shrink-0">{inv.number}</span>
                    <span className="flex-1 min-w-[100px] text-[#B9C2D6] truncate flex items-center gap-1.5">
                      {inv.buyer?.name || '—'} <Chan channel={inv.channel} />
                    </span>
                    <span className="text-[#F8FAFC] w-20 text-right shrink-0">{(inv.total_ttc ?? 0).toFixed(2)} €</span>
                    <Pill state={credited ? 'credited' : (inv.pa_status || inv.state)} />
                    <MiniChip value={inv.review_status} map={REVIEW_MAP} />
                    <MiniChip value={inv.payment_status} map={PAY_MAP} />
                    {/* Review action — works even on a REFUSED invoice, which is
                        exactly what the 4-status split unlocked. */}
                    {inv.review_status !== 'validated' && onReview && (
                      <button disabled={busy} onClick={() => onReview(inv.id, 'validated')}
                        className="text-[11px] font-semibold px-2 py-1 rounded-lg text-white disabled:opacity-50 shrink-0"
                        style={{ background: '#3DDC97' }}>
                        {busy ? '…' : 'Valider'}
                      </button>
                    )}
                    {/* A refused invoice is only truly fixed by a credit note —
                        validating it just records that the accountant looked at
                        it. This is the button that actually clears the alert. */}
                    {['refused', 'error'].includes(inv.pa_status || inv.state)
                      && !credited && onCreditNote && (
                      <button disabled={crediting === inv.id}
                              onClick={() => onCreditNote(inv.id, inv.number)}
                              className="text-[11px] font-semibold px-2 py-1 rounded-lg border disabled:opacity-50 shrink-0"
                              style={{ borderColor: '#FF6B6B', color: '#FF6B6B' }}>
                        {crediting === inv.id ? '…' : 'Créer un avoir'}
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {(data.credit_notes || []).length > 0 && (
            <>
              <h4 className="text-sm font-bold text-[#F8FAFC] mt-4 mb-2">Avoirs émis</h4>
              <div className="divide-y" style={{ borderColor: 'rgba(255,255,255,.10)' }}>
                {data.credit_notes.map((cn) => (
                  <div key={cn.id} className="py-2 flex items-center gap-2 text-sm">
                    <span className="font-semibold text-[#F8FAFC] w-28 shrink-0">{cn.number}</span>
                    <span className="flex-1 text-[#B9C2D6] truncate">corrige {cn.original_number}</span>
                    <span className="w-20 text-right font-semibold" style={{ color: '#FF6B6B' }}>
                      −{Math.abs(cn.amount_ttc ?? 0).toFixed(2)} €
                    </span>
                  </div>
                ))}
              </div>
            </>
          )}

        </div>
        )}

        {/* ── Room: ACHATS — photograph, sync, list supplier invoices ────── */}
        {room === 'achats' && (
        <div className="p-5">
          <div className="grid grid-cols-2 gap-2 mb-4">
            <label className="rounded-xl border p-4 cursor-pointer text-center"
                   style={{ borderColor: '#7C7CF8', borderStyle: 'dashed' }}>
              <div className="text-xl">📷</div>
              <div className="text-xs font-bold" style={{ color: '#7C7CF8' }}>
                Photographier une facture fournisseur
              </div>
              <div className="text-[10px] text-[#7C879F]">même un ticket de caisse (Metro, Carrefour…)</div>
              <input type="file" accept="image/*" className="hidden"
                     onChange={(e) => { const f = e.target.files && e.target.files[0]; e.target.value = '';
                       if (f && onOcr) onOcr(s.tenant_id, f, false); }} />
            </label>
            <button onClick={() => onSyncRec && onSyncRec(s.tenant_id)}
                    className="rounded-xl border p-4 text-center" style={{ borderColor: 'rgba(255,255,255,.10)' }}>
              <div className="text-xl">🔄</div>
              <div className="text-xs font-bold text-[#B9C2D6]">Synchroniser les e-factures</div>
              <div className="text-[10px] text-[#7C879F]">récupère depuis la plateforme du client</div>
            </button>
          </div>
          <h4 className="text-sm font-bold text-[#F8FAFC] mb-2">
            Factures reçues ({(data.received || []).length})
          </h4>
          {(data.received || []).length === 0 ? (
            <div className="text-xs text-[#7C879F]">
              Rien encore — photographiez un ticket ou synchronisez. Dès septembre 2026, les
              e-factures des fournisseurs arriveront ici toutes seules.
            </div>
          ) : (
            <div className="divide-y" style={{ borderColor: 'rgba(255,255,255,.10)' }}>
              {data.received.map((r) => (
                <div key={r.id} className="py-2 flex items-center gap-2 text-sm">
                  <span className="font-semibold text-[#F8FAFC] w-28 shrink-0 truncate">{r.number || '—'}</span>
                  <span className="flex-1 text-[#B9C2D6] truncate">{r.supplier?.name || '—'}</span>
                  {r.source === 'ocr' && <span className="text-[10px]">📷</span>}
                  <span className="text-[#F8FAFC] w-20 text-right">{(r.total_ttc ?? 0).toFixed(2)} €</span>
                </div>
              ))}
            </div>
          )}
        </div>
        )}

        {/* ── Room: INDICATEURS — the score, spelled out ─────────────────── */}
        {room === 'indicateurs' && (
        <div className="p-5">
          <div className="flex items-center gap-4 mb-4">
            <div className="text-4xl font-extrabold" style={{ color: b.c }}>
              <LiveText>{String(s.score)}</LiveText><span className="text-base text-[#7C879F]">/100</span>
            </div>
            <div>
              <div className="text-sm font-bold" style={{ color: b.c }}><LiveText>{b.label}</LiveText></div>
              <div className="text-[11px] text-[#7C879F]">Bouclier fiscal — ce que verrait un contrôle. Indicateur informatif, ni conseil fiscal ni ECF.</div>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2 mb-4">
            <div className="rounded-xl border p-3" style={{ borderColor: unpaid.length ? 'rgba(255,107,107,.35)' : 'rgba(255,255,255,.10)' }}>
              <LiveText as="div" className="text-lg font-extrabold" style={{ color: unpaid.length ? '#FF6B6B' : '#3DDC97' }}>{`${unpaidTot.toFixed(0)} €`}</LiveText>
              <div className="text-[10.5px] text-[#7C879F]">impayés clients à encaisser</div>
            </div>
            <div className="rounded-xl border p-3" style={{ borderColor: 'rgba(255,255,255,.10)' }}>
              <LiveText as="div" className="text-lg font-extrabold text-[#F8FAFC]">{String((data.received || []).length)}</LiveText>
              <div className="text-[10.5px] text-[#7C879F]">pièces d'achat au dossier</div>
            </div>
          </div>
          <h4 className="text-sm font-bold text-[#F8FAFC] mb-2">Points de vigilance ({(s.alerts || []).length})</h4>
          {(s.alerts || []).length === 0 ? (
            <div className="text-xs" style={{ color: '#3DDC97' }}>✓ Aucune anomalie — dossier cohérent.</div>
          ) : (
            <ul className="space-y-1.5">
              {s.alerts.map((a, i) => (
                <li key={i} className="flex items-start gap-2 text-sm">
                  <AlertTriangle size={14} className="mt-0.5 shrink-0" style={{ color: BAND[a.level]?.c }} />
                  <LiveText className="text-[#B9C2D6]">{a.message}</LiveText>
                </li>
              ))}
            </ul>
          )}
          <button onClick={() => setRoom('agent')}
                  className="mt-4 text-xs font-semibold px-3 py-2 rounded-xl border"
                  style={{ borderColor: 'rgba(255,255,255,.18)', color: '#C77DFF' }}>
            🤖 Calculer la TVA / lancer les contrôles → L'agent a préparé
          </button>
        </div>
        )}
        </div>

        </div>

        {/* ── Bottom navigation — four tabs ──────────────────────────────
            Four, not five. The fifth was "Plus", whose contents were already on
            Synthèse; a tab that leads somewhere you can already reach costs a
            decision and returns nothing. Synthèse now IS the "everything" tab.  */}
        <div className="sticky bottom-0 z-10 mc-surface mt-auto"
             style={{ borderTop: `1px solid ${MC.stroke}`,
                      paddingBottom: 'max(6px, env(safe-area-inset-bottom))' }}>
        {/* The bar tracks the content column. Full-bleed on desktop turned each
            tab into a 370px slab, which reads as a toolbar, not a tab bar. */}
        <div className="w-full max-w-2xl mx-auto px-2 pt-1.5 grid grid-cols-4">
          {[[null, '🗂️', 'Synthèse'], ['achats', '🛒', 'Achats'],
            ['ventes', '📤', 'Ventes'], ['agent', '🤖', 'Agent']].map(([r, ic, lb]) => {
            // A sub-room opened from the hub keeps Synthèse lit — you are still
            // "inside" it, and nothing else on the bar would be true.
            const active = room === r
              || (r === null && ['pieces', 'abos', 'indicateurs'].includes(room));
            return (
              <button key={String(lb)} onClick={() => setRoom(r)}
                      className="flex flex-col items-center py-1.5 rounded-xl cursor-pointer"
                      style={{ color: active ? MC.indigo : MC.ink3,
                               background: active ? 'rgba(124,124,248,.12)' : 'transparent',
                               transition: `background .22s ${EASE}, color .22s ${EASE}` }}>
                <span className="text-lg leading-none">{ic}</span>
                <span className="text-[10px] font-semibold mt-0.5">{lb}</span>
              </button>
            );
          })}
        </div>
        </div>
      </div>

      {/* Floating 📷 — photograph a piece from anywhere in the dossier.
          On the Ventes tab it files a SALES invoice, everywhere else a purchase. */}
      <label className="fixed bottom-20 right-5 w-14 h-14 rounded-2xl flex items-center justify-center text-2xl cursor-pointer z-20"
             style={{ background: `linear-gradient(135deg, ${MC.indigo}, #5B5BE8)`,
                      boxShadow: '0 14px 34px -12px rgba(124,124,248,.95)' }}
             title={room === 'ventes' ? 'Photographier une facture de vente'
                    : 'Photographier une facture fournisseur / un ticket'}>
        <span>📷</span>
        <input type="file" accept="image/*" className="hidden"
               onChange={(e) => { const f = e.target.files && e.target.files[0]; e.target.value = '';
                 if (f && onOcr) onOcr(s.tenant_id, f, room === 'ventes'); }} />
      </label>
    </div>
  );
}

/** One "room" card on the dossier hub — icon, label, counter, badge. */
function HubCard({ icon, title, desc, count, badge, accent, onClick }) {
  return (
    <button onClick={onClick} className="hub-card flex items-center gap-3 text-left p-4 cursor-pointer"
            style={{ ...glass(accent ? 'accent' : undefined), borderRadius: 16 }}>
      <span className="w-12 h-12 rounded-xl flex items-center justify-center text-xl shrink-0"
            style={{ background: accent ? 'rgba(124,124,248,.22)' : 'rgba(255,255,255,.07)',
                     border: `1px solid ${MC.stroke}` }}>{icon}</span>
      <span className="flex-1 min-w-0">
        <span className="block text-sm font-bold" style={{ color: MC.ink }}>{title}</span>
        <span className="block text-[11px] truncate" style={{ color: MC.ink3 }}>{desc}</span>
      </span>
      {badge > 0 && (
        <LiveText className="text-[11px] font-bold px-2 py-0.5 rounded-full shrink-0"
              style={{ background: 'rgba(255,107,107,.16)', color: MC.red }}>{String(badge)}</LiveText>
      )}
      {!(badge > 0) && (count ?? null) !== null && (
        <LiveText className="text-xs font-semibold shrink-0" style={{ color: MC.ink2 }}>{String(count)}</LiveText>
      )}
      <ChevronRight size={16} style={{ color: MC.ink3 }} className="shrink-0" />
    </button>
  );
}

/**
 * DossierSkin — the one place the dossier's dark surfaces are defined.
 *
 * The dossier used to open as a light lavender sheet on top of a dark navy
 * dashboard, which read as landing on a different product mid-click. Rather
 * than rewrite ~450 lines of utility classes, the handful of surface classes
 * those lines already use (`mc-surface`, `divide-y`, form fields) are redefined
 * here in the mission-control language, so the whole dossier inherits it.
 */
function DossierSkin() {
  return (
    <style>{`
      .mc-surface{background:${MC.glass};backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px)}
      .hub-card{transition:transform .2s ${EASE}, box-shadow .2s ${EASE}, background .2s ${EASE}}
      .hub-card:hover{transform:translateY(-2px);background:${MC.glassStrong}}
      .hub-card:active{transform:scale(.99)}
      [class*="divide-y"] > * + *{border-top-color:${MC.stroke} !important}
      /* Controls are handled by the .mc-dark scope in index.css, which is the
         only place that can outrank the global light form defaults. */
      input[type=file]{background:none;border:none}
    `}</style>
  );
}
