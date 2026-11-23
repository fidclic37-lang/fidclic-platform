// Run: node --test src/lib/chartPoint.test.js
// « Une erreur d'affichage » on the Tableau de bord (user, 2026-11-23): the
// cursor rested on point 20 of « Ce mois-ci », the owner picked « 7 derniers
// jours », and the chart drew the 7 new points while still pointing at the
// 20th — pts[20] is undefined, .value crashed the whole page. The point the
// chart shows is now read through these, never by a raw index.
import test from 'node:test';
import assert from 'node:assert/strict';
import { activeIndex, cleanSeries } from './chartPoint.js';

test('activeIndex: a pinned point wins over the hovered one', () => {
  assert.equal(activeIndex(10, 3, 7), 3);
  assert.equal(activeIndex(10, null, 7), 7);
  assert.equal(activeIndex(10, null, null), null);
});

test('activeIndex: an index from the previous, longer series is dropped', () => {
  assert.equal(activeIndex(7, null, 20), null);      // the crash of 2026-11-23
  assert.equal(activeIndex(7, 20, null), null);
  assert.equal(activeIndex(7, 7, null), null);       // one past the end
  assert.equal(activeIndex(7, 6, null), 6);          // the last one is fine
});

test('activeIndex: a stale pinned index falls back to a valid hover', () => {
  assert.equal(activeIndex(7, 20, 2), 2);
});

test('activeIndex: empty series, negatives and non-integers give nothing', () => {
  assert.equal(activeIndex(0, 0, 0), null);
  assert.equal(activeIndex(5, -1, null), null);
  assert.equal(activeIndex(5, null, 1.5), null);
  assert.equal(activeIndex(5, '2', null), null);
  assert.equal(activeIndex(5, undefined, undefined), null);
  assert.equal(activeIndex(undefined, 1, 1), null);
});

test('cleanSeries: keeps the points, drops what is not a point', () => {
  const a = { date: '2026-11-01', value: 3 };
  const b = { label: '9h', value: 0 };
  assert.deepEqual(cleanSeries([a, null, undefined, 'x', 4, b]), [a, b]);
});

test('cleanSeries: anything that is not a list is an empty list', () => {
  for (const v of [undefined, null, {}, 'abc', 12, { length: 2 }]) assert.deepEqual(cleanSeries(v), [], String(v));
});

test('cleanSeries: the same list comes back when nothing is dropped', () => {
  const s = [{ date: '2026-11-01', value: 1 }];
  assert.equal(cleanSeries(s), s);                   // no new array → no needless redraw
});
