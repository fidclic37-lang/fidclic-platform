/** Paramètres › Équipe & accès › ⋮ opens whole on screen, one at a time (user, 2026-11-10). */
import { test } from '@playwright/test';
import { SIZES, signIn, checkMenus } from './helpers/menuOnScreen.js';

for (const size of SIZES) {
  test(`every team member's ⋮ menu opens whole on screen (${size.width}×${size.height})`, async ({ page, request }) => {
    await page.setViewportSize(size);
    await signIn(page, request);
    await page.goto('/dashboard/parametres/equipe');
    await checkMenus(page, page.getByRole('button', { name: /^Actions — / }), { min: 1 });
  });
}
