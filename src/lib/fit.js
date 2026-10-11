// « Même affichage partout » (index.html): the app may be zoomed to fit the
// window. A position read with getBoundingClientRect is then on screen
// pixels, while a `position: fixed` popup is placed in the app's own pixels.
// These helpers convert — measuring the scale the browser really applies, so
// they hold in every engine (one that reports unscaled boxes gives a ratio
// of 1 and needs no conversion).

export const fitZoom = () => Number(typeof window !== 'undefined' && window.__fitZoom) || 1;

/** The element's box in the app's own pixels. */
export function fitRect(el) {
  const r = el.getBoundingClientRect();
  const k = el.offsetWidth ? r.width / el.offsetWidth : fitZoom();
  const s = k > 0 ? k : 1;
  return { top: r.top / s, left: r.left / s, right: r.right / s, bottom: r.bottom / s, width: r.width / s, height: r.height / s };
}

/** The window's size in the app's own pixels (the browser reports it on
 *  screen pixels, whatever the zoom). */
export const viewW = () => (document.documentElement.clientWidth || window.innerWidth) / fitZoom();
export const viewH = () => (document.documentElement.clientHeight || window.innerHeight) / fitZoom();

/** n vh / vw for inline styles (Tailwind classes are rewritten at build time). */
export const vh = (n) => `calc(${n} * var(--fit-vh, 1vh))`;
