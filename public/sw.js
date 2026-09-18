/* eslint-disable no-restricted-globals */
/**
 * FidClic service worker.
 *
 * Responsibilities:
 *   1. Receive Web Push payloads from the backend (VAPID-signed)
 *      and display them as native notifications on the customer's device.
 *   2. Open the wallet card (or a deep link) when the user taps a notification.
 *
 * Lives at /sw.js (top-level scope) so it can intercept push events and
 * notification clicks for the entire app.
 *
 * IMPORTANT: keep this file dependency-free. It runs in a worker context with
 * no React, no fetch wrapper, no bundler — just plain ES2015+.
 */

/* ---- Lifecycle: take control of all open clients on first install ------- */
self.addEventListener('install', (event) => {
  // Activate this SW as soon as it's installed; otherwise old clients still
  // talk to the previous version until tabs close.
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

/* ---- Push event: backend just sent us a Web Push payload ---------------- */
self.addEventListener('push', (event) => {
  let payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch (_e) {
    // Backend always sends JSON, but be defensive in case raw text arrives.
    try { payload = { title: 'FidClic', body: event.data.text() }; }
    catch { payload = { title: 'FidClic', body: 'Vous avez un nouveau message.' }; }
  }

  const title = payload.title || 'FidClic';
  const body = payload.body || '';
  const url = payload.url || '/';
  const icon = payload.icon || '/favicon.svg';
  const badge = payload.badge || '/favicon.svg';
  const tag = payload.tag || 'fidelitour';   // collapses similar pushes into one

  event.waitUntil(
    self.registration.showNotification(title, {
      body,
      icon,
      badge,
      tag,
      data: { url },
      // Re-show even if the same tag was used before, so the customer sees
      // updated content (e.g. a new offer with the same campaign tag).
      renotify: !!payload.renotify,
      // Vibration only triggers on phones; ignored elsewhere.
      vibrate: [80, 40, 80],
    })
  );
});

/* ---- Notification click: focus or open the wallet card ------------------ */
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const targetUrl = (event.notification.data && event.notification.data.url) || '/';

  event.waitUntil((async () => {
    const allClients = await self.clients.matchAll({
      type: 'window',
      includeUncontrolled: true,
    });

    // Prefer focusing a tab that's already open on the same origin.
    for (const client of allClients) {
      try {
        const clientUrl = new URL(client.url);
        const targetParsed = new URL(targetUrl, self.location.origin);
        if (clientUrl.origin === targetParsed.origin) {
          await client.focus();
          if ('navigate' in client) {
            try { await client.navigate(targetUrl); } catch (_e) { /* ignored */ }
          }
          return;
        }
      } catch (_e) { /* ignore parse errors and try next client */ }
    }

    // Otherwise open a new tab.
    if (self.clients.openWindow) {
      await self.clients.openWindow(targetUrl);
    }
  })());
});

/* ---- Subscription change: re-subscribe automatically -------------------- */
self.addEventListener('pushsubscriptionchange', (event) => {
  // Browsers fire this when a subscription is invalidated/rotated. We can't
  // re-subscribe from the SW alone (we need the VAPID key from the backend),
  // so notify the page on next open by storing a flag the app can read.
  // The wallet card page resubscribes on load if it sees this flag.
  event.waitUntil((async () => {
    const cache = await caches.open('fidelitour-meta');
    await cache.put(
      '/__push-resubscribe',
      new Response(JSON.stringify({ at: Date.now() }), {
        headers: { 'Content-Type': 'application/json' },
      })
    );
  })());
});
