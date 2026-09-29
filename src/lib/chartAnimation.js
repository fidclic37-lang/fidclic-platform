/* Charts are drawn finished — no entrance animation.

   Recharts replays a series' entrance animation from zero whenever the chart
   is re-laid out. Full-page screenshot tools resize the window (sometimes the
   width too, which collapses the sidebar and rebuilds the layout) and capture
   straight away, so pies and bars came out empty and lines without their
   path. Animating only for a moment after a page opened was not enough: a
   rebuilt layout counts as a page opening. A chart that is always drawn
   complete is right in every screenshot, on every resize, and in print.

   Every Recharts series asks `chartAnimation()`, so this is the one switch. */
export function markPageOpened() {
  // Kept for the dashboard shell's call; nothing to time any more.
}

export function chartAnimation() {
  return false;
}
