import { vh } from './lib/fit';
import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import lazyPage from './lib/lazyPage';
import { BranchProvider } from './contexts/BranchContext';

// Top-level error boundary so ANY uncaught render crash on ANY route
// shows a useful message instead of blank-screening the whole app.
// Without this, a thrown error inside a component (e.g. a deeply-nested
// destructure of an unexpected payload shape) bubbles out of React and
// the browser shows nothing — terrible for debugging on a phone where
// you can't open DevTools easily.
class RootErrorBoundary extends React.Component {
  constructor(props) { super(props); this.state = { error: null }; }
  static getDerivedStateFromError(error) { return { error }; }
  componentDidCatch(error, info) {
    // eslint-disable-next-line no-console
    console.error('[root] uncaught render crash:', error, info?.componentStack);
  }
  render() {
    if (this.state.error) {
      return (
        <div style={{
          minHeight: vh(100), display: 'flex', alignItems: 'center',
          justifyContent: 'center', background: '#FDFBF7',
          fontFamily: 'system-ui, -apple-system, sans-serif',
          padding: '2rem', textAlign: 'center',
        }}>
          <div style={{
            background: 'white', padding: '2rem', borderRadius: 16,
            border: '1px solid #E7E5E4', maxWidth: 480, width: '100%',
            boxShadow: '0 10px 30px -10px rgba(0,0,0,.1)',
          }}>
            <div style={{ fontSize: 32, marginBottom: 8 }}>⚠️</div>
            <h2 style={{ margin: '0 0 8px', fontSize: 18, color: '#1C1917' }}>
              Une erreur d'affichage est survenue
            </h2>
            <p style={{ margin: '0 0 12px', fontSize: 13, color: '#57534E' }}>
              La page n'a pas pu être affichée correctement.
            </p>
            <details style={{ textAlign: 'left', marginBottom: 16 }}>
              <summary style={{ fontSize: 12, color: '#8B8680', cursor: 'pointer' }}>
                Détail technique
              </summary>
              <code style={{
                display: 'block', marginTop: 8, padding: 8,
                background: '#F3EFE7', borderRadius: 6,
                fontSize: 11, color: '#57534E',
                whiteSpace: 'pre-wrap', wordBreak: 'break-word',
              }}>
                {String(this.state.error?.message || this.state.error)}
              </code>
            </details>
            <button
              onClick={() => window.location.reload()}
              style={{
                padding: '10px 20px', borderRadius: 8, border: 'none',
                background: '#B85C38', color: 'white', cursor: 'pointer',
                fontSize: 13, fontWeight: 500,
              }}
            >
              Recharger la page
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

import LoginPage from './pages/LoginPage';
const RegisterPage = lazyPage(() => import('./pages/RegisterPage'));
import { onboardingPath } from './lib/onboarding';
const OnboardingCompanyPage = lazyPage(() => import('./pages/OnboardingCompanyPage'));
const OnboardingPlanPage = lazyPage(() => import('./pages/OnboardingPlanPage'));
const OnboardingVerifyPage = lazyPage(() => import('./pages/OnboardingVerifyPage'));
const OnboardingCardPage = lazyPage(() => import('./pages/OnboardingCardPage'));
const OnboardingDonePage = lazyPage(() => import('./pages/OnboardingDonePage'));
const DashboardLayout = lazyPage(() => import('./pages/DashboardLayout'));
// Analyses is the page on /dashboard/analytics. The two older takes
// (AnalyticsPage, AnalyticsPageV2) are kept on disk for rollback only —
// to revert, import one of them here instead.
// Legacy AnalyticsPage kept for rollback during the dark-redesign rollout.
// AnalyticsPageV2 is the new dark redesign that replaces it on the
// /dashboard/analytics route. To revert: swap the imports here.
// import AnalyticsPage from './pages/AnalyticsPage';
// import AnalyticsPage from './pages/AnalyticsPageV2';
const AnalysesPage = lazyPage(() => import('./pages/AnalysesPage'));
// The redesigned till (user, 2026-10-13). ScanPage stays in the repo,
// unrouted, until the new one has been through a few real services.
const ScanPage = lazyPage(() => import('./pages/ScanPage')); // eslint-disable-line no-unused-vars -- superseded by ScanPageV2, kept for rollback
const ScanPageV2 = lazyPage(() => import('./pages/ScanPageV2'));
const CampaignsPage = lazyPage(() => import('./pages/CampaignsPage'));
const SettingsPage = lazyPage(() => import('./pages/SettingsPage'));
const ParametresPage = lazyPage(() => import('./pages/ParametresPage'));
const CataloguePage = lazyPage(() => import('./pages/CataloguePage'));
const JoinPage = lazyPage(() => import('./pages/JoinPage'));
const MyWalletCardPage = lazyPage(() => import('./pages/MyWalletCardPage'));
const ReaddCardPage = lazyPage(() => import('./pages/ReaddCardPage'));
const CardOffersPage = lazyPage(() => import('./pages/CardOffersPage'));
const CardSharePage = lazyPage(() => import('./pages/CardSharePage'));
const HistoryPage = lazyPage(() => import('./pages/HistoryPage'));

const AdminDashboard = lazyPage(() => import('./pages/AdminDashboard')); // eslint-disable-line no-unused-vars -- superseded by admin/AdminDashboardPage, kept for rollback
const AdminDashboardPage = lazyPage(() => import('./pages/admin/AdminDashboardPage'));
// Rollback: the previous Analytics page — import AdminAnalyticsPage from './pages/AdminAnalyticsPage';
const AnalyticsGlobalPage = lazyPage(() => import('./pages/admin/AnalyticsGlobalPage'));
const AdminTenantsPage = lazyPage(() => import('./pages/AdminTenantsPage')); // eslint-disable-line no-unused-vars -- superseded by admin/CommercesPage, kept for rollback
const CommercesPage = lazyPage(() => import('./pages/admin/CommercesPage'));
const CommerceDetailPage = lazyPage(() => import('./pages/admin/CommerceDetailPage'));
const ViewAsEntry = lazyPage(() => import('./pages/admin/ViewAsEntry'));
const SecuriteOverviewPage = lazyPage(() => import('./pages/admin/securite/SecuriteOverviewPage'));
const RolesPage = lazyPage(() => import('./pages/admin/securite/RolesPage'));
const ConnexionsPage = lazyPage(() => import('./pages/admin/securite/ConnexionsPage'));
const JournalPage = lazyPage(() => import('./pages/admin/securite/JournalPage'));
const SecuritySettingsPage = lazyPage(() => import('./pages/admin/securite/SecuritySettingsPage'));
const SupportCenterPage = lazyPage(() => import('./pages/admin/support/SupportCenterPage'));
const SuiviEquipePage = lazyPage(() => import('./pages/admin/equipe/SuiviEquipePage'));
import { can, moduleOfPath, firstAllowed } from './lib/perms';
// Rollback: the previous plan editor — import AdminPlansPage from './pages/AdminPlansPage';
const PlanLimitsPage = lazyPage(() => import('./pages/admin/PlanLimitsPage'));
const AdminInvoicingPage = lazyPage(() => import('./pages/AdminInvoicingPage'));
const CrmOverviewPage = lazyPage(() => import('./pages/crm/CrmOverviewPage'));
// Rollback: the overview's previous layout — import CrmOverviewPageV1 from './pages/crm/CrmOverviewPageV1';
const CrmProspectsPage = lazyPage(() => import('./pages/crm/CrmProspectsPage'));
const CrmPipelinePage = lazyPage(() => import('./pages/crm/CrmPipelinePage'));
const CrmTasksPage = lazyPage(() => import('./pages/crm/CrmTasksPage'));
const CrmCalendarPage = lazyPage(() => import('./pages/crm/CrmCalendarPage'));
const CrmCallsPage = lazyPage(() => import('./pages/crm/CrmCallsPage'));
const CrmSequencesPage = lazyPage(() => import('./pages/crm/CrmSequencesPage'));
const CrmTemplatesPage = lazyPage(() => import('./pages/crm/CrmTemplatesPage'));
const AdminCardDesignerPage = lazyPage(() => import('./pages/AdminCardDesignerPage')); // eslint-disable-line no-unused-vars -- section removed (user, 2026-09-30), kept for rollback
const LoyaltyCardPage = lazyPage(() => import('./pages/LoyaltyCardPage'));
// Carte de fidélité before the 4-step redesign (2026-10-11), kept unrouted for rollback:
// const LoyaltyCardPageLegacy = lazyPage(() => import('./pages/LoyaltyCardPageLegacy'));
const ComingSoonPage = lazyPage(() => import('./pages/ComingSoonPage'));
const HelpPage = lazyPage(() => import('./pages/HelpPage'));
const GeolocationPage = lazyPage(() => import('./pages/GeolocationPage'));
const ReferralPage = lazyPage(() => import('./pages/ReferralPage'));
const AutomationsPage = lazyPage(() => import('./pages/AutomationsPage'));
const AutomationEditorPage = lazyPage(() => import('./pages/AutomationEditorPage'));
const DashboardHomePage = lazyPage(() => import('./pages/DashboardHomePage'));
const ClientsPage = lazyPage(() => import('./pages/ClientsPage'));
const SegmentationPage = lazyPage(() => import('./pages/SegmentationPage'));
// Insights — rebuilt to the approved design. The previous InsightsPage stays
// in the repo, unrouted, for rollback.
const InsightsGrowthPage = lazyPage(() => import('./pages/InsightsGrowthPage'));
// FidClic IA Copilote — replaces the previous AI assistant, which stays in the
// repo, unrouted, for rollback.
const CopilotPage = lazyPage(() => import('./pages/CopilotPage'));
// Campagnes — rebuilt to the approved design. CampaignsPage stays in the
// repo, unrouted, for rollback.
const CampagnesPage = lazyPage(() => import('./pages/CampagnesPage'));
// Rapports mensuels des campagnes (Pro AI).
const CampaignReportsPage = lazyPage(() => import('./pages/CampaignReportsPage'));
const NotificationsPage = lazyPage(() => import('./pages/NotificationsPage'));
// Rollback: the previous AI assistant — import AdminAIAssistantPage from './pages/AdminAIAssistantPage';
const AiIntelligencePage = lazyPage(() => import('./pages/admin/ai/AiIntelligencePage'));
const AiSavedPage = lazyPage(() => import('./pages/admin/ai/AiSavedPage'));
const AiReportsPage = lazyPage(() => import('./pages/admin/ai/AiReportsPage'));
// Removed from the super admin (2026-09-30): import AdminCampaignsPage from './pages/AdminCampaignsPage';
// Rollback: the previous Insights page — import AdminInsightsPage from './pages/AdminInsightsPage';
const AdminInsightsBoard = lazyPage(() => import('./pages/admin/InsightsPage'));
import GoogleTranslateBridge, { RouteAwareRetranslator } from './components/GoogleTranslateBridge';
// Facturation module (French e-invoicing) — post-login module chooser + home.
const ModuleChooserPage = lazyPage(() => import('./pages/ModuleChooserPage'));
const FacturationHome = lazyPage(() => import('./pages/FacturationHome'));
const CabinetDashboard = lazyPage(() => import('./pages/CabinetDashboard'));
const CabinetTeam = lazyPage(() => import('./pages/CabinetTeam'));
const CabinetCases = lazyPage(() => import('./pages/CabinetCases'));
const CabinetReview = lazyPage(() => import('./pages/CabinetReview'));
import CabinetPasswordGate from './components/CabinetPasswordGate';
import { EINVOICING_VISIBLE, OWNER_HOME } from './lib/modules';
import { hasPagePerms } from './lib/pagePerms';
const CabinetSignup = lazyPage(() => import('./pages/CabinetSignup'));
const ResetPasswordPage = lazyPage(() => import('./pages/ResetPasswordPage'));
const ChangerEmailPage = lazyPage(() => import('./pages/ChangerEmailPage'));
// Public marketing pages — one per product line, so each audience gets a whole
// page instead of an anchor buried in the homepage.
const FacturationLanding = lazyPage(() => import('./pages/FacturationLanding'));
const CabinetLanding = lazyPage(() => import('./pages/CabinetLanding'));

/**
 * ScrollToTop — without this, navigating from the landing page to a product
 * page keeps the old scroll position and the visitor lands mid-page, which
 * feels broken. Anchor links (#pricing) are left alone.
 */
const ScrollToTop = () => {
  const { pathname, hash } = useLocation();
  React.useEffect(() => {
    if (!hash) window.scrollTo({ top: 0, left: 0, behavior: 'instant' });
  }, [pathname, hash]);
  return null;
};

// An owner whose sign-up isn't finished is parked on the step they stopped at
// (lib/onboarding.js). No dashboard, no modules, until the plan step has
// started the trial.
const needsOnboarding = (user) => Boolean(onboardingPath(user));

/* Inside /admin: each member of FidClic's team sees the sections their role
   allows (Sécurité › Rôles & Permissions); the server refuses the rest too. */
function AdminGate({ children }) {
  const { user } = useAuth();
  const { pathname } = useLocation();
  const module = moduleOfPath(pathname);
  if (!module || can(user, module)) return children;
  const first = firstAllowed(user);
  if (pathname === '/admin' || pathname === '/admin/') return first ? <Navigate to={first} replace /> : <NoAccess />;
  return <NoAccess first={first} />;
}

function NoAccess({ first }) {
  return (
    <div className="mx-auto mt-16 max-w-md rounded-2xl border border-[#E6EEFB] bg-white p-8 text-center">
      <p className="text-[18px] font-bold text-[#0B1C3F]">Accès non autorisé</p>
      <p className="mt-2 text-[14px] text-[#475569]">Votre rôle ne permet pas d'ouvrir cette section. Demandez l'accès au Super Admin.</p>
      {first && <a href={first} className="mt-4 inline-block rounded-xl bg-[#2F6BFF] px-4 py-2 text-[14px] font-medium text-white">Retour à mon espace</a>}
    </div>
  );
}

const ProtectedRoute = ({ children, allowedRoles, skipOnboardingGate = false, partialOk = false }) => {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <div>Loading...</div>;
  if (!user) return <Navigate to="/login" replace />;
  if (!skipOnboardingGate && needsOnboarding(user)) return <Navigate to={onboardingPath(user)} replace />;
  // An account with its own permissions (Équipe & accès): a /dashboard page
  // opens if it may « Voir » it — the server checks every call too.
  // Its permissions decide, not its role (user, 2026-10-22): the page opens
  // inside the platform, and DashboardLayout shows « Accès non autorisé » on
  // one it may not « Voir » — never a redirect that hides the page.
  if (hasPagePerms(user) && location.pathname.startsWith('/dashboard')) return children;
  // Administrateurs, and managers covering only some establishments, reach
  // the data pages once those pages filter by establishment; until then they
  // work from Paramètres › Équipe & accès (the server refuses the rest too).
  const partial = ['administrateur', 'manager'].includes(user.role) && user.scope === 'partial';
  if (partial && !partialOk && !(allowedRoles || []).includes('staff')) {
    return <Navigate to="/dashboard" replace />;
  }
  if (allowedRoles && !allowedRoles.includes(user.role)) {
    if (user.role === 'administrateur') return <Navigate to="/dashboard" replace />;
    // Staff and managers land on the page they *are* allowed to use instead of
    // being kicked to the landing page. Staff → /dashboard/scan; everyone else
    // back to the landing.
    if (user.role === 'staff') return <Navigate to="/dashboard/scan" replace />;
    if (user.role === 'manager') return <Navigate to="/dashboard/analytics" replace />;
    if (user.role === 'comptable') return <Navigate to="/cabinet" replace />;
    return <Navigate to="/" replace />;
  }
  return children;
};

const PublicRoute = ({ children }) => {
  const { user, loading } = useAuth();
  if (loading) return <div>Loading...</div>;
  if (user) {
    if (needsOnboarding(user)) return <Navigate to={onboardingPath(user)} replace />;
    if (['super_admin', 'fidclic_team'].includes(user.role)) return <Navigate to="/admin" replace />;
    if (user.role === 'commercial') return <Navigate to="/admin/crm" replace />;
    // Owners land on the module chooser (CRM+Fidélité vs Facturation) — or,
    // while e-invoicing is hidden (lib/modules), straight on the dashboard.
    // Handles already-logged-in sessions too (not just fresh logins).
    if (user.role === 'business_owner') return <Navigate to={OWNER_HOME} replace />;
    if (user.role === 'comptable') return <Navigate to="/cabinet" replace />;
    return <Navigate to="/dashboard" replace />;
  }
  return children;
};

// app.fidclic.com is the product; the public site lives at www.fidclic.com
// (fidclic.fr redirects there too). A visitor who opens "/" — on the app or
// on localhost — lands on that site. The app's older built-in LandingPage
// (pages/LandingPage.jsx) is kept for rollback but no longer routed.
const MARKETING_URL = 'https://www.fidclic.com/';

const MarketingHome = () => {
  const standalone = (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches)
    || window.navigator.standalone === true;
  let card = null;
  try { card = localStorage.getItem('fidelitour:last_card'); } catch (e) { /* private mode */ }
  React.useEffect(() => { if (!standalone) window.location.replace(MARKETING_URL); }, [standalone]);

  // Installed icons can open "/" (iOS ignores start_url): send them back
  // into the app instead of out to the website.
  if (standalone) {
    if (card && /^FT-?[A-Z0-9]+$/i.test(card)) return <Navigate to={`/card/${card}`} replace />;
    return <Navigate to="/login" replace />;
  }
  return null;
};

// Shown while a page's file downloads (first visit only, then cached).
export const PageLoader = () => (
  <div role="status" aria-label="Chargement" className="flex min-h-[40vh] items-center justify-center">
    <span className="h-7 w-7 animate-spin rounded-full border-[3px] border-[#DCE6FA] border-t-[#2F6BFF]" />
  </div>
);

function App() {
  return (
    <RootErrorBoundary>
    <AuthProvider>
      <BranchProvider>
       <Router>
        {/* Full-page translation bridge. Loads Google Translate Element
            once, hidden. LanguageSwitcher calls applyGoogleTranslate(lang)
            on every change → entire DOM (including dynamic API content
            and modal copy) flips to the chosen language. Layout stays LTR
            even for Arabic. */}
        <GoogleTranslateBridge />
        {/* Re-applies translation on every route change so deep pages
            (Insights, Card Designer, AI Assistant, etc.) get walked
            from scratch and don't stay in French after navigation. */}
        <RouteAwareRetranslator />
        <ScrollToTop />
        <React.Suspense fallback={<PageLoader />}>
        <Routes>
          <Route path="/" element={<PublicRoute><MarketingHome /></PublicRoute>} />
          <Route path="/login" element={<PublicRoute><LoginPage /></PublicRoute>} />
          <Route path="/register" element={<PublicRoute><RegisterPage /></PublicRoute>} />
          {/* Onboarding steps 2 and 3 — the only protected pages a half-registered owner may see. */}
          <Route path="/onboarding/entreprise" element={
            <ProtectedRoute allowedRoles={['business_owner']} skipOnboardingGate>
              <OnboardingCompanyPage />
            </ProtectedRoute>
          } />
          <Route path="/onboarding/verification" element={
            <ProtectedRoute allowedRoles={['business_owner']} skipOnboardingGate>
              <OnboardingVerifyPage />
            </ProtectedRoute>
          } />
          <Route path="/onboarding/formule" element={
            <ProtectedRoute allowedRoles={['business_owner']} skipOnboardingGate>
              <OnboardingPlanPage />
            </ProtectedRoute>
          } />
          <Route path="/onboarding/carte" element={
            <ProtectedRoute allowedRoles={['business_owner']}>
              <OnboardingCardPage />
            </ProtectedRoute>
          } />
          <Route path="/onboarding/termine" element={
            <ProtectedRoute allowedRoles={['business_owner']}>
              <OnboardingDonePage />
            </ProtectedRoute>
          } />
          <Route path="/voir-compte" element={<ViewAsEntry />} />
          <Route path="/join/:slug" element={<JoinPage />} />
          {/* one link per channel (Paramètres › Lien d'inscription): /join/<slug>/insta, /wa… */}
          <Route path="/join/:slug/:channel" element={<JoinPage />} />
          {/* an establishment's own link, then its channel: /join/<slug>/<store>/insta (multi-store) */}
          <Route path="/join/:slug/:channel/:channel2" element={<JoinPage />} />
          {/* The French address the Paramètres page hands out; /join stays for every QR already printed. */}
          <Route path="/inscription/:slug" element={<JoinPage />} />
          <Route path="/inscription/:slug/:channel" element={<JoinPage />} />
          <Route path="/inscription/:slug/:channel/:channel2" element={<JoinPage />} />
          <Route path="/card/:barcodeId/offres" element={<CardOffersPage />} />
          <Route path="/card/:barcodeId/partager" element={<CardSharePage />} />
          <Route path="/card/:barcodeId" element={<MyWalletCardPage />} />
          {/* a card given back by the shop: a one-time link (features/card_status) */}
          <Route path="/carte/recuperer/:token" element={<ReaddCardPage />} />

          {/* Public product pages. Deliberately NOT wrapped in PublicRoute: a
              logged-in owner or accountant must still be able to read about the
              other module (and share the link) without being bounced to their
              dashboard. */}
          {/* E-invoicing is hidden for now (lib/modules): its pages send
              visitors to the site and owners to their dashboard. */}
          <Route path="/facturation-electronique" element={EINVOICING_VISIBLE ? <FacturationLanding /> : <Navigate to="/" replace />} />
          <Route path="/experts-comptables" element={EINVOICING_VISIBLE ? <CabinetLanding /> : <Navigate to="/" replace />} />

          {/* Facturation module — post-login chooser (Option A) + home.
              Owner/manager only; loyalty-only tenants see the "activate" prompt. */}
          <Route path="/modules" element={EINVOICING_VISIBLE ? (
            <ProtectedRoute allowedRoles={['business_owner', 'manager']}>
              <ModuleChooserPage />
            </ProtectedRoute>
          ) : <Navigate to="/dashboard" replace />} />
          <Route path="/facturation" element={EINVOICING_VISIBLE ? (
            <ProtectedRoute allowedRoles={['business_owner', 'manager']}>
              <FacturationHome />
            </ProtectedRoute>
          ) : <Navigate to="/dashboard" replace />} />
          {/* Accountant (comptable) control tower over all their linked clients. */}
          <Route path="/reinitialiser" element={<ResetPasswordPage />} />
          {/* where the « Confirmer cette adresse » link of the e-mail lands */}
          <Route path="/changer-email" element={<ChangerEmailPage />} />
          <Route path="/cabinet/inscription" element={EINVOICING_VISIBLE ? (
            <PublicRoute><CabinetSignup /></PublicRoute>
          ) : <Navigate to="/" replace />} />
          <Route path="/cabinet" element={
            <ProtectedRoute allowedRoles={['comptable']}>
              <CabinetPasswordGate><CabinetDashboard /></CabinetPasswordGate>
            </ProtectedRoute>
          } />
          <Route path="/cabinet/equipe" element={
            <ProtectedRoute allowedRoles={['comptable']}>
              <CabinetPasswordGate><CabinetTeam /></CabinetPasswordGate>
            </ProtectedRoute>
          } />
          <Route path="/cabinet/cas" element={
            <ProtectedRoute allowedRoles={['comptable']}>
              <CabinetPasswordGate><CabinetCases /></CabinetPasswordGate>
            </ProtectedRoute>
          } />
          <Route path="/cabinet/revue" element={
            <ProtectedRoute allowedRoles={['comptable']}>
              <CabinetPasswordGate><CabinetReview /></CabinetPasswordGate>
            </ProtectedRoute>
          } />

          {/* Business Owner Routes — per-page role enforcement.
              - business_owner: full access
              - manager: analytics, insights, customers, map, scan (no campaigns/settings/AI)
              - staff: scan ONLY — every other route redirects them back to /dashboard/scan */}
          <Route path="/dashboard" element={
            <ProtectedRoute allowedRoles={['business_owner', 'administrateur', 'manager', 'staff']} partialOk>
              <DashboardLayout />
            </ProtectedRoute>
          }>
            {/* Tableau de bord — rebuilt to the approved design. OwnerDashboard
                stays in the repo, unrouted, until its smart search and time
                filter have a home on the new page. */}
            <Route index element={
              <ProtectedRoute allowedRoles={['business_owner', 'administrateur', 'manager']} partialOk>
                <DashboardHomePage />
              </ProtectedRoute>
            } />
            <Route path="analytics" element={
              <ProtectedRoute allowedRoles={['business_owner', 'administrateur', 'manager']} partialOk>
                <AnalysesPage />
              </ProtectedRoute>
            } />
            <Route path="insights" element={
              <ProtectedRoute allowedRoles={['business_owner', 'administrateur', 'manager']} partialOk>
                <InsightsGrowthPage />
              </ProtectedRoute>
            } />
            {/* Clients — rebuilt to the approved design. The previous
                CustomersPage stays in the repo, unrouted, until its saved
                segments and campaign composer have a home on the new page. */}
            <Route path="customers" element={
              <ProtectedRoute allowedRoles={['business_owner', 'administrateur', 'manager']} partialOk>
                <ClientsPage />
              </ProtectedRoute>
            } />
            {/* Géolocalisation clients — catchment rings + travel-time bands.
                Replaces CustomerMapPage, whose France-wide dot map this page
                supersedes; the old file stays in the repo, unrouted. */}
            <Route path="map" element={
              <ProtectedRoute allowedRoles={['business_owner', 'administrateur', 'manager']} partialOk>
                <GeolocationPage />
              </ProtectedRoute>
            } />
            {/* Scan is the ONE page staff can reach. */}
            <Route path="scan" element={
              <ProtectedRoute allowedRoles={['business_owner', 'administrateur', 'manager', 'staff']}>
                <ScanPageV2 />
              </ProtectedRoute>
            } />
            {/* Carte de fidélité — the merchant's single card. The old
                CardDesignerPage it replaces has been removed; its advanced
                knobs live in the "Options avancées" panel on this page. */}
            <Route path="segmentation" element={
              <ProtectedRoute allowedRoles={['business_owner', 'administrateur', 'manager']} partialOk>
                <SegmentationPage />
              </ProtectedRoute>
            } />
            <Route path="automations" element={
              <ProtectedRoute allowedRoles={['business_owner', 'administrateur', 'manager']} partialOk>
                <AutomationsPage />
              </ProtectedRoute>
            } />
            <Route path="automations/nouvelle" element={
              <ProtectedRoute allowedRoles={['business_owner', 'administrateur']} partialOk>
                <AutomationEditorPage />
              </ProtectedRoute>
            } />
            <Route path="automations/:id" element={
              <ProtectedRoute allowedRoles={['business_owner', 'administrateur', 'manager']} partialOk>
                <AutomationEditorPage />
              </ProtectedRoute>
            } />
            <Route path="referral" element={
              <ProtectedRoute allowedRoles={['business_owner', 'administrateur', 'manager']} partialOk>
                <ReferralPage />
              </ProtectedRoute>
            } />
            <Route path="card" element={
              <ProtectedRoute allowedRoles={['business_owner', 'administrateur', 'manager']} partialOk>
                <LoyaltyCardPage />
              </ProtectedRoute>
            } />
            {/* Besoin d'aide ? — FAQ + assistant + the three contact channels.
                Reachable by every role; the sidebar's help row points here. */}
            <Route path="aide" element={
              <ProtectedRoute allowedRoles={['business_owner', 'administrateur', 'manager', 'staff', 'super_admin']}>
                <HelpPage />
              </ProtectedRoute>
            } />
            <Route path="campaigns" element={
              <ProtectedRoute allowedRoles={['business_owner', 'administrateur', 'manager']} partialOk>
                <CampagnesPage />
              </ProtectedRoute>
            } />
            <Route path="campaigns/reports" element={
              <ProtectedRoute allowedRoles={['business_owner', 'administrateur', 'manager']} partialOk>
                <CampaignReportsPage />
              </ProtectedRoute>
            } />
            <Route path="ai-assistant" element={
              <ProtectedRoute allowedRoles={['business_owner', 'administrateur', 'manager']} partialOk>
                <CopilotPage />
              </ProtectedRoute>
            } />
            <Route path="catalogue" element={
              <ProtectedRoute allowedRoles={['business_owner', 'administrateur', 'manager']} partialOk>
                <CataloguePage />
              </ProtectedRoute>
            } />
            {/* Paramètres — one page, one tab per sub-page (like Analyses). The
                older all-in-one page stays at /settings for what has not moved yet. */}
            <Route path="parametres" element={<Navigate to="/dashboard/parametres/etablissement" replace />} />
            <Route path="parametres/:section" element={
              <ProtectedRoute allowedRoles={['business_owner', 'administrateur', 'manager']} partialOk>
                <ParametresPage />
              </ProtectedRoute>
            } />
            <Route path="settings" element={
              <ProtectedRoute allowedRoles={['business_owner']}>
                <SettingsPage />
              </ProtectedRoute>
            } />
            {/* The bell's « Voir toutes les notifications de cette boutique ». */}
            <Route path="notifications" element={
              <ProtectedRoute allowedRoles={['business_owner', 'administrateur', 'manager']} partialOk>
                <NotificationsPage />
              </ProtectedRoute>
            } />
            <Route path="history" element={
              <ProtectedRoute allowedRoles={['business_owner', 'administrateur', 'manager']} partialOk>
                <HistoryPage />
              </ProtectedRoute>
            } />
            {/* Anything else under /dashboard goes home. Without this a removed
                page — /dashboard/surveys, say — left a bookmark rendering the
                shell around nothing at all. */}
            <Route path="*" element={<Navigate to="/dashboard" replace />} />
          </Route>

          {/* Super Admin Routes */}
          {/* The shell opens to the super admin and to the sales team
              (« commercial »), who only ever sees the CRM. */}
          <Route path="/admin" element={
            <ProtectedRoute allowedRoles={['super_admin', 'commercial', 'fidclic_team']}>
              <DashboardLayout />
            </ProtectedRoute>
          }>
            <Route index element={<AdminGate><AdminDashboardPage /></AdminGate>} />
            <Route path="analytics" element={<AdminGate><AnalyticsGlobalPage /></AdminGate>} />
            <Route path="insights" element={<AdminGate><AdminInsightsBoard /></AdminGate>} />
            <Route path="tenants" element={<Navigate to="/admin/commerces" replace />} />
            <Route path="commerces" element={<AdminGate><CommercesPage /></AdminGate>} />
            <Route path="commerces/:id" element={<AdminGate><CommerceDetailPage /></AdminGate>} />
            <Route path="plans" element={<AdminGate><PlanLimitsPage /></AdminGate>} />
            <Route path="facturation" element={<AdminGate><AdminInvoicingPage /></AdminGate>} />
            <Route path="card-designer" element={<Navigate to="/admin" replace />} />
            <Route path="ai" element={<AdminGate><AiIntelligencePage /></AdminGate>} />
            <Route path="ai/sauvegardes" element={<AdminGate><AiSavedPage /></AdminGate>} />
            <Route path="ai/rapports" element={<AdminGate><AiReportsPage /></AdminGate>} />
            {/* CRM de prospection */}
            <Route path="crm" element={<AdminGate><CrmOverviewPage /></AdminGate>} />
            <Route path="crm/prospects" element={<AdminGate><CrmProspectsPage /></AdminGate>} />
            <Route path="crm/pipeline" element={<AdminGate><CrmPipelinePage /></AdminGate>} />
            <Route path="crm/taches" element={<AdminGate><CrmTasksPage /></AdminGate>} />
            <Route path="crm/calendrier" element={<AdminGate><CrmCalendarPage /></AdminGate>} />
            <Route path="crm/sequences" element={<AdminGate><CrmSequencesPage /></AdminGate>} />
            <Route path="crm/modeles" element={<AdminGate><CrmTemplatesPage /></AdminGate>} />
            <Route path="crm/appels" element={<AdminGate><CrmCallsPage /></AdminGate>} />
            {/* Import / Export, Suivi des conversations and Statistiques were removed from the CRM (user, 2026-10-01); old links land on the overview. */}
            <Route path="crm/import" element={<Navigate to="/admin/crm" replace />} />
            <Route path="crm/conversations" element={<Navigate to="/admin/crm" replace />} />
            <Route path="crm/statistiques" element={<Navigate to="/admin/crm" replace />} />
            {/* Sécurité — FidClic's own team */}
            <Route path="securite" element={<AdminGate><SecuriteOverviewPage /></AdminGate>} />
            <Route path="securite/roles" element={<AdminGate><RolesPage /></AdminGate>} />
            <Route path="securite/connexions" element={<AdminGate><ConnexionsPage /></AdminGate>} />
            <Route path="securite/journal" element={<AdminGate><JournalPage /></AdminGate>} />
            <Route path="securite/parametres" element={<AdminGate><SecuritySettingsPage /></AdminGate>} />
            <Route path="support" element={<AdminGate><SupportCenterPage /></AdminGate>} />
            {/* Suivi d'équipe — FidClic's own team tasks (features/team_tasks.py) */}
            <Route path="equipe" element={<AdminGate><SuiviEquipePage /></AdminGate>} />
          </Route>
        </Routes>
        </React.Suspense>
       </Router>
      </BranchProvider>
    </AuthProvider>
    </RootErrorBoundary>
  );
}

export default App;
