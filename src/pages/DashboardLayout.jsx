import React from 'react';
import { Outlet, Link, useLocation, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import NotificationBell from '../components/NotificationBell';
import EstablishmentSwitcher from '../components/EstablishmentSwitcher';
import { markPageOpened } from '../lib/chartAnimation';
import BillingBanner from '../components/BillingBanner';
import LanguageSwitcher from '../components/LanguageSwitcher';
import { useAuth } from '../contexts/AuthContext';
import { ownerAPI } from '../lib/api';
import {
  Home, Users, QrCode, LogOut, BarChart3, Settings2, Palette,
  Database, BrainCircuit, Megaphone, MapPin, Sparkles, Sparkle, CreditCard, Shield, History,
  Building2, ChevronsLeft, ChevronsRight, LifeBuoy, PieChart, Share2, Zap, ShoppingBag
} from 'lucide-react';
import { C, themeForRole, AmbientBackdrop } from '../components/PageShell';

/* =====================================================================
   DashboardLayout — the shell used by every authenticated page.

   Role-aware: the sidebar's brand mark, active-nav glow, and role pill
   shift their gradient to match the role theme defined in PageShell, so
   admin / owner / staff each get a visually distinct identity while
   sharing the same layout chassis.
   ===================================================================== */

// Resolves whether a given nav row is "active" given the current path.
// /dashboard and /admin are exact-match (otherwise they'd swallow every
// child route); everything else uses startsWith so subpages stay lit.
const isNavActive = (currentPath, target) => {
  if (target === '/dashboard' || target === '/admin') return currentPath === target;
  return currentPath === target || currentPath.startsWith(target + '/');
};


const NavLink = ({ to, icon: Icon, label, currentPath, role, collapsed, badge, alsoActive = [] }) => {
  const active = isNavActive(currentPath, to) || alsoActive.some((p) => isNavActive(currentPath, p));
  const theme = themeForRole(role);
  return (
    <Link
      to={to}
      title={collapsed ? label : undefined}
      className={`flc-nav ${active ? 'on' : ''} relative group flex items-center ${collapsed ? 'justify-center px-2' : 'gap-2.5 px-2.5'} py-[7px] rounded-xl text-[13.5px] transition-all`}
      style={{ fontWeight: active ? 600 : 450 }}
    >
      <span
        className="w-8 h-8 shrink-0 rounded-lg flex items-center justify-center transition-colors"
        style={{ color: 'inherit' }}
      >
        <Icon className="w-[18px] h-[18px]" />
      </span>
      {!collapsed && (
        <>
          <span className="truncate flex-1">{label}</span>
          {badge && (
            <span
              className="text-[10px] px-2 py-0.5 rounded-full font-semibold shrink-0 bg-[#2F6BFF] text-white"
            >
              {badge}
            </span>
          )}
        </>
      )}
    </Link>
  );
};

// Same visual treatment as NavLink, but a button that triggers logout.
// Placed inline within each role's nav so it sits directly under Settings
// (or last nav item for roles without Settings).
const SignOutNavItem = ({ onClick, collapsed }) => {
  const { t } = useTranslation();
  return (
    <button
      type="button"
      onClick={onClick}
      title={collapsed ? t('nav.sign_out') : undefined}
      className={`relative group flex items-center ${collapsed ? 'justify-center px-2' : 'gap-2.5 px-2.5'} py-[7px] rounded-lg text-[13.5px] transition-all w-full text-left`}
      style={{ color: 'var(--ink-mute)', background: 'transparent', fontWeight: 400 }}
      onMouseOver={(e) => {
        e.currentTarget.style.background = 'color-mix(in srgb, var(--flc-accent, #C73E2C) 10%, transparent)';
        e.currentTarget.style.color = 'var(--flc-accent-deep, #8A322B)';
      }}
      onMouseOut={(e) => {
        e.currentTarget.style.background = 'transparent';
        e.currentTarget.style.color = 'var(--ink-mute)';
      }}
    >
      <span
        className="w-8 h-8 shrink-0 rounded-lg flex items-center justify-center transition-colors"
        style={{ color: 'inherit', border: '1px solid transparent' }}
      >
        <LogOut className="w-[18px] h-[18px]" />
      </span>
      {!collapsed && <span className="truncate">{t('nav.sign_out')}</span>}
    </button>
  );
};

/* ────────────────────────────────────────────────────────────────────────
 * UserMenu — clickable avatar in the top toolbar.
 *
 * What's inside:
 *   • Big circle with the user's initial — gradient matches the role theme.
 *   • Small dot at the bottom-right ("you're logged in" indicator — purely
 *     visual cue, lifted from the reference mockup).
 *   • Click → opens a dropdown panel showing the full email, the role label,
 *     a link into Settings, and a Sign-out button.
 *
 * Why this exists separately from the sidebar's Sign-out item: the avatar
 * is the universal "account menu" affordance every SaaS dashboard uses.
 * The patron expects to click their picture to get out — without it, the
 * status dot was decorative noise that the user noticed and asked about.
 * ──────────────────────────────────────────────────────────────────── */
function UserMenu({ user, theme, role, onLogout }) {
  const { t } = useTranslation();
  const [open, setOpen] = React.useState(false);
  const ref = React.useRef(null);

  // Close when clicking outside the menu — standard popover hygiene.
  React.useEffect(() => {
    if (!open) return;
    const onDocClick = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  }, [open]);

  const initial = (user?.email || '?').charAt(0).toUpperCase();
  const roleLabel =
    role === 'business_owner' ? t('nav.business_owner') :
    role === 'manager' ? t('nav.manager') :
    role === 'staff' ? t('nav.staff') :
    role === 'super_admin' ? t('nav.admin') : t('nav.user');

  return (
    <div className="relative shrink-0" ref={ref}>
      <button
        type="button"
        aria-label={t('nav.account_menu')}
        onClick={() => setOpen((v) => !v)}
        className="relative w-9 h-9 rounded-full flex items-center justify-center text-white hover:opacity-90 transition-opacity"
        style={{
          background: `linear-gradient(135deg, ${theme.from} 0%, ${theme.to} 100%)`,
          fontWeight: 500,
          fontSize: 13,
          letterSpacing: '0.02em',
        }}
      >
        {initial}
        <span
          aria-hidden="true"
          className="absolute bottom-0 right-0 w-2.5 h-2.5 rounded-full"
          style={{ background: 'var(--tone-success-line, #7FA269)', boxShadow: '0 0 0 2px var(--flc-card, #FFFFFF)' }}
        />
      </button>

      {open && (
        <div
          className="absolute right-0 top-full mt-2 w-64 rounded-xl overflow-hidden z-50"
          style={{
            background: 'var(--flc-card, #FFFFFF)',
            border: '1px solid var(--hairline, #EFEDE9)',
            boxShadow: '0 12px 28px rgba(0,0,0,0.10), 0 4px 8px rgba(0,0,0,0.04)',
          }}
        >
          <div className="px-4 py-3" style={{ borderBottom: '1px solid var(--hairline, #EFEDE9)' }}>
            <div className="flex items-center gap-2.5">
              <div
                className="w-9 h-9 rounded-full flex items-center justify-center text-white shrink-0"
                style={{
                  background: `linear-gradient(135deg, ${theme.from} 0%, ${theme.to} 100%)`,
                  fontWeight: 500, fontSize: 13,
                }}
              >
                {initial}
              </div>
              <div className="min-w-0">
                <p className="text-[13px] truncate" style={{ color: 'var(--ink)', fontWeight: 500 }}>
                  {user?.email || '—'}
                </p>
                <p className="text-[11px]" style={{ color: 'var(--ink-mute)' }}>
                  {roleLabel}
                </p>
              </div>
            </div>
          </div>
          <Link
            to="/dashboard/parametres"
            onClick={() => setOpen(false)}
            className="flex items-center gap-2 px-4 py-2.5 text-[13px] hover:bg-[#FAFAF8] transition-colors"
            style={{ color: 'var(--ink)' }}
          >
            <Settings2 size={14} style={{ color: 'var(--ink-mute)' }} />
            {t('nav.settings')}
          </Link>
          <button
            type="button"
            onClick={() => { setOpen(false); onLogout(); }}
            className="w-full text-left flex items-center gap-2 px-4 py-2.5 text-[13px] hover:bg-[#FAEDEB] transition-colors"
            style={{ color: 'var(--flc-accent-deep, #8A322B)', borderTop: '1px solid var(--hairline, #EFEDE9)' }}
          >
            <LogOut size={14} />
            {t('nav.sign_out')}
          </button>
        </div>
      )}
    </div>
  );
}

const DashboardLayout = () => {
  // Fidelity dual theme: Eclat (light) / Minuit Dore (dark). The class on the
  // layout root drives every CSS var; PageShell tokens read those vars, so
  // inline styles flip too.
  // Dark mode shipped with P3/P4: every dashboard page passed the
  // dual-theme probe (no bright surfaces left under .flc-nuit).
  // The day/night switch lived in the top bar and went with it when the bar was
  // rebuilt to the approved design. Rather than leave anyone who had chosen
  // dark with no way back out, the stored preference is ignored and the light
  // skin — the one the design is drawn in — is the only one served. The state
  // stays so a switch can be put back wherever it belongs, in one line.
  const nuit = false;

  const { user, logout } = useAuth();
  const { t } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
  // Global search — smart routing.
  //
  // The owner expects: "card" → Card Designer, "settings" → Settings,
  // "campaign" → Campaigns, etc. If the query matches a known
  // section/page synonym, we navigate directly there. Otherwise we treat
  // it as a customer search (barcode FT-XXXX → exact, anything else →
  // free-text q=).
  const [searchQ, setSearchQ] = React.useState('');

  // Keyword → route mapping. Each route lists the words (FR + EN) that
  // should land the user on that page. Match is case-insensitive and
  // word-boundary aware (so "carte cadeau" still routes to Card Designer
  // via "carte"). Order doesn't matter — we pick the first key whose
  // keyword list matches.
  const ROUTE_SYNONYMS = React.useMemo(() => ([
    { route: '/dashboard',                              words: ['dashboard', 'tableau de bord', 'tableau', 'accueil', 'home', 'overview', 'vue d’ensemble', 'welcome'] },
    { route: '/dashboard/analytics',                    words: ['analytics', 'analyses', 'analyse', 'kpi', 'kpis', 'stats', 'statistiques', 'rapport', 'reports', 'metrics', 'metric', 'métriques'] },
    { route: '/dashboard/parametres/regles-clients',     words: ['customer status', 'statut client', 'segment', 'segments', 'statuts'] },
    { route: '/dashboard/catalogue',                    words: ['catalogue', 'catalog', 'produits', 'produit', 'products', 'menu', 'carte des produits', 'prix'] },
    { route: '/dashboard/insights',                     words: ['insights', 'insight', 'reco', 'recommendations', 'recommandations', 'suggestion', 'suggestions', 'ai', 'ia'] },
    { route: '/dashboard/map',                          words: ['map', 'carte (geo)', 'geographie', 'geography', 'géographie', 'localisation', 'lieux'] },
    { route: '/dashboard/card-designer',                words: ['card designer', 'card', 'carte', 'carte de fidélité', 'loyalty card', 'design', 'pass', 'wallet', 'walletpass'] },
    { route: '/dashboard/campaigns',                    words: ['campaigns', 'campaign', 'campagnes', 'campagne', 'sms', 'push', 'message', 'messages', 'notif', 'notifications'] },
    { route: '/dashboard/ai-assistant',                 words: ['fidclic ia', 'fidclic ai', 'copilote', 'copilot', 'ai assistant', 'assistant', 'chatbot', 'chat', 'assistant ia'] },
    { route: '/dashboard/history',                      words: ['history', 'historique', 'logs', 'journal', 'activity log', 'audit'] },
    { route: '/dashboard/scan',                         words: ['scan', 'scanner', 'qr', 'qr code', 'visit', 'visite', 'check-in', 'checkin'] },
    { route: '/dashboard/customers',                    words: ['customers', 'clients', 'customer', 'client', 'liste clients'] },
    { route: '/dashboard/parametres',                   words: ['settings', 'parametres', 'paramètres', 'reglages', 'réglages', 'config', 'configuration', 'preferences', 'préférences', 'compte', 'account', 'profile', 'profil', 'billing', 'facturation', 'plan', 'equipe', 'équipe', 'team', 'staff', 'utilisateurs', 'users'] },
  ]), []);

  const submitSearch = (e) => {
    e?.preventDefault?.();
    const raw = (searchQ || '').trim();
    if (!raw) {
      navigate('/dashboard/customers');
      return;
    }

    // 1) Barcode lookup — direct hit on the customer.
    const isBarcode = /^FT-?[A-Z0-9]{4,}/i.test(raw);
    if (isBarcode) {
      navigate(`/dashboard/customers?barcode_id=${encodeURIComponent(raw)}`);
      return;
    }

    // 2) Page/section synonyms — route to the matching page.
    const q = raw.toLowerCase();
    for (const entry of ROUTE_SYNONYMS) {
      for (const w of entry.words) {
        const wl = w.toLowerCase();
        // Exact match OR query starts/ends/contains the keyword as a token.
        const re = new RegExp(`(^|[^a-zà-ÿ])${wl.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}([^a-zà-ÿ]|$)`, 'i');
        if (q === wl || re.test(q)) {
          navigate(entry.route);
          return;
        }
      }
    }

    // 3) Fallback — free-text customer search.
    navigate(`/dashboard/customers?q=${encodeURIComponent(raw)}`);
  };
  const currentPath = location.pathname;
  // Charts on the page that is opening may play their entrance animation;
  // after that a resize (or a full-page screenshot) draws them finished.
  // Marked during render, before the page's charts render.
  const markedPath = React.useRef(null);
  if (markedPath.current !== currentPath) {
    markedPath.current = currentPath;
    markPageOpened();
  }
  const role = user?.role || 'default';
  const theme = themeForRole(role);

  // Collapsed-sidebar toggle (persisted across reloads). When true the
  // aside shrinks to a 72px icons-only rail; click again to expand.
  // Key is versioned (-v2) so a previous accidentally-collapsed state
  // doesn't override the default expanded view on the next deploy.
  const [collapsed, setCollapsed] = React.useState(() => {
    if (typeof window === 'undefined') return false;
    try { return window.localStorage.getItem('fdt:sidebar:collapsed-v2') === '1'; }
    catch { return false; }
  });
  React.useEffect(() => {
    try { window.localStorage.setItem('fdt:sidebar:collapsed-v2', collapsed ? '1' : '0'); }
    catch { /* localStorage may be blocked — fine */ }
  }, [collapsed]);

  // Fetch tenant identity once — shown in the sidebar so the user always
  // knows which business account they're acting as. Prevents the "wait,
  // why isn't this scan working" tenant-mismatch confusion.
  const [tenantInfo, setTenantInfo] = React.useState(null);
  React.useEffect(() => {
    // A platform admin has no shop of their own — the call would only 403.
    if (!user || user.role === 'super_admin') return undefined;
    let alive = true;
    ownerAPI.getTenant?.()
      .then((r) => { if (alive) setTenantInfo(r.data || null); })
      .catch(() => { /* silent — keep header generic */ });
    return () => { alive = false; };
  }, [user?.email]);

  // Analytics moved to the unified light theme (av2-light-skin) — same
  // palette as the rest of the dashboard so navigating Analytics ↔
  // Customers ↔ Campaigns no longer flips colour modes. Keeping the
  // variable as `false` so a future per-route theme toggle has a single
  // place to wire in without re-introducing the dead branches.
  const isAnalyticsDark = false;

  return (
    <div
      className={`relative flex min-h-screen fdt-dash flc ${nuit ? "flc-nuit" : ""}`}
      style={{ transition: 'background 200ms ease' }}
    >
      <AmbientBackdrop role={role} />

      <aside
        className={`sticky top-0 z-10 ${collapsed ? 'w-[72px]' : 'w-64'} h-screen flex flex-col shrink-0 transition-[width,background-color] duration-200 ease-out fd-aside fd-sidebar-host`}
        style={{
          background: 'color-mix(in srgb, var(--flc-card, #FFFFFF) 78%, transparent)',
          backdropFilter: 'blur(14px)',
          borderRight: `1px solid ${C.hairline}`,
          alignSelf: 'flex-start',
        }}
      >
        {/* Collapse toggle — pinned to the right edge, same button in both
            states. The arrow points the way it will move the rail, so the
            collapsed rail has a visible way back out; a single hamburger in
            both states never said which. */}
        <button
          type="button"
          onClick={() => setCollapsed((v) => !v)}
          aria-label={collapsed ? t('nav.expand_sidebar') : t('nav.collapse_sidebar')}
          aria-expanded={!collapsed}
          title={collapsed ? t('nav.expand_sidebar') : t('nav.collapse_sidebar')}
          className="absolute -right-3 top-6 z-20 w-7 h-7 rounded-full flex items-center justify-center transition-all hover:scale-110"
          style={{
            // White in both states — a black puck on a white rail read as a
            // different control depending on which way the arrow pointed.
            background: '#FFFFFF',
            border: '1px solid #E6EEFB',
            boxShadow: '0 2px 8px rgba(11,28,63,0.12)',
            color: '#334155',
          }}
        >
          {collapsed ? <ChevronsRight size={15} strokeWidth={2.25} />
                    : <ChevronsLeft size={15} strokeWidth={2.25} />}
        </button>

        {/* Brand mark, then the shop whose figures are on screen. The account
            badge that used to sit here became the establishment switcher — one
            place to say which shop you are looking at. */}
        <div className={collapsed ? 'px-3 pt-3 pb-1' : 'px-4 pt-4 pb-1'}>
          <Link to="/" className={`flex items-center ${collapsed ? 'justify-center' : 'gap-2.5'}`}>
            <div
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-[16px] font-bold text-white"
              style={{ background: '#2F6BFF', boxShadow: '0 8px 18px -10px rgba(47,107,255,.9)' }}
              title={collapsed ? 'FidClic' : undefined}
            >
              F
            </div>
            {!collapsed && (
              <span className="text-[19px] font-bold leading-none tracking-[-0.02em]" style={{ color: '#0B1C3F' }}>
                FidClic
              </span>
            )}
          </Link>
        </div>
        {role !== 'super_admin' && <EstablishmentSwitcher tenant={tenantInfo} collapsed={collapsed} />}

        <div className="px-4">
          <div className="h-px" style={{ background: C.hairline }} />
        </div>

        <nav className={`flex-1 ${collapsed ? 'px-2' : 'px-3'} py-2 space-y-[1px] overflow-y-auto`}>
          {role === 'business_owner' && (
            <>
              {/* Order follows the approved sidebar mockup. Every row points at
                  a page that exists. */}
              <NavLink to="/dashboard"               icon={Home}         label={t('nav.dashboard')}        currentPath={currentPath} role={role} collapsed={collapsed} />
              <NavLink to="/dashboard/analytics"     icon={BarChart3}    label={t('nav.analytics')}        currentPath={currentPath} role={role} collapsed={collapsed} />
              <NavLink to="/dashboard/customers"     icon={Users}        label={t('nav.customers')}        currentPath={currentPath} role={role} collapsed={collapsed} />
              <NavLink to="/dashboard/campaigns"     icon={Megaphone}    label={t('nav.campaigns')}     currentPath={currentPath} role={role} collapsed={collapsed} />
              <NavLink to="/dashboard/card"          icon={CreditCard}   label={t('nav.loyalty_card')}  currentPath={currentPath} role={role} collapsed={collapsed} />
              <NavLink to="/dashboard/automations"   icon={Zap}          label={t('nav.automations')} currentPath={currentPath} role={role} collapsed={collapsed} />
              <NavLink to="/dashboard/segmentation"  icon={PieChart}     label={t('nav.segmentation')}  currentPath={currentPath} role={role} collapsed={collapsed} />
              <NavLink to="/dashboard/referral"      icon={Share2}       label={t('nav.referral')}      currentPath={currentPath} role={role} collapsed={collapsed} />
              <NavLink to="/dashboard/map"           icon={MapPin}       label={t('nav.geolocation')}   currentPath={currentPath} role={role} collapsed={collapsed} />
              <NavLink to="/dashboard/catalogue"     icon={ShoppingBag}  label={t('nav.catalogue')}     currentPath={currentPath} role={role} collapsed={collapsed} />
              <NavLink to="/dashboard/insights"      icon={Sparkles}     label={t('nav.insights')}         currentPath={currentPath} role={role} collapsed={collapsed} />
              <NavLink to="/dashboard/ai-assistant"  icon={Sparkle} label={t('nav.ai_assistant')}  currentPath={currentPath} role={role} collapsed={collapsed} badge="Nouveau" />
              <NavLink to="/dashboard/history"       icon={History}      label={t('nav.history')}       currentPath={currentPath} role={role} collapsed={collapsed} />
              {/* Paramètres is one page with tabs, like Analyses. The older
                  all-in-one settings page stays reachable from its tabs. */}
              <NavLink to="/dashboard/parametres" icon={Settings2} label={t('nav.settings')} currentPath={currentPath} role={role} collapsed={collapsed} alsoActive={['/dashboard/settings']} />
              <SignOutNavItem onClick={logout} collapsed={collapsed} />
            </>
          )}
          {role === 'manager' && (
            <>
              <NavLink to="/dashboard/analytics" icon={BarChart3} label={t('nav.analytics')}    currentPath={currentPath} role={role} collapsed={collapsed} />
              <NavLink to="/dashboard/insights"  icon={Sparkles}  label={t('nav.insights')}     currentPath={currentPath} role={role} collapsed={collapsed} />
              <NavLink to="/dashboard/customers" icon={Users}     label={t('nav.customers')}    currentPath={currentPath} role={role} collapsed={collapsed} />
              <NavLink to="/dashboard/map"       icon={MapPin}    label={t('nav.geolocation')} currentPath={currentPath} role={role} collapsed={collapsed} />
              <NavLink to="/dashboard/history"   icon={History}   label={t('nav.history')}      currentPath={currentPath} role={role} collapsed={collapsed} />
              <SignOutNavItem onClick={logout} collapsed={collapsed} />
            </>
          )}
          {role === 'staff' && (
            <>
              <NavLink to="/dashboard/scan" icon={QrCode} label={t('nav.scan_visit')} currentPath={currentPath} role={role} collapsed={collapsed} />
              <SignOutNavItem onClick={logout} collapsed={collapsed} />
            </>
          )}
          {role === 'super_admin' && (
            <>
              <NavLink to="/admin"               icon={Home}         label="Dashboard"          currentPath={currentPath} role={role} collapsed={collapsed} />
              <NavLink to="/admin/analytics"     icon={BarChart3}    label="Global Analytics"   currentPath={currentPath} role={role} collapsed={collapsed} />
              <NavLink to="/admin/insights"      icon={Sparkles}     label="Insights"           currentPath={currentPath} role={role} collapsed={collapsed} />
              <NavLink to="/admin/tenants"       icon={Database}     label="Manage Businesses"  currentPath={currentPath} role={role} collapsed={collapsed} />
              <NavLink to="/admin/plans"         icon={Shield}       label="Plan Limits"        currentPath={currentPath} role={role} collapsed={collapsed} />
              <NavLink to="/admin/card-designer" icon={Palette}      label="Card Designer"      currentPath={currentPath} role={role} collapsed={collapsed} />
              <NavLink to="/admin/campaigns"     icon={Megaphone}    label="Campaigns"          currentPath={currentPath} role={role} collapsed={collapsed} />
              <NavLink to="/admin/ai"            icon={BrainCircuit} label="AI Intelligence"    currentPath={currentPath} role={role} collapsed={collapsed} />
              <SignOutNavItem onClick={logout} collapsed={collapsed} />
            </>
          )}
        </nav>

        {/* Help — one row at the foot of the rail, in both states. The help
            icon that used to sit in the top bar went with the bar, so this is
            the single way in and it has to survive the collapsed rail. */}
        <div className={`mt-auto ${collapsed ? 'flex justify-center px-2 pb-3' : 'px-3 pb-3'}`}>
          <button
            type="button"
            onClick={() => navigate('/dashboard/aide')}
            title={collapsed ? t('nav.help') : undefined}
            aria-label={t('nav.help')}
            className={collapsed
              ? 'flex h-9 w-9 items-center justify-center rounded-xl transition-colors'
              : 'flex w-full items-center gap-2.5 rounded-xl px-3 py-2.5 text-left transition-colors'}
            style={{ background: '#EAF1FF', color: '#2F6BFF' }}
          >
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full"
                  style={{ background: collapsed ? 'transparent' : '#2F6BFF', color: collapsed ? '#2F6BFF' : '#fff' }}>
              <LifeBuoy size={collapsed ? 17 : 13} />
            </span>
            {!collapsed && (
              <>
                <span className="min-w-0 flex-1 truncate text-[13px] font-semibold" style={{ color: '#1D4ED8' }}>
                  {t('nav.help')}
                </span>
              </>
            )}
          </button>
        </div>

      </aside>

      <main className="relative z-10 flex-1 overflow-auto">
        {/* Global billing health banner — only renders if there's something to
            warn about (past-due, canceled, trial ending soon). Otherwise
            invisible and out of the way. */}
        {role === 'business_owner' && <BillingBanner />}

        {/* Premium top toolbar — search + bell + avatar.
            Sits as a sticky bar across every dashboard page (matches the
            reference mockup with the search bar centered and the bell +
            user avatar pinned right). On non-owner roles we keep the bell
            slot hidden so staff don't see owner-only alerts. */}
        {role === 'business_owner' && (
          <div
            className="sticky top-0 z-30 relative flex items-center justify-center px-6 lg:px-8 py-2.5 backdrop-blur"
            style={{
              background: 'color-mix(in srgb, var(--flc-card, #FFFFFF) 82%, transparent)',
              borderBottom: '1px solid var(--hairline, #EFEDE9)',
            }}
          >
            {/* Global search — Enter routes to /dashboard/customers with
                the query. Barcode-style inputs (FT-XXXX) hit the customer
                page filter by barcode_id; everything else hits the free
                text search. */}
            <form
              onSubmit={submitSearch}
              className="flex items-center gap-2 rounded-full px-3.5 py-2 shrink-0 w-[260px] lg:w-[420px] xl:w-[520px]"
              style={{ background: 'var(--flc-card, #FFFFFF)', border: '1px solid var(--hairline, #EFEDE9)' }}
            >
              <button type="submit" aria-label={t('common.search')} className="shrink-0" style={{ lineHeight: 0 }}>
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ color: 'var(--ink-mute, #8D857D)' }}>
                  <circle cx="11" cy="11" r="7" />
                  <path d="M21 21l-4.3-4.3" />
                </svg>
              </button>
              <input
                type="text"
                value={searchQ}
                onChange={(e) => setSearchQ(e.target.value)}
                placeholder={t('nav.search_placeholder')}
                aria-label={t('common.search')}
                className="flex-1 min-w-0 bg-transparent outline-none text-[13px]"
                style={{ color: 'var(--ink, #171412)', fontWeight: 400 }}
              />
              {searchQ && (
                <button
                  type="button"
                  onClick={() => setSearchQ('')}
                  aria-label={t('nav.search_clear')}
                  className="shrink-0 text-[10px] px-1 py-0.5 rounded hover:bg-[#F5F4F1]"
                  style={{ color: 'var(--ink-mute, #8D857D)' }}
                >✕</button>
              )}
              <kbd
                className="text-[9.5px] px-1 py-0.5 rounded shrink-0"
                style={{
                  background: 'var(--flc-paper2, #F5F4F1)',
                  color: 'var(--ink-mute, #8D857D)',
                  border: '1px solid var(--hairline, #EFEDE9)',
                  fontWeight: 500,
                }}
                title={t('nav.search_enter_hint')}
              >
                ⌘ K
              </kbd>
            </form>

            {/* The bar carries the search, the bell and the account — nothing
                else. The branch pills moved into the sidebar's establishment
                switcher, where picking a shop belongs; help has its own row at
                the foot of the sidebar. */}
            <div className="absolute right-6 lg:right-8 flex items-center gap-3">
              <NotificationBell platformAdmin={role === 'super_admin'} />

              {/* User menu avatar */}
              <UserMenu user={user} theme={theme} role={role} onLogout={logout} />
            </div>
          </div>
        )}

        <div className="px-6 py-5 lg:px-8 lg:py-5 max-w-[1600px] mx-auto">
          <Outlet />
        </div>
      </main>
    </div>
  );
};

export default DashboardLayout;
