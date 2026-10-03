/**
 * Bring an element on screen and make it pulse for ~2 seconds, so the eye
 * lands on it (user, 2026-10-03: the Tableau de bord's CA opens Analyses on
 * the CA card; « Inviter un utilisateur » shows the invitation form).
 * Style: .fc-flash in index.css.
 */
export function flash(el, { block = 'center', focus = null } = {}) {
  if (!el) return;
  el.scrollIntoView({ behavior: 'smooth', block });
  el.classList.remove('fc-flash');
  void el.offsetWidth;                       // restart the animation if it was running
  el.classList.add('fc-flash');
  window.setTimeout(() => el.classList.remove('fc-flash'), 2200);
  if (focus) window.setTimeout(() => el.querySelector(focus)?.focus({ preventScroll: true }), 450);
}
