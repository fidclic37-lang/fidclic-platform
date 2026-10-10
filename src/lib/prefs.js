/* Paramètres › Préférences, applied to the whole app (features/preferences.py).

   Applied once the signed-in account is known (AuthContext):
   - currency  — the business's; every « € » on screen is written in it,
                 French style (« 1 234,56 CHF »), exactly as
                 Intl.NumberFormat('fr-FR') would. FidClic's own prices and
                 invoices stay in euros: any area marked data-currency="eur"
                 is left alone. Nothing is converted — the amounts are the
                 shop's own figures, typed in its own currency.
   - timezone  — dates and times without an explicit zone are shown in it.
   - date_format — numeric dates (31/12/2026) follow the chosen order.
   - link_target — links to other sites open in a new tab, or not.
   - confirm_actions, per_page — read by the pages that need them. */

const state = { currency: 'EUR', symbol: '€', timezone: null, dateFormat: 'dmy', linkTarget: 'same', confirm: true, perPage: 20 };
let observer = null;
let patched = false;
let linksBound = false;

export const currencyCode = () => state.currency;
export const perPage = () => state.perPage;
export const confirmImportant = (message) => (!state.confirm || window.confirm(message));

export function symbolFor(code) {
  try {
    return new Intl.NumberFormat('fr-FR', { style: 'currency', currency: code }).formatToParts(1)
      .find((p) => p.type === 'currency')?.value || code;
  } catch { return code; }
}

// Currency names in the interface's own language, from the browser (QA R5
// F08: in Arabic they stayed French, mixed with the translated page).
export function allCurrencies(lang = 'fr') {
  let codes = [];
  try { codes = Intl.supportedValuesOf('currency'); } catch { codes = ['EUR', 'USD', 'GBP', 'CHF', 'MAD', 'XOF', 'CAD', 'INR', 'AED', 'SAR']; }
  let names = null;
  try { names = new Intl.DisplayNames([lang, 'fr'], { type: 'currency' }); } catch { /* ignore */ }
  return codes.map((c) => ({ code: c, name: names ? names.of(c) : c, symbol: symbolFor(c) }))
    .sort((a, b) => (a.code === 'EUR' ? -1 : b.code === 'EUR' ? 1 : a.name.localeCompare(b.name, lang)));
}

export function allTimezones() {
  try { return Intl.supportedValuesOf('timeZone'); } catch { return ['Europe/Paris', 'Europe/Brussels', 'Europe/Zurich', 'Europe/London', 'Africa/Casablanca', 'America/New_York', 'Asia/Dubai', 'Asia/Kolkata']; }
}

export function tzLabel(tz) {
  try {
    const off = new Intl.DateTimeFormat('fr-FR', { timeZone: tz, timeZoneName: 'shortOffset' }).formatToParts(new Date())
      .find((p) => p.type === 'timeZoneName')?.value || '';
    return `(${off.replace('GMT', 'UTC') || 'UTC'}) ${tz.split('/').pop().replace(/_/g, ' ')}`;
  } catch { return tz; }
}

/* ── currency on screen ─────────────────────────────────────────────── */
const SKIP = new Set(['SCRIPT', 'STYLE', 'TEXTAREA', 'INPUT', 'CODE']);
function rewrite(node) {
  if (state.currency === 'EUR') return;
  const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT, {
    acceptNode: (n) => {
      if (!n.nodeValue || n.nodeValue.indexOf('€') === -1) return NodeFilter.FILTER_REJECT;
      const el = n.parentElement;
      if (!el || SKIP.has(el.tagName) || el.closest('[data-currency="eur"]')) return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    },
  });
  const hits = [];
  while (walker.nextNode()) hits.push(walker.currentNode);
  hits.forEach((n) => { n.nodeValue = n.nodeValue.replace(/€/g, state.symbol); });
}
function watchCurrency() {
  if (observer) { observer.disconnect(); observer = null; }
  if (state.currency === 'EUR' || typeof MutationObserver === 'undefined') return;
  rewrite(document.body);
  observer = new MutationObserver((muts) => {
    for (const m of muts) {
      if (m.type === 'characterData') rewrite(m.target.parentNode || document.body);
      else m.addedNodes.forEach((n) => rewrite(n.nodeType === 3 ? (n.parentNode || document.body) : n));
    }
  });
  observer.observe(document.body, { childList: true, subtree: true, characterData: true });
}

/* ── time zone and date order ───────────────────────────────────────── */
const NUMERIC = new Set(['numeric', '2-digit']);
function numericOnly(o) {
  if (!o) return true;
  const keys = Object.keys(o).filter((k) => o[k] !== undefined && k !== 'timeZone');
  return keys.every((k) => ['day', 'month', 'year'].includes(k) && NUMERIC.has(o[k]));
}
function patchDates() {
  if (patched) return;
  patched = true;
  const P = Date.prototype;
  const orig = { s: P.toLocaleString, d: P.toLocaleDateString, t: P.toLocaleTimeString };
  const withTz = (o) => (state.timezone && !(o && o.timeZone) ? { ...(o || {}), timeZone: state.timezone } : o);
  P.toLocaleString = function (loc, o) { return orig.s.call(this, loc, withTz(o)); };
  P.toLocaleTimeString = function (loc, o) { return orig.t.call(this, loc, withTz(o)); };
  P.toLocaleDateString = function (loc, o) {
    if (state.dateFormat !== 'dmy' && numericOnly(o) && !Number.isNaN(this.getTime())) {
      const parts = new Intl.DateTimeFormat('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric', timeZone: withTz(o)?.timeZone })
        .formatToParts(this).reduce((a, p) => ({ ...a, [p.type]: p.value }), {});
      if (state.dateFormat === 'mdy') return `${parts.month}/${parts.day}/${parts.year}`;
      if (state.dateFormat === 'ymd') return `${parts.year}-${parts.month}-${parts.day}`;
      if (state.dateFormat === 'dmy_dot') return `${parts.day}.${parts.month}.${parts.year}`;
    }
    return orig.d.call(this, loc, withTz(o));
  };
}

/* ── links to other sites ───────────────────────────────────────────── */
function bindLinks() {
  if (linksBound) return;
  linksBound = true;
  document.addEventListener('click', (e) => {
    const a = e.target.closest && e.target.closest('a[href]');
    if (!a || a.target || e.defaultPrevented) return;
    try {
      const url = new URL(a.href, window.location.href);
      if (url.origin !== window.location.origin && /^https?:$/.test(url.protocol) && state.linkTarget === 'new') {
        a.target = '_blank'; a.rel = 'noopener noreferrer';
      }
    } catch { /* ignore */ }
  }, true);
}

export function applyPrefs(prefs = {}, currency = 'EUR') {
  state.currency = (currency || 'EUR').toUpperCase();
  state.symbol = symbolFor(state.currency);
  state.timezone = prefs.timezone || null;
  state.dateFormat = prefs.date_format || 'dmy';
  state.linkTarget = prefs.link_target || 'same';
  state.confirm = prefs.confirm_actions !== false;
  state.perPage = Number(prefs.per_page) || 20;
  patchDates();
  bindLinks();
  watchCurrency();
}
