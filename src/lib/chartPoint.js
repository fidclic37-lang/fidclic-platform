/**
 * Which point a chart shows under the cursor, read safely.
 *
 * 2026-11-23, « Une erreur d'affichage est survenue » on the Tableau de bord:
 * the cursor rested on day 20 of a 30-day chart, the owner picked « 7
 * derniers jours », and React drew the 7 new points while the chart still
 * held « index 20 » — pts[20] was undefined and reading .value took the page
 * down. The reset ran in an effect, one paint too late. A chart now asks
 * activeIndex() during the render, so an index from another series is never
 * read, whatever the order of events.
 */

const ok = (i, n) => Number.isInteger(i) && i >= 0 && i < n;

/** The index to show: the pinned one, else the hovered one — only if it is
 *  a point of THIS series; otherwise null. */
export function activeIndex(length, pinned, hover) {
  const n = Number.isInteger(length) ? length : 0;
  if (ok(pinned, n)) return pinned;
  if (ok(hover, n)) return hover;
  return null;
}

/** The series as a list of point objects: anything else (null, a string, an
 *  answer that is not a list) is left out. The same list is returned when
 *  nothing is dropped, so the chart does not redraw for nothing. */
export function cleanSeries(series) {
  if (!Array.isArray(series)) return [];
  const isPoint = (p) => p !== null && typeof p === 'object' && !Array.isArray(p);
  return series.every(isPoint) ? series : series.filter(isPoint);
}
