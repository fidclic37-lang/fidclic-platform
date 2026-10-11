// vh / vw rebuilt on the fit scale (index.html, « même affichage partout »):
// when the app is zoomed to fit the window, 100vh would cover only part of
// it — so every vh / vw in the CSS (Tailwind's h-screen, max-h-[90vh]…, our
// own index.css) reads --fit-vh / --fit-vw instead, which the script sets to
// the window's real height / width at the current scale. Without the script
// the fallback is the plain unit.
const fitUnits = () => ({
  postcssPlugin: 'fit-viewport-units',
  Declaration(decl) {
    if (!/\d(?:vh|vw)\b/.test(decl.value) || decl.value.includes('--fit-v')) return;
    decl.value = decl.value.replace(/(-?\d*\.?\d+)(vh|vw)\b/g,
      (m, n, u) => `calc(${n} * var(--fit-${u}, 1${u}))`);
  },
});
fitUnits.postcss = true;

// The width breakpoints follow the same scale: a media query sees the real
// window (1280 px), while the scaled app is 1536 px wide inside it — so
// every width-only @media (Tailwind's sm…2xl and min-[…] / max-[…], our own
// index.css) becomes a container query on <body> (« fit », index.css),
// which measures the page in its scaled pixels. Queries that mix in
// anything else (prefers-reduced-motion, print…) stay media queries.
const WIDTH_ONLY = /^\s*\(\s*(?:min|max)-width\s*:\s*[\d.]+px\s*\)(?:\s+and\s+\(\s*(?:min|max)-width\s*:\s*[\d.]+px\s*\))*\s*$/;
const fitBreakpoints = () => ({
  postcssPlugin: 'fit-breakpoints',
  AtRuleExit: {
    media(rule) {
      if (!WIDTH_ONLY.test(rule.params)) return;
      rule.name = 'container';
      rule.raws.afterName = ' ';
      rule.params = `fit ${rule.params.trim()}`;
    },
  },
});
fitBreakpoints.postcss = true;

export default {
  plugins: [
    (await import('tailwindcss')).default(),
    (await import('autoprefixer')).default(),
    fitUnits(),
    fitBreakpoints(),
  ],
};
