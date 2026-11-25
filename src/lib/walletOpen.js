/**
 * « Ajouter à Apple Wallet », then that card on the iPhone (user, 2026-11-25:
 * « wohi card dikhe, not other cards, aur itne steps n ho »).
 *
 * Safari hands the pass to iOS; iOS adds it and comes back to the page — it
 * never opens the Wallet app, and never tells the page. No web page may open
 * Wallet at one card (Apple, Developer Forums 811976, June 2026); shoebox://
 * opened it on the other cards, so it is gone. The iPhone does tell our server
 * the moment the card is in its Wallet: the page waits for that word
 * (GET /api/card/<id>/apple-wallet/added) and says « Carte ajoutée », and the
 * server rings the card's own « Bienvenue » banner, which opens that card.
 *
 * The card's key rides on every link here: a card's key kept only in the
 * phone's memory was gone by the tap once (Soan, Royal Trim Liberté,
 * 2026-11-25: five « Ajouter » taps refused, 403).
 */

// ask every 2 s, for 90 s at most: the sheet is read, « Ajouter » is tapped,
// the iPhone links the card within seconds of that
export const WAIT = { every: 2000, until: 90_000 };

const CARD = /^FT-[A-Z0-9]+$/;
const cardOf = (barcodeId) => {
  const bc = String(barcodeId || '').trim().toUpperCase();
  return CARD.test(bc) ? bc : null;
};

/** The pass itself, with the card's key when there is one. */
export function passHref(barcodeId, key) {
  const bc = cardOf(barcodeId);
  if (!bc) return null;
  return `/api/card/${bc}/apple-wallet.pkpass${key ? `?k=${encodeURIComponent(key)}` : ''}`;
}

/** The add page — opened in Safari from another app or browser, it shows the
 *  Wallet sheet at once. Never without the key: Safari could not add it. */
export function addPageHref(origin, barcodeId, key) {
  const bc = cardOf(barcodeId);
  const base = String(origin || '').replace(/\/+$/, '');
  if (!bc || !key || !/^https?:\/\/[^/]+$/i.test(base)) return null;
  return `${base}/card/${bc}/ajouter?k=${encodeURIComponent(key)}`;
}

const realSleep = (ms) => new Promise((ok) => { setTimeout(ok, ms); });

/** true once ask() answers exactly true; false when the time is up or
 *  cancelled() says so. No question while the page is hidden (hidden()), and
 *  a question that fails (offline) is not an answer. */
export async function waitForAppleAdd({
  ask, every = WAIT.every, until = WAIT.until,
  sleep = realSleep, now = () => Date.now(),
  hidden = () => false, cancelled = () => false,
}) {
  const start = now();
  while (now() - start < until) {
    await sleep(every);                       // the sheet is still open at first
    if (cancelled()) return false;
    if (hidden()) continue;
    try {
      if ((await ask()) === true) return true;
    } catch (_e) { /* not an answer: ask again */ }
    if (cancelled()) return false;
  }
  return false;
}
