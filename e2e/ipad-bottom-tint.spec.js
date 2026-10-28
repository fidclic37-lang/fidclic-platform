/**
 * iPad: an orange band under the app, above the home indicator (user,
 * 2026-10-28, Royal Trim Liberté, scan page). iOS 26 tints the bars at the
 * screen's edges from the page's position:fixed elements; the dashboard kept
 * a fixed backdrop from the April terracotta theme — two blurred orange /
 * red orbs, nearly invisible on the page but picked up by iOS. No fixed
 * element of the app (nor anything inside one) may carry a warm colour, and
 * the installed app's manifest no longer names the old terracotta either.
 * Local server only.
 */
import { test, expect } from '@playwright/test';
import fs from 'node:fs';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only

// signed in as the demo owner, its first open store picked (no store screen)
async function signIn(page, request) {
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const store = ((br && br.branches) || br || []).find((x) => x.status !== 'closed')?.id || '';
  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
    try { sessionStorage.removeItem('ft_pick_store'); } catch (_e) { /* ignore */ }
  }, [login.access_token, store]);
}

// every colour painted by a fixed element or its children, as [r, g, b, a]
const fixedColours = () => {
  const out = [];
  const rgba = (s) => { const m = s.match(/[\d.]+/g); return m ? m.map(Number) : null; };
  for (const el of document.querySelectorAll('body *')) {
    if (getComputedStyle(el).position !== 'fixed') continue;
    for (const n of [el, ...el.querySelectorAll('*')]) {
      const cs = getComputedStyle(n);
      if (cs.display === 'none') continue;
      const c = rgba(cs.backgroundColor);
      if (c && (c[3] === undefined || c[3] > 0)) out.push({ where: `${n.tagName}.${String(n.className).slice(0, 60)}`, c });
      const g = cs.backgroundImage.match(/rgba?\([^)]+\)/g) || [];
      g.forEach((x) => out.push({ where: `${n.tagName}.${String(n.className).slice(0, 60)} (gradient)`, c: rgba(x) }));
    }
  }
  return out;
};
// warm = red → orange → yellow, clearly coloured (not white / grey / blue)
const warm = ([r, g, b]) => {
  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  if (max - min < 60) return false;
  let h;
  if (max === r) h = (60 * ((g - b) / (max - min)) + 360) % 360;
  else if (max === g) h = 60 * ((b - r) / (max - min)) + 120;
  else h = 60 * ((r - g) / (max - min)) + 240;
  return h < 55 || h > 320;
};

for (const size of [{ width: 1180, height: 820 }, { width: 820, height: 1180 }]) {
  test(`iPad ${size.width}×${size.height}: nothing fixed is orange (iOS tints the bottom bar from it)`, async ({ page, request }) => {
    await page.setViewportSize(size);
    await signIn(page, request);
    for (const url of ['/dashboard', '/dashboard/scan', '/dashboard/clients']) {
      await page.goto(url);
      await page.waitForLoadState('networkidle');
      const hot = (await page.evaluate(fixedColours)).filter((x) => warm(x.c));
      expect(hot, `${url}: fixed + orange`).toEqual([]);
    }
  });
}

test('the installed app is no longer themed terracotta', async () => {
  const m = JSON.parse(fs.readFileSync('public/manifest.json', 'utf8'));
  const hex = m.theme_color.replace('#', '');
  const rgb = [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16));
  expect(warm(rgb), `theme_color ${m.theme_color}`).toBe(false);
});
