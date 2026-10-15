/**
 * Show the owner what the search found.
 *
 * Landing on the right page is half an answer: « did it understand me? » is
 * the other half (user, 2026-10-15). So the term travels in the URL as ?hl=
 * and the first thing on the page that carries it is outlined for a few
 * seconds and scrolled to.
 *
 * Text only, and never inside a field: changing what is typed in an input
 * would be worse than not highlighting at all.
 */
const CLASS = 'fid-hl';
const SKIP = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'INPUT', 'TEXTAREA', 'SELECT', 'OPTION']);

/** « Géolocalisation » must be found by typing « geolocalisation ». */
export const flat = (s) => (s || '').normalize('NFD').replace(/\p{Diacritic}/gu, '').toLowerCase();

function clear() {
  document.querySelectorAll(`.${CLASS}`).forEach((el) => {
    const parent = el.parentNode;
    if (!parent) return;
    parent.replaceChild(document.createTextNode(el.textContent), el);
    parent.normalize();
  });
}

/**
 * Outline the first occurrence of `term` under `root`.
 * Returns true when something was found.
 */
export function highlight(term, root = document.querySelector('main') || document.body) {
  const needle = flat(term).trim();
  if (!needle || needle.length < 2 || !root) return false;
  clear();

  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      if (!node.nodeValue || !node.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
      for (let p = node.parentElement; p && p !== root; p = p.parentElement) {
        if (SKIP.has(p.tagName) || p.classList?.contains(CLASS)) return NodeFilter.FILTER_REJECT;
      }
      return NodeFilter.FILTER_ACCEPT;
    },
  });

  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const i = flat(n.nodeValue).indexOf(needle);
    if (i < 0) continue;
    // the accent-stripped index is the same index: NFD removal never shifts
    // the characters that remain, and we only ever drop combining marks.
    const span = document.createElement('span');
    span.className = CLASS;
    const after = n.splitText(i);
    after.splitText(needle.length);
    span.appendChild(after.cloneNode(true));
    after.parentNode.replaceChild(span, after);
    span.scrollIntoView({ block: 'center', behavior: 'smooth' });
    setTimeout(clear, 4000);
    return true;
  }
  return false;
}

/**
 * The page may still be fetching when we arrive, so look again a few times
 * before giving up. Returns a cancel function.
 */
export function highlightWhenReady(term, tries = [120, 500, 1200, 2500]) {
  const timers = tries.map((ms) => setTimeout(() => highlight(term), ms));
  return () => timers.forEach(clearTimeout);
}
