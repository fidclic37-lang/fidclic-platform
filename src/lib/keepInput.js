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
 * The window's own × / « Annuler » still close it — those are asked for.
 * Échap (QA R7 F36, 2026-10-23: it silently threw the typing away) now asks
 * « Continuer la modification » / « Abandonner » first. A window nobody typed
 * in still closes on a tap beside it, or on Échap, as before.
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
  win.addEventListener('keydown', (e) => escapeGuard(win, e), true);
}

/* Échap over a window with unsaved typing: a small question first. « Abandonner »
   replays the Échap so the window closes the way it always did. */
function topDirty(doc) {
  const all = doc.querySelectorAll('.fixed.inset-0[data-keep-input="1"]');
  return all.length ? all[all.length - 1] : null;
}

function escapeGuard(win, e) {
  if (e.key !== 'Escape' || win.__fidclicEscapeOk) return;
  const doc = win.document;
  if (doc.getElementById('fc-discard-ask')) {        // the question is open: Échap = keep editing
    e.stopImmediatePropagation(); e.preventDefault();
    doc.getElementById('fc-discard-ask').remove();
    return;
  }
  const backdrop = topDirty(doc);
  if (!backdrop) return;
  e.stopImmediatePropagation();
  e.preventDefault();
  const from = e.target;
  askDiscard(doc, () => {
    delete backdrop.dataset.keepInput;
    win.__fidclicEscapeOk = true;
    try {
      (from && from.isConnected ? from : backdrop).dispatchEvent(new win.KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', bubbles: true, cancelable: true }));
    } finally { win.__fidclicEscapeOk = false; }
  }, () => { if (from && from.focus) from.focus(); nudge(backdrop); });
}

function askDiscard(doc, onDiscard, onKeep) {
  const wrap = doc.createElement('div');
  wrap.id = 'fc-discard-ask';
  wrap.setAttribute('role', 'alertdialog');
  wrap.setAttribute('aria-modal', 'true');
  wrap.setAttribute('aria-label', 'Modifications non enregistrées');
  // inline styles, not « fixed inset-0 »: this is not one of the app's windows
  wrap.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;z-index:2147483000;display:flex;align-items:center;justify-content:center;background:rgba(11,28,63,.35)';
  wrap.innerHTML = `
    <div style="width:min(92vw,400px);border-radius:16px;background:#fff;padding:20px;box-shadow:0 24px 60px -20px rgba(11,28,63,.45);font-family:inherit">
      <p style="margin:0;font-size:16px;font-weight:700;color:#0B1C3F">Abandonner les modifications ?</p>
      <p style="margin:8px 0 18px;font-size:13.5px;line-height:1.5;color:#475569">Ce que vous avez saisi n'est pas enregistré.</p>
      <div style="display:flex;justify-content:flex-end;gap:8px">
        <button type="button" data-a="keep" style="height:40px;padding:0 14px;border-radius:10px;border:0;background:#2F6BFF;color:#fff;font-weight:600;font-size:13.5px;cursor:pointer">Continuer la modification</button>
        <button type="button" data-a="discard" style="height:40px;padding:0 14px;border-radius:10px;border:1px solid #F5C2C2;background:#fff;color:#B91C1C;font-weight:600;font-size:13.5px;cursor:pointer">Abandonner</button>
      </div>
    </div>`;
  const close = () => wrap.remove();
  wrap.addEventListener('click', (ev) => {
    const a = ev.target && ev.target.getAttribute && ev.target.getAttribute('data-a');
    ev.stopPropagation();
    if (a === 'discard') { close(); onDiscard(); } else if (a === 'keep' || ev.target === wrap) { close(); onKeep(); }
  });
  doc.body.appendChild(wrap);
  const keep = wrap.querySelector('[data-a="keep"]');
  if (keep) keep.focus();
}
