/** Super admin › CRM › Séquences d'emails › ⋯ opens whole on screen, one at a time (user, 2026-11-10). */
import { test, expect } from '@playwright/test';
import { SIZES, signIn, checkMenus } from './helpers/menuOnScreen.js';

const ADMIN = { email: 'admin@fidelitour.com', password: 'Fidelit0ur!Adm' };   // local seed only

for (const size of SIZES) {
  test(`every sequence's ⋯ menu opens whole on screen (${size.width}×${size.height})`, async ({ page, request }) => {
    test.setTimeout(120_000);
    await page.setViewportSize(size);
    const H = await signIn(page, request, ADMIN);
    // sequences of its own, so the list has rows to the bottom (local only)
    for (let i = 1; i <= 6; i += 1) {
      const r = await request.post('/api/crm/sequences', { headers: H, data: { name: `Séquence menu ${size.width}-${i}` } });
      expect(r.ok(), await r.text()).toBeTruthy();
    }
    await page.goto('/admin/crm/sequences');
    await checkMenus(page, page.getByRole('button', { name: 'Actions', exact: true }));
    // the « Nouvelle séquence » menu is untouched
    await page.getByRole('button', { name: /Nouvelle séquence/ }).click();
    await expect(page.getByRole('button', { name: 'Séquence vierge' })).toBeVisible();
  });
}
