/**
 * The period menu of the Tableau de bord and Analyses (user, 2026-11-03):
 * « Ce mois-ci » by default and again on the 1st of every month, a whole
 * month (1 → 28/29/30/31), one date, a from–to range — and ONE period for
 * both pages: chosen on one, the other opens on it. The presets stay.
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
const openMenu = async (page) => { await button(page).click(); await expect(page.getByRole('listbox')).toBeVisible(); };

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

test('a whole month on Analyses — and the Tableau de bord opens on it', async ({ page, request }) => {
  await signIn(page, request);
  await page.goto('/dashboard/analytics');
  await openMenu(page);
  const lm = lastMonth();
  const call = nextCall(page, '/api/owner/analyses');
  await page.getByLabel('Un mois').selectOption(`m${lm.y}-${pad(lm.m)}`);
  const q = await call;
  expect([q.date_from, q.date_to]).toEqual([lm.from, lm.to]);
  await expect(button(page)).toContainText(lm.label);
  // the same period on the other page
  const call2 = nextCall(page, '/api/owner/home/overview');
  await page.goto('/dashboard');
  const q2 = await call2;
  expect([q2.date_from, q2.date_to]).toEqual([lm.from, lm.to]);
  await expect(button(page)).toContainText(lm.label);
});

test('one date', async ({ page, request }) => {
  await signIn(page, request);
  await page.goto('/dashboard');
  await openMenu(page);
  const lm = lastMonth();
  const day = `${lm.y}-${pad(lm.m)}-15`;
  await page.getByLabel('Une date').fill(day);
  const call = nextCall(page, '/api/owner/home/overview');
  await page.getByRole('button', { name: 'Voir ce jour' }).click();
  const q = await call;
  expect([q.date_from, q.date_to]).toEqual([day, day]);
  await expect(button(page)).toContainText(`15 ${MOIS[lm.m - 1]} ${lm.y}`);
});

test('a from–to range', async ({ page, request }) => {
  await signIn(page, request);
  await page.goto('/dashboard/analytics');
  await openMenu(page);
  const lm = lastMonth();
  const a = `${lm.y}-${pad(lm.m)}-05`;
  const b = `${lm.y}-${pad(lm.m)}-20`;
  await page.getByLabel('Du', { exact: true }).fill(a);
  await page.getByLabel('Au', { exact: true }).fill(b);
  const call = nextCall(page, '/api/owner/analyses');
  await page.getByRole('button', { name: 'Voir la période' }).click();
  const q = await call;
  expect([q.date_from, q.date_to]).toEqual([a, b]);
  await expect(button(page)).toContainText(`5 → 20 ${MOIS[lm.m - 1]} ${lm.y}`);
});

test('a range the wrong way round is explained, not sent', async ({ page, request }) => {
  await signIn(page, request);
  await page.goto('/dashboard');
  await openMenu(page);
  const lm = lastMonth();
  await page.getByLabel('Du', { exact: true }).fill(`${lm.y}-${pad(lm.m)}-20`);
  await page.getByLabel('Au', { exact: true }).fill(`${lm.y}-${pad(lm.m)}-05`);
  await page.getByRole('button', { name: 'Voir la période' }).click();
  await expect(page.getByText('La date de début est après la date de fin.')).toBeVisible();
});

test('the presets stay: « 7 derniers jours » still reads 7 days', async ({ page, request }) => {
  await signIn(page, request);
  await page.goto('/dashboard');
  await openMenu(page);
  const call = nextCall(page, '/api/owner/home/overview');
  await page.getByRole('option', { name: '7 derniers jours' }).click();
  const q = await call;
  expect(q.days).toBe('7');
  expect(q.date_from).toBeUndefined();
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
  const [y, m] = parisToday().split('-').map(Number);
  const next = m === 12 ? `m${y + 1}-01` : `m${y}-${pad(m + 1)}`;
  await expect(page.getByLabel('Un mois').locator(`option[value="${next}"]`)).toHaveCount(0);
  await expect(page.getByLabel('Un mois').locator(`option[value="m${y}-${pad(m)}"]`)).toHaveCount(1);
});
