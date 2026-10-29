/**
 * Groupe témoin — how many of a send of `n` clients are kept out, the same
 * rule as the server (api/features/temoin.py hold_count, user 2026-10-29):
 * 15 %, at least 4, never more than half, nobody under 3 clients.
 * 3→1, 4–5→2, 6–7→3, 8–26→4, 27+→15 %.
 */
export function holdCount(n, share = 15, min = 4) {
  const count = Math.floor(Number(n) || 0);
  if (count < 3) return 0;
  return Math.min(Math.max(min, Math.floor((count * share) / 100)), Math.floor(count / 2));
}

/** The real share a send keeps out, for « (27 %, tirés au hasard) ». */
export function heldPct(held, count) {
  return count > 0 ? Math.round((held * 100) / count) : 0;
}
