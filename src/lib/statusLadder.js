/* Règles clients › the two ladders (user, 2026-11-25).

   A client's one Statut is read from the time line first (how long since the
   last visit), then from the owner's mixed rules, then from frequency. On the
   time line each step only says where it starts; the server works out where
   it ends (the day before the next step) and sends it as `range`. These
   helpers turn that into words and suggest where a new step could start. */

const fr = (n) => String(n).replace('.', ',');
const plural = (n, one, many) => (Number(n) <= 1 ? one : many);

export function rangeText(rule) {
  if (!rule) return '';
  if (rule.enabled === false) return 'Désactivée';
  const r = rule.range;
  if (!r) return '';
  if (rule.group === 'absence') {
    if (r.to === null || r.to === undefined) return `${r.from} jours et plus`;
    if (r.to === r.from) return `${r.from} ${plural(r.from, 'jour', 'jours')}`;
    return `${r.from} – ${r.to} jours`;
  }
  if (r.max !== undefined) {
    if (Number(r.max) === 0) return 'Aucune visite';
    return `${fr(r.max)} ${plural(r.max, 'visite', 'visites')} ou moins`;
  }
  if (r.from !== undefined) return `${fr(r.from)} ${plural(r.from, 'visite', 'visites')} / mois et plus`;
  return '';
}

export function impactText(preview) {
  if (!preview || typeof preview.changed !== 'number') return '';
  const { changed, moves = [] } = preview;
  if (!changed) return 'Aucun client ne change de statut.';
  if (moves.length === 1) {
    const m = moves[0];
    return `${changed} ${plural(changed, 'client passe', 'clients passent')} de « ${m.from_label} » à « ${m.to_label} ».`;
  }
  const shown = moves.slice(0, 2).map((m) => `${m.count} de « ${m.from_label} » à « ${m.to_label} »`).join(', ');
  return `${changed} clients changent de statut : ${shown}${moves.length > 2 ? '…' : '.'}`;
}

const tenth = (x) => Math.round(x * 10) / 10;

/** Where a new step could start without landing on another one. */
export function suggestStart(rules, group) {
  const live = (rules || []).filter((r) => r.group === group && r.enabled !== false && r.range);
  if (group === 'absence') {
    const steps = live.filter((r) => r.key !== 'actif' && r.range.from !== undefined);
    const closed = steps.filter((r) => r.range.to !== null && r.range.to !== undefined && r.range.to > r.range.from)
      .sort((a, b) => (b.range.to - b.range.from) - (a.range.to - a.range.from));
    if (closed.length) {
      const { from, to } = closed[0].range;
      return from + Math.ceil((to - from) / 2);
    }
    const open = steps.find((r) => r.range.to === null || r.range.to === undefined);
    return open ? open.range.from + 30 : 60;
  }
  const starts = live.filter((r) => r.key !== 'nouveau' && r.range.from !== undefined)
    .map((r) => Number(r.range.from)).sort((a, b) => a - b);
  if (!starts.length) return 6;
  if (starts.length === 1) return tenth(starts[0] * 2);
  let best = [starts[0], starts[1]];
  for (let i = 1; i < starts.length - 1; i += 1) {
    if (starts[i + 1] - starts[i] > best[1] - best[0]) best = [starts[i], starts[i + 1]];
  }
  return tenth((best[0] + best[1]) / 2);
}

/** A new owner step: one condition of its ladder. */
export function newStep(group, value) {
  return group === 'absence'
    ? { key: null, name: '', icon: 'clock', tone: 'amber', description: '', enabled: true,
        conditions: [{ type: 'not_visited_since', value }] }
    : { key: null, name: '', icon: 'trending-up', tone: 'violet', description: '', enabled: true,
        conditions: [{ type: 'visits_per_month', value }] };
}
