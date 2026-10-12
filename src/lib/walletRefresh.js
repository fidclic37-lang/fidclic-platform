import { ownerAPI } from './api';

/**
 * Wallet cards still waiting after a save (2026-10-13). A save sends what it
 * can in a few seconds and queues the rest (api/features/wallet_passes
 * .queue_refresh) — renaming an establishment used to wait for every card
 * and end in « erreur 504 ». The page sends the rest right after, in the
 * background, a few seconds per call, until nothing is left.
 */
let running = false;
let timer = null;

export async function drainWallet() {
  if (running) return;
  running = true;
  try {
    for (let i = 0; i < 30; i += 1) {
      // eslint-disable-next-line no-await-in-loop
      const { data } = await ownerAPI.walletRefresh();
      if (!data?.left) break;
    }
  } catch (_e) {
    /* the daily run sends what is left */
  } finally {
    running = false;
  }
}

// a burst of saves → one follow-up
export function kickWallet(delay = 800) {
  if (timer) clearTimeout(timer);
  timer = setTimeout(() => { timer = null; drainWallet(); }, delay);
}
