/** Super admin › Commerces › ⋯ opens whole on screen, one at a time (user, 2026-11-10). */
import { test } from '@playwright/test';
import { SIZES, signIn, checkMenus } from './helpers/menuOnScreen.js';

const ADMIN = { email: 'admin@fidelitour.com', password: 'Fidelit0ur!Adm' };   // local seed only

for (const size of SIZES) {
  test(`every business's ⋯ menu opens whole on screen (${size.width}×${size.height})`, async ({ page, request }) => {
    test.setTimeout(120_000);                 // the admin list reads every business
    await page.setViewportSize(size);
    await signIn(page, request, ADMIN);
    await page.goto('/admin/commerces');
    await checkMenus(page, page.getByRole('button', { name: 'Actions', exact: true }));
  });
}
