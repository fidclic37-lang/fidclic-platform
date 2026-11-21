/**
 * The period menu of the Tableau de bord and Analyses (user, 2026-11-03):
 * « Ce mois-ci » by default and again on the 1st of every month, a whole
 * month (1 → 28/29/30/31), one date, a from–to range — and ONE period for
 * both pages: chosen on one, the other opens on it. The presets stay.
 * Simpler menu (user, 2026-11-21): three tabs — Rapide, Mois, Calendrier —
 * one month grid, one calendar (one click = a day, two = du → au).
 * Local server only.
 */
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only

// today in Paris, YYYY-MM-DD — the shop's calendar, not the test machine's
const parisToday = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Paris' }).format(new Date());
const pad = (n) => String(n).padStart(2, '0');
const lastDay = (y, m) => new Date(Date.UTC(y, m, 0)).getUTCDate();          // m 1-12
const MOIS = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre'];

function lastMonth() {
  const [y, m] = parisToday().split('-').map(Number);
  const py = m === 1 ? y - 1 : y;
  const pm = m === 1 ? 12 : m - 1;
  return { y: py, m: pm, from: `${py}-${pad(pm)}-01`, to: `${py}-${pad(pm)}-${pad(lastDay(py, pm))}`,
           label: `${MOIS[pm - 1][0].toUpperCase()}${MOIS[pm - 1].slice(1)} ${py}` };
}

async function signIn(page, request, stored) {
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const store = ((br && br.branches) || br || []).find((x) => x.status !== 'closed')?.id || '';
  await page.goto('/login');
  await page.evaluate(([t, s, st]) => {
    localStorage.clear();
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
    if (st) localStorage.setItem('fidclic:period', st);
    try { sessionStorage.removeItem('ft_pick_store'); } catch (_e) { /* ignore */ }
  }, [login.access_token, store, stored ? JSON.stringify(stored) : '']);
}

// the next request to `path`, its query
const nextCall = (page, path) => page.waitForRequest((r) => r.url().includes(path))
  .then((r) => Object.fromEntries(new URL(r.url()).searchParams));

const button = (page) => page.getByRole('button', { name: 'Période analysée' }).first();
const menu = (page) => page.getByRole('dialog', { name: 'Choisir la période' });
const openMenu = async (page) => { await button(page).click(); await expect(menu(page)).toBeVisible(); };
const tab = (page, name) => menu(page).getByRole('tab', { name, exact: true });
const dayBtn = (page, iso) => menu(page).getByRole('button',
  { name: `${Number(iso.slice(8, 10))} ${MOIS[Number(iso.slice(5, 7)) - 1]} ${iso.slice(0, 4)}`, exact: true });
// the calendar on last month
async function calendarOnLastMonth(page) {
  await tab(page, 'Calendrier').click();
  await menu(page).getByRole('button', { name: 'Mois précédent' }).click();
}

test('first visit: « Ce mois-ci », the 1st of this month until today', async ({ page, request }) => {
  await signIn(page, request);
  const today = parisToday();
  const call = nextCall(page, '/api/owner/home/overview');
  await page.goto('/dashboard');
  const q = await call;
  expect(q.date_from).toBe(`${today.slice(0, 8)}01`);
  expect(q.date_to).toBe(today);
  await expect(button(page)).toContainText('Ce mois-ci');
});

test('three tabs, only one shown at a time — Rapide first', async ({ page, request }) => {
  await signIn(page, request);
  await page.goto('/dashboard');
  await openMenu(page);
  for (const t of ['Rapide', 'Mois', 'Calendrier']) await expect(tab(page, t)).toBeVisible();
  await expect(tab(page, 'Rapide')).toHaveAttribute('aria-selected', 'true');
  await expect(menu(page).getByRole('button', { name: '7 derniers jours' })).toBeVisible();
  await expect(menu(page).getByRole('button', { name: 'Mois précédent' })).toHaveCount(0);
  await tab(page, 'Calendrier').click();
  await expect(menu(page).getByRole('button', { name: '7 derniers jours' })).toHaveCount(0);
  await expect(menu(page).getByRole('button', { name: 'Mois précédent' })).toBeVisible();
});

test('a whole month on Analyses, one click — and the Tableau de bord opens on it', async ({ page, request }) => {
  await signIn(page, request);
  await page.goto('/dashboard/analytics');
  await openMenu(page);
  const lm = lastMonth();
  await tab(page, 'Mois').click();
  const call = nextCall(page, '/api/owner/analyses');
  await menu(page).getByRole('button', { name: lm.label, exact: true }).click();
  const q = await call;
  expect([q.date_from, q.date_to]).toEqual([lm.from, lm.to]);
  await expect(button(page)).toContainText(lm.label);
  await expect(menu(page)).toHaveCount(0);
  // the same period on the other page
  const call2 = nextCall(page, '/api/owner/home/overview');
  await page.goto('/dashboard');
  const q2 = await call2;
  expect([q2.date_from, q2.date_to]).toEqual([lm.from, lm.to]);
  await expect(button(page)).toContainText(lm.label);
  // reopened, the menu shows the Mois tab with that month picked
  await openMenu(page);
  await expect(tab(page, 'Mois')).toHaveAttribute('aria-selected', 'true');
  await expect(menu(page).getByRole('button', { name: lm.label, exact: true })).toHaveAttribute('aria-pressed', 'true');
});

test('one date: one click on the calendar, then Appliquer', async ({ page, request }) => {
  await signIn(page, request);
  await page.goto('/dashboard');
  await openMenu(page);
  const lm = lastMonth();
  const day = `${lm.y}-${pad(lm.m)}-15`;
  await calendarOnLastMonth(page);
  await dayBtn(page, day).click();
  const call = nextCall(page, '/api/owner/home/overview');
  await menu(page).getByRole('button', { name: 'Appliquer' }).click();
  const q = await call;
  expect([q.date_from, q.date_to]).toEqual([day, day]);
  await expect(button(page)).toContainText(`15 ${MOIS[lm.m - 1]} ${lm.y}`);
});

test('a from–to range: two clicks', async ({ page, request }) => {
  await signIn(page, request);
  await page.goto('/dashboard/analytics');
  await openMenu(page);
  const lm = lastMonth();
  const a = `${lm.y}-${pad(lm.m)}-05`;
  const b = `${lm.y}-${pad(lm.m)}-20`;
  await calendarOnLastMonth(page);
  await dayBtn(page, a).click();
  await dayBtn(page, b).click();
  await expect(menu(page)).toContainText(`5 → 20 ${MOIS[lm.m - 1]} ${lm.y}`);
  const call = nextCall(page, '/api/owner/analyses');
  await menu(page).getByRole('button', { name: 'Appliquer' }).click();
  const q = await call;
  expect([q.date_from, q.date_to]).toEqual([a, b]);
  await expect(button(page)).toContainText(`5 → 20 ${MOIS[lm.m - 1]} ${lm.y}`);
  // reopened: Calendrier tab, the range still marked
  await openMenu(page);
  await expect(tab(page, 'Calendrier')).toHaveAttribute('aria-selected', 'true');
  await expect(dayBtn(page, a)).toHaveAttribute('aria-pressed', 'true');
  await expect(dayBtn(page, b)).toHaveAttribute('aria-pressed', 'true');
});

test('a range clicked the wrong way round is put right, not refused', async ({ page, request }) => {
  await signIn(page, request);
  await page.goto('/dashboard');
  await openMenu(page);
  const lm = lastMonth();
  const a = `${lm.y}-${pad(lm.m)}-05`;
  const b = `${lm.y}-${pad(lm.m)}-20`;
  await calendarOnLastMonth(page);
  await dayBtn(page, b).click();
  await dayBtn(page, a).click();
  const call = nextCall(page, '/api/owner/home/overview');
  await menu(page).getByRole('button', { name: 'Appliquer' }).click();
  const q = await call;
  expect([q.date_from, q.date_to]).toEqual([a, b]);
});

test('Appliquer with no day picked explains itself and sends nothing', async ({ page, request }) => {
  await signIn(page, request);
  await page.goto('/dashboard');
  await openMenu(page);
  await tab(page, 'Calendrier').click();
  await menu(page).getByRole('button', { name: 'Appliquer' }).click();
  await expect(menu(page).getByText('Choisissez un jour, ou deux pour une période.')).toBeVisible();
  await expect(button(page)).toContainText('Ce mois-ci');
});

test('the future cannot be picked: no next month, tomorrow greyed', async ({ page, request }) => {
  await signIn(page, request);
  await page.goto('/dashboard');
  await openMenu(page);
  await tab(page, 'Calendrier').click();
  await expect(menu(page).getByRole('button', { name: 'Mois suivant' })).toBeDisabled();
  const t = parisToday();
  await expect(dayBtn(page, t)).toBeEnabled();
  const [y, m, d] = t.split('-').map(Number);
  if (d < lastDay(y, m)) await expect(dayBtn(page, `${y}-${pad(m)}-${pad(d + 1)}`)).toBeDisabled();
});

test('two years back in one go with the month list of the calendar', async ({ page, request }) => {
  await signIn(page, request);
  await page.goto('/dashboard');
  await openMenu(page);
  await tab(page, 'Calendrier').click();
  const pick = menu(page).getByLabel('Mois affiché');
  const opts = await pick.locator('option').count();
  expect(opts).toBeGreaterThanOrEqual(24);
  const oldestKey = await pick.locator('option').last().getAttribute('value');
  await pick.selectOption(oldestKey);
  await expect(menu(page).getByRole('button', { name: 'Mois précédent' })).toBeDisabled();
});

test('the presets stay: « 7 derniers jours » still reads 7 days', async ({ page, request }) => {
  await signIn(page, request);
  await page.goto('/dashboard');
  await openMenu(page);
  const call = nextCall(page, '/api/owner/home/overview');
  await menu(page).getByRole('button', { name: '7 derniers jours' }).click();
  const q = await call;
  expect(q.days).toBe('7');
  expect(q.date_from).toBeUndefined();
});

test('« les derniers N jours / mois » stays on the Rapide tab', async ({ page, request }) => {
  await signIn(page, request);
  await page.goto('/dashboard');
  await openMenu(page);
  await menu(page).getByLabel('Nombre').fill('3');
  await menu(page).getByLabel('Unité').selectOption('m');
  await menu(page).getByRole('button', { name: 'Appliquer' }).click();
  await expect(button(page)).toContainText('3 derniers mois');
});

test('a period chosen last month gives way to « Ce mois-ci » on the 1st', async ({ page, request }) => {
  const [y, m] = parisToday().split('-').map(Number);
  const before = m === 1 ? `${y - 1}-12` : `${y}-${pad(m - 1)}`;
  await signIn(page, request, { p: '90', m: before });
  await page.goto('/dashboard');
  await expect(button(page)).toContainText('Ce mois-ci');
});

test('…while one chosen this month is kept', async ({ page, request }) => {
  await signIn(page, request, { p: '90', m: parisToday().slice(0, 7) });
  const call = nextCall(page, '/api/owner/home/overview');
  await page.goto('/dashboard/');
  expect((await call).days).toBe('90');
  await expect(button(page)).toContainText('90 derniers jours');
});

test('an old link with ?days= still opens on its period', async ({ page, request }) => {
  await signIn(page, request);
  const call = nextCall(page, '/api/owner/home/overview');
  await page.goto('/dashboard?days=90');
  expect((await call).days).toBe('90');
});

test('a month in the future is not offered', async ({ page, request }) => {
  await signIn(page, request);
  await page.goto('/dashboard');
  await openMenu(page);
  await tab(page, 'Mois').click();
  const [y, m] = parisToday().split('-').map(Number);
  const cur = `${MOIS[m - 1][0].toUpperCase()}${MOIS[m - 1].slice(1)} ${y}`;
  await expect(menu(page).getByRole('button', { name: cur, exact: true })).toBeEnabled();
  if (m < 12) {
    const nxt = `${MOIS[m][0].toUpperCase()}${MOIS[m].slice(1)} ${y}`;
    await expect(menu(page).getByRole('button', { name: nxt, exact: true })).toBeDisabled();
  }
});

test('Échap closes the menu without changing the period', async ({ page, request }) => {
  await signIn(page, request);
  await page.goto('/dashboard');
  await openMenu(page);
  await tab(page, 'Calendrier').click();
  await page.keyboard.press('Escape');
  await expect(menu(page)).toHaveCount(0);
  await expect(button(page)).toContainText('Ce mois-ci');
});
