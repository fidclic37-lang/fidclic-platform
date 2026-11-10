/* The establishment this tab works in (the dropdown under the logo).

   An owner's choice is remembered in localStorage — reloads and new tabs keep
   it. A super admin's « Accéder au compte » tab keeps its own in
   sessionStorage (user, 2026-11-10: opened from one boutique, it works in that
   boutique): two such tabs on two stores never overwrite each other, and the
   owner's or super admin's own choice in the other tabs is left untouched. */
const KEY = 'ft_selected_branch_v1';
const VIEW_KEY = 'fidclic_view_token';            // lib/api.js — kept here to avoid an import cycle

const viewing = () => { try { return !!sessionStorage.getItem(VIEW_KEY); } catch (_e) { return false; } };
const box = () => (viewing() ? sessionStorage : localStorage);

export function getStoreChoice() {
  try {
    const raw = box().getItem(KEY);
    return !raw || raw === 'null' || raw === 'undefined' ? null : raw;
  } catch (_e) { return null; }
}

export function setStoreChoice(id) {
  try {
    if (id == null || id === '') box().removeItem(KEY);
    else box().setItem(KEY, id);
  } catch (_e) { /* private mode */ }
}
