/** Historique › ⋯ opens whole on screen, one at a time (user, 2026-11-10). */
import { test } from '@playwright/test';
import { SIZES, signIn, checkMenus } from './helpers/menuOnScreen.js';

for (const size of SIZES) {
  test(`every line's ⋯ menu opens whole on screen (${size.width}×${size.height})`, async ({ page, request }) => {
    await page.setViewportSize(size);
    await signIn(page, request);
    await page.goto('/dashboard/history');
    await checkMenus(page, page.getByRole('button', { name: "Plus d'actions" }));
  });
}
