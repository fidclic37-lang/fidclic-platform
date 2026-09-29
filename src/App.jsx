import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { AuthProvider, useAuth } from './contexts/AuthContext';
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
          minHeight: '100vh', display: 'flex', alignItems: 'center',
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

import LandingPage from './pages/LandingPage';
import LoginPage from './pages/LoginPage';
import RegisterPage from './pages/RegisterPage';
import OnboardingCompanyPage from './pages/OnboardingCompanyPage';
import OnboardingCardPage from './pages/OnboardingCardPage';
import OnboardingDonePage from './pages/OnboardingDonePage';
import DashboardLayout from './pages/DashboardLayout';
// Analyses is the page on /dashboard/analytics. The two older takes
// (AnalyticsPage, AnalyticsPageV2) are kept on disk for rollback only —
// to revert, import one of them here instead.
// Legacy AnalyticsPage kept for rollback during the dark-redesign rollout.
// AnalyticsPageV2 is the new dark redesign that replaces it on the
// /dashboard/analytics route. To revert: swap the imports here.
// import AnalyticsPage from './pages/AnalyticsPage';
// import AnalyticsPage from './pages/AnalyticsPageV2';
import AnalysesPage from './pages/AnalysesPage';
import ScanPage from './pages/ScanPage';
import CampaignsPage from './pages/CampaignsPage';
import SettingsPage from './pages/SettingsPage';
import ParametresPage from './pages/ParametresPage';
import CataloguePage from './pages/CataloguePage';
import JoinPage from './pages/JoinPage';
import MyWalletCardPage from './pages/MyWalletCardPage';
import HistoryPage from './pages/HistoryPage';

import AdminDashboard from './pages/AdminDashboard';
import AdminAnalyticsPage from './pages/AdminAnalyticsPage';
import AdminTenantsPage from './pages/AdminTenantsPage';
import AdminPlansPage from './pages/AdminPlansPage';
import AdminCardDesignerPage from './pages/AdminCardDesignerPage';
import LoyaltyCardPage from './pages/LoyaltyCardPage';
import ComingSoonPage from './pages/ComingSoonPage';
import HelpPage from './pages/HelpPage';
import GeolocationPage from './pages/GeolocationPage';
import ReferralPage from './pages/ReferralPage';
import AutomationsPage from './pages/AutomationsPage';
import DashboardHomePage from './pages/DashboardHomePage';
import ClientsPage from './pages/ClientsPage';
import SegmentationPage from './pages/SegmentationPage';
// Insights — rebuilt to the approved design. The previous InsightsPage stays
// in the repo, unrouted, for rollback.
import InsightsGrowthPage from './pages/InsightsGrowthPage';
// FidClic IA Copilote — replaces the previous AI assistant, which stays in the
// repo, unrouted, for rollback.
import CopilotPage from './pages/CopilotPage';
// Campagnes — rebuilt to the approved design. CampaignsPage stays in the
// repo, unrouted, for rollback.
import CampagnesPage from './pages/CampagnesPage';
import AdminAIAssistantPage from './pages/AdminAIAssistantPage';
import AdminCampaignsPage from './pages/AdminCampaignsPage';
import AdminInsightsPage from './pages/AdminInsightsPage';
import GoogleTranslateBridge, { RouteAwareRetranslator } from './components/GoogleTranslateBridge';
// Facturation module (French e-invoicing) — post-login module chooser + home.
import ModuleChooserPage from './pages/ModuleChooserPage';
import FacturationHome from './pages/FacturationHome';
import CabinetDashboard from './pages/CabinetDashboard';
import CabinetTeam from './pages/CabinetTeam';
import CabinetCases from './pages/CabinetCases';
import CabinetReview from './pages/CabinetReview';
import CabinetPasswordGate from './components/CabinetPasswordGate';
import CabinetSignup from './pages/CabinetSignup';
import ResetPasswordPage from './pages/ResetPasswordPage';
// Public marketing pages — one per product line, so each audience gets a whole
// page instead of an anchor buried in the homepage.
import FacturationLanding from './pages/FacturationLanding';
import CabinetLanding from './pages/CabinetLanding';

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

// An owner who created their account but never completed the company step
// (onboarding_status="company") is parked on /onboarding/entreprise: no
// dashboard, no modules, until step 2 is done and the trial has started.
const needsOnboarding = (user) => user?.role === 'business_owner' && user?.onboarding_status === 'company';

const ProtectedRoute = ({ children, allowedRoles, skipOnboardingGate = false, partialOk = false }) => {
  const { user, loading } = useAuth();
  if (loading) return <div>Loading...</div>;
  if (!user) return <Navigate to="/login" replace />;
  if (!skipOnboardingGate && needsOnboarding(user)) return <Navigate to="/onboarding/entreprise" replace />;
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
    if (needsOnboarding(user)) return <Navigate to="/onboarding/entreprise" replace />;
    if (user.role === 'super_admin') return <Navigate to="/admin" replace />;
    // Owners land on the module chooser (CRM+Fidélité vs Facturation).
    // Handles already-logged-in sessions too (not just fresh logins).
    if (user.role === 'business_owner') return <Navigate to="/modules" replace />;
    if (user.role === 'comptable') return <Navigate to="/cabinet" replace />;
    return <Navigate to="/dashboard" replace />;
  }
  return children;
};

// app.fidclic.com is the product; the public site lives at www.fidclic.com
// (fidclic.fr redirects there too). A visitor who types the app address
// lands on that site rather than the app's older built-in LandingPage,
// which is kept (and still shown on localhost) but no longer served.
const MARKETING_URL = 'https://www.fidclic.com/';

const MarketingHome = () => {
  const local = /^(localhost|127\.0\.0\.1|\[::1\])$/.test(window.location.hostname);
  const standalone = (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches)
    || window.navigator.standalone === true;
  let card = null;
  try { card = localStorage.getItem('fidelitour:last_card'); } catch (e) { /* private mode */ }
  const leave = !local && !standalone;
  React.useEffect(() => { if (leave) window.location.replace(MARKETING_URL); }, [leave]);

  if (local) return <LandingPage />;
  // Installed icons can open "/" (iOS ignores start_url): send them back
  // into the app instead of out to the website.
  if (standalone) {
    if (card && /^FT-?[A-Z0-9]+$/i.test(card)) return <Navigate to={`/card/${card}`} replace />;
    return <Navigate to="/login" replace />;
  }
  return null;
};

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
        <Routes>
          <Route path="/" element={<PublicRoute><MarketingHome /></PublicRoute>} />
          <Route path="/login" element={<PublicRoute><LoginPage /></PublicRoute>} />
          <Route path="/register" element={<PublicRoute><RegisterPage /></PublicRoute>} />
          {/* Onboarding step 2 — the only protected page a half-registered owner may see. */}
          <Route path="/onboarding/entreprise" element={
            <ProtectedRoute allowedRoles={['business_owner']} skipOnboardingGate>
              <OnboardingCompanyPage />
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
          <Route path="/join/:slug" element={<JoinPage />} />
          {/* The French address the Paramètres page hands out; /join stays for every QR already printed. */}
          <Route path="/inscription/:slug" element={<JoinPage />} />
          <Route path="/card/:barcodeId" element={<MyWalletCardPage />} />

          {/* Public product pages. Deliberately NOT wrapped in PublicRoute: a
              logged-in owner or accountant must still be able to read about the
              other module (and share the link) without being bounced to their
              dashboard. */}
          <Route path="/facturation-electronique" element={<FacturationLanding />} />
          <Route path="/experts-comptables" element={<CabinetLanding />} />

          {/* Facturation module — post-login chooser (Option A) + home.
              Owner/manager only; loyalty-only tenants see the "activate" prompt. */}
          <Route path="/modules" element={
            <ProtectedRoute allowedRoles={['business_owner', 'manager']}>
              <ModuleChooserPage />
            </ProtectedRoute>
          } />
          <Route path="/facturation" element={
            <ProtectedRoute allowedRoles={['business_owner', 'manager']}>
              <FacturationHome />
            </ProtectedRoute>
          } />
          {/* Accountant (comptable) control tower over all their linked clients. */}
          <Route path="/reinitialiser" element={<ResetPasswordPage />} />
          <Route path="/cabinet/inscription" element={
            <PublicRoute><CabinetSignup /></PublicRoute>
          } />
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
              <ProtectedRoute allowedRoles={['business_owner', 'manager', 'staff']}>
                <ScanPage />
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
              <ProtectedRoute allowedRoles={['business_owner', 'manager']}>
                <AutomationsPage />
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
              <ProtectedRoute allowedRoles={['business_owner', 'manager', 'staff', 'super_admin']}>
                <HelpPage />
              </ProtectedRoute>
            } />
            <Route path="campaigns" element={
              <ProtectedRoute allowedRoles={['business_owner', 'administrateur', 'manager']} partialOk>
                <CampagnesPage />
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
            <Route path="parametres" element={<Navigate to="/dashboard/parametres/regles-clients" replace />} />
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
          <Route path="/admin" element={
            <ProtectedRoute allowedRoles={['super_admin']}>
              <DashboardLayout />
            </ProtectedRoute>
          }>
            <Route index element={<AdminDashboard />} />
            <Route path="analytics" element={<AdminAnalyticsPage />} />
            <Route path="insights" element={<AdminInsightsPage />} />
            <Route path="tenants" element={<AdminTenantsPage />} />
            <Route path="plans" element={<AdminPlansPage />} />
            <Route path="campaigns" element={<AdminCampaignsPage />} />
            <Route path="card-designer" element={<AdminCardDesignerPage />} />
            <Route path="ai" element={<AdminAIAssistantPage />} />
          </Route>
        </Routes>
       </Router>
      </BranchProvider>
    </AuthProvider>
    </RootErrorBoundary>
  );
}

export default App;
