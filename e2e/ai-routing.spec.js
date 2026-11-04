/**
 * Super admin › FIDCLIC AI › Routage (user, 2026-11-04): which model does which
 * job. A change applies at once, can be undone in one click, and the page asks
 * for a Golden set run until one has tested this table. The rules themselves
 * are api/tests/test_ai_routing.py. Local server only.
 */
import { test, expect } from '@playwright/test';

const ADMIN = { email: 'admin@fidelitour.com', password: 'Fidelit0ur!Adm' };   // local seed only
test.use({ viewport: { width: 1536, height: 960 } });

test('Routage: the table, a change, the undo, the Golden set reminder', async ({ page, request }) => {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const login = await (await request.post('/api/auth/login', { data: ADMIN })).json();
  await page.goto('/login');
  await page.evaluate((t) => localStorage.setItem('fidelitour_access_token', t), login.access_token);
  await page.goto('/admin/ai/routage');
  await expect(page.getByRole('heading', { name: 'Routage de FidClic IA' })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole('link', { name: 'Routage' })).toBeVisible();

  const copilot = page.getByTestId('route-copilot');
  const support = page.getByTestId('route-support');
  await expect(copilot).toContainText('Copilote');
  await expect(copilot.locator('select')).toHaveValue('claude-opus-5-5');
  await expect(copilot).toContainText('Fable 5.1');              // what it climbs to
  await expect(support.locator('select')).toHaveValue('claude-sonnet-5-5');
  await expect(support).toContainText('Opus 5.5');
  await expect(page.getByTestId('routing-rows').locator('tr')).toHaveCount(12);
  await expect(page.getByTestId('routing-golden')).toContainText('Lancer le Golden set');

  await support.locator('select').selectOption('claude-opus-5-5');
  await expect(support).toContainText('Fable 5.1');
  await expect(support.getByRole('button', { name: 'Revenir à Sonnet 5.5' })).toBeVisible();
  await page.reload();
  await expect(page.getByTestId('route-support').locator('select')).toHaveValue('claude-opus-5-5');

  await page.getByTestId('route-support').getByRole('button', { name: 'Revenir à Sonnet 5.5' }).click();
  await expect(page.getByTestId('route-support').locator('select')).toHaveValue('claude-sonnet-5-5');
  await expect(page.getByTestId('route-support').getByRole('button', { name: 'Revenir à Opus 5.5' })).toBeVisible();

  await page.getByTestId('routing-golden').getByRole('button', { name: 'Lancer le Golden set' }).click();
  await expect(page.getByText(/GitHub|Golden set/).first()).toBeVisible();
  expect(errors).toEqual([]);
});
