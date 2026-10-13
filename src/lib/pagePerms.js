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
  ['/dashboard/parametres', 'settings'], ['/dashboard/settings', 'settings'],
];
const ORDER = ['dashboard', 'scan', 'analytics', 'customers', 'campaigns', 'card', 'automations', 'segmentation',
  'referral', 'geolocation', 'catalogue', 'insights', 'ai', 'history', 'settings', 'team', 'billing'];
const HOME = { dashboard: '/dashboard', team: '/dashboard/parametres/equipe', billing: '/dashboard/parametres/abonnement',
  settings: '/dashboard/parametres' };

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
