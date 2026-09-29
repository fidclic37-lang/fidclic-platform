/* Charts animate when a page opens — never when it is merely resized.

   Recharts replays a series' entrance animation from zero every time its
   container changes size. A full-page screenshot resizes the window to the
   whole page and captures at once, so pies and bars came out empty (and
   lines without their path). The same happened on any window resize or
   sidebar toggle. Series ask `chartAnimation()` instead of animating always:
   true for a short while after a page opens, false afterwards, so a later
   resize draws the finished chart straight away. */
const INTRO_MS = 2000;
const clock = () => (typeof performance !== 'undefined' ? performance.now() : Date.now());
let openedAt = clock();

/** Called by the dashboard shell whenever the route changes. */
export function markPageOpened() {
  openedAt = clock();
}

export function chartAnimation() {
  return clock() - openedAt < INTRO_MS;
}
