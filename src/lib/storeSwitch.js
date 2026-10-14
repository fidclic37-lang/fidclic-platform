/**
 * Who may change the establishment they are working in.
 *
 * The rule lived twice — in the sidebar's switcher and on the Scan page — and
 * the two copies had already drifted: « membre » could switch in both places
 * although nobody meant it to. One rule now, read by both.
 *
 * By default the owner and an administrateur choose; a manager, a membre and
 * an employé work where they are. The owner or an administrateur can hand the
 * choice to one account from Équipe & accès, and that wins (user, 2026-10-14).
 */
export const FREE_ROLES = ['business_owner', 'administrateur'];

export function canSwitchStore(user) {
  if (!user) return false;
  if (typeof user.can_switch_store === 'boolean') return user.can_switch_store;
  return FREE_ROLES.includes(user.role);
}
