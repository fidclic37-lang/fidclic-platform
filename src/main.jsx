import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App.jsx';

// Number fields (user, 2026-10-02): a field holding 0 kept its 0 when the
// person typed (« 0878 »), on every number field of the app (82 of them).
// Before React reads the keystroke, leading zeros go: « 0878 » → « 878 »,
// « 05 » → « 5 » (« 0 » alone and « 0,5 » stay). The value is written with
// the browser's own setter so React still sees the change and keeps its
// state in step.
if (typeof document !== 'undefined' && typeof HTMLInputElement === 'function') {
  const nativeValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
  // Codes are not quantities (2026-10-09): a postal code (06000 Nice), a
  // one-time code (012345), a SIRET or a phone number keeps its zeros. They
  // are recognised by their autocomplete, a fixed length (maxlength), or an
  // explicit data-keep-zeros.
  const KEEP = ['one-time-code', 'postal-code', 'tel', 'tel-national'];
  const isCode = (el) => el.hasAttribute('data-keep-zeros') || el.maxLength > 0
    || KEEP.includes((el.getAttribute('autocomplete') || '').toLowerCase());
  const numeric = (el) => el instanceof HTMLInputElement && !isCode(el)
    && (el.type === 'number' || ['numeric', 'decimal'].includes((el.getAttribute('inputmode') || '').toLowerCase()));
  document.addEventListener('input', (e) => {
    const el = e.target;
    if (!numeric(el) || !nativeValue?.set) return;
    const v = el.value;
    const clean = typeof v === 'string' ? v.replace(/^(-?)0+(?=\d)/, '$1') : v;
    if (clean !== v) nativeValue.set.call(el, clean);
  }, true);
}

// Browser translation (Chrome « Traduire », Edge, Safari) — wanted by the user
// (2026-10-01). Those tools put each text of the page into <font> elements
// holding the translation; React still points at its own text node. When
// React then removes or changes that text (« Chargement… » once the page has
// loaded, a figure after a new period), the translation was left on screen
// (2026-10-02, and again 2026-10-03 on the live site).
//
// The translator's exact steps are not documented, so every way it can do it
// is covered — each one links React's text node to the <font> showing it:
//   1. the text node replaced by the <font>, in one step;
//   2. the <font> inserted next to the text node, then the text node removed;
//   3. the text node moved inside the <font>;
//   4. the text node left in place, emptied, with the <font> beside it.
// Removing a text node removes its <font>; a text React changes is put back
// in place of its stale <font>, and the browser translates it again.
// (Loaders also carry key="loading", so React drops the whole element.)
if (typeof Node === 'function' && Node.prototype && !Node.prototype.__fcTranslateSafe) {
  const isFont = (n) => !!n && n.nodeName === 'FONT';
  const stand = new WeakMap();                   // text node → the <font> nodes showing it
  const link = (text, fonts) => {
    const list = fonts.filter(isFont);
    if (!list.length) return;
    const had = stand.get(text) || [];
    stand.set(text, [...had, ...list.filter((f) => !had.includes(f))]);
  };
  // Each link is made from the mutation record itself (a snapshot taken when
  // the translator acted), never from the live neighbours — a sentence made of
  // several React texts (« {pct} % de votre CA ({ca}) ») has translated
  // neighbours that are NOT this text's translation.
  const note = (records) => {
    for (const r of records) {
      if (r.type !== 'childList') continue;
      const fonts = [...r.addedNodes].filter(isFont);
      const texts = [...r.removedNodes].filter((n) => n.nodeType === 3);
      if (texts.length && fonts.length) {                       // 1. replaced in one step
        texts.forEach((t) => link(t, fonts));
        continue;
      }
      if (fonts.length && r.nextSibling && r.nextSibling.nodeType === 3) {
        link(r.nextSibling, fonts);                             // 2./3./4. <font> put just before its text
      }
      for (const t of texts) {                                  // 3. text moved inside its <font>
        if (!isFont(t.parentNode)) continue;
        let f = t.parentNode;
        while (isFont(f.parentNode)) f = f.parentNode;
        link(t, [f]);
      }
    }
  };
  let watcher = null;
  if (typeof MutationObserver === 'function') {
    watcher = new MutationObserver(note);
    watcher.observe(document.documentElement, { childList: true, subtree: true });
  }
  const standIns = (node) => {
    if (watcher) note(watcher.takeRecords());
    return (stand.get(node) || []).filter((f) => f.parentNode && f !== node && !f.contains(node));
  };
  const outerFont = (node, parent) => {         // 3. the <font> (inside `parent`) holding a moved text node
    let f = node.parentNode;
    if (!isFont(f)) return null;
    while (f && f.parentNode !== parent && isFont(f.parentNode)) f = f.parentNode;
    return f && f.parentNode === parent ? f : null;
  };

  const removeChild = Node.prototype.removeChild;
  Node.prototype.removeChild = function patchedRemoveChild(child) {
    if (child && child.nodeType === 3) {
      for (const f of standIns(child)) removeChild.call(f.parentNode, f);
      if (child.parentNode !== this) {
        const f = outerFont(child, this);
        if (f) { removeChild.call(this, f); return child; }
      }
    }
    if (child && child.parentNode !== this) {
      if (child.parentNode) return removeChild.call(child.parentNode, child);
      return child;
    }
    return removeChild.call(this, child);
  };
  const insertBefore = Node.prototype.insertBefore;
  Node.prototype.insertBefore = function patchedInsertBefore(newNode, ref) {
    if (ref && ref.parentNode !== this) {
      const f = standIns(ref).find((x) => x.parentNode === this) || (ref.nodeType === 3 ? outerFont(ref, this) : null);
      return insertBefore.call(this, newNode, f || null);
    }
    return insertBefore.call(this, newNode, ref);
  };
  // A text React changes after translation: written into its own node, off
  // screen or emptied. Put it back in place of its stale translation; the
  // browser translates it again.
  const value = Object.getOwnPropertyDescriptor(Node.prototype, 'nodeValue');
  if (value && value.set) {
    Object.defineProperty(Node.prototype, 'nodeValue', {
      ...value,
      set(v) {
        value.set.call(this, v);
        if (this.nodeType !== 3) return;
        const fonts = standIns(this);
        const moved = !this.parentNode ? null : (isFont(this.parentNode) ? this.parentNode : null);
        if (!fonts.length && !moved) return;
        const anchor = fonts[0] || (() => { let f = moved; while (isFont(f.parentNode)) f = f.parentNode; return f; })();
        if (!anchor.parentNode) return;
        insertBefore.call(anchor.parentNode, this, anchor);
        for (const f of [...fonts, anchor]) if (f.parentNode && f !== this) removeChild.call(f.parentNode, f);
      },
    });
  }
  Node.prototype.__fcTranslateSafe = true;
}
import './index.css';
// Initialise the translation layer BEFORE the React tree mounts so the
// first paint already shows the chosen language. The import has the
// side effect of bootstrapping i18next with FR/EN/AR resources.
import './lib/i18n';
import { installKeepInput } from './lib/keepInput';
import { installCleanEmail } from './lib/cleanEmail';

// a window with something typed in it never closes on a tap beside it (QA BUG-003 / BUG-007)
installKeepInput();
// an e-mail field drops the invisible characters a copied address brings along
installCleanEmail();

// ───────────────────────────────────────────────────────────────────────
// PWA launch failsafe — runs BEFORE React renders, so it never flashes
// the landing page.
//
// Why: on some iOS versions the home-screen icon ignores the per-card
// manifest's start_url and just opens the site root ("/"). When that
// happens, the customer sees the landing page instead of their card —
// which is exactly the bug the user reported.
//
// Recovery: if we're running in standalone display-mode (i.e. launched
// from a PWA icon, not a browser tab) AND the URL we landed on is the
// root, AND we previously stored which card this device was used for
// (MyWalletCardPage writes 'fidelitour:last_card' on visit), then
// SYNCHRONOUSLY rewrite the URL to /card/<barcode> before React mounts.
//
// Uses history.replaceState so React Router picks up the right path on
// first render and the customer never sees an intermediate flash.
// ───────────────────────────────────────────────────────────────────────
(function pwaLaunchFailsafe() {
  try {
    const isStandalone =
      window.matchMedia?.('(display-mode: standalone)').matches ||
      // iOS Safari-specific. matchMedia returns false for installed PWAs
      // on older iOS — we have to read this non-standard navigator flag.
      window.navigator.standalone === true;
    if (!isStandalone) return;
    if (window.location.pathname !== '/' && window.location.pathname !== '') return;
    const lastCard = localStorage.getItem('fidelitour:last_card');
    if (!lastCard || !/^FT-?[A-Z0-9]+$/i.test(lastCard)) return;
    // Replace (not push) so the back button doesn't return to "/".
    window.history.replaceState({}, '', `/card/${lastCard}`);
  } catch (_e) {
    // localStorage blocked / no matchMedia — fall through to normal boot.
  }
})();

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);

// ---------------------------------------------------------------------------
// PWA service-worker registration.
//
// Why we do it from main.jsx (not the SW itself):
//   - The SW lives at /sw.js (top-level scope), but it doesn't register itself.
//     The page must call navigator.serviceWorker.register() once on load.
//   - Without this, push notifications never fire because there's no active
//     SW to receive the push event.
//
// The SW is required for:
//   1. Receiving Web Push payloads (even when the tab is closed).
//   2. iOS PWA push (only works once the page is added to home screen AND
//      a SW is registered — both are non-negotiable on iOS Safari).
//   3. Offline-shell-style "open the wallet card even on flaky LTE".
//
// We register on the first page-load 'load' event so it doesn't compete with
// initial paint. We also no-op gracefully on browsers without SW support
// (very old Safari / desktop IE-equivalents).
// ---------------------------------------------------------------------------
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker
      .register('/sw.js', { scope: '/' })
      .then((reg) => {
        // Re-check for SW updates whenever the user comes back to the tab.
        // This way a deploy that ships a new sw.js is picked up without the
        // user having to hard-reload.
        document.addEventListener('visibilitychange', () => {
          if (document.visibilityState === 'visible') {
            reg.update().catch(() => {});
          }
        });
      })
      .catch((err) => {
        // Don't crash the app if SW registration fails — push just won't work.
        // eslint-disable-next-line no-console
        console.warn('[FidClic] Service worker registration failed:', err);
      });
  });
}
