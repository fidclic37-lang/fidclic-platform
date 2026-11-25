/**
 * « Ajouter à Apple Wallet », then the Wallet opens (user, 2026-11-25: the
 * card was added, the Wallet app never opened).
 *
 * Safari hands the pass to iOS; iOS adds it and comes back to Safari — it
 * never opens the Wallet app, and never tells the page. The iPhone does tell
 * our server: it links itself to the card the moment the card is in its
 * Wallet (GET /api/card/<id>/apple-wallet/added). The page waits for that word,
 * then opens the Wallet app.
 *
 * shoebox:// is the Wallet app's own address. Apple does not document it (no
 * web page can open Wallet in a supported way); it is what opens it today.
 */
export const APPLE_WALLET_APP = 'shoebox://';

// ask every 2 s, for 90 s at most: the sheet is read, « Ajouter » is tapped,
// the iPhone links the card within seconds of that
export const WAIT = { every: 2000, until: 90_000 };

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
