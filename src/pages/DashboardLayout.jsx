import React from 'react';
import NoPageAccess from '../components/NoPageAccess';
import { pageOfPath } from '../lib/pagePerms';
import { flat, highlightWhenReady } from '../lib/searchHighlight';
import { Outlet, Link, useLocation, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import NotificationBell from '../components/NotificationBell';
import EstablishmentSwitcher from '../components/EstablishmentSwitcher';
import StoreGate from '../components/StoreGate';
import BottomNav from '../components/BottomNav';
import { markPageOpened } from '../lib/chartAnimation';
import { useBranch } from '../contexts/BranchContext';
import BillingBanner from '../components/BillingBanner';
import { PlanAccessContext, usePlanAccess, usePlanAccessState, UpgradeModal, LockedSection, LimitBanner, openUpgrade } from '../components/PlanAccess';
import LanguageSwitcher from '../components/LanguageSwitcher';
import { useAuth } from '../contexts/AuthContext';
import { ownerAPI, supportAPI } from '../lib/api';
import {
  Home, Users, QrCode, LogOut, BarChart3, Settings2,
  Database, BrainCircuit, Megaphone, MapPin, Sparkles, Sparkle, CreditCard, Shield, History,
  Building2, ChevronsLeft, ChevronsRight, LifeBuoy, Headphones, PieChart, Share2, Zap, ShoppingBag,
  UserRound, UsersRound, Kanban, ListChecks, CalendarDays, Mail, MailOpen, Phone, ChevronDown, ClipboardCheck,
  Receipt, Eye, ShieldCheck, Lock, Menu, Link2, X as XIcon,
} from 'lucide-react';
import { can, isTeam, moduleOfPath } from '../lib/perms';
import { C, themeForRole } from '../components/PageShell';
import { protectNames } from '../lib/translator';
import { drainWallet, kickWallet } from '../lib/walletRefresh';

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
// The logo's two colours (public/brand/fidclic-logo.png).
const BRAND_BLUE = '#1450B8';
const BRAND_YELLOW = '#F8B008';

const isNavActive = (currentPath, target) => {
  if (target === '/dashboard' || target === '/admin') return currentPath === target;
  return currentPath === target || currentPath.startsWith(target + '/');
};


const NavLink = ({ to, icon: Icon, label, currentPath, role, collapsed, badge, alsoActive = [], denied = false }) => {
  const active = isNavActive(currentPath, to) || alsoActive.some((p) => isNavActive(currentPath, p));
  const theme = themeForRole(role);
  // Super admin › Plan Limits: a section the plan does not include.
  const lock = usePlanAccess()?.lockOf?.(to);
  return (
    <Link
      to={to}
      onClick={lock ? (e) => { e.preventDefault(); openUpgrade(lock); } : undefined}
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
          {(lock || denied) && <Lock className="h-3.5 w-3.5 shrink-0 opacity-60" aria-label={denied && !lock ? 'Accès non autorisé' : 'Offre supérieure'} />}
          {badge && !lock && (
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

/* CRM de prospection — a group that opens on its own on any /admin/crm page. */
// one row per page (features/role_perms.PAGES); Paramètres opens on the tab the account may see
const PERM_NAV = [
  { keys: ['dashboard'], to: '/dashboard', icon: Home, label: 'Tableau de bord' },
  { keys: ['scan'], to: '/dashboard/scan', icon: QrCode, label: 'Enregistrer une visite' },
  { keys: ['analytics'], to: '/dashboard/analytics', icon: BarChart3, label: 'Analyses' },
  { keys: ['customers'], to: '/dashboard/customers', icon: Users, label: 'Clients' },
  { keys: ['campaigns'], to: '/dashboard/campaigns', icon: Megaphone, label: 'Campagnes' },
  { keys: ['card'], to: '/dashboard/card', icon: CreditCard, label: 'Carte de fidélité' },
  { keys: ['automations'], to: '/dashboard/automations', icon: Zap, label: 'Automatisations' },
  { keys: ['segmentation'], to: '/dashboard/segmentation', icon: PieChart, label: 'Segmentation' },
  { keys: ['referral'], to: '/dashboard/referral', icon: Share2, label: 'Parrainage' },
  { keys: ['geolocation'], to: '/dashboard/map', icon: MapPin, label: 'Géolocalisation' },
  { keys: ['catalogue'], to: '/dashboard/catalogue', icon: ShoppingBag, label: 'Catalogue produits' },
  { keys: ['insights'], to: '/dashboard/insights', icon: Sparkles, label: 'Insights' },
  { keys: ['ai'], to: '/dashboard/ai-assistant', icon: Sparkle, label: 'FidClic IA' },
  { keys: ['history'], to: '/dashboard/history', icon: History, label: 'Historique' },
  // Paramètres: open as soon as one of its tabs is (each tab checks its own)
  // never locked: its Préférences and Sécurité tabs are the account's own
  { keys: ['settings', 'billing', 'team', 'milestones', 'employee_links'], to: '/dashboard/parametres', icon: Settings2, label: 'Paramètres', also: ['/dashboard/settings'], open: true },
  { keys: ['team'], to: '/dashboard/parametres/equipe', icon: Users, label: 'Équipe & accès', shortcut: true, unless: 'settings' },
  // « Mon lien d'inscription » — only for an account that has the permission
  // without Paramètres, which already leads there (2026-10-16).
  { keys: ['employee_links'], to: '/dashboard/parametres/lien-inscription', icon: Link2,
    label: "Mon lien d'inscription", shortcut: true, unless: 'settings' },
];

const CRM_ITEMS = [
  ['/admin/crm', 'Vue d\'ensemble', UserRound], ['/admin/crm/prospects', 'Prospects', Users], ['/admin/crm/pipeline', 'Pipeline', Kanban],
  ['/admin/crm/taches', 'Tâches', ListChecks], ['/admin/crm/calendrier', 'Calendrier', CalendarDays], ['/admin/crm/sequences', 'Séquences d\'emails', Mail],
  ['/admin/crm/modeles', 'Modèles d\'emails', MailOpen], ['/admin/crm/appels', 'Appels', Phone],
];
const CrmNav = ({ currentPath, role, collapsed }) => {
  const inCrm = currentPath.startsWith('/admin/crm');
  const [open, setOpen] = React.useState(inCrm);
  React.useEffect(() => { if (inCrm) setOpen(true); }, [inCrm]);
  if (collapsed) return <NavLink to="/admin/crm" icon={UsersRound} label="CRM de prospection" currentPath={currentPath} role={role} collapsed={collapsed} alsoActive={CRM_ITEMS.map(([to]) => to)} />;
  return (
    <div>
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open}
              className={`flex w-full items-center gap-2.5 rounded-xl px-2.5 py-[7px] text-[13.5px] transition-all ${inCrm ? 'bg-[#2F6BFF] font-semibold text-white' : 'text-[#0B1C3F] hover:bg-[#F4F7FC]'}`}>
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg"><UsersRound className="h-[18px] w-[18px]" /></span>
        <span className="flex-1 truncate text-left">CRM de prospection</span>
        <ChevronDown size={15} className={`transition ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div className="mt-1 space-y-[1px] rounded-xl bg-[#F4F8FF] py-1">
          {CRM_ITEMS.map(([to, label, Icon]) => {
            const on = to === '/admin/crm' ? currentPath === '/admin/crm' : currentPath.startsWith(to);
            return (
              <Link key={to} to={to} className={`flex items-center gap-2.5 rounded-lg px-4 py-[6px] text-[13px] ${on ? 'bg-[#E3EDFF] font-semibold text-[#2F6BFF]' : 'text-[#475569] hover:text-[#2F6BFF]'}`}>
                <Icon size={15} className="shrink-0" /> <span className="truncate">{label}</span>
              </Link>
            );
          })}
        </div>
      )}
    </div>
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
 *   • A tile with the user's initial, in the FidClic logo's blue.
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
    role === 'administrateur' ? 'Administrateur' :
    role === 'manager' ? t('nav.manager') :
    role === 'staff' ? t('nav.staff') :
    role === 'super_admin' ? t('nav.admin') : t('nav.user');

  return (
    <div className="relative shrink-0" ref={ref}>
      <button
        type="button"
        aria-label={t('nav.account_menu')}
        onClick={() => setOpen((v) => !v)}
        className="relative w-10 h-10 rounded-[12px] flex items-center justify-center text-white hover:opacity-90 transition-opacity"
        style={{
          // The FidClic mark's own blue tile (user, 2026-10-02).
          background: `linear-gradient(135deg, #1F63E0 0%, ${BRAND_BLUE} 100%)`,
          boxShadow: '0 8px 16px -10px rgba(20,80,184,.8)',
          color: '#FFFFFF',
          fontWeight: 700,
          fontSize: 15,
          letterSpacing: '0.02em',
        }}
      >
        {initial}
        <span
          aria-hidden="true"
          className="absolute bottom-0 right-0 w-2.5 h-2.5 rounded-full"
          style={{ background: BRAND_YELLOW, boxShadow: '0 0 0 2px var(--flc-card, #FFFFFF)' }}
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
                className="w-9 h-9 rounded-[11px] flex items-center justify-center text-white shrink-0"
                style={{
                  background: `linear-gradient(135deg, #1F63E0 0%, ${BRAND_BLUE} 100%)`,
                  color: '#FFFFFF', fontWeight: 700, fontSize: 14,
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
  // Centre de support: tickets with a merchant message nobody has read yet.
  const [supportUnread, setSupportUnread] = React.useState(0);
  const seesSupport = isTeam(user) && can(user, 'support');
  React.useEffect(() => {
    if (!seesSupport) return undefined;
    const load = () => { if (!document.hidden) supportAPI.badge().then(({ data }) => setSupportUnread(data.unread || 0)).catch(() => {}); };
    load();
    const id = setInterval(load, 60000);
    return () => clearInterval(id);
  }, [seesSupport, location.pathname]);
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
  // Extra words per page, on top of its own label in the sidebar. The sidebar
  // is the list of pages; keeping a second copy of the routes here is what
  // broke the search — « /dashboard/card-designer » stopped existing, and with
  // nothing matching, everything fell through to the client list (user,
  // 2026-10-15: « kuch bhi search kro toh clients page pr le jaata hai »).
  const EXTRA_WORDS = React.useMemo(() => ({
    '/dashboard': ['dashboard', 'accueil', 'home', 'overview', 'vue d\u2019ensemble'],
    '/dashboard/scan': ['scan', 'scanner', 'qr', 'caisse', 'visite', 'visites', 'check-in', 'checkin', 'passage'],
    '/dashboard/analytics': ['analytics', 'kpi', 'kpis', 'stats', 'statistiques', 'rapport', 'reports', 'metrics', 'chiffre d\u2019affaires', 'ca'],
    '/dashboard/customers': ['customers', 'customer', 'client', 'fiche client', 'liste clients'],
    '/dashboard/campaigns': ['campaigns', 'campaign', 'campagne', 'sms', 'push', 'message', 'messages', 'notification', 'notifications', 'offre', 'offres'],
    '/dashboard/card': ['card', 'carte', 'loyalty card', 'design', 'pass', 'wallet', 'tampons', 'points', 'paliers', 'recompenses'],
    '/dashboard/automations': ['automations', 'automation', 'automatisation', 'anniversaire', 'relance', 'inactif', 'scenario', 'scenarios'],
    '/dashboard/segmentation': ['segments', 'segment'],
    '/dashboard/referral': ['referral', 'parrain', 'filleul', 'parrainages'],
    '/dashboard/map': ['map', 'geolocalisation', 'geo', 'localisation', 'lieux', 'rayon', 'geographie'],
    '/dashboard/catalogue': ['catalog', 'produits', 'produit', 'products', 'menu', 'prix', 'services'],
    '/dashboard/insights': ['insight', 'reco', 'recommandations', 'recommendations', 'suggestion', 'suggestions'],
    '/dashboard/ai-assistant': ['fidclic ia', 'fidclic ai', 'copilote', 'copilot', 'assistant', 'chat', 'ia', 'ai'],
    '/dashboard/history': ['history', 'logs', 'journal', 'audit', 'activite'],
    '/dashboard/parametres': ['settings', 'parametres', 'reglages', 'config', 'configuration', 'preferences', 'compte', 'account', 'profil', 'billing', 'facturation', 'abonnement', 'plan', 'securite', 'lien d\u2019inscription', 'qr'],
    '/dashboard/parametres/equipe': ['equipe', 'team', 'staff', 'utilisateurs', 'users', 'acces', 'roles', 'role'],
    '/dashboard/parametres/regles-clients': ['statut client', 'statuts', 'regles clients'],
  }), []);

  // Every page the sidebar knows, with its own label — so a page added there
  // is searchable the same day, by its name, without touching this.
  const ROUTE_SYNONYMS = React.useMemo(() => {
    const rows = PERM_NAV.map((n) => ({
      route: n.to,
      words: [n.label, ...(EXTRA_WORDS[n.to] || [])],
    }));
    for (const [route, words] of Object.entries(EXTRA_WORDS)) {
      if (!rows.some((r) => r.route === route)) rows.push({ route, words });
    }
    // longest word first: « lien d\u2019inscription » must win over « lien »
    return rows.sort((a, b) => Math.max(...b.words.map((w) => w.length)) - Math.max(...a.words.map((w) => w.length)));
  }, [EXTRA_WORDS]);

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

    // 2) Page/section synonyms — route to the matching page, and say what was
    //    matched so the page can show it (?hl=). « geolocalisation » finds
    //    « Géolocalisation »: accents are stripped on both sides.
    const q = flat(raw);
    for (const entry of ROUTE_SYNONYMS) {
      for (const w of entry.words) {
        const wl = flat(w);
        // Both ways round: « carte de fidélité » typed in full contains the
        // word, and « catalogue » is one word of « Catalogue produits ».
        const token = (needle, hay) => new RegExp(
          `(^|[^a-z0-9])${needle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}([^a-z0-9]|$)`, 'i').test(hay);
        if (q === wl || token(wl, q) || token(q, wl)) {
          navigate(`${entry.route}?hl=${encodeURIComponent(w)}`);
          return;
        }
      }
    }

    // 3) Fallback — free-text customer search, with the term shown there too.
    navigate(`/dashboard/customers?q=${encodeURIComponent(raw)}&hl=${encodeURIComponent(raw)}`);
  };
  // What the search found, outlined on the page it opened (user, 2026-10-15:
  // « highlight bhi krde taaki pta chale ki sahi hai ki nhi »). The page may
  // still be loading, so it is tried again a few times.
  React.useEffect(() => {
    const hl = new URLSearchParams(location.search).get('hl');
    if (!hl) return undefined;
    return highlightWhenReady(hl);
  }, [location.pathname, location.search]);

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
  const partialScope = ['administrateur', 'manager'].includes(role) && user?.scope === 'partial';
  const { branchId, branches: myBranches } = useBranch();
  // Rôles et permissions par page (Équipe & accès): an account with its own
  // switches sees the pages it may « Voir » in the establishment chosen
  const pagePerms = role !== 'business_owner' && user?.page_perms && typeof user.page_perms === 'object' ? user.page_perms : null;
  const myLevels = React.useMemo(() => {
    if (!pagePerms) return null;
    if (branchId && pagePerms[branchId]) return pagePerms[branchId];
    const all = Object.values(pagePerms);
    if (!all.length) return {};
    const rank = { none: 0, view: 1, edit: 2 };
    return Object.fromEntries(Object.keys(all[0]).map((k) => [k, all.map((p) => p[k] || 'none').reduce((a, b) => (rank[a] <= rank[b] ? a : b))]));
  }, [pagePerms, branchId]);
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

  // « Accéder au compte » : le bandeau se réduit (user, 2026-10-16 — il
  // couvrait le bas des pages et empêchait de se servir du compte). Le choix
  // est retenu PAR COMMERCE : entrer dans un autre compte réaffiche l'avis en
  // entier, puisqu'il dit dans quel compte on est et que tout est journalisé.
  const viewKey = user?.view_as ? `fdt:view-as:collapsed:${user.tenant_id || user.tenant_name || ''}` : '';
  const [viewBarOpen, setViewBarOpen] = React.useState(true);
  React.useEffect(() => {
    if (!viewKey) return;
    try { setViewBarOpen(window.localStorage.getItem(viewKey) !== '1'); }
    catch { setViewBarOpen(true); }
  }, [viewKey]);
  const setViewBar = (open) => {
    setViewBarOpen(open);
    try { window.localStorage.setItem(viewKey, open ? '0' : '1'); }
    catch { /* localStorage may be blocked — the choice just lasts this page */ }
  };

  // Phone and tablet (QA F09, 2026-10-08: at 390 px the open menu took
  // ~230 px and the header buttons overlapped): below 1024 px the menu is a
  // drawer over the page, opened from ☰ and closed by a tap outside, Escape
  // or any navigation; the icons-only rail exists on large screens only.
  const SMALL = '(max-width: 1023px)';
  const [small, setSmall] = React.useState(() => typeof window !== 'undefined' && !!window.matchMedia?.(SMALL).matches);
  React.useEffect(() => {
    const mq = window.matchMedia?.(SMALL);
    if (!mq) return undefined;
    const on = () => setSmall(mq.matches);
    on();
    mq.addEventListener ? mq.addEventListener('change', on) : mq.addListener(on);
    return () => (mq.removeEventListener ? mq.removeEventListener('change', on) : mq.removeListener(on));
  }, []);
  const [menuOpen, setMenuOpen] = React.useState(false);
  React.useEffect(() => { setMenuOpen(false); }, [currentPath]);
  // Wallet cards a save left queued: sent in the background (lib/walletRefresh)
  React.useEffect(() => {
    if (!['business_owner', 'administrateur', 'manager'].includes(user?.role)) return undefined;
    drainWallet();                               // anything left from before
    const on = () => kickWallet();
    window.addEventListener('fidclic:wallet-kick', on);
    return () => window.removeEventListener('fidclic:wallet-kick', on);
  }, [user?.role]);
  React.useEffect(() => {
    if (!menuOpen) return undefined;
    const key = (e) => { if (e.key === 'Escape') setMenuOpen(false); };
    window.addEventListener('keydown', key);
    const before = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { window.removeEventListener('keydown', key); document.body.style.overflow = before; };
  }, [menuOpen]);
  const rail = !small && collapsed;

  // Fetch tenant identity once — shown in the sidebar so the user always
  // knows which business account they're acting as. Prevents the "wait,
  // why isn't this scan working" tenant-mismatch confusion.
  const [tenantInfo, setTenantInfo] = React.useState(null);
  React.useEffect(() => {
    // A platform admin has no shop of their own — the call would only 403.
    if (!user || isTeam(user)) return undefined;
    let alive = true;
    ownerAPI.getTenant?.()
      .then((r) => { if (alive) setTenantInfo(r.data || null); })
      .catch(() => { /* silent — keep header generic */ });
    return () => { alive = false; };
  }, [user?.email]);
  // The business, its establishments and the person signed in are names:
  // the page translator leaves them as written (QA F08).
  React.useEffect(() => {
    const t = tenantInfo || {};
    protectNames([t.name, t.legal_name, t.commercial_name, t.brand_name,
      ...((t.branches || []).map((b) => b.name)), ...((myBranches || []).map((b) => b.name)), user?.name, user?.full_name,
      [user?.first_name, user?.last_name].filter(Boolean).join(' ')]);
  }, [tenantInfo, user, myBranches]);

  // Analytics moved to the unified light theme (av2-light-skin) — same
  // palette as the rest of the dashboard so navigating Analytics ↔
  // Customers ↔ Campaigns no longer flips colour modes. Keeping the
  // variable as `false` so a future per-route theme toggle has a single
  // place to wire in without re-introducing the dead branches.
  const isAnalyticsDark = false;
  const planAccess = usePlanAccessState(role);
  const pageLock = planAccess.lockOf(currentPath);
  // A page this team account may not « Voir » here: the menu stays, the page
  // says « Accès non autorisé » (Paramètres checks each of its tabs itself).
  const deniedPage = (() => {
    if (!myLevels || currentPath.startsWith('/dashboard/parametres')) return null;
    const key = pageOfPath(currentPath);
    if (!key || (myLevels[key] || 'none') !== 'none') return null;
    return (PERM_NAV.find((n) => n.keys[0] === key) || {}).label || 'cette page';
  })();

  return (
    <PlanAccessContext.Provider value={planAccess}>
    <div
      className={`relative flex min-h-screen fdt-dash flc ${nuit ? "flc-nuit" : ""} ${isTeam(user) ? 'fd-admin' : ''}`}
      style={{ transition: 'background 200ms ease' }}
    >
      {/* No fixed backdrop any more (user, 2026-10-28): the April theme's two
          blurred orange / red orbs were all but invisible on the blue design,
          yet iOS 26 tints the bar under the app from fixed elements — an
          orange band on the shop's iPad. Every role has the plain canvas. */}

      {small && menuOpen && (
        <div className="fixed inset-0 z-[55] bg-[#0B1C3F]/40" onClick={() => setMenuOpen(false)} aria-hidden="true" />
      )}
      <aside
        className={`${small
          ? `fixed inset-y-0 left-0 z-[60] w-[280px] max-w-[85vw] shadow-2xl ${menuOpen ? 'translate-x-0' : '-translate-x-full invisible'}`
          : `sticky top-0 z-10 ${rail ? 'w-[72px]' : 'w-64'}`} h-screen flex flex-col shrink-0 transition-[width,background-color,transform] duration-200 ease-out fd-aside fd-sidebar-host`}
        aria-hidden={small && !menuOpen ? true : undefined}
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
          className="absolute -right-3 top-6 z-20 w-7 h-7 rounded-full hidden lg:flex items-center justify-center transition-all hover:scale-110"
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
        {/* phone / tablet: the drawer's own way out */}
        {small && (
          <button type="button" onClick={() => setMenuOpen(false)} aria-label="Fermer le menu"
                  className="absolute right-3 top-3 z-20 flex h-9 w-9 items-center justify-center rounded-full bg-white text-[#334155] shadow-[0_2px_8px_rgba(11,28,63,0.12)]">
            <XIcon size={18} />
          </button>
        )}

        {/* Brand mark, then the shop whose figures are on screen. The account
            badge that used to sit here became the establishment switcher — one
            place to say which shop you are looking at. */}
        <div className={rail ? 'px-3 pt-3 pb-1' : 'px-4 pt-4 pb-1'}>
          <Link to="/" className={`flex items-center ${rail ? 'justify-center' : 'gap-2.5'}`}>
            {/* The FidClic logo: the F-and-cursor mark, « Fid » in blue, « Clic » in yellow. */}
            <img src="/brand/fidclic-icon.png" alt="FidClic" width="36" height="36"
                 className="h-9 w-9 shrink-0 object-contain"
                 style={{ filter: 'drop-shadow(0 8px 14px rgba(20,80,184,.28))' }}
                 title={rail ? 'FidClic' : undefined} />
            {!rail && (
              <span className="text-[21px] font-extrabold leading-none tracking-[-0.02em]">
                <span style={{ color: BRAND_BLUE }}>Fid</span><span style={{ color: BRAND_YELLOW }}>Clic</span>
              </span>
            )}
            {!rail && isTeam(user) && (
              <span className="max-w-[92px] truncate rounded-md bg-[#EAF1FF] px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-[#2F6BFF]">
                {role === 'super_admin' ? 'SUPER ADMIN' : (user?.platform_role_name || 'COMMERCIAL')}
              </span>
            )}
          </Link>
        </div>
        {/* The owner picks any establishment, an administrateur one of its
            own; a manager or an employé sees its establishment's name. */}
        {!isTeam(user) && <EstablishmentSwitcher tenant={tenantInfo} collapsed={rail} />}

        <div className="px-4">
          <div className="h-px" style={{ background: C.hairline }} />
        </div>

        <nav className={`flex-1 ${rail ? 'px-2' : 'px-3'} py-2 space-y-[1px] overflow-y-auto`}>
          {role === 'business_owner' && (
            <>
              {/* Order follows the approved sidebar mockup. Every row points at
                  a page that exists. */}
              <NavLink to="/dashboard"               icon={Home}         label={t('nav.dashboard')}        currentPath={currentPath} role={role} collapsed={rail} />
              {/* At the till the owner scans from their own account too. */}
              <NavLink to="/dashboard/scan"          icon={QrCode}       label={t('nav.scan_visit')}       currentPath={currentPath} role={role} collapsed={rail} />
              <NavLink to="/dashboard/analytics"     icon={BarChart3}    label={t('nav.analytics')}        currentPath={currentPath} role={role} collapsed={rail} />
              <NavLink to="/dashboard/customers"     icon={Users}        label={t('nav.customers')}        currentPath={currentPath} role={role} collapsed={rail} />
              <NavLink to="/dashboard/campaigns"     icon={Megaphone}    label={t('nav.campaigns')}     currentPath={currentPath} role={role} collapsed={rail} />
              <NavLink to="/dashboard/card"          icon={CreditCard}   label={t('nav.loyalty_card')}  currentPath={currentPath} role={role} collapsed={rail} />
              <NavLink to="/dashboard/automations"   icon={Zap}          label={t('nav.automations')} currentPath={currentPath} role={role} collapsed={rail} />
              <NavLink to="/dashboard/segmentation"  icon={PieChart}     label={t('nav.segmentation')}  currentPath={currentPath} role={role} collapsed={rail} />
              <NavLink to="/dashboard/referral"      icon={Share2}       label={t('nav.referral')}      currentPath={currentPath} role={role} collapsed={rail} />
              <NavLink to="/dashboard/map"           icon={MapPin}       label={t('nav.geolocation')}   currentPath={currentPath} role={role} collapsed={rail} />
              <NavLink to="/dashboard/catalogue"     icon={ShoppingBag}  label={t('nav.catalogue')}     currentPath={currentPath} role={role} collapsed={rail} />
              <NavLink to="/dashboard/insights"      icon={Sparkles}     label={t('nav.insights')}         currentPath={currentPath} role={role} collapsed={rail} />
              <NavLink to="/dashboard/ai-assistant"  icon={Sparkle} label={t('nav.ai_assistant')}  currentPath={currentPath} role={role} collapsed={rail} badge="Nouveau" />
              <NavLink to="/dashboard/history"       icon={History}      label={t('nav.history')}       currentPath={currentPath} role={role} collapsed={rail} />
              {/* Paramètres is one page with tabs, like Analyses. The older
                  all-in-one settings page stays reachable from its tabs. */}
              <NavLink to="/dashboard/parametres" icon={Settings2} label={t('nav.settings')} currentPath={currentPath} role={role} collapsed={rail} alsoActive={['/dashboard/settings']} />
              <SignOutNavItem onClick={logout} collapsed={rail} />
            </>
          )}
          {myLevels && (
            <>
              {/* Every page, the owner's menu (user, 2026-10-22): one it may not
                  « Voir » shows a lock and opens on « Accès non autorisé ». The two
                  shortcuts (Équipe, Mon lien) only for an account without Paramètres. */}
              {PERM_NAV.filter((n) => !n.shortcut
                || (n.keys.some((k) => (myLevels[k] || 'none') !== 'none') && (myLevels[n.unless] || 'none') === 'none')).map((n) => (
                <NavLink key={n.to} to={n.to} icon={n.icon} label={n.label} currentPath={currentPath} role={role} collapsed={rail} alsoActive={n.also}
                         denied={!n.open && !n.keys.some((k) => (myLevels[k] || 'none') !== 'none')} />
              ))}
              <SignOutNavItem onClick={logout} collapsed={rail} />
            </>
          )}
          {!myLevels && role === 'manager' && !partialScope && (
            <>
              <NavLink to="/dashboard/analytics" icon={BarChart3} label={t('nav.analytics')}    currentPath={currentPath} role={role} collapsed={rail} />
              <NavLink to="/dashboard/insights"  icon={Sparkles}  label={t('nav.insights')}     currentPath={currentPath} role={role} collapsed={rail} />
              <NavLink to="/dashboard/ai-assistant" icon={Sparkle} label={t('nav.ai_assistant')} currentPath={currentPath} role={role} collapsed={rail} />
              <NavLink to="/dashboard/customers" icon={Users}     label={t('nav.customers')}    currentPath={currentPath} role={role} collapsed={rail} />
              <NavLink to="/dashboard/campaigns" icon={Megaphone} label={t('nav.campaigns')}    currentPath={currentPath} role={role} collapsed={rail} />
              <NavLink to="/dashboard/segmentation" icon={PieChart} label={t('nav.segmentation')} currentPath={currentPath} role={role} collapsed={rail} />
              <NavLink to="/dashboard/map"       icon={MapPin}    label={t('nav.geolocation')} currentPath={currentPath} role={role} collapsed={rail} />
              <NavLink to="/dashboard/history"   icon={History}   label={t('nav.history')}      currentPath={currentPath} role={role} collapsed={rail} />
              <NavLink to="/dashboard/scan"      icon={QrCode}    label={t('nav.scan_visit')}   currentPath={currentPath} role={role} collapsed={rail} />
              <NavLink to="/dashboard/parametres/equipe" icon={Settings2} label={t('nav.team')} currentPath={currentPath} role={role} collapsed={rail} alsoActive={['/dashboard/parametres']} />
              <SignOutNavItem onClick={logout} collapsed={rail} />
            </>
          )}
          {/* An administrateur — and a manager covering only some of the
              establishments — works from the team page until the data pages
              filter by establishment. */}
          {!myLevels && (role === 'administrateur' || (role === 'manager' && partialScope)) && (
            <>
              <NavLink to="/dashboard"               icon={Home}         label={t('nav.dashboard')}        currentPath={currentPath} role={role} collapsed={rail} />
              <NavLink to="/dashboard/analytics"     icon={BarChart3}    label={t('nav.analytics')}        currentPath={currentPath} role={role} collapsed={rail} />
              <NavLink to="/dashboard/customers"     icon={Users}        label={t('nav.customers')}        currentPath={currentPath} role={role} collapsed={rail} />
              <NavLink to="/dashboard/campaigns"     icon={Megaphone}    label={t('nav.campaigns')}        currentPath={currentPath} role={role} collapsed={rail} />
              <NavLink to="/dashboard/card"          icon={CreditCard}   label={t('nav.loyalty_card')}     currentPath={currentPath} role={role} collapsed={rail} />
              <NavLink to="/dashboard/automations"   icon={Zap}          label={t('nav.automations')}      currentPath={currentPath} role={role} collapsed={rail} />
              <NavLink to="/dashboard/segmentation"  icon={PieChart}     label={t('nav.segmentation')}     currentPath={currentPath} role={role} collapsed={rail} />
              <NavLink to="/dashboard/insights"      icon={Sparkles}     label={t('nav.insights')}         currentPath={currentPath} role={role} collapsed={rail} />
              <NavLink to="/dashboard/ai-assistant"  icon={Sparkle}      label={t('nav.ai_assistant')}     currentPath={currentPath} role={role} collapsed={rail} />
              <NavLink to="/dashboard/referral"      icon={Share2}       label={t('nav.referral')}         currentPath={currentPath} role={role} collapsed={rail} />
              <NavLink to="/dashboard/map"           icon={MapPin}       label={t('nav.geolocation')}      currentPath={currentPath} role={role} collapsed={rail} />
              <NavLink to="/dashboard/catalogue"     icon={ShoppingBag}  label={t('nav.catalogue')}        currentPath={currentPath} role={role} collapsed={rail} />
              <NavLink to="/dashboard/history"       icon={History}      label={t('nav.history')}          currentPath={currentPath} role={role} collapsed={rail} />
              <NavLink to="/dashboard/scan" icon={QrCode} label={t('nav.scan_visit')} currentPath={currentPath} role={role} collapsed={rail} />
              <NavLink to="/dashboard/parametres/equipe" icon={Settings2} label={t('nav.team')} currentPath={currentPath} role={role} collapsed={rail} alsoActive={['/dashboard/parametres']} />
              <SignOutNavItem onClick={logout} collapsed={rail} />
            </>
          )}
          {!myLevels && role === 'staff' && (
            <>
              <NavLink to="/dashboard/scan" icon={QrCode} label={t('nav.scan_visit')} currentPath={currentPath} role={role} collapsed={rail} />
              <SignOutNavItem onClick={logout} collapsed={rail} />
            </>
          )}
          {/* FidClic's team — the approved mockup's order and French names.
              Each role sees the sections it may open (Sécurité › Rôles). */}
          {isTeam(user) && (
            <>
              {can(user, 'dashboard') && <NavLink to="/admin" icon={Home} label="Dashboard" currentPath={currentPath} role={role} collapsed={rail} />}
              {can(user, 'commerces') && <NavLink to="/admin/commerces" icon={Database} label="Commerces" currentPath={currentPath} role={role} collapsed={rail} />}
              {can(user, 'analytics') && <NavLink to="/admin/analytics" icon={BarChart3} label="Analytics" currentPath={currentPath} role={role} collapsed={rail} />}
              {can(user, 'insights') && <NavLink to="/admin/insights" icon={Sparkles} label="Insights" currentPath={currentPath} role={role} collapsed={rail} />}
              {can(user, 'plan_limits') && <NavLink to="/admin/plans" icon={Shield} label="Plan Limits" currentPath={currentPath} role={role} collapsed={rail} />}
              {can(user, 'facturation') && <NavLink to="/admin/facturation" icon={Receipt} label="Facturation" currentPath={currentPath} role={role} collapsed={rail} />}
              {can(user, 'crm') && <CrmNav currentPath={currentPath} role={role} collapsed={rail} />}
              {can(user, 'ai') && <NavLink to="/admin/ai" icon={BrainCircuit} label="FIDCLIC AI" currentPath={currentPath} role={role} collapsed={rail} />}
              {can(user, 'securite') && <NavLink to="/admin/securite" icon={ShieldCheck} label="Admin" currentPath={currentPath} role={role} collapsed={rail} />}
              {can(user, 'support') && <NavLink to="/admin/support" icon={Headphones} label="Centre de support" currentPath={currentPath} role={role} collapsed={rail} badge={supportUnread || null} />}
              {can(user, 'equipe') && <NavLink to="/admin/equipe" icon={ClipboardCheck} label="Suivi d'équipe" currentPath={currentPath} role={role} collapsed={rail} />}
              <SignOutNavItem onClick={logout} collapsed={rail} />
            </>
          )}
        </nav>

        {/* Help — one row at the foot of the rail, in both states. The help
            icon that used to sit in the top bar went with the bar, so this is
            the single way in and it has to survive the collapsed rail. */}
        {/* FidClic's team answers from « Centre de support » (in the menu); the
            merchant's « Besoin d'aide ? » row is not theirs. */}
        {!isTeam(user) && (
        <div className={`mt-auto ${rail ? 'flex justify-center px-2 pb-3' : 'px-3 pb-3'}`}>
          <button
            type="button"
            onClick={() => navigate('/dashboard/aide')}
            title={rail ? t('nav.help') : undefined}
            aria-label={t('nav.help')}
            className={rail
              ? 'flex h-9 w-9 items-center justify-center rounded-xl transition-colors'
              : 'flex w-full items-center gap-2.5 rounded-xl px-3 py-2.5 text-left transition-colors'}
            style={{ background: '#EAF1FF', color: '#2F6BFF' }}
          >
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full"
                  style={{ background: rail ? 'transparent' : '#2F6BFF', color: rail ? '#2F6BFF' : '#fff' }}>
              <LifeBuoy size={rail ? 17 : 13} />
            </span>
            {!rail && (
              <>
                <span className="min-w-0 flex-1 truncate text-[13px] font-semibold" style={{ color: '#1D4ED8' }}>
                  {t('nav.help')}
                </span>
              </>
            )}
          </button>
        </div>
        )}

      </aside>

      {/* « Accéder au compte » from the super admin: full access (every change
          is audited under the admin's name), or read-only for a team member
          who may only look — said either way.
          Floating, outside <main>: the pages style main's first child. */}
      {user?.view_as && (viewBarOpen ? (
        <div role="status" className="fixed bottom-4 left-1/2 z-[70] flex w-[min(760px,calc(100%-32px))] -translate-x-1/2 flex-wrap items-center gap-3 rounded-2xl px-4 py-3 text-[13px] shadow-[0_18px_50px_-18px_rgba(11,28,63,.7)]"
             style={{ background: '#0B1C3F', color: '#fff' }}>
          <Eye size={16} className="shrink-0" />
          {user.view_as.can_edit ? (
            <span className="min-w-0 flex-1">Vous êtes dans le compte de <strong>{user.tenant_name}</strong> avec un <strong>accès complet</strong>, ouvert par {user.view_as.by}. Chaque modification est enregistrée à votre nom dans le journal.</span>
          ) : (
            <span className="min-w-0 flex-1">Vue en <strong>lecture seule</strong> du compte de <strong>{user.tenant_name}</strong>, ouverte par {user.view_as.by}. Aucune modification n'est possible.</span>
          )}
          <button type="button" onClick={logout} className="rounded-lg px-3 py-1.5 font-medium" style={{ background: 'rgba(255,255,255,.16)', color: '#fff' }}>Quitter la vue</button>
          <button type="button" onClick={() => setViewBar(false)} aria-label="Réduire le bandeau"
                  title="Réduire — le bandeau se range en bas à droite"
                  className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg"
                  style={{ background: 'rgba(255,255,255,.16)', color: '#fff' }}>
            <ChevronDown size={16} />
          </button>
        </div>
      ) : (
        /* Réduit : le bandeau couvrait le bas des pages et empêchait de se
           servir du compte (user, 2026-10-16). « Quitter la vue » reste à un
           clic, et le point bleu rappelle qu'on n'est pas chez soi. */
        <div role="status" className="fixed bottom-4 right-4 z-[70] flex items-center gap-1.5 rounded-full py-1.5 pl-2.5 pr-1.5 text-[12.5px] shadow-[0_18px_50px_-18px_rgba(11,28,63,.7)]"
             style={{ background: '#0B1C3F', color: '#fff' }}>
          <button type="button" onClick={() => setViewBar(true)}
                  aria-label={`Vue du compte de ${user.tenant_name} — afficher le bandeau`}
                  title={`Vue du compte de ${user.tenant_name}`}
                  className="flex items-center gap-1.5 rounded-full px-1 py-0.5 font-medium">
            <Eye size={14} className="shrink-0" />
            <span className="max-w-[140px] truncate">{user.tenant_name}</span>
          </button>
          <button type="button" onClick={logout} className="rounded-full px-2.5 py-1 font-semibold"
                  style={{ background: 'rgba(255,255,255,.16)', color: '#fff' }}>Quitter</button>
        </div>
      ))}
      {/* No z-index here (user, 2026-10-30): with one, <main> was its own layer
          UNDER the phone's bottom tab bar (BottomNav, z-40), so every window
          opened from a page had its bottom — its save button — painted under
          the bar. Without it, a window's own z-50 puts it above the bar. */}
      <main className="relative flex-1 overflow-auto">
        {/* A team member whose role may look at this section but not change it. */}
        {isTeam(user) && role !== 'super_admin' && moduleOfPath(currentPath) && can(user, moduleOfPath(currentPath))
          && !can(user, moduleOfPath(currentPath), 'edit') && (
          <p className="mx-4 mt-3 flex items-center gap-2 rounded-xl border border-[#FDE68A] bg-[#FFFBEB] px-4 py-2 text-[12.5px] text-[#92400E]">
            <Eye size={14} /> Lecture seule : votre rôle permet de consulter cette section, pas de la modifier.
          </p>
        )}
        {/* Global billing health banner — only renders if there's something to
            warn about (past-due, canceled, trial ending soon). Otherwise
            invisible and out of the way. */}
        {role === 'business_owner' && !user?.view_as && <BillingBanner />}
        {role === 'business_owner' && !user?.view_as && <LimitBanner />}
        {/* Paramètres › Sécurité › Suppression du compte: the owner can still
            change its mind during the 30 days. */}
        {role === 'business_owner' && tenantInfo?.deletion_scheduled_at && (
          <div className="mx-4 mt-3 flex flex-wrap items-center gap-3 rounded-xl border border-[#FCD9D9] bg-[#FEF4F4] px-4 py-3 text-[13.5px] text-[#B42318]">
            <span className="flex-1">
              Suppression du compte programmée : vos données seront supprimées le{' '}
              {new Date(new Date(tenantInfo.deletion_scheduled_at).getTime() + 30 * 86400000).toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' })}.
              Votre équipe ne peut plus se connecter.
            </span>
            <button type="button" onClick={() => ownerAPI.restoreAccount().then(() => window.location.reload())}
                    className="rounded-lg bg-[#E11D48] px-4 py-2 font-medium text-white">Annuler la suppression</button>
          </div>
        )}

        {/* Phone / tablet, roles without the owner's bar: ☰ to reach the menu. */}
        {small && role !== 'business_owner' && (
          <div className="sticky top-0 z-30 flex items-center gap-3 border-b border-[#E6EEFB] bg-white/90 px-3 py-2.5 backdrop-blur">
            <button type="button" onClick={() => setMenuOpen(true)} aria-label="Ouvrir le menu" aria-expanded={menuOpen}
                    className="flex h-9 w-9 items-center justify-center rounded-xl border border-[#E6EEFB] bg-white text-[#334155]">
              <Menu size={18} />
            </button>
            <span className="text-[15px] font-bold text-[#0B1C3F]">FidClic</span>
          </div>
        )}

        {/* Premium top toolbar — search + bell + avatar.
            Sits as a sticky bar across every dashboard page (matches the
            reference mockup with the search bar centered and the bell +
            user avatar pinned right). On non-owner roles we keep the bell
            slot hidden so staff don't see owner-only alerts. */}
        {role === 'business_owner' && (
          <div
            className="sticky top-0 z-30 relative flex items-center gap-2 px-3 py-2.5 backdrop-blur sm:px-4 lg:justify-center lg:px-8"
            style={{
              background: 'color-mix(in srgb, var(--flc-card, #FFFFFF) 82%, transparent)',
              borderBottom: '1px solid var(--hairline, #EFEDE9)',
            }}
          >
            {/* Global search — Enter routes to /dashboard/customers with
                the query. Barcode-style inputs (FT-XXXX) hit the customer
                page filter by barcode_id; everything else hits the free
                text search. */}
            {small && (
              <button type="button" onClick={() => setMenuOpen(true)} aria-label="Ouvrir le menu" aria-expanded={menuOpen}
                      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-[#E6EEFB] bg-white text-[#334155]">
                <Menu size={18} />
              </button>
            )}
            <form
              onSubmit={submitSearch}
              className="flex min-w-0 flex-1 items-center gap-2 rounded-full px-3.5 py-2 lg:w-[340px] lg:flex-none lg:shrink-0 xl:w-[460px] 2xl:w-[520px]"
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
                className="hidden text-[9.5px] px-1 py-0.5 rounded shrink-0 lg:inline"
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

            {/* The bar carries the scanner shortcut, the search, the bell and
                the account. Scanner (user, 2026-10-04): an owner at the counter
                scans from any page in one click. The branch pills moved into the
                sidebar's establishment switcher; help has its own row at the
                foot of the sidebar. */}
            <div className="flex shrink-0 items-center gap-2 lg:absolute lg:right-8 lg:gap-3">
              {/* on a phone the bottom bar carries it, large */}
              {(!user?.view_as || user.view_as.can_edit) && !small && (
                <Link to="/dashboard/scan" title={t('nav.scan_visit')} aria-label={t('nav.scan_visit')}
                      className={`inline-flex h-9 items-center gap-2 rounded-full px-2.5 text-[13.5px] font-semibold text-white transition hover:-translate-y-px xl:px-4 ${
                        currentPath === '/dashboard/scan' ? 'bg-[#1E4FD8]' : 'bg-[#2F6BFF] hover:bg-[#2559DB]'}`}
                      style={{ boxShadow: '0 8px 18px -10px rgba(47,107,255,.8)' }}>
                  <QrCode size={16} strokeWidth={2.2} />
                  <span className="hidden xl:inline">{t('nav.scan_short')}</span>
                </Link>
              )}
              <NotificationBell platformAdmin={role === 'super_admin'} />

              {/* User menu avatar */}
              <UserMenu user={user} theme={theme} role={role} onLogout={logout} />
            </div>
          </div>
        )}

        <div className={`px-3 py-4 sm:px-6 sm:py-5 lg:px-8 lg:py-5 max-w-[1600px] mx-auto ${small && role === 'business_owner' ? 'pb-28' : ''}`}>
          {!myLevels && (partialScope || role === 'administrateur') && (
            <div className="mb-4 flex items-start gap-3 rounded-xl border border-[#C9DBFB] bg-[#EFF5FF] px-4 py-3 text-[13px] text-[#1E4FD8]">
              <span className="mt-0.5 font-bold">i</span>
              <span>
                Tableau de bord, analyses, clients, campagnes, segmentation et insights de vos établissements
                sont disponibles. Les autres pages arrivent très bientôt — vous gérez aussi votre équipe et scannez les cartes.
              </span>
            </div>
          )}
          {/* A new establishment chosen under the logo: the page is rebuilt,
              so it reads its data again for that establishment. */}
          {/* The plan is known before a page loads, so a locked page never starts. */}
          {!planAccess.ready ? null : pageLock ? <LockedSection detail={pageLock} /> : deniedPage ? <NoPageAccess label={deniedPage} /> : <React.Suspense fallback={<div role="status" aria-label="Chargement" className="flex min-h-[50vh] items-center justify-center"><span className="h-7 w-7 animate-spin rounded-full border-[3px] border-[#DCE6FA] border-t-[#2F6BFF]" /></div>}><StoreGate><Outlet key={branchId || 'shop'} /></StoreGate></React.Suspense>}
        </div>
      </main>
      {/* the owner's phone: the everyday places under the thumb, the scanner in the middle */}
      {small && role === 'business_owner' && (
        <BottomNav path={currentPath} onMenu={() => setMenuOpen(true)}
                   canScan={!user?.view_as || user.view_as.can_edit} />
      )}
      <UpgradeModal />
    </div>
    </PlanAccessContext.Provider>
  );
};

export default DashboardLayout;
