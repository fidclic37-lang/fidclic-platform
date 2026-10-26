/**
 * Super admin › FIDCLIC AI › Précision (user, 2026-10-25): what the client
 * brain predicted for each next visit and what really happened, against the
 * plain mean and the shop's own rule, brain-v1 beside brain-v2 (in observation)
 * with the switch; the journal exports as an anonymous CSV.
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
  // the buttons answer at once; the work runs in the tick (user, 2026-10-26)
  const run = await request.post('/api/admin/ai/precision/backtest', { headers: H, data: {} });
  expect(run.ok(), await run.text()).toBeTruthy();
  const learn = await request.post('/api/admin/ai/precision/learn', { headers: H });
  expect(learn.ok(), await learn.text()).toBeTruthy();
  const d = await (await request.get('/api/admin/ai/precision', { headers: H })).json();
  expect(d.jobs.some((j) => j.kind === 'learn')).toBeTruthy();

  await page.goto('/login');
  await page.evaluate((t) => localStorage.setItem('fidelitour_access_token', t), login.access_token);
  await page.goto('/admin/ai/precision');
  await expect(page.getByRole('heading', { name: 'Précision de FidClic IA' })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole('link', { name: 'Précision' })).toBeVisible();
  // what runs in the background, and how far it got
  await expect(page.getByTestId('ai-jobs')).toBeVisible();
  await expect(page.getByTestId('ai-job-learn')).toContainText('Réapprentissage de brain-v2');
  page.once('dialog', (dlg) => dlg.accept());
  await page.getByRole('button', { name: /Relancer le backtest/ }).click();
  await expect(page.getByText(/Backtest lancé|déjà en cours/)).toBeVisible();
  // brain-v1 in service, brain-v2 in observation, side by side with the baselines
  const cmp = page.getByTestId('precision-compare');
  await expect(cmp.getByTestId('compare-brain-v1')).toContainText('En service');
  await expect(cmp.getByTestId('compare-brain-v2')).toContainText('En observation');
  await expect(cmp).toContainText('Moyenne simple');
  const sw = page.getByTestId('switch-v2');
  if (d.compare.can_switch) await expect(sw).toBeEnabled();
  else {
    await expect(sw).toBeDisabled();
    await expect(page.getByTestId('switch-why-not')).toBeVisible();
  }
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
