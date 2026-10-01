/**
 * translator.js — custom DOM-walking translation layer.
 *
 * WHY THIS EXISTS:
 *   Google Translate Element is fundamentally fragile on React SPAs.
 *   React's reconciliation rewrites the DOM and Google's MutationObserver
 *   gets confused — deep pages (Insights, AI Assistant, anything with
 *   heavy widget remounting) stay in the source language no matter how
 *   often we re-trigger the widget. We tried, it doesn't work.
 *
 * THE FIX:
 *   Walk the DOM ourselves, collect every meaningful text node, batch
 *   them through Google's free `translate_a/single` endpoint (the same
 *   one Chrome's own translator uses — CORS-enabled with `client=gtx`),
 *   cache results forever, and apply translations directly to
 *   `node.nodeValue`. React leaves text node values alone unless props
 *   change, so once translated, content STAYS translated until the user
 *   picks a new language or the source text actually changes.
 *
 *   A MutationObserver catches every new text node (route changes, modal
 *   opens, async API renders, infinite scroll) and queues it for a
 *   debounced translation pass.
 *
 * NETWORK NOTES:
 *   - Endpoint: https://translate.googleapis.com/translate_a/single
 *     CORS-enabled when client=gtx. No API key. No documented rate
 *     limit; real-world usage suggests several thousand requests/day
 *     per IP is fine for our scale.
 *   - We batch text with a `\n¶¶¶\n` separator (Google preserves
 *     newlines and uncommon glyphs), so 50 short strings = 1 request.
 *   - Two-tier cache:
 *       memory Map (instant) + localStorage (persists across reloads)
 *     Re-visiting any page after first translation pass is free.
 *
 * SOURCE LANGUAGE:
 *   The platform was authored in French, so we translate FROM 'fr'.
 *   Picking 'fr' from the language switcher restores originals from
 *   the per-node original-text cache — no API call needed.
 */

const ENDPOINT = 'https://translate.googleapis.com/translate_a/single';
const SOURCE_LANG = 'fr';

// Separator used to batch-translate multiple strings in one request.
// Must survive a round-trip through the translation service unchanged.
// Triple-pilcrow with newlines: Google preserves punctuation reliably.
const SEP = '\n¶¶¶\n';

// Sentinel attribute on the <body> so we know which language is
// currently applied to the DOM. Lets us short-circuit redundant passes.
const APPLIED_ATTR = 'data-ft-lang';

// In-memory cache: Map<originalText, { en: '...', ar: '...' }>
const memCache = new Map();

// Restore the cache from localStorage on module load (cheap — runs once).
try {
  const raw = localStorage.getItem('fidelitour:translations');
  if (raw) {
    const obj = JSON.parse(raw);
    for (const [k, v] of Object.entries(obj)) memCache.set(k, v);
  }
} catch { /* localStorage blocked — fine, runs in memory only */ }

// Debounced localStorage write — translations land in the page first,
// persistence happens at idle. Caps storage at ~2MB to avoid filling
// the quota on a slow connection where uncached pages translate
// hundreds of new strings.
let persistTimer = null;
function schedulePersist() {
  if (persistTimer) clearTimeout(persistTimer);
  persistTimer = setTimeout(() => {
    try {
      const obj = Object.fromEntries(memCache);
      const json = JSON.stringify(obj);
      if (json.length < 2 * 1024 * 1024) {
        localStorage.setItem('fidelitour:translations', json);
      }
    } catch { /* quota exceeded or blocked — keep working in memory */ }
  }, 1500);
}

/**
 * Translate an array of strings into `targetLang`. Cached lookups are
 * synchronous-ish (still returns a promise so the caller doesn't have
 * to branch). Cache misses go to Google's endpoint in batches.
 *
 * Returns an array of translated strings in the same order. On any
 * network failure, returns the originals so the page stays readable
 * (we'd rather show French text than blank/garbled output).
 */
export async function translateBatch(texts, targetLang) {
  if (!targetLang || targetLang === SOURCE_LANG) return texts.slice();

  // Build the result array, marking which indices need a network fetch.
  const result = new Array(texts.length);
  const need = []; // [{ i, text }, ...]
  for (let i = 0; i < texts.length; i++) {
    const txt = texts[i];
    if (!txt) { result[i] = txt; continue; }
    const cached = memCache.get(txt);
    if (cached && cached[targetLang]) {
      result[i] = cached[targetLang];
    } else {
      need.push({ i, text: txt });
    }
  }

  if (need.length === 0) return result;

  // Group into chunks of ≤ 40 strings to stay under the URL length limit
  // (Google's GET endpoint chokes around 5KB of query string).
  const CHUNK = 40;
  for (let off = 0; off < need.length; off += CHUNK) {
    const slice = need.slice(off, off + CHUNK);
    const joined = slice.map((s) => s.text).join(SEP);
    const url = `${ENDPOINT}?client=gtx&sl=${SOURCE_LANG}&tl=${targetLang}&dt=t&q=${encodeURIComponent(joined)}`;
    try {
      const res = await fetch(url, { credentials: 'omit' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      // Google returns: [[[seg1, origSeg1, ...], [seg2, origSeg2, ...], ...], ...]
      // Concatenate all segments back into one string, then split on SEP.
      const concat = (data[0] || []).map((row) => row[0]).join('');
      const parts = concat.split(SEP);
      for (let k = 0; k < slice.length; k++) {
        const { i, text } = slice[k];
        const translated = (parts[k] ?? '').trim();
        result[i] = translated || text;
        // Cache (even if translated === text, so we don't re-fetch it).
        const entry = memCache.get(text) || {};
        entry[targetLang] = result[i];
        memCache.set(text, entry);
      }
    } catch (e) {
      // Network blocked / endpoint down. Fall back to originals for this
      // chunk — the user sees French rather than a broken page.
      // eslint-disable-next-line no-console
      console.warn('[translator] batch translation failed:', e);
      for (const { i, text } of slice) result[i] = text;
    }
  }

  schedulePersist();
  return result;
}

// ---------------------------------------------------------------------------
// DOM walker.
//
// Collects every text node inside `root` that's worth translating.
// Skips: scripts/styles/code/pre/textarea (would never want translated),
// numbers-only strings, ultra-short strings, anything inside an element
// flagged translate="no" or class="notranslate".
// ---------------------------------------------------------------------------
const SKIP_TAGS = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'CODE', 'PRE', 'TEXTAREA', 'INPUT']);

// Each translated text node remembers its original via a private symbol
// so we can revert when the user switches back to French without
// re-fetching anything.
const ORIGINAL = Symbol('ft.original');

function shouldTranslateNode(node) {
  const txt = node.nodeValue;
  if (!txt) return false;
  const trimmed = txt.trim();
  if (trimmed.length < 2) return false;
  // Skip pure numerics / dates / currencies / barcodes.
  if (/^[\d\s.,€$%+\-*/:_/()]+$/.test(trimmed)) return false;
  if (/^FT-[A-Z0-9]+$/i.test(trimmed)) return false;
  let p = node.parentElement;
  const root = node.ownerDocument && node.ownerDocument.documentElement;
  // An opt-out on <html> itself is about the BROWSER's translation, never
  // this layer (it once switched this layer off on every page). Opt-outs
  // inside the page still work.
  while (p && p !== root) {
    if (SKIP_TAGS.has(p.tagName)) return false;
    if (p.getAttribute && p.getAttribute('translate') === 'no') return false;
    if (p.classList && p.classList.contains('notranslate')) return false;
    p = p.parentElement;
  }
  return true;
}

function collectTextNodes(root) {
  const out = [];
  if (!root || !root.ownerDocument) return out;
  const walker = root.ownerDocument.createTreeWalker(
    root,
    NodeFilter.SHOW_TEXT,
    { acceptNode: (n) => (shouldTranslateNode(n) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT) },
  );
  let n;
  while ((n = walker.nextNode())) out.push(n);
  return out;
}

// Also translate `placeholder` attrs on inputs/textareas, `title` on
// any element, and `aria-label` — these don't render as text nodes but
// users see them in tooltips, screen readers, and empty form fields.
const ATTR_TARGETS = [
  { selector: 'input[placeholder], textarea[placeholder]', attr: 'placeholder' },
  { selector: '[title]', attr: 'title' },
  { selector: '[aria-label]', attr: 'aria-label' },
];

const ATTR_ORIGINAL = Symbol('ft.attrOriginals');

function collectAttrJobs(root) {
  const jobs = []; // [{ el, attr, text }, ...]
  if (!root || !root.querySelectorAll) return jobs;
  for (const { selector, attr } of ATTR_TARGETS) {
    let nodes;
    try { nodes = root.querySelectorAll(selector); } catch { continue; }
    for (const el of nodes) {
      const v = el.getAttribute(attr);
      if (!v || v.trim().length < 2) continue;
      if (/^[\d\s.,€$%+\-*/:_/()]+$/.test(v.trim())) continue;
      jobs.push({ el, attr, text: v });
    }
  }
  return jobs;
}

// ---------------------------------------------------------------------------
// Public API.
// ---------------------------------------------------------------------------
let currentLang = SOURCE_LANG;
let observer = null;
const pendingNodes = new Set();
let flushTimer = null;

/**
 * Apply (or revert) translations across the whole document. Idempotent —
 * call as many times as you want; cached translations make repeats free.
 */
export async function applyTranslation(lang) {
  currentLang = lang || SOURCE_LANG;
  document.body.setAttribute(APPLIED_ATTR, currentLang);
  // Keep layout LTR even when target is Arabic (owner explicitly asked).
  document.documentElement.setAttribute('dir', 'ltr');
  document.documentElement.setAttribute('lang', currentLang);

  if (currentLang === SOURCE_LANG) {
    // Restore originals from the per-node stash.
    for (const node of collectTextNodes(document.body)) {
      if (node[ORIGINAL] != null) {
        node.nodeValue = node[ORIGINAL];
      }
    }
    // Restore attribute originals too.
    document.querySelectorAll('input, textarea, [title], [aria-label]').forEach((el) => {
      const stash = el[ATTR_ORIGINAL];
      if (!stash) return;
      for (const [attr, original] of Object.entries(stash)) {
        el.setAttribute(attr, original);
      }
    });
    ensureObserver(); // keep observing so future nodes don't need translation either
    return;
  }

  await translateAllUnder(document.body);
  ensureObserver();
}

async function translateAllUnder(root) {
  if (currentLang === SOURCE_LANG) return;

  // ---- text nodes ----
  const nodes = collectTextNodes(root);
  if (nodes.length > 0) {
    const originals = nodes.map((n) => {
      // Stash the original on first translation so we can revert later.
      if (n[ORIGINAL] == null) n[ORIGINAL] = n.nodeValue;
      return n[ORIGINAL].trim();
    });
    const translated = await translateBatch(originals, currentLang);
    // Bail if the user switched languages mid-flight.
    if (currentLang === SOURCE_LANG) return;
    for (let i = 0; i < nodes.length; i++) {
      const node = nodes[i];
      const original = node[ORIGINAL];
      if (!original) continue;
      const t = translated[i];
      if (!t || t === original.trim()) continue;
      // Preserve leading/trailing whitespace from the original text node.
      const leading = original.match(/^\s*/)[0];
      const trailing = original.match(/\s*$/)[0];
      node.nodeValue = leading + t + trailing;
    }
  }

  // ---- attributes (placeholder / title / aria-label) ----
  const attrJobs = collectAttrJobs(root);
  if (attrJobs.length > 0) {
    const originals = attrJobs.map((j) => {
      const stash = j.el[ATTR_ORIGINAL] || {};
      if (stash[j.attr] == null) stash[j.attr] = j.text;
      j.el[ATTR_ORIGINAL] = stash;
      return stash[j.attr];
    });
    const translated = await translateBatch(originals, currentLang);
    if (currentLang === SOURCE_LANG) return;
    for (let i = 0; i < attrJobs.length; i++) {
      const t = translated[i];
      if (t && t !== originals[i]) attrJobs[i].el.setAttribute(attrJobs[i].attr, t);
    }
  }
}

// ---------------------------------------------------------------------------
// Mutation observer — catches new text nodes from React renders, modal
// opens, route changes, async API content.
// ---------------------------------------------------------------------------
function ensureObserver() {
  if (observer) return;
  observer = new MutationObserver((mutations) => {
    if (currentLang === SOURCE_LANG) return;
    for (const m of mutations) {
      if (m.type === 'characterData') {
        if (shouldTranslateNode(m.target)) pendingNodes.add(m.target);
      } else if (m.type === 'childList') {
        for (const added of m.addedNodes) {
          if (added.nodeType === Node.TEXT_NODE) {
            if (shouldTranslateNode(added)) pendingNodes.add(added);
          } else if (added.nodeType === Node.ELEMENT_NODE) {
            // Mark the whole subtree for re-translation. We'll re-walk
            // it in scheduleFlush so we also pick up its descendants
            // and any attributes (placeholder/title/aria-label).
            pendingNodes.add(added);
          }
        }
      } else if (m.type === 'attributes') {
        // Placeholder/title/aria-label on existing element changed —
        // re-translate that single element's attributes.
        if (m.target.nodeType === Node.ELEMENT_NODE) pendingNodes.add(m.target);
      }
    }
    scheduleFlush();
  });
  observer.observe(document.body, {
    childList: true,
    subtree: true,
    characterData: true,
    attributes: true,
    attributeFilter: ['placeholder', 'title', 'aria-label'],
  });
}

function scheduleFlush() {
  if (flushTimer) clearTimeout(flushTimer);
  flushTimer = setTimeout(async () => {
    if (currentLang === SOURCE_LANG || pendingNodes.size === 0) {
      pendingNodes.clear();
      return;
    }
    const items = Array.from(pendingNodes);
    pendingNodes.clear();
    // Split into text nodes (translate in place) and element nodes
    // (re-walk subtree). Both end up going through translateAllUnder
    // for the element case; text nodes get inlined here.
    const textNodes = items.filter((n) => n.nodeType === Node.TEXT_NODE && shouldTranslateNode(n));
    const elements = items.filter((n) => n.nodeType === Node.ELEMENT_NODE);

    if (textNodes.length > 0) {
      const originals = textNodes.map((n) => {
        if (n[ORIGINAL] == null) n[ORIGINAL] = n.nodeValue;
        return n[ORIGINAL].trim();
      });
      const translated = await translateBatch(originals, currentLang);
      if (currentLang === SOURCE_LANG) return;
      for (let i = 0; i < textNodes.length; i++) {
        const node = textNodes[i];
        const original = node[ORIGINAL];
        if (!original) continue;
        const t = translated[i];
        if (!t || t === original.trim()) continue;
        const leading = original.match(/^\s*/)[0];
        const trailing = original.match(/\s*$/)[0];
        node.nodeValue = leading + t + trailing;
      }
    }
    for (const el of elements) {
      // eslint-disable-next-line no-await-in-loop
      await translateAllUnder(el);
    }
  }, 150);
}

// Convenience: pull active language from the existing localStorage key
// that i18next-browser-languagedetector uses, so this layer agrees with
// the LanguageSwitcher / i18next.
export function getActiveLanguage() {
  try {
    return localStorage.getItem('fidelitour:lang') || SOURCE_LANG;
  } catch {
    return SOURCE_LANG;
  }
}
