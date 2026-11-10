/**
 * Super admin › Tableau de bord › « Activité du jour » (user, 2026-11-10):
 * Parrainage, Campagnes + automatisations, Nouveaux clients — every
 * business's activity of one Paris day, today live, past days with ‹ › or
 * the date. Local server only, on the demo data.
 */
import { test, expect } from '@playwright/test';

const ADMIN = { email: 'admin@fidelitour.com', password: 'Fidelit0ur!Adm' };   // local seed only
test.use({ viewport: { width: 1536, height: 960 } });

test('the super admin reads the activity of the day, section by section', async ({ page, request }) => {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const login = await (await request.post('/api/auth/login', { data: ADMIN })).json();
  const A = { Authorization: `Bearer ${login.access_token}` };
  const today = await (await request.get('/api/admin/dashboard/activity', { headers: A })).json();
  expect(today.today).toBe(true);
  expect(today.sections.map((s) => s.key)).toEqual(['parrainage', 'campagnes', 'nouveaux_clients']);

  // a past day with something to open (the demo has clients joining over weeks)
  let busy = null;
  let day = today.prev;
  for (let i = 0; i < 40 && !busy; i += 1) {
    const r = await (await request.get(`/api/admin/dashboard/activity?day=${day}`, { headers: A })).json();
    if (r.sections.some((s) => s.rows.length)) busy = r; else day = r.prev;
  }
  expect(busy).toBeTruthy();

  await page.goto('/login');
  await page.evaluate((t) => localStorage.setItem('fidelitour_access_token', t), login.access_token);
  await page.goto('/admin');
  await expect(page.getByRole('heading', { name: 'Activité du jour' })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('activity-day')).toHaveText("Aujourd'hui");
  for (const s of today.sections) await expect(page.getByTestId(`total-${s.key}`)).toHaveText(String(s.total));
  await expect(page.getByText('Activité récente')).toHaveCount(0);

  // ‹ goes back one day and asks for it
  const asked = page.waitForRequest((r) => r.url().includes(`/api/admin/dashboard/activity?day=${today.prev}`));
  await page.getByRole('button', { name: 'Jour précédent' }).click();
  await asked;
  await expect(page.getByTestId('activity-day')).not.toHaveText("Aujourd'hui");

  // the busy day, by its date
  await page.getByLabel('Choisir un jour').fill(busy.day);
  const sec = busy.sections.find((s) => s.rows.length);
  for (const s of busy.sections) await expect(page.getByTestId(`total-${s.key}`)).toHaveText(String(s.total));
  const list = page.getByTestId(`section-${sec.key}`);
  await expect(list.locator(':scope > li')).toHaveCount(sec.rows.length);
  const first = list.locator(':scope > li').first();
  await expect(first).toContainText(sec.rows[0].tenant_name);
  await first.getByRole('button').first().click();
  await expect(first.locator('ul li')).toHaveCount(Math.min(sec.rows[0].items.length, 50));
  await page.screenshot({ path: 'test-results/admin-daily-activity.png', fullPage: true });
  // no phone number, no e-mail on the page
  const text = await page.locator('main').innerText().catch(() => page.locator('body').innerText());
  expect(text).not.toMatch(/0[67]\d{8}|@[a-z0-9-]+\.[a-z]{2,}/i);

  // « Aujourd'hui » comes back to the live day
  await page.getByRole('button', { name: "Aujourd'hui" }).click();
  await expect(page.getByTestId('activity-day')).toHaveText("Aujourd'hui");
  expect(errors).toEqual([]);
});
