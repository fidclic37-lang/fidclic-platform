/*
 * A window with something typed in it never closes on a tap beside it
 * (QA BUG-003 / BUG-007, user 2026-10-13: « bahar tap kiya, sab mit gaya »).
 *
 * Every window of the app sits on a full-screen backdrop (`fixed inset-0`)
 * whose click closes it — about 35 of them. Rather than change each one, this
 * listens to the whole page:
 *   • typing, picking or ticking inside a backdrop marks it « dirty »;
 *   • a click, mousedown or pointerdown landing on a dirty backdrop itself
 *     (not on the window) is stopped before React sees it, and the window
 *     gives a small shake: it stayed open on purpose.
 * The window's own × / « Annuler » / Échap still close it — those are asked
 * for. A window nobody typed in still closes on a tap beside it, as before.
 */

const isBackdrop = (el) => !!(el && el.classList && el.classList.contains('fixed') && el.classList.contains('inset-0'));

function backdropOf(el) {
  for (let p = el; p && p !== document.body; p = p.parentElement) {
    if (isBackdrop(p)) return p;
  }
  return null;
}

const FIELDS = 'input, textarea, select, [contenteditable="true"]';

function nudge(backdrop) {
  const box = backdrop.firstElementChild;
  if (!box || !box.animate) return;
  box.animate(
    [{ transform: 'translateX(0)' }, { transform: 'translateX(-6px)' }, { transform: 'translateX(6px)' },
      { transform: 'translateX(-3px)' }, { transform: 'translateX(0)' }],
    { duration: 260, easing: 'ease-out' },
  );
}

export function markDirty(target) {
  if (!target || !target.matches || !target.matches(FIELDS)) return;
  // looking something up is not filling a form: a search box keeps the tap-beside close
  if (target.type === 'search') return;
  const hint = `${target.getAttribute('placeholder') || ''} ${target.getAttribute('aria-label') || ''}`.trim();
  if (/^rechercher/i.test(hint)) return;
  const b = backdropOf(target);
  if (b) b.dataset.keepInput = '1';
}

export function installKeepInput(win = window) {
  if (!win || win.__fidclicKeepInput) return;
  win.__fidclicKeepInput = true;
  const doc = win.document;
  const mark = (e) => markDirty(e.target);
  doc.addEventListener('input', mark, true);
  doc.addEventListener('change', mark, true);
  const guard = (e) => {
    const t = e.target;
    if (!isBackdrop(t) || t.dataset.keepInput !== '1') return;
    e.stopPropagation();
    e.preventDefault();
    if (e.type === 'click') nudge(t);
  };
  // on the window, capturing: before React's own listeners on the root
  ['pointerdown', 'mousedown', 'click'].forEach((type) => win.addEventListener(type, guard, true));
}
