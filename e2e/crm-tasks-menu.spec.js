/** Super admin › CRM › Tâches › ⋯ opens whole on screen, one at a time (user, 2026-11-10). */
import { test, expect } from '@playwright/test';
import { SIZES, signIn, checkMenus } from './helpers/menuOnScreen.js';

const ADMIN = { email: 'admin@fidelitour.com', password: 'Fidelit0ur!Adm' };   // local seed only

for (const size of SIZES) {
  test(`every task's ⋯ menu opens whole on screen (${size.width}×${size.height})`, async ({ page, request }) => {
    test.setTimeout(120_000);
    await page.setViewportSize(size);
    const H = await signIn(page, request, ADMIN);
    // tasks of its own, so the list has rows to the bottom (local only)
    for (let i = 1; i <= 6; i += 1) {
      const r = await request.post('/api/crm/tasks', { headers: H, data: { title: `Tâche menu ${size.width}-${i}`, due_at: new Date(Date.now() + i * 86400000).toISOString() } });
      expect(r.ok(), await r.text()).toBeTruthy();
    }
    await page.goto('/admin/crm/taches');
    await checkMenus(page, page.getByRole('button', { name: 'Actions', exact: true }));
  });
}
