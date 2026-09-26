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
import OwnerDashboard from './pages/OwnerDashboard';
// Analyses is the page on /dashboard/analytics. The two older takes
// (AnalyticsPage, AnalyticsPageV2) are kept on disk for rollback only —
// to revert, import one of them here instead.
// import AnalyticsPage from './pages/AnalyticsPage';
// import AnalyticsPage from './pages/AnalyticsPageV2';
import AnalysesPage from './pages/AnalysesPage';
import CustomersPage from './pages/CustomersPage';
import ScanPage from './pages/ScanPage';
import CampaignsPage from './pages/CampaignsPage';
import AIAssistantPage from './pages/AIAssistantPage';
import SettingsPage from './pages/SettingsPage';
import JoinPage from './pages/JoinPage';
import MyWalletCardPage from './pages/MyWalletCardPage';
import InsightsPage from './pages/InsightsPage';
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

const ProtectedRoute = ({ children, allowedRoles, skipOnboardingGate = false }) => {
  const { user, loading } = useAuth();
  if (loading) return <div>Loading...</div>;
  if (!user) return <Navigate to="/login" replace />;
  if (!skipOnboardingGate && needsOnboarding(user)) return <Navigate to="/onboarding/entreprise" replace />;
  if (allowedRoles && !allowedRoles.includes(user.role)) {
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
          <Route path="/" element={<PublicRoute><LandingPage /></PublicRoute>} />
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
            <ProtectedRoute allowedRoles={['business_owner', 'manager', 'staff']}>
              <DashboardLayout />
            </ProtectedRoute>
          }>
            <Route index element={
              <ProtectedRoute allowedRoles={['business_owner', 'manager']}>
                <OwnerDashboard />
              </ProtectedRoute>
            } />
            <Route path="analytics" element={
              <ProtectedRoute allowedRoles={['business_owner', 'manager']}>
                <AnalysesPage />
              </ProtectedRoute>
            } />
            <Route path="insights" element={
              <ProtectedRoute allowedRoles={['business_owner', 'manager']}>
                <InsightsPage />
              </ProtectedRoute>
            } />
            <Route path="customers" element={
              <ProtectedRoute allowedRoles={['business_owner', 'manager']}>
                <CustomersPage />
              </ProtectedRoute>
            } />
            {/* Géolocalisation clients — catchment rings + travel-time bands.
                Replaces CustomerMapPage, whose France-wide dot map this page
                supersedes; the old file stays in the repo, unrouted. */}
            <Route path="map" element={
              <ProtectedRoute allowedRoles={['business_owner', 'manager']}>
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
              <ProtectedRoute allowedRoles={['business_owner', 'manager']}>
                <ComingSoonPage title="Segmentation"
                  description="Regroupez vos clients par comportement — fréquence, panier, ancienneté — et ciblez chaque groupe." />
              </ProtectedRoute>
            } />
            <Route path="automations" element={
              <ProtectedRoute allowedRoles={['business_owner', 'manager']}>
                <AutomationsPage />
              </ProtectedRoute>
            } />
            <Route path="referral" element={
              <ProtectedRoute allowedRoles={['business_owner', 'manager']}>
                <ReferralPage />
              </ProtectedRoute>
            } />
            <Route path="card" element={
              <ProtectedRoute allowedRoles={['business_owner', 'manager']}>
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
              <ProtectedRoute allowedRoles={['business_owner']}>
                <CampaignsPage />
              </ProtectedRoute>
            } />
            <Route path="ai-assistant" element={
              <ProtectedRoute allowedRoles={['business_owner']}>
                <AIAssistantPage />
              </ProtectedRoute>
            } />
            <Route path="settings" element={
              <ProtectedRoute allowedRoles={['business_owner']}>
                <SettingsPage />
              </ProtectedRoute>
            } />
            <Route path="history" element={
              <ProtectedRoute allowedRoles={['business_owner', 'manager']}>
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
