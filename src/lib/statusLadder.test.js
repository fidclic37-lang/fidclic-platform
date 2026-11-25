// Règles clients › the two ladders (user, 2026-11-25): what each step says.
// Run: node --test src/lib/statusLadder.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { rangeText, impactText, suggestStart, newStep } from './statusLadder.js';

const abs = (range, enabled = true) => ({ group: 'absence', enabled, range });
const fq = (range, enabled = true, key = null) => ({ group: 'frequency', enabled, range, key });

test('an absence step reads its days', () => {
  assert.equal(rangeText(abs({ from: 0, to: 30 })), '0 – 30 jours');
  assert.equal(rangeText(abs({ from: 31, to: 44 })), '31 – 44 jours');
  assert.equal(rangeText(abs({ from: 180, to: null })), '180 jours et plus');
  assert.equal(rangeText(abs({ from: 45, to: 45 })), '45 jours');
  assert.equal(rangeText(abs({ from: 1, to: 1 })), '1 jour');
});

test('a frequency step reads its visits a month, French decimals', () => {
  assert.equal(rangeText(fq({ from: 6 })), '6 visites / mois et plus');
  assert.equal(rangeText(fq({ from: 2.5 })), '2,5 visites / mois et plus');
  assert.equal(rangeText(fq({ from: 1 })), '1 visite / mois et plus');
  assert.equal(rangeText(fq({ max: 1 }, true, 'nouveau')), '1 visite ou moins');
  assert.equal(rangeText(fq({ max: 3 }, true, 'nouveau')), '3 visites ou moins');
  assert.equal(rangeText(fq({ max: 0 }, true, 'nouveau')), 'Aucune visite');
});

test('no range: switched off, a mixed rule, or nothing', () => {
  assert.equal(rangeText(abs(null, false)), 'Désactivée');
  assert.equal(rangeText({ group: 'custom', enabled: true, range: null }), '');
  assert.equal(rangeText(null), '');
  assert.equal(rangeText(abs(undefined)), '');
});

test('the impact of a change, in one sentence', () => {
  assert.equal(impactText({ changed: 0, moves: [] }), 'Aucun client ne change de statut.');
  assert.equal(impactText({ changed: 1, moves: [{ from_label: 'A', to_label: 'B', count: 1 }] }),
    '1 client passe de « A » à « B ».');
  assert.equal(impactText({ changed: 23, moves: [{ from_label: 'Client bientôt perdu', to_label: 'À relancer', count: 23 }] }),
    '23 clients passent de « Client bientôt perdu » à « À relancer ».');
  assert.equal(impactText({
    changed: 30,
    moves: [{ from_label: 'A', to_label: 'B', count: 20 }, { from_label: 'C', to_label: 'B', count: 7 },
      { from_label: 'D', to_label: 'B', count: 3 }],
  }), '30 clients changent de statut : 20 de « A » à « B », 7 de « C » à « B »…');
  assert.equal(impactText(null), '');
  assert.equal(impactText({}), '');
});

test('a new step starts in the middle of the widest closed range', () => {
  const rules = [
    { group: 'absence', enabled: true, key: 'actif', range: { from: 0, to: 30 } },
    { group: 'absence', enabled: true, key: 'bientot_perdu', range: { from: 31, to: 89 } },
    { group: 'absence', enabled: true, key: 'dormant', range: { from: 90, to: null } },
    { group: 'frequency', enabled: true, key: 'nouveau', range: { max: 1 } },
    { group: 'frequency', enabled: true, key: 'regulier', range: { from: 2 } },
    { group: 'frequency', enabled: true, key: 'fidele', range: { from: 4 } },
    { group: 'frequency', enabled: true, key: 'vip', range: { from: 8 } },
  ];
  assert.equal(suggestStart(rules, 'absence'), 60);          // 31 – 89 → 60, never inside Actif
  assert.equal(suggestStart(rules, 'frequency'), 6);         // between 4 and 8
  // only Dormant left open: one month after it
  assert.equal(suggestStart([{ group: 'absence', enabled: true, key: 'dormant', range: { from: 90, to: null } }], 'absence'), 120);
  // a single frequency step: twice it
  assert.equal(suggestStart([{ group: 'frequency', enabled: true, key: 'fidele', range: { from: 4 } }], 'frequency'), 8);
  // nothing at all
  assert.equal(suggestStart([], 'absence'), 60);
  assert.equal(suggestStart([], 'frequency'), 6);
  // a range of one day cannot be split: the next wider one is used
  assert.equal(suggestStart([
    { group: 'absence', enabled: true, key: 'actif', range: { from: 0, to: 30 } },
    { group: 'absence', enabled: true, key: 'bientot_perdu', range: { from: 31, to: 31 } },
    { group: 'absence', enabled: true, key: 'x', range: { from: 32, to: 89 } },
    { group: 'absence', enabled: true, key: 'dormant', range: { from: 90, to: null } },
  ], 'absence'), 61);
  // switched-off steps leave no range and are ignored
  assert.equal(suggestStart([{ group: 'absence', enabled: false, key: 'dormant', range: null }], 'absence'), 60);
});

test('a new step is one condition of its ladder', () => {
  const s = newStep('absence', 45);
  assert.deepEqual(s.conditions, [{ type: 'not_visited_since', value: 45 }]);
  assert.equal(s.key, null);
  assert.equal(s.enabled, true);
  const f = newStep('frequency', 6);
  assert.deepEqual(f.conditions, [{ type: 'visits_per_month', value: 6 }]);
  assert.notEqual(s.icon, f.icon);
});
