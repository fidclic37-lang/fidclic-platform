/**
 * Super admin › FIDCLIC AI › Précision (user, 2026-10-25): what the client
 * brain predicted for each next visit and what really happened, against the
 * plain mean and the 30-day rule; the journal exports as an anonymous CSV.
 * Local server only.
 */
import { test, expect } from '@playwright/test';

const ADMIN = { email: 'admin@fidelitour.com', password: 'Fidelit0ur!Adm' };   // local seed only
test.use({ viewport: { width: 1536, height: 960 } });

test('the accuracy page shows the journal, and exports it', async ({ page, request }) => {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const login = await (await request.post('/api/auth/login', { data: ADMIN })).json();
  const H = { Authorization: `Bearer ${login.access_token}` };
  const run = await request.post('/api/admin/ai/precision/backtest', { headers: H, data: {} });
  expect(run.ok(), await run.text()).toBeTruthy();
  const d = await (await request.get('/api/admin/ai/precision', { headers: H })).json();

  await page.goto('/login');
  await page.evaluate((t) => localStorage.setItem('fidelitour_access_token', t), login.access_token);
  await page.goto('/admin/ai/precision');
  await expect(page.getByRole('heading', { name: 'Précision de FidClic IA' })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole('link', { name: 'Précision' })).toBeVisible();
  if (d.summary.checked + d.summary.not_returned > 0) {
    await expect(page.getByTestId('precision-checked')).toContainText(d.summary.checked.toLocaleString('fr-FR'));
    await expect(page.getByTestId('precision-error')).toContainText('moyenne simple');
    await expect(page.getByTestId('precision-calibration')).toBeVisible();
  } else {
    await expect(page.getByTestId('precision-empty')).toBeVisible();
  }
  const [dl] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: /Exporter le journal/ }).click()]);
  expect(dl.suggestedFilename()).toBe('fidclic-ia-journal.csv');
  await page.screenshot({ path: 'test-results/ai-precision.png', fullPage: true });
  expect(errors).toEqual([]);
});
