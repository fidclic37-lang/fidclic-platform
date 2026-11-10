// Where a ⋮ menu's top goes (features: lib/anchoredMenu.js). Pure, no imports:
// the e2e suite checks it on its own.

export const GAP = 4;
export const EDGE = 8;

/** Where the menu's top goes, in the app's pixels. */
export function placeMenu({ anchorTop, anchorBottom, height, viewH: vh }) {
  const top0 = Number(anchorTop) || 0;
  const bottom0 = Number(anchorBottom) || 0;
  const h = Math.max(0, Number(height) || 0);
  const H = Math.max(0, Number(vh) || 0);
  let top = bottom0 + GAP;                                 // below
  if (top + h > H - EDGE) top = top0 - GAP - h;            // above
  if (top < EDGE) top = Math.max(EDGE, H - h - EDGE);      // neither: as high as it needs
  return top;
}
