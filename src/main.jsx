import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App.jsx';

// Browser translation (Chrome « Traduire », Edge, Safari) — wanted by the user
// (2026-10-01). Those tools wrap the page's text in <font> elements; React
// then tries to remove or insert next to a node that is no longer where it
// left it and the page crashes (« Failed to execute 'removeChild' on 'Node' »).
// The well-known guard: if the node moved, let the operation pass quietly.
if (typeof Node === 'function' && Node.prototype && !Node.prototype.__fcTranslateSafe) {
  const removeChild = Node.prototype.removeChild;
  Node.prototype.removeChild = function patchedRemoveChild(child) {
    if (child && child.parentNode !== this) {
      if (child.parentNode) return child.parentNode.removeChild(child);
      return child;
    }
    return removeChild.call(this, child);
  };
  const insertBefore = Node.prototype.insertBefore;
  Node.prototype.insertBefore = function patchedInsertBefore(newNode, ref) {
    if (ref && ref.parentNode !== this) return insertBefore.call(this, newNode, null);
    return insertBefore.call(this, newNode, ref);
  };
  Node.prototype.__fcTranslateSafe = true;
}
import './index.css';
// Initialise the translation layer BEFORE the React tree mounts so the
// first paint already shows the chosen language. The import has the
// side effect of bootstrapping i18next with FR/EN/AR resources.
import './lib/i18n';

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
