// Panne MongoDB du 2026-11-03 : la page de connexion disait « Email ou mot de
// passe incorrect » alors que la base était injoignable. Une panne doit dire
// « service indisponible » ; seuls de vrais mauvais identifiants disent
// « incorrect ».
import { test, expect } from '@playwright/test';

const SERVICE = /Service momentanément indisponible/;
const WRONG = 'Email ou mot de passe incorrect.';

async function submit(page) {
  await page.goto('/login');
  await page.locator('input[type="email"]').first().fill('owner@example.fr');
  await page.locator('input[type="password"]').first().fill('Whatever-1A!');
  await page.locator('button[type="submit"]').first().click();
}

test('503 de la base → « service indisponible », jamais « incorrect »', async ({ page }) => {
  await page.route('**/api/auth/login', (r) => r.fulfill({
    status: 503,
    contentType: 'application/json',
    body: JSON.stringify({ detail: 'Service momentanément indisponible, réessayez dans quelques minutes.', code: 'db_unavailable' }),
  }));
  await submit(page);
  await expect(page.getByText(SERVICE)).toBeVisible();
  await expect(page.getByText(WRONG)).toHaveCount(0);
});

test('fonction Vercel expirée (504 HTML, sans detail) → « service indisponible »', async ({ page }) => {
  await page.route('**/api/auth/login', (r) => r.fulfill({ status: 504, contentType: 'text/html', body: '<h1>FUNCTION_INVOCATION_TIMEOUT</h1>' }));
  await submit(page);
  await expect(page.getByText(SERVICE)).toBeVisible();
  await expect(page.getByText(WRONG)).toHaveCount(0);
});

test('réseau coupé → « service indisponible »', async ({ page }) => {
  await page.route('**/api/auth/login', (r) => r.abort('failed'));
  await submit(page);
  await expect(page.getByText(SERVICE)).toBeVisible();
  await expect(page.getByText(WRONG)).toHaveCount(0);
});

test('vrais mauvais identifiants → toujours « incorrect »', async ({ page }) => {
  await submit(page);
  await expect(page.getByText(WRONG)).toBeVisible();
  await expect(page.getByText(SERVICE)).toHaveCount(0);
});
