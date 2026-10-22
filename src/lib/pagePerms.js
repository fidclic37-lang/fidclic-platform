/* Rôles et permissions par page (Équipe & accès, 2026-10-13): which page a
   /dashboard address is, and whether an account with its own permissions
   may open it. Mirrors api/features/role_perms.PAGES. */
export const PAGE_ROUTES = [
  ['/dashboard/scan', 'scan'], ['/dashboard/analytics', 'analytics'], ['/dashboard/analyses', 'analytics'],
  ['/dashboard/customers', 'customers'], ['/dashboard/clients', 'customers'], ['/dashboard/campaigns', 'campaigns'],
  ['/dashboard/card', 'card'], ['/dashboard/automations', 'automations'], ['/dashboard/segmentation', 'segmentation'],
  ['/dashboard/referral', 'referral'], ['/dashboard/map', 'geolocation'], ['/dashboard/catalogue', 'catalogue'],
  ['/dashboard/insights', 'insights'], ['/dashboard/ai-assistant', 'ai'], ['/dashboard/history', 'history'],
  ['/dashboard/parametres/equipe', 'team'], ['/dashboard/parametres/abonnement', 'billing'],
  // « Liens d'inscription par employé » (2026-10-16): its own permission, so an
  // employee can be given it without the rest of Paramètres. Listed BEFORE
  // /dashboard/parametres, which would otherwise swallow it.
  ['/dashboard/parametres/lien-inscription', 'employee_links'],
  ['/dashboard/parametres', 'settings'], ['/dashboard/settings', 'settings'],
];
const ORDER = ['dashboard', 'scan', 'analytics', 'customers', 'campaigns', 'card', 'automations', 'segmentation',
  'referral', 'geolocation', 'catalogue', 'insights', 'ai', 'history', 'settings', 'team', 'billing',
  'employee_links'];
const HOME = { dashboard: '/dashboard', team: '/dashboard/parametres/equipe', billing: '/dashboard/parametres/abonnement',
  settings: '/dashboard/parametres', employee_links: '/dashboard/parametres/lien-inscription' };

export const hasPagePerms = (user) => Boolean(user && user.role !== 'business_owner' && user.page_perms
  && typeof user.page_perms === 'object');

export function pageOfPath(path) {
  if (path === '/dashboard' || path === '/dashboard/') return 'dashboard';
  const hit = PAGE_ROUTES.find(([p]) => path === p || path.startsWith(`${p}/`));
  return hit ? hit[1] : null;
}

// « Voir » in at least one of its establishments
export const canSee = (user, key) => Object.values(user.page_perms || {}).some((p) => (p?.[key] || 'none') !== 'none');

export function firstAllowed(user) {
  const k = ORDER.find((x) => canSee(user, x));
  if (!k) return null;
  return HOME[k] || PAGE_ROUTES.find(([, v]) => v === k)?.[0] || '/dashboard';
}

/* The one question every page asks (user, 2026-10-22: « based on permissions
   given in the roles… sections accessible hona chahiye »), for every business:
   the owner may everything; a team account what its « Voir » / « Modifier »
   switches say in the establishment chosen in the menu (the lowest of its
   establishments when none is chosen — never more than everywhere). */
const RANK = { none: 0, view: 1, edit: 2 };
const OWNER_ROLES = ['business_owner', 'super_admin'];
export function levelOf(user, key) {
  if (!user) return 'none';
  if (OWNER_ROLES.includes(user.role)) return 'edit';
  const perms = user.page_perms;
  if (!perms || typeof perms !== 'object') return 'none';
  let store = null;
  try { store = window.localStorage.getItem('ft_selected_branch_v1'); } catch { store = null; }
  if (store && perms[store]) return perms[store][key] || 'none';
  const all = Object.values(perms);
  if (!all.length) return 'none';
  return all.map((p) => p?.[key] || 'none').reduce((a, b) => (RANK[a] <= RANK[b] ? a : b));
}
export const canView = (user, key) => RANK[levelOf(user, key)] >= 1;
export const canEdit = (user, key) => levelOf(user, key) === 'edit';
