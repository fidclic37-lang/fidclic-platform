// Super admin › Sécurité › Rôles & Permissions — what the signed-in member of
// FidClic's team may see (« view ») or change (« edit »). The server enforces
// the same rules on every call; this only shapes the menu and the pages.
export const TEAM_ROLES = ['super_admin', 'fidclic_team', 'commercial'];
export const isTeam = (user) => TEAM_ROLES.includes(user?.role);

export function can(user, module, level = 'view') {
  if (!user) return false;
  if (user.role === 'super_admin') return true;
  if (module === 'securite' && level === 'edit') return false;
  return !!user.permissions?.[module]?.[level];
}

// Each /admin page and the section it belongs to, in menu order.
export const ADMIN_ROUTES = [
  ['/admin', 'dashboard'], ['/admin/commerces', 'commerces'], ['/admin/analytics', 'analytics'], ['/admin/insights', 'insights'],
  ['/admin/campaigns', 'campagnes'], ['/admin/plans', 'plan_limits'], ['/admin/facturation', 'facturation'],
  ['/admin/card-designer', 'card_designer'], ['/admin/crm', 'crm'], ['/admin/ai', 'ai'], ['/admin/securite', 'securite'],
];

export function moduleOfPath(path) {
  const hit = [...ADMIN_ROUTES].sort((a, b) => b[0].length - a[0].length)
    .find(([p]) => (p === '/admin' ? path === '/admin' || path === '/admin/' : path === p || path.startsWith(`${p}/`)));
  return hit?.[1] || null;
}

export function firstAllowed(user) {
  return ADMIN_ROUTES.find(([, m]) => can(user, m))?.[0] || null;
}
