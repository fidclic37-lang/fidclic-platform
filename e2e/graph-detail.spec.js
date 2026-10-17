/**
 * Reading a point of « Évolution du chiffre d'affaires » / « Nouveaux clients »
 * (user, 2026-10-16): the cursor on a point shows that day, leaving takes it
 * away, a click keeps it with the day's detail — and the Tableau de bord and
 * Analyses behave the same, because they draw the same chart.
 */
import { test, expect } from '@playwright/test';

const OWNER = { email: 'demo.owner@fidelitour.com', password: 'Owner!Demo2026' };   // local seed only

async function asOwner(page, request) {
  const login = await (await request.post('/api/auth/login', { data: OWNER })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const br = await (await request.get('/api/owner/branches', { headers: H })).json();
  const store = ((br && br.branches) || br || []).find((b) => b.status !== 'closed')?.id || '';
  await page.goto('/login');
  await page.evaluate(([t, s]) => {
    localStorage.setItem('fidelitour_access_token', t);
    if (s) localStorage.setItem('ft_selected_branch_v1', s);
    try { sessionStorage.removeItem('ft_pick_store'); } catch (_e) { /* ignore */ }
  }, [login.access_token, store]);
  return { H };
}

/** Hover the middle of a chart, then assert what the card says. */
async function hoverMiddle(chart) {
  await chart.scrollIntoViewIfNeeded();
  const box = await chart.boundingBox();
  await chart.page().mouse.move(box.x + box.width / 2, box.y + box.height / 2);
}

async function readsAPoint(page, chart) {
  await hoverMiddle(chart);
  const tip = chart.getByTestId('trend-tip');
  await expect(tip).toBeVisible();
  await expect(tip).toContainText('Cliquez pour le détail');

  // the cursor leaves — so does the card
  await page.mouse.move(2, 2);
  await expect(chart.getByTestId('trend-tip')).toHaveCount(0);

  // a click keeps it, with the day's story and a way out
  await hoverMiddle(chart);
  await page.mouse.down();
  await page.mouse.up();
  const detail = chart.getByTestId('trend-detail');
  await expect(detail).toBeVisible();
  await expect(detail).toContainText('Part de la période');
  await expect(detail.getByRole('button', { name: 'Fermer' })).toBeVisible();

  // …and it stays while the cursor is elsewhere, unlike the hover card
  await page.mouse.move(2, 2);
  await expect(chart.getByTestId('trend-detail')).toBeVisible();

  await page.keyboard.press('Escape');
  await expect(chart.getByTestId('trend-detail')).toHaveCount(0);
}

test.describe.serial('a point of the two charts answers the cursor', () => {
  test.use({ viewport: { width: 1536, height: 960 } });

  test('Tableau de bord: revenue (line) and new customers (bars)', async ({ page, request }) => {
    await asOwner(page, request);
    await page.goto('/dashboard');
    const charts = page.getByTestId('trend-chart');
    await expect(charts).toHaveCount(2, { timeout: 15_000 });
    await readsAPoint(page, charts.nth(0));          // chiffre d'affaires
    await readsAPoint(page, charts.nth(1));          // nouveaux clients
  });

  test('a revenue point says the visits behind it', async ({ page, request }) => {
    const { H } = await asOwner(page, request);
    const d = await (await request.get('/api/owner/home/overview?days=30', { headers: H })).json();
    expect(Array.isArray(d.revenue_series)).toBe(true);
    // every point carries its visits, so the card can show the basket
    expect(d.revenue_series.every((p) => typeof p.visits === 'number')).toBe(true);

    await page.goto('/dashboard');
    const chart = page.getByTestId('trend-chart').first();
    await expect(chart).toBeVisible({ timeout: 15_000 });
    // The busy day is found ON THE CHART. It used to be taken from the index
    // of the call above — but that call carries no establishment while the
    // chart does, so the two series are not the same days. It happened to
    // line up until the window moved (CI, 2026-10-17: the click landed on an
    // empty 17 September and « Panier moyen » is rightly absent there).
    const points = chart.getByRole('button');
    const total = await points.count();
    const detail = chart.getByTestId('trend-detail');
    let busy = null;
    for (let i = 0; i < total && !busy; i += 1) {
      await points.nth(i).click();
      await expect(detail).toContainText('Visites');
      const said = await detail.innerText();
      if (Number((/Visites\s*([\d\u202f\u00a0 ]+)/.exec(said) || [])[1]?.replace(/\D/g, '') || 0) > 0) busy = said;
      else await page.keyboard.press('Escape');
    }
    test.skip(!busy, 'no visit in the seeded period');
    expect(busy, 'a day with visits says the basket behind them').toContain('Panier moyen');
  });

  test('Analyses draws the same chart, so it reads the same', async ({ page, request }) => {
    await asOwner(page, request);
    await page.goto('/dashboard/analytics');
    const charts = page.getByTestId('trend-chart');
    await expect(charts.first()).toBeVisible({ timeout: 20_000 });
    await readsAPoint(page, charts.nth(0));          // chiffre d'affaires
    await readsAPoint(page, charts.nth(1));          // nombre de clients
  });
});
