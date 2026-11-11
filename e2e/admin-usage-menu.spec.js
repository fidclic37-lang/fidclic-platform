/** Super admin › Analytics › Gestion des abonnements › ⋯ opens whole on screen (user, 2026-11-10). */
import { test } from '@playwright/test';
import { SIZES, signIn, checkMenus } from './helpers/menuOnScreen.js';

const ADMIN = { email: 'admin@fidelitour.com', password: 'Fidelit0ur!Adm' };   // local seed only

for (const size of SIZES) {
  test(`every business's ⋯ menu opens whole on screen (${size.width}×${size.height})`, async ({ page, request }) => {
    test.setTimeout(150_000);                 // the analytics page reads the whole platform
    await page.setViewportSize(size);
    await signIn(page, request, ADMIN);
    await page.goto('/admin/analytics');
    await checkMenus(page, page.getByRole('button', { name: /^Actions pour / }), { min: 1 });
  });
}
