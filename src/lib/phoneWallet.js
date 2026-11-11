/* Which Wallet(s) this phone can hold (user, 2026-10-13; Samsung 2026-11-11).
   An iPhone: Apple's. An Android phone: Google's — and Samsung's, since
   Chrome on a Galaxy hides the model (« Android 10; K »), so any Android phone
   may be one; Samsung Internet or an « SM- » model says it is. A computer or
   another phone: none. Pure, unit-tested (node --test src/lib/phoneWallet.test.js). */
const isApple = (ua, touch) => /iPad|iPhone|iPod/.test(ua) || (/Macintosh/.test(ua) && touch > 1);
const isGalaxy = (ua) => /SamsungBrowser|SM-[A-Z0-9]/.test(ua);

export function phoneWallet(ua = navigator.userAgent, touch = navigator.maxTouchPoints || 0) {
  if (isApple(ua, touch)) return 'apple';
  if (/Android/.test(ua)) return 'google';
  return null;
}

export function phoneWallets(ua = navigator.userAgent, touch = navigator.maxTouchPoints || 0) {
  if (isApple(ua, touch)) return ['apple'];
  if (/Android/.test(ua)) return isGalaxy(ua) ? ['samsung', 'google'] : ['google', 'samsung'];
  return [];
}

export function walletOrder(ua = navigator.userAgent, touch = navigator.maxTouchPoints || 0) {
  const own = phoneWallets(ua, touch);
  return [...own, ...['apple', 'google', 'samsung'].filter((k) => !own.includes(k))];
}
